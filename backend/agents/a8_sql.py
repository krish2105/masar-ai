"""A8 — Text-to-SQL, guarded.

The model proposes SQL; a deterministic guard decides whether it runs. Four
independent layers, described in `services/sql_guard.py`, and the last two
assume the first two will eventually be defeated.

Two design choices worth stating:

* **The schema card, not `information_schema`.** A curated card costs fewer
  tokens *and* produces better SQL, because it carries the semantics the model
  actually needs — that `grain` differs by mode, that names are inconsistent
  and must be matched with `ILIKE`, that `scale_anomaly` rows must be excluded
  from trends.
* **One repair attempt, then a gap.** A failing query is returned to the model
  once with its error, which fixes most syntax and column-name mistakes. After
  that it becomes a named gap for the Grader rather than an nth attempt — the
  Supervisor re-planning with different tools recovers more often than the same
  agent trying again.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row

from backend.services.logging import get_logger
from backend.services.sql_guard import SqlGuardError, validate

log = get_logger(__name__)

SCHEMA_CARD_PATH = Path(__file__).resolve().parents[1] / "config" / "schema_card.md"

ALLOWED_TABLES = {
    "dim_station",
    "dim_stop",
    "dim_route",
    "dim_date",
    "dim_salik_tariff",
    "bridge_route_stop",
    "fact_ridership_monthly",
    "fact_modal_split_monthly",
}

STATEMENT_TIMEOUT_MS = 5000
MAX_RESULT_ROWS = 200


@lru_cache(maxsize=1)
def schema_card() -> str:
    return SCHEMA_CARD_PATH.read_text(encoding="utf-8")


_SYSTEM_PROMPT = """You write PostgreSQL SELECT queries against the schema below.

Return JSON only:
{"sql": "<one SELECT statement>", "explanation": "<one sentence>"}

{schema}

