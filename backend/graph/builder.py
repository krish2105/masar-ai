"""LangGraph assembly — the stateful graph with a cycle.

    guardrail → language → intent → supervisor → execute → grader ─┐
                                        ▲                          │
                                        └──── insufficient ────────┘
                                                                   │
                                                    sufficient → synthesis

The cycle is the point. A classical RAG pipeline is a DAG: retrieve, generate,
done. Here the Grader can send control back to the Supervisor with *named gaps*,
and the Supervisor must produce a different plan addressing them — up to three
times, then answer anyway with an explicit low-confidence caveat.

LangGraph was chosen over LangChain's AgentExecutor precisely for this. The
control flow is an explicit state machine that can be inspected, constrained and
replayed, which matters enormously when the system has to justify why it
produced an answer.

Sub-tasks within a plan run concurrently via `asyncio.gather` where their
dependencies allow, so a plan touching retrieval, SQL and geospatial pays the
cost of its slowest branch rather than the sum of all three.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass
from typing import Any, Callable

from langgraph.graph import END, StateGraph

from backend.agents.a1_guardrail import GuardrailAgent
from backend.agents.a2_language import LanguageAgent
from backend.agents.a3_intent import IntentAgent
from backend.agents.a4_supervisor import SupervisorAgent, execution_order
from backend.agents.a5_rewriter import RewriterAgent
from backend.agents.a7_reranker import RerankerAgent
from backend.agents.a8_sql import TextToSqlAgent
from backend.agents.a9_live_api import LiveApiAgent
from backend.agents.a10_geospatial import GeoError, GeospatialAgent
from backend.agents.a11_calculator import (
    CalculationError,
    drive_vs_transit,
    monthly_commute_cost,
    nol_fare,
    salik_cost,
)
from backend.agents.a12_grader import GraderAgent
from backend.agents.a13_synthesis import SynthesisAgent
from backend.agents.a14_observability import Tracer
from backend.config.settings import get_settings
from backend.graph.state import (
    Confidence,
    Evidence,
    EvidenceType,
    Intent,
    MasarState,
    Plan,
    Source,
    SubTask,
    ToolClass,
    new_state,
)
from backend.retrieval.hybrid import HybridRetriever
from backend.services.logging import get_logger

log = get_logger(__name__)


@dataclass
class Agents:
    """Everything the graph needs, constructed once and shared."""

    guardrail: GuardrailAgent
    language: LanguageAgent
    intent: IntentAgent
    supervisor: SupervisorAgent
    rewriter: RewriterAgent
    retriever: HybridRetriever
    reranker: RerankerAgent
    sql: TextToSqlAgent
    api: LiveApiAgent
    geo: GeospatialAgent
    grader: GraderAgent
    synthesis: SynthesisAgent
    router: Any = None


def build_agents(router=None) -> Agents:
    settings = get_settings()
    return Agents(
        guardrail=GuardrailAgent(router),
        language=LanguageAgent(),
        intent=IntentAgent(router),
        supervisor=SupervisorAgent(router),
        rewriter=RewriterAgent(router),
        retriever=HybridRetriever(settings.pg_dsn),
        reranker=RerankerAgent(),
        sql=TextToSqlAgent(settings.pg_dsn_readonly, router),
        api=LiveApiAgent(settings.dubai_pulse_api_key, settings.dubai_pulse_api_secret),
        geo=GeospatialAgent(settings.pg_dsn),
        grader=GraderAgent(router, threshold=settings.grader_threshold),
        synthesis=SynthesisAgent(router),
        router=router,
    )


# =============================================================================
# Sub-task execution
# =============================================================================


async def _run_retrieve(agents: Agents, task: SubTask, state: MasarState) -> list[Evidence]:
    query = str(task.params.get("query") or state.get("sanitized_query", ""))
    rewrite = await agents.rewriter.run(query)
    variants = rewrite.all_queries()

    chunks = await asyncio.to_thread(
        agents.retriever.search_multi, variants, top_k=50
    )
    result = await asyncio.to_thread(agents.reranker.run, query, chunks, sub_task_id=task.id)
    return result.evidence


async def _run_sql(agents: Agents, task: SubTask, state: MasarState) -> list[Evidence]:
    question = str(task.params.get("question") or state.get("sanitized_query", ""))
    result = await agents.sql.run(question)

    if not result.success:
        state.setdefault("sub_task_errors", {})[task.id] = result.gap or result.error
        return []

    return [
        Evidence(
            content=(
                f"Query: {result.explanation or question}\n"
                f"SQL: {result.sql}\n"
                f"Result ({result.row_count} rows):\n{result.to_evidence_text()}"
            ),
            evidence_type=EvidenceType.SQL_RESULT,
            source=Source(
                id="",
                type=EvidenceType.SQL_RESULT,
                dataset_or_doc=", ".join(result.tables) or "star schema",
                source_url="https://www.dubaipulse.gov.ae/",
                row_id_or_chunk_id=f"{result.row_count} rows",
                captured_at=str(result.rows[0].get("captured_at")) if result.rows and "captured_at" in result.rows[0] else None,
                source_tier="archive",
            ),
            score=0.95,
            sub_task_id=task.id,
        )
    ]


async def _run_geo(agents: Agents, task: SubTask, state: MasarState) -> list[Evidence]:
    operation = str(task.params.get("operation", "nearest"))
    place = str(task.params.get("place") or state.get("sanitized_query", ""))

    try:
        if operation == "between":
            result = await asyncio.to_thread(
                agents.geo.between, place, str(task.params.get("destination", ""))
            )
        elif operation == "catchment":
            resolved = await asyncio.to_thread(agents.geo.resolve_place, place)
            if resolved is None:
                raise GeoError(f"could not resolve {place!r}")
            result = await asyncio.to_thread(
                agents.geo.catchment,
                resolved.latitude,
                resolved.longitude,
                radius_km=float(task.params.get("radius_km", 1.0)),
            )
        else:
            result = await asyncio.to_thread(
                agents.geo.nearest_to_place, place, limit=int(task.params.get("limit", 5))
            )
    except GeoError as exc:
        state.setdefault("sub_task_errors", {})[task.id] = str(exc)
        return []
    except Exception as exc:  # noqa: BLE001
        state.setdefault("sub_task_errors", {})[task.id] = f"{type(exc).__name__}: {exc}"
        return []

    lines: list[str] = []
    if result.origin and result.destination:
        lines.append(
            f"{result.origin.name} to {result.destination.name}: "
            f"{result.distance_km:.2f} km straight-line"
        )
        if result.interchanges is not None:
            lines.append(
                "Direct route available" if result.interchanges == 0
                else f"Requires {result.interchanges} interchange(s)"
            )
        if result.shared_routes:
            lines.append(f"Routes: {', '.join(result.shared_routes[:8])}")
    for place_item in result.places[:10]:
        zone = f", fare zone {place_item.zone_id}" if place_item.zone_id is not None else ""
        lines.append(
            f"{place_item.name} ({place_item.mode or place_item.kind}{zone}) — "
            f"{place_item.distance_km:.2f} km"
        )
    lines.extend(result.caveats)

    if not lines:
        state.setdefault("sub_task_errors", {})[task.id] = "geospatial search returned nothing"
        return []

    return [
        Evidence(
            content="\n".join(lines),
            evidence_type=EvidenceType.GEO_RESULT,
            source=Source(
                id="",
                type=EvidenceType.GEO_RESULT,
                dataset_or_doc="dim_station / dim_stop (computed)",
                source_url="https://www.dubaipulse.gov.ae/",
                row_id_or_chunk_id=f"{len(result.places)} places",
                source_tier="archive",
            ),
            score=0.9,
            sub_task_id=task.id,
        )
    ]


async def _run_calc(agents: Agents, task: SubTask, state: MasarState) -> list[Evidence]:
    """Deterministic arithmetic. No model touches these numbers."""
    params = task.params
    operation = str(params.get("operation", "nol_fare"))

    def _int(key: str, default: int) -> int:
        try:
            return int(params.get(key, default))
        except (TypeError, ValueError):
            return default

    try:
        if operation == "monthly_commute":
            calculation = monthly_commute_cost(
                zones=_int("zones", 2),
                card_type=str(params.get("card_type", "silver")),  # type: ignore[arg-type]
                working_days=params.get("working_days") and _int("working_days", 22),
            )
        elif operation == "salik":
            calculation = salik_cost(
                crossings_per_day=_int("crossings_per_day", 2),
                working_days=params.get("working_days") and _int("working_days", 22),
            )
        elif operation == "drive_vs_transit":
            calculation = drive_vs_transit(
                zones=_int("zones", 2),
                distance_km_one_way=float(params.get("distance_km_one_way", 20.0)),
                salik_crossings_per_day=_int("crossings_per_day", 0),
                card_type=str(params.get("card_type", "silver")),  # type: ignore[arg-type]
            )
        else:
            calculation = nol_fare(
                zones=_int("zones", 2),
                card_type=str(params.get("card_type", "silver")),  # type: ignore[arg-type]
            )
    except CalculationError as exc:
        state.setdefault("sub_task_errors", {})[task.id] = str(exc)
        return []

    payload = calculation.to_dict()
    lines = [
        f"CALCULATED — {payload['kind']}: {payload['currency']} {payload['total']}",
        "Breakdown:",
        *[f"  {b['label']}: {b['amount']}" for b in payload["breakdown"] if b["amount"]],
        "Assumptions:",
        *[f"  {a['label_en']} (source: {a['source']})" for a in payload["assumptions"]],
    ]
    if payload["caveats"]:
        lines += ["Caveats:", *[f"  {c}" for c in payload["caveats"]]]

    citation = payload["citations"][0] if payload["citations"] else {}
    return [
        Evidence(
            content="\n".join(lines),
            evidence_type=EvidenceType.CALC_RESULT,
            source=Source(
                id="",
                type=EvidenceType.CALC_RESULT,
                dataset_or_doc=f"A11 deterministic calculator ({payload['kind']})",
                source_url=citation.get("source", "config/fares.yaml"),
                row_id_or_chunk_id=payload["total"],
                captured_at=citation.get("effective_from"),
                source_tier="archive" if citation.get("verified_against_dataset") else "synthetic",
                is_synthetic=not citation.get("verified_against_dataset", False),
            ),
            score=1.0,
            sub_task_id=task.id,
        )
    ]


async def _run_api(agents: Agents, task: SubTask, state: MasarState) -> list[Evidence]:
    result = await agents.api.fetch(str(task.params.get("dataset", "")))
    if not result.success:
        state.setdefault("sub_task_errors", {})[task.id] = result.gap
        state["data_freshness"] = "archived"
        return []
    state["data_freshness"] = result.freshness
    return [
        Evidence(
            content=f"Live API result ({result.dataset}): {result.rows[:20]}",
            evidence_type=EvidenceType.API_RESULT,
            source=Source(
                id="",
                type=EvidenceType.API_RESULT,
                dataset_or_doc=result.dataset,
                source_url=f"https://api.dubaipulse.gov.ae/open/rta/{result.dataset}",
                source_tier="live_api",
            ),
            score=0.85,
            sub_task_id=task.id,
        )
    ]


_EXECUTORS: dict[ToolClass, Callable] = {
    ToolClass.RETRIEVE: _run_retrieve,
    ToolClass.SQL: _run_sql,
    ToolClass.GEO: _run_geo,
    ToolClass.CALC: _run_calc,
    ToolClass.API: _run_api,
}


# =============================================================================
# Graph nodes
# =============================================================================


def make_graph(agents: Agents, tracer: Tracer | None = None):
    settings = get_settings()
    max_cycles = settings.max_replan_cycles

    def _trace(agent_id: str, **kwargs) -> None:
        if tracer is not None:
            tracer.record(agent_id, **kwargs)

    # ---- A1 -------------------------------------------------------------
    async def guardrail_node(state: MasarState) -> dict:
        started = time.perf_counter()
        result = await agents.guardrail.run(state["raw_query"])
        _trace(
            "A1",
            latency_ms=(time.perf_counter() - started) * 1000,
            decision=result.verdict,
            reason=result.reason,
            rules=result.matched_rules,
        )
        return {
            "safe": result.safe,
            "sanitized_query": result.sanitized,
            "block_reason": result.reason if not result.safe else None,
            # Carried so the language node can pick the right redirect language.
            "_redirect_en": result.redirect_message_en,
            "_redirect_ar": result.redirect_message_ar,
        }

    # ---- A2 -------------------------------------------------------------
    async def language_node(state: MasarState) -> dict:
        started = time.perf_counter()
        result = agents.language.run(state.get("sanitized_query") or state["raw_query"])
        _trace(
            "A2",
            latency_ms=(time.perf_counter() - started) * 1000,
            decision=f"{result.language}→{result.response_language}",
            arabizi=result.is_arabizi,
        )
        return {
            "language": result.language,
            "script": result.script,
            "normalized_query": result.normalized,
            "transliterated_query": result.transliterated,
            "response_language": result.response_language,
            "query_variants": result.search_variants(),
        }

    # ---- A3 -------------------------------------------------------------
    async def intent_node(state: MasarState) -> dict:
        started = time.perf_counter()
        result = await agents.intent.run(state["sanitized_query"])
        _trace(
            "A3",
            latency_ms=(time.perf_counter() - started) * 1000,
            decision=str(result.intent),
            confidence=result.confidence,
            method=result.method,
            routed_to_multihop=result.routed_to_multihop,
        )
        return {"intent": result.intent, "intent_confidence": result.confidence}

    # ---- A4 -------------------------------------------------------------
    async def supervisor_node(state: MasarState) -> dict:
        cycle = state.get("cycle", 0)
        started = time.perf_counter()
        grade = state.get("grade")
        previous = state.get("plan")

        result = await agents.supervisor.run(
            state["sanitized_query"],
            state.get("intent", Intent.MULTI_HOP),
            cycle=cycle,
            previous_plan=previous if cycle > 0 else None,
            gaps=grade.gaps if grade and cycle > 0 else None,
            grader_reasoning=grade.reasoning if grade and cycle > 0 else "",
        )
        _trace(
            "A4",
            latency_ms=(time.perf_counter() - started) * 1000,
            decision=f"planned {len(result.plan.sub_tasks)} sub-tasks",
            cycle=cycle,
            tools=[t.tool.value for t in result.plan.sub_tasks],
            method=result.method,
            addresses_gaps=result.plan.addresses_gaps,
            repeated_previous=result.repeated_previous,
            is_replan=cycle > 0,
        )
        return {"plan": result.plan, "plan_history": [result.plan]}

    # ---- A5–A11 ----------------------------------------------------------
    async def execute_node(state: MasarState) -> dict:
        plan: Plan = state["plan"]
        cycle = state.get("cycle", 0)
        collected: list[Evidence] = []

        for wave in execution_order(plan):
            started = time.perf_counter()
            results = await asyncio.gather(
                *[
                    _EXECUTORS[task.tool](agents, task, state)
                    for task in wave
                    if task.tool in _EXECUTORS
                ],
                return_exceptions=True,
            )
            for task, outcome in zip(wave, results, strict=False):
                if isinstance(outcome, Exception):
                    log.warning(
                        "execute.sub_task_failed",
                        task=task.id,
                        tool=task.tool.value,
                        error=f"{type(outcome).__name__}: {outcome}",
                    )
                    state.setdefault("sub_task_errors", {})[task.id] = str(outcome)[:200]
                    continue
                collected.extend(outcome)

            _trace(
                "A6" if any(t.tool is ToolClass.RETRIEVE for t in wave) else "A8",
                latency_ms=(time.perf_counter() - started) * 1000,
                decision=f"wave of {len(wave)} sub-task(s) → {len(collected)} evidence items",
                cycle=cycle,
                tools=[t.tool.value for t in wave],
            )

        return {"evidence": collected}

    # ---- A12 -------------------------------------------------------------
    async def grader_node(state: MasarState) -> dict:
        cycle = state.get("cycle", 0)
        started = time.perf_counter()
        result = await agents.grader.run(
            state["sanitized_query"], state.get("evidence", []), cycle=cycle
        )
        report = result.report

        _trace(
            "A12",
            latency_ms=(time.perf_counter() - started) * 1000,
            decision="sufficient" if report.sufficient else f"insufficient → re-plan (cycle {cycle + 1})",
            cycle=cycle,
            scores=report.scores,
            weakest_axis=report.weakest_axis,
            gaps=report.gaps,
            method=result.method,
        )
        history = [*state.get("grade_history", []), report]
        return {"grade": report, "grade_history": history}

    # ---- A13 -------------------------------------------------------------
    async def synthesis_node(state: MasarState) -> dict:
        started = time.perf_counter()
        result = await agents.synthesis.run(
            state["sanitized_query"],
            state.get("evidence", []),
            response_language=state.get("response_language", "en"),
            grade=state.get("grade"),
            cycles_used=state.get("cycle", 0),
            max_cycles=max_cycles,
            degraded_mode=state.get("degraded_mode", False),
        )
        _trace(
            "A13",
            latency_ms=(time.perf_counter() - started) * 1000,
            decision=f"{str(result.confidence)} confidence, {len(result.citations)} citations",
            provider=result.provider,
            unsourced_removed=result.unsourced_removed,
        )
        return {
            "answer": result.answer,
            "citations": result.citations,
            "confidence": result.confidence,
            "assumptions": result.assumptions,
        }

    # ---- blocked path ----------------------------------------------------
    async def blocked_node(state: MasarState) -> dict:
        arabic = state.get("response_language") == "ar"
        message = state.get("_redirect_ar" if arabic else "_redirect_en") or ""
        return {
            "answer": message,
            "citations": [],
            "confidence": Confidence.HIGH,  # a correct refusal is a correct answer
            "intent": Intent.OUT_OF_SCOPE,
        }

    # ---- edges -----------------------------------------------------------
    def after_guardrail(state: MasarState) -> str:
        return "language" if state.get("safe", True) else "language_blocked"

    def after_grader(state: MasarState) -> str:
        """The cycle. This function is the corrective loop."""
        grade = state.get("grade")
        cycle = state.get("cycle", 0)
        if grade is not None and not grade.sufficient and cycle < max_cycles - 1:
            log.info(
                "graph.replan",
                cycle=cycle,
                next_cycle=cycle + 1,
                gaps=grade.gaps[:3],
                weakest=grade.weakest_axis,
            )
            return "replan"
        return "synthesis"

    async def increment_cycle(state: MasarState) -> dict:
        return {"cycle": state.get("cycle", 0) + 1}

    graph = StateGraph(MasarState)
    graph.add_node("guardrail", guardrail_node)
    graph.add_node("language", language_node)
    graph.add_node("language_blocked", language_node)
    graph.add_node("blocked", blocked_node)
    graph.add_node("intent", intent_node)
    graph.add_node("supervisor", supervisor_node)
    graph.add_node("execute", execute_node)
    graph.add_node("grader", grader_node)
    graph.add_node("increment_cycle", increment_cycle)
    graph.add_node("synthesis", synthesis_node)

    graph.set_entry_point("guardrail")
    graph.add_conditional_edges(
        "guardrail", after_guardrail,
        {"language": "language", "language_blocked": "language_blocked"},
    )
    graph.add_edge("language_blocked", "blocked")
    graph.add_edge("blocked", END)

    graph.add_edge("language", "intent")
    graph.add_edge("intent", "supervisor")
    graph.add_edge("supervisor", "execute")
    graph.add_edge("execute", "grader")
    graph.add_conditional_edges(
        "grader", after_grader,
        {"replan": "increment_cycle", "synthesis": "synthesis"},
    )
    graph.add_edge("increment_cycle", "supervisor")  # ← the cycle
    graph.add_edge("synthesis", END)

    return graph.compile()


# =============================================================================
# Turn runner
# =============================================================================


class MasarGraph:
    """One compiled graph, reused across turns."""

    def __init__(self, agents: Agents) -> None:
        self.agents = agents
        self.settings = get_settings()

    async def run_turn(
        self, query: str, *, session_id: str | None = None, turn_id: str | None = None
    ) -> tuple[MasarState, Tracer]:
        session_id = session_id or str(uuid.uuid4())
        turn_id = turn_id or str(uuid.uuid4())

        tracer = Tracer(
            session_id=session_id,
            turn_id=turn_id,
            trace_dir=self.settings.trace_dir,
            dsn=self.settings.pg_dsn,
        )
        compiled = make_graph(self.agents, tracer)
        state = new_state(session_id=session_id, turn_id=turn_id, raw_query=query)

        if self.agents.router is not None:
            report = self.settings.capability_report()
            state["degraded_mode"] = bool(report["degraded_mode"])

        started = time.perf_counter()
        # recursion_limit bounds the cycle: nodes per pass × max cycles, plus slack.
        final = await compiled.ainvoke(
            state, config={"recursion_limit": 8 * self.settings.max_replan_cycles + 12}
        )
        elapsed = (time.perf_counter() - started) * 1000

        tracer.record(
            "A14",
            latency_ms=0.0,
            decision=f"turn complete in {elapsed:.0f}ms",
            cycle=final.get("cycle", 0),
            replans=final.get("cycle", 0),
            evidence_items=len(final.get("evidence", [])),
        )
        tracer.flush()

        log.info(
            "graph.turn_complete",
            turn_id=turn_id,
            elapsed_ms=round(elapsed, 1),
            cycles=final.get("cycle", 0),
            evidence=len(final.get("evidence", [])),
            confidence=str(final.get("confidence", "")),
        )
        return final, tracer
