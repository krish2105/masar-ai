"""Four-config ablation study.

Isolates each layer's contribution by running the golden set under progressively
richer configurations:

    naive          dense-only retrieval, no rerank, single pass
    hybrid         dense + FTS (RRF fusion), no rerank, single pass
    hybrid+rerank  dense + FTS + cross-encoder rerank, single pass
    full agentic   the above + the corrective loop (A4 re-plan / A12 grade)

Each config is assembled by SWAPPING components on a fresh Agents container — the
production graph code is never modified — plus a `max_cycles` override that
run_turn already accepts (0 = single pass). Emits a markdown comparison table so
the contribution of hybrid fusion, reranking and the agentic loop is legible.

    python -m backend.tests.golden.ablation --limit 20
"""

from __future__ import annotations

import argparse
import asyncio
import statistics
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from backend.config.settings import get_settings
from backend.graph.builder import Agents, MasarGraph, build_agents
from backend.graph.state import Evidence, EvidenceType, Source
from backend.retrieval.hybrid import RetrievedChunk
from backend.services.llm_router import get_router
from backend.services.logging import configure_logging, get_logger
from backend.tests.golden.run_eval import QuestionResult, evaluate_question, load_golden

log = get_logger(__name__)

RERANK_TOP_K = 8


@dataclass(frozen=True)
class AblationConfig:
    name: str
    fts: bool  # dense + FTS vs dense-only
    rerank: bool  # cross-encoder rerank
    agentic: bool  # the corrective loop

    @property
    def max_cycles(self) -> int:
        """0 disables the corrective loop entirely (single pass)."""
        return get_settings().max_replan_cycles if self.agentic else 0


CONFIGS: list[AblationConfig] = [
    AblationConfig("naive", fts=False, rerank=False, agentic=False),
    AblationConfig("hybrid", fts=True, rerank=False, agentic=False),
    AblationConfig("hybrid+rerank", fts=True, rerank=True, agentic=False),
    AblationConfig("full agentic", fts=True, rerank=True, agentic=True),
]


# =============================================================================
# Component swaps — production retrieval/reranker are left untouched
# =============================================================================


class DenseOnlyRetriever:
    """Wraps HybridRetriever, forcing sparse_weight=0 so fusion is dense-only."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner

    def search_multi(self, queries: list[str], *, top_k: int = 50, **kwargs: Any) -> Any:
        return self._inner.search_multi(queries, top_k=top_k, sparse_weight=0.0, **kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


def _chunk_to_evidence(chunk: RetrievedChunk, sub_task_id: str | None) -> Evidence:
    """Mirror the reranker's Evidence construction, minus the cross-encoder."""
    evidence_type = (
        EvidenceType.SQL_RESULT if chunk.kind == "row_summary" else EvidenceType.DOCUMENT
    )
    return Evidence(
        content=chunk.raw_text,
        evidence_type=evidence_type,
        source=Source(
            id="",
            type=evidence_type,
            dataset_or_doc=chunk.source_table or chunk.title or chunk.doc_id,
            source_url=chunk.source_url,
            row_id_or_chunk_id=chunk.row_key or chunk.chunk_id,
            captured_at=chunk.captured_at,
            last_updated=chunk.retrieved_date,
        ),
        score=chunk.score,
        sub_task_id=sub_task_id,
        dense_score=chunk.dense_score,
        sparse_score=chunk.sparse_score,
    )


@dataclass(slots=True)
class _NoOpResult:
    evidence: list[Evidence]
    candidates_in: int
    kept: int
    dropped_below_threshold: int
    threshold: float


class NoOpReranker:
    """Keeps the top-k in retrieval order and converts to evidence — no rerank."""

    def __init__(self, *, top_k: int = RERANK_TOP_K) -> None:
        self.top_k = top_k

    def run(
        self, query: str, chunks: list[RetrievedChunk], *, sub_task_id: str | None = None
    ) -> _NoOpResult:
        kept = chunks[: self.top_k]
        evidence = [_chunk_to_evidence(c, sub_task_id) for c in kept]
        return _NoOpResult(evidence, len(chunks), len(evidence), len(chunks) - len(evidence), 0.0)


def build_ablation_agents(config: AblationConfig, router: Any) -> Agents:
    agents = build_agents(router)
    if not config.fts:
        agents.retriever = DenseOnlyRetriever(agents.retriever)  # type: ignore[assignment]
    if not config.rerank:
        agents.reranker = NoOpReranker()  # type: ignore[assignment]
    return agents


