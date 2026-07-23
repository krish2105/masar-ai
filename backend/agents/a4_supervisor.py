"""A4 — Supervisor / Planner. The heart of the system.

Decomposes a question into a typed sub-task DAG, dispatches independent tasks in
parallel, and — when the Grader returns control — produces a *different* plan
addressing the named gaps.

The re-plan is the part that matters. A re-plan that repeats the failed plan is
a bug, not a retry, so the previous plan and the gaps are both supplied to the
model, and a structural check rejects a revision identical to its predecessor.
Every revision is logged with the gaps it was meant to close, which makes the
loop inspectable in the trace viewer rather than something the reader is asked
to believe.

A deterministic fallback planner covers the case where every provider fails.
Intent alone is enough to build a reasonable plan, so the system still answers.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from backend.graph.state import EvidenceType, Intent, Plan, SubTask, ToolClass
from backend.services.logging import get_logger

log = get_logger(__name__)

MAX_SUB_TASKS = 6

_SYSTEM_PROMPT = """You plan how to answer questions about Dubai's public transport open data.

Emit JSON only:
{
  "sub_tasks": [
    {"id": "t1", "description": "...", "tool": "retrieve|sql|api|geo|calc",
     "depends_on": [], "params": {}}
  ],
  "reasoning": "one or two sentences on why this plan",
  "expected_evidence_types": ["document","sql_result","geo_result","calc_result"]
}

TOOLS

retrieve — hybrid search over service documentation, network guides, fare
           reference and generated summaries of database rows.
           params: {"query": "<search text>"}

sql      — query the star schema. Tables:
             dim_station(station_key, station_name_en, station_name_ar, mode,
                         line_name, zone_id, latitude, longitude)
             dim_stop(stop_id, stop_name_en, mode, latitude, longitude)
             dim_route(route_key, route_number, mode, route_type, origin_en,
                       destination_en, stop_count, route_length_km)
             bridge_route_stop(route_key, route_number, mode, stop_id, stop_order)
             fact_ridership_monthly(date_key, year, month_num, mode, grain,
                                    entity_name, trips, scale_anomaly)
             fact_modal_split_monthly(date_key, year, transport_type, trips)
             dim_salik_tariff(date_key, year, fare_aed)
             dim_date(date_key, year, month, month_name_en, quarter)
           params: {"question": "<what to compute, in words>"}

geo      — nearest stops/stations, distance, catchment, interchange count.
           params: {"operation": "nearest|between|catchment",
                    "place": "...", "destination": "...", "radius_km": 1.0}

calc     — deterministic fare and toll arithmetic. NEVER compute money yourself.
           params: {"operation": "nol_fare|monthly_commute|salik|drive_vs_transit",
                    "zones": 2, "card_type": "silver", "working_days": 22,
                    "crossings_per_day": 2, "distance_km_one_way": 20.0}

RULES

1. Two to four sub-tasks for most questions. One is fine for a simple lookup.
2. Independent sub-tasks get empty depends_on so they run in parallel.
3. Any question involving money MUST include a calc sub-task. Never compute
   fares in the plan or in prose.
4. A zone number needed by calc must come from a sql or geo sub-task first —
   express that with depends_on.
5. Prefer sql for anything countable, retrieve for anything explanatory.
6. Ridership rows carry scale_anomaly; exclude flagged rows from trends."""

_REPLAN_PROMPT = """Your previous plan did not gather sufficient evidence.

PREVIOUS PLAN:
{previous}

GAPS THE GRADER IDENTIFIED:
{gaps}

GRADER REASONING:
{reasoning}

Produce a DIFFERENT plan that closes those gaps. Repeating the previous plan is
useless — change the tools, change the queries, or decompose differently. If the
previous plan searched documents and found nothing, try SQL. If SQL returned
nothing, broaden the query or search documents instead.

