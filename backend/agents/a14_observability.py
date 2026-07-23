"""A14 — Observability. Runs on every state transition.

Emits one record per agent hop: which agent, which model and provider, tokens,
latency, the decision it made, and which planning cycle it belonged to. Written
to JSONL on disk and to Postgres, and exposed at `/api/v1/trace/{turn_id}`.

This is what makes the "agentic" claim falsifiable rather than asserted. A
reader can watch the Grader return control to the Planner with named gaps, see
the revised plan differ from the failed one, and check that the citation on a
number resolves to a real row. A system that cannot be audited this way is
asking to be taken on trust.

Writing a trace must never break a turn. Every failure here is caught and
logged; a lost trace record is a smaller problem than a lost answer.
"""

from __future__ import annotations

import json
import time
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator

import psycopg

from backend.graph.state import TraceHop
from backend.services.logging import get_logger

log = get_logger(__name__)

DDL = """
CREATE TABLE IF NOT EXISTS agent_traces (
    id            BIGSERIAL PRIMARY KEY,
    session_id    TEXT NOT NULL,
    turn_id       TEXT NOT NULL,
    hop_index     INTEGER NOT NULL,
    agent_id      TEXT NOT NULL,
    agent_name    TEXT NOT NULL,
    ts            TIMESTAMPTZ NOT NULL DEFAULT now(),
    latency_ms    DOUBLE PRECISION NOT NULL DEFAULT 0,
    model_used    TEXT,
    provider      TEXT,
    tokens_in     INTEGER NOT NULL DEFAULT 0,
    tokens_out    INTEGER NOT NULL DEFAULT 0,
    cost_estimate_usd DOUBLE PRECISION NOT NULL DEFAULT 0,
    decision      TEXT,
    cycle         INTEGER NOT NULL DEFAULT 0,
    error         TEXT,
    metadata      JSONB
);

CREATE INDEX IF NOT EXISTS idx_traces_turn    ON agent_traces (turn_id, hop_index);
CREATE INDEX IF NOT EXISTS idx_traces_session ON agent_traces (session_id, ts DESC);
CREATE INDEX IF NOT EXISTS idx_traces_agent   ON agent_traces (agent_id);
"""

AGENT_NAMES: dict[str, tuple[str, str]] = {
    "A1": ("Guardrail", "الحماية"),
    "A2": ("Language & Normalise", "اللغة والتوحيد"),
    "A3": ("Intent Router", "توجيه النية"),
    "A4": ("Supervisor / Planner", "المشرف والمخطط"),
    "A5": ("Query Rewriter", "إعادة صياغة الاستعلام"),
    "A6": ("Hybrid Retriever", "الاسترجاع الهجين"),
    "A7": ("Reranker", "إعادة الترتيب"),
    "A8": ("Text-to-SQL", "تحويل النص إلى SQL"),
    "A9": ("Live API", "واجهة البيانات"),
    "A10": ("Geospatial", "التحليل المكاني"),
    "A11": ("Numeric Calculator", "الحاسبة الرقمية"),
    "A12": ("Grader (CRAG)", "المُقيِّم"),
    "A13": ("Synthesis + Citation", "التركيب والاستشهاد"),
    "A14": ("Observability", "المراقبة"),
}


def agent_label(agent_id: str, lang: str = "en") -> str:
    names = AGENT_NAMES.get(agent_id, (agent_id, agent_id))
    return names[1] if lang == "ar" else names[0]