# =============================================================================
# Run + aggregate
# =============================================================================


def config_metrics(config_name: str, results: list[QuestionResult]) -> dict[str, Any]:
    if not results:
        return {"config": config_name, "n": 0}
    latencies = sorted(r.latency_s for r in results)
    p50 = statistics.median(latencies)
    return {
        "config": config_name,
        "n": len(results),
        "pass_rate": round(sum(1 for r in results if r.passed) / len(results), 3),
        "citation_validity": round(sum(1 for r in results if r.citation_valid) / len(results), 3),
        "mean_evidence": round(statistics.mean(r.evidence_count for r in results), 2),
        "p50_latency_s": round(p50, 2),
        "replan_rate": round(sum(1 for r in results if r.replan_cycles > 0) / len(results), 3),
    }


async def run_config(
    config: AblationConfig, questions: list[dict[str, Any]], router: Any, dsn: str
) -> dict[str, Any]:
    agents = build_ablation_agents(config, router)
    graph = MasarGraph(agents)
    results: list[QuestionResult] = []
    for index, item in enumerate(questions, 1):
        print(f"    [{config.name}] {index}/{len(questions)} {item['id']}")
        result = await evaluate_question(graph, item, dsn, max_cycles=config.max_cycles)
        results.append(result)
    return config_metrics(config.name, results)


# =============================================================================
# Markdown table (pure — unit-tested)
# =============================================================================

_COLUMNS = [
    ("config", "Config"),
    ("pass_rate", "Pass rate"),
    ("citation_validity", "Citation validity"),
    ("mean_evidence", "Mean evidence"),
    ("p50_latency_s", "p50 latency (s)"),
    ("replan_rate", "Re-plan rate"),
]


def render_table(rows: list[dict[str, Any]]) -> str:
    header = "| " + " | ".join(label for _, label in _COLUMNS) + " |"
    sep = "|" + "|".join("---" for _ in _COLUMNS) + "|"
    lines = [header, sep]
    for row in rows:
        cells = []
        for key, _ in _COLUMNS:
            value = row.get(key, "—")
            cells.append(str(value) if not isinstance(value, float) else f"{value:g}")
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def render_report(rows: list[dict[str, Any]], *, n: int, generated_at: str) -> str:
    return (
        f"# Ablation study\n\n"
        f"_Generated {generated_at} over {n} question(s) per config._\n\n"
        "Each config adds one capability to the previous: dense-only → + FTS fusion "
        "→ + cross-encoder rerank → + the corrective loop. A monotonic rise in pass "
        "rate isolates each layer's contribution; the loop's cost shows in latency.\n\n"
        + render_table(rows)
        + "\n\n_Deterministic metrics only. Judged context-precision per config requires "
        "the RAGAS judge (`run_eval --ragas`); it is omitted here to keep the ablation "
        "runnable without cloud calls._\n"
    )


async def main(argv: list[str] | None = None) -> int:
    configure_logging()
    parser = argparse.ArgumentParser(description="Masar AI — four-config ablation study")
    parser.add_argument("--limit", type=int, default=20, help="questions per config (default 20)")
    parser.add_argument("--lang", choices=["en", "ar"], default=None)
    args = parser.parse_args(argv)

    settings = get_settings()
    golden = load_golden()
    questions = golden["questions"]
    if args.lang:
        questions = [q for q in questions if q["lang"] == args.lang]
    # Skip graph-only reachability questions — they'd fail every config equally.
    questions = [q for q in questions if not q.get("requires_graph")]
    if args.limit:
        questions = questions[: args.limit]

    router = await get_router()
    rows: list[dict[str, Any]] = []
    for config in CONFIGS:
        print(f"\n  ── {config.name} ──")
        rows.append(await run_config(config, questions, router, settings.pg_dsn))
    await router.aclose()

    generated_at = datetime.now(tz=UTC).strftime("%Y-%m-%d %H:%M UTC")
    report = render_report(rows, n=len(questions), generated_at=generated_at)

    settings.eval_report_dir.mkdir(parents=True, exist_ok=True)
    path = settings.eval_report_dir / f"ablation-{datetime.now(tz=UTC).strftime('%Y-%m-%d')}.md"
    path.write_text(report, encoding="utf-8")

    print("\n" + render_table(rows) + "\n")
    print(f"  report → {path}\n")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