Same JSON format. Add "addresses_gaps": ["<gap>", ...] naming which gaps each
revision targets."""


@dataclass(slots=True)
class PlanResult:
    plan: Plan
    method: str = "model"
    provider: str | None = None
    repeated_previous: bool = False
    """True when the model returned the same plan again — the loop would stall."""

    raw: dict = field(default_factory=dict)


def _plan_signature(plan: Plan) -> str:
    """Structural identity of a plan, for detecting a no-op re-plan."""
    return json.dumps(
        sorted(
            (t.tool.value, json.dumps(t.params, sort_keys=True, default=str))
            for t in plan.sub_tasks
        ),
        sort_keys=True,
    )


class SupervisorAgent:
    def __init__(self, router=None) -> None:
        self.router = router

    # ---------------------------------------------------------- fallback ----
    @staticmethod
    def fallback_plan(query: str, intent: Intent, cycle: int = 0) -> Plan:
        """Intent-driven plan used when no model is reachable.

        Deliberately simple and always valid. A degraded plan that runs beats a
        clever plan that never executes.
        """
        tasks: list[SubTask] = []

        if intent in (Intent.SERVICE_INFO, Intent.OUT_OF_SCOPE):
            tasks.append(SubTask(id="t1", description="Search documentation", tool=ToolClass.RETRIEVE, params={"query": query}))

        elif intent == Intent.FARE_COST:
            tasks += [
                SubTask(id="t1", description="Find fare rules and zones", tool=ToolClass.RETRIEVE, params={"query": query}),
                SubTask(id="t2", description="Look up station fare zones", tool=ToolClass.SQL, params={"question": f"fare zones for stations mentioned in: {query}"}),
                SubTask(id="t3", description="Compute the fare", tool=ToolClass.CALC, depends_on=["t2"], params={"operation": "monthly_commute", "zones": 2}),
            ]

        elif intent == Intent.NETWORK_ANALYTICS:
            tasks += [
                SubTask(id="t1", description="Query ridership facts", tool=ToolClass.SQL, params={"question": query}),
                SubTask(id="t2", description="Search network context", tool=ToolClass.RETRIEVE, params={"query": query}),
            ]

        elif intent == Intent.GEOSPATIAL:
            tasks += [
                SubTask(id="t1", description="Find nearby stops and stations", tool=ToolClass.GEO, params={"operation": "nearest", "place": query}),
                SubTask(id="t2", description="Search station reference", tool=ToolClass.RETRIEVE, params={"query": query}),
            ]

        elif intent == Intent.JOURNEY_PLANNING:
            tasks += [
                SubTask(id="t1", description="Find route connections", tool=ToolClass.SQL, params={"question": query}),
                SubTask(id="t2", description="Search route documentation", tool=ToolClass.RETRIEVE, params={"query": query}),
            ]

        else:  # MULTI_HOP
            tasks += [
                SubTask(id="t1", description="Search documentation", tool=ToolClass.RETRIEVE, params={"query": query}),
                SubTask(id="t2", description="Query the star schema", tool=ToolClass.SQL, params={"question": query}),
                SubTask(id="t3", description="Geospatial context", tool=ToolClass.GEO, params={"operation": "nearest", "place": query}),
            ]

        # A re-plan must differ from what already failed; widen the search.
        if cycle > 0:
            tasks.append(
                SubTask(
                    id=f"t{len(tasks) + 1}",
                    description="Broadened documentation search after insufficient evidence",
                    tool=ToolClass.RETRIEVE,
                    params={"query": " ".join(query.split()[:6])},
                )
            )

        return Plan(
            sub_tasks=tasks[:MAX_SUB_TASKS],
            reasoning=f"Deterministic fallback plan for intent {intent}.",
            expected_evidence_types=[EvidenceType.DOCUMENT],
            cycle=cycle,
        )

    # -------------------------------------------------------------- plan ----
    async def run(
        self,
        query: str,
        intent: Intent,
        *,
        cycle: int = 0,
        previous_plan: Plan | None = None,
        gaps: list[str] | None = None,
        grader_reasoning: str = "",
    ) -> PlanResult:
        if self.router is None:
            return PlanResult(
                plan=self.fallback_plan(query, intent, cycle), method="fallback"
            )

        messages = [{"role": "system", "content": _SYSTEM_PROMPT}]
        if cycle > 0 and previous_plan is not None:
            messages.append(
                {
                    "role": "user",
                    "content": _REPLAN_PROMPT.format(
                        previous=json.dumps(
                            [
                                {"tool": t.tool.value, "description": t.description, "params": t.params}
                                for t in previous_plan.sub_tasks
                            ],
                            indent=2,
                            default=str,
                        ),
                        gaps="\n".join(f"- {g}" for g in (gaps or [])) or "- (none named)",
                        reasoning=grader_reasoning or "(none given)",
                    ),
                }
            )
        messages.append(
            {"role": "user", "content": f"Intent: {intent}\nQuestion: {query}"}
        )

        try:
            payload, completion = await self.router.complete_json("planning", messages)
        except Exception as exc:  # noqa: BLE001
            log.warning("supervisor.model_failed", error=f"{type(exc).__name__}: {exc}")
            return PlanResult(
                plan=self.fallback_plan(query, intent, cycle), method="fallback_after_error"
            )

        plan = self._parse(payload, query, intent, cycle, gaps)

        repeated = False
        if previous_plan is not None and _plan_signature(plan) == _plan_signature(previous_plan):
            # The model reissued the failed plan. Widening deterministically is
            # better than looping on the same evidence.
            repeated = True
            log.warning("supervisor.replan_identical", cycle=cycle)
            plan.sub_tasks.append(
                SubTask(
                    id=f"t{len(plan.sub_tasks) + 1}",
                    description="Broadened search added because the re-plan repeated the previous plan",
                    tool=ToolClass.RETRIEVE,
                    params={"query": " ".join(query.split()[:6])},
                )
            )

        log.info(
            "supervisor.planned",
            cycle=cycle,
            sub_tasks=len(plan.sub_tasks),
            tools=[t.tool.value for t in plan.sub_tasks],
            provider=completion.provider,
            addresses_gaps=plan.addresses_gaps,
        )
        return PlanResult(
            plan=plan,
            method=f"model:{completion.provider}",
            provider=completion.provider,
            repeated_previous=repeated,
            raw=payload,
        )

    def _parse(
        self, payload: dict, query: str, intent: Intent, cycle: int, gaps: list[str] | None
    ) -> Plan:
        raw_tasks = payload.get("sub_tasks") or []
        tasks: list[SubTask] = []

        for index, item in enumerate(raw_tasks[:MAX_SUB_TASKS], start=1):
            if not isinstance(item, dict):
                continue
            tool_name = str(item.get("tool", "retrieve")).strip().lower()
            try:
                tool = ToolClass(tool_name)
            except ValueError:
                log.warning("supervisor.unknown_tool", tool=tool_name)
                continue

            params = item.get("params")
            params = params if isinstance(params, dict) else {}
            # A retrieve task without a query is useless; default to the question.
            if tool is ToolClass.RETRIEVE and not params.get("query"):
                params["query"] = query
            if tool is ToolClass.SQL and not params.get("question"):
                params["question"] = query

            depends = item.get("depends_on")
            depends = [str(d) for d in depends] if isinstance(depends, list) else []

            tasks.append(
                SubTask(
                    id=str(item.get("id") or f"t{index}"),
                    description=str(item.get("description", ""))[:300],
                    tool=tool,
                    depends_on=depends,
                    params=params,
                )
            )

        if not tasks:
            log.warning("supervisor.empty_plan", cycle=cycle)
            return self.fallback_plan(query, intent, cycle)

        evidence_types: list[EvidenceType] = []
        for name in payload.get("expected_evidence_types") or []:
            try:
                evidence_types.append(EvidenceType(str(name).strip().lower()))
            except ValueError:
                continue

        return Plan(
            sub_tasks=tasks,
            reasoning=str(payload.get("reasoning", ""))[:500],
            expected_evidence_types=evidence_types,
            cycle=cycle,
            addresses_gaps=[str(g) for g in (payload.get("addresses_gaps") or gaps or [])],
        )


def execution_order(plan: Plan) -> list[list[SubTask]]:
    """Group sub-tasks into waves that can run concurrently.

    Each wave contains only tasks whose dependencies are already satisfied. A
    dependency cycle or a reference to a non-existent task would otherwise hang
    the graph, so any remaining tasks are emitted as a final wave rather than
    being dropped.
    """
    remaining = {t.id: t for t in plan.sub_tasks}
    done: set[str] = set()
    waves: list[list[SubTask]] = []

    while remaining:
        ready = [
            task
            for task in remaining.values()
            if all(dep in done or dep not in {t.id for t in plan.sub_tasks} for dep in task.depends_on)
        ]
        if not ready:
            log.warning(
                "supervisor.dependency_cycle",
                unresolved=list(remaining),
                detail="emitting remaining tasks in one wave rather than deadlocking",
            )
            waves.append(list(remaining.values()))
            break
        waves.append(ready)
        for task in ready:
            done.add(task.id)
            remaining.pop(task.id, None)

    return waves