class Tracer:
    """Collects hops for one turn, then persists them."""

    def __init__(self, session_id: str, turn_id: str, trace_dir: Path, dsn: str | None = None) -> None:
        self.session_id = session_id
        self.turn_id = turn_id
        self.trace_dir = trace_dir
        self.dsn = dsn
        self.hops: list[TraceHop] = []

    # ------------------------------------------------------------ capture --
    def record(
        self,
        agent_id: str,
        *,
        latency_ms: float = 0.0,
        decision: str | None = None,
        cycle: int = 0,
        model_used: str | None = None,
        provider: str | None = None,
        tokens_in: int = 0,
        tokens_out: int = 0,
        cost_estimate_usd: float = 0.0,
        error: str | None = None,
        **metadata: Any,
    ) -> TraceHop:
        hop = TraceHop(
            agent_id=agent_id,
            agent_name=agent_label(agent_id),
            latency_ms=round(latency_ms, 2),
            model_used=model_used,
            provider=provider,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_estimate_usd=cost_estimate_usd,
            decision=decision,
            cycle=cycle,
            error=error,
            metadata=metadata,
        )
        self.hops.append(hop)
        log.info(
            "trace.hop",
            agent=agent_id,
            latency_ms=hop.latency_ms,
            decision=decision,
            cycle=cycle,
            provider=provider,
        )
        return hop

    @contextmanager
    def span(self, agent_id: str, *, cycle: int = 0, **metadata: Any) -> Iterator[dict[str, Any]]:
        """Time an agent and record it, whether it succeeds or raises.

        The mutable dict yielded lets the body attach a decision and model
        details; the timing and the record happen regardless, so a failing agent
        still appears in the trace instead of vanishing from it.
        """
        started = time.perf_counter()
        context: dict[str, Any] = {"decision": None}
        error: str | None = None
        try:
            yield context
        except Exception as exc:  # noqa: BLE001 — recorded, then re-raised
            error = f"{type(exc).__name__}: {exc}"[:400]
            raise
        finally:
            self.record(
                agent_id,
                latency_ms=(time.perf_counter() - started) * 1000,
                decision=context.get("decision"),
                cycle=cycle,
                model_used=context.get("model"),
                provider=context.get("provider"),
                tokens_in=context.get("tokens_in", 0),
                tokens_out=context.get("tokens_out", 0),
                error=error,
                **{k: v for k, v in {**metadata, **context}.items()
                   if k not in {"decision", "model", "provider", "tokens_in", "tokens_out"}},
            )

    # ------------------------------------------------------------ persist --
    @property
    def total_latency_ms(self) -> float:
        return round(sum(h.latency_ms for h in self.hops), 2)

    @property
    def replan_count(self) -> int:
        """How many times the Grader sent control back to the Planner.

        The single most-cited number in the trace: it is the observable
        difference between this system and a linear pipeline.
        """
        return max((h.cycle for h in self.hops), default=0)

    def summary(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "turn_id": self.turn_id,
            "hops": len(self.hops),
            "agents_used": sorted({h.agent_id for h in self.hops}),
            "total_latency_ms": self.total_latency_ms,
            "replan_cycles": self.replan_count,
            "providers": sorted({h.provider for h in self.hops if h.provider}),
            "tokens_in": sum(h.tokens_in for h in self.hops),
            "tokens_out": sum(h.tokens_out for h in self.hops),
            "cost_estimate_usd": round(sum(h.cost_estimate_usd for h in self.hops), 6),
            "errors": [
                {"agent_id": h.agent_id, "error": h.error} for h in self.hops if h.error
            ],
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.summary(),
            "generated_at": datetime.now(tz=UTC).isoformat(),
            "trace": [h.model_dump() for h in self.hops],
        }

    def write_jsonl(self) -> Path | None:
        try:
            directory = self.trace_dir / self.session_id
            directory.mkdir(parents=True, exist_ok=True)
            path = directory / f"{self.turn_id}.jsonl"
            with path.open("w", encoding="utf-8") as fh:
                fh.write(json.dumps({"_summary": self.summary()}, ensure_ascii=False) + "\n")
                for index, hop in enumerate(self.hops):
                    fh.write(
                        json.dumps(
                            {"hop_index": index, **hop.model_dump()},
                            ensure_ascii=False,
                            default=str,
                        )
                        + "\n"
                    )
            return path
        except Exception as exc:  # noqa: BLE001 — never break a turn over a trace
            log.warning("trace.jsonl_failed", error=f"{type(exc).__name__}: {exc}")
            return None

    def write_postgres(self) -> bool:
        if not self.dsn:
            return False
        try:
            with psycopg.connect(self.dsn, connect_timeout=3) as conn:
                with conn.cursor() as cur:
                    cur.execute(DDL)
                    for index, hop in enumerate(self.hops):
                        cur.execute(
                            """
                            INSERT INTO agent_traces (
                                session_id, turn_id, hop_index, agent_id, agent_name,
                                latency_ms, model_used, provider, tokens_in, tokens_out,
                                cost_estimate_usd, decision, cycle, error, metadata
                            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)
                            """,
                            (
                                self.session_id, self.turn_id, index, hop.agent_id,
                                hop.agent_name, hop.latency_ms, hop.model_used,
                                hop.provider, hop.tokens_in, hop.tokens_out,
                                hop.cost_estimate_usd, hop.decision, hop.cycle,
                                hop.error,
                                json.dumps(hop.metadata, ensure_ascii=False, default=str),
                            ),
                        )
                conn.commit()
            return True
        except Exception as exc:  # noqa: BLE001
            log.warning("trace.postgres_failed", error=f"{type(exc).__name__}: {exc}")
            return False

    def flush(self) -> None:
        self.write_jsonl()
        self.write_postgres()


def load_trace(dsn: str, turn_id: str) -> dict[str, Any] | None:
    """Read a turn's trace back — what `/api/v1/trace/{turn_id}` serves."""
    try:
        with psycopg.connect(dsn, connect_timeout=3) as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT hop_index, agent_id, agent_name, ts, latency_ms, model_used,
                       provider, tokens_in, tokens_out, cost_estimate_usd,
                       decision, cycle, error, metadata
                FROM agent_traces WHERE turn_id = %s ORDER BY hop_index
                """,
                (turn_id,),
            )
            rows = cur.fetchall()
    except Exception as exc:  # noqa: BLE001
        log.warning("trace.load_failed", error=f"{type(exc).__name__}: {exc}")
        return None

    if not rows:
        return None

    hops = [
        {
            "hop_index": r[0], "agent_id": r[1], "agent_name": r[2],
            "timestamp": r[3].isoformat() if r[3] else None, "latency_ms": r[4],
            "model_used": r[5], "provider": r[6], "tokens_in": r[7],
            "tokens_out": r[8], "cost_estimate_usd": r[9], "decision": r[10],
            "cycle": r[11], "error": r[12], "metadata": r[13] or {},
        }
        for r in rows
    ]
    return {
        "turn_id": turn_id,
        "hops": len(hops),
        "total_latency_ms": round(sum(h["latency_ms"] for h in hops), 2),
        "replan_cycles": max((h["cycle"] for h in hops), default=0),
        "agents_used": sorted({h["agent_id"] for h in hops}),
        "trace": hops,
    }