Write exactly one SELECT. No semicolons, no comments, no explanation outside the
JSON. If the question cannot be answered from this schema, return
{"sql": "", "explanation": "<what is missing>"} — an honest gap is far better
than a query against a table that does not exist."""


@dataclass(slots=True)
class SqlResult:
    success: bool
    sql: str = ""
    rows: list[dict[str, Any]] = field(default_factory=list)
    row_count: int = 0
    explanation: str = ""
    error: str = ""
    gap: str = ""
    """Set when the sub-task could not be completed — consumed by A12."""

    latency_ms: float = 0.0
    repaired: bool = False
    tables: list[str] = field(default_factory=list)
    provider: str | None = None

    def to_evidence_text(self, *, max_rows: int = 20) -> str:
        """Render rows as text the Grader and Synthesiser can read."""
        if not self.rows:
            return "Query returned no rows."
        columns = [c for c in self.rows[0] if not c.startswith("_")]
        lines = [" | ".join(columns)]
        for row in self.rows[:max_rows]:
            lines.append(
                " | ".join("" if row.get(c) is None else str(row.get(c))[:60] for c in columns)
            )
        if self.row_count > max_rows:
            lines.append(f"… and {self.row_count - max_rows} more rows")
        return "\n".join(lines)


class TextToSqlAgent:
    def __init__(self, readonly_dsn: str, router=None) -> None:
        self.dsn = readonly_dsn
        self.router = router

    # ------------------------------------------------------------ execute --
    def execute(self, sql: str) -> tuple[list[dict[str, Any]], str]:
        """Run validated SQL under the read-only role."""
        try:
            with psycopg.connect(self.dsn, connect_timeout=5) as conn:
                with conn.cursor(row_factory=dict_row) as cur:
                    # Layer four, set explicitly rather than relying on the role
                    # default, so the bound is visible at the call site.
                    cur.execute(f"SET LOCAL statement_timeout = {STATEMENT_TIMEOUT_MS}")
                    cur.execute(sql)
                    rows = cur.fetchmany(MAX_RESULT_ROWS)
            return [dict(r) for r in rows], ""
        except psycopg.errors.QueryCanceled:
            return [], f"query exceeded the {STATEMENT_TIMEOUT_MS}ms timeout"
        except psycopg.errors.InsufficientPrivilege as exc:
            # Layer three caught something layers one and two missed.
            log.error("sql.privilege_denied", error=str(exc)[:200])
            return [], "the read-only role refused this statement"
        except Exception as exc:
            return [], f"{type(exc).__name__}: {exc}"[:300]

    # ---------------------------------------------------------------- run --
    async def run(self, question: str, *, allow_repair: bool = True) -> SqlResult:
        started = time.perf_counter()

        if self.router is None:
            return SqlResult(
                success=False,
                gap="No model available to generate SQL; the analytical database was not queried.",
                latency_ms=(time.perf_counter() - started) * 1000,
            )

        messages = [
            {"role": "system", "content": _SYSTEM_PROMPT.replace("{schema}", schema_card())},
            {"role": "user", "content": question},
        ]

        attempt = 0
        repaired = False
        while attempt <= (1 if allow_repair else 0):
            attempt += 1
            try:
                payload, completion = await self.router.complete_json("sql", messages)
            except Exception as exc:
                return SqlResult(
                    success=False,
                    error=f"{type(exc).__name__}: {exc}"[:200],
                    gap="SQL generation failed; the analytical database was not queried.",
                    latency_ms=(time.perf_counter() - started) * 1000,
                )

            raw_sql = str(payload.get("sql", "")).strip()
            explanation = str(payload.get("explanation", ""))[:300]

            if not raw_sql:
                # The model correctly recognised the schema cannot answer this.
                return SqlResult(
                    success=False,
                    explanation=explanation,
                    gap=explanation or "The question cannot be answered from the star schema.",
                    latency_ms=(time.perf_counter() - started) * 1000,
                    provider=completion.provider,
                )

            try:
                guarded = validate(raw_sql, allowed_tables=ALLOWED_TABLES)
            except SqlGuardError as exc:
                log.warning("sql.guard_rejected", error=str(exc)[:200], attempt=attempt)
                if attempt <= 1 and allow_repair:
                    messages.append({"role": "assistant", "content": raw_sql})
                    messages.append(
                        {
                            "role": "user",
                            "content": (
                                f"That statement was rejected by the safety guard: {exc}. "
                                "Rewrite it as a single read-only SELECT over the listed "
                                "tables only."
                            ),
                        }
                    )
                    repaired = True
                    continue
                return SqlResult(
                    success=False,
                    sql=raw_sql,
                    error=str(exc),
                    gap=f"Generated SQL was rejected by the safety guard: {exc}",
                    latency_ms=(time.perf_counter() - started) * 1000,
                    provider=completion.provider,
                )

            rows, error = self.execute(guarded.sql)

            if error:
                log.warning("sql.execution_failed", error=error[:200], attempt=attempt)
                if attempt <= 1 and allow_repair:
                    messages.append({"role": "assistant", "content": guarded.sql})
                    messages.append(
                        {
                            "role": "user",
                            "content": (
                                f"That query failed with: {error}. Correct it. "
                                "Check column names against the schema."
                            ),
                        }
                    )
                    repaired = True
                    continue
                return SqlResult(
                    success=False,
                    sql=guarded.sql,
                    error=error,
                    gap=f"The analytical query failed: {error}",
                    latency_ms=(time.perf_counter() - started) * 1000,
                    tables=guarded.tables,
                    provider=completion.provider,
                    repaired=repaired,
                )

            latency = (time.perf_counter() - started) * 1000
            log.info(
                "sql.executed",
                rows=len(rows),
                tables=guarded.tables,
                repaired=repaired,
                latency_ms=round(latency, 1),
            )
            return SqlResult(
                success=True,
                sql=guarded.sql,
                rows=rows,
                row_count=len(rows),
                explanation=explanation,
                latency_ms=latency,
                repaired=repaired,
                tables=guarded.tables,
                provider=completion.provider,
                gap="" if rows else "The query ran but matched no rows.",
            )

        return SqlResult(
            success=False,
            gap="SQL generation did not produce a runnable query.",
            latency_ms=(time.perf_counter() - started) * 1000,
        )
