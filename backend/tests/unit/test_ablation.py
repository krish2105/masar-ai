"""Four-config ablation harness — the parts that need no cloud or database.

The end-to-end run needs the backend + keys; here we prove the config logic, the
component swaps that make each config, and the markdown rendering.
"""

from __future__ import annotations

from types import SimpleNamespace

from backend.graph.state import EvidenceType
from backend.tests.golden.ablation import (
    CONFIGS,
    AblationConfig,
    DenseOnlyRetriever,
    NoOpReranker,
    _chunk_to_evidence,
    config_metrics,
    render_report,
    render_table,
)


def _fake_chunk(chunk_id: str, *, kind: str = "document", score: float = 0.5) -> SimpleNamespace:
    return SimpleNamespace(
        chunk_id=chunk_id,
        raw_text=f"text-{chunk_id}",
        kind=kind,
        source_table=None,
        title=f"title-{chunk_id}",
        doc_id=f"doc-{chunk_id}",
        source_url="https://example.test",
        row_key=None,
        captured_at="2026-01-01",
        retrieved_date="2026-07-24",
        dense_score=0.4,
        sparse_score=0.3,
        score=score,
    )


class TestConfigs:
    def test_four_configs_add_one_capability_each(self) -> None:
        assert [c.name for c in CONFIGS] == ["naive", "hybrid", "hybrid+rerank", "full agentic"]
        assert (CONFIGS[0].fts, CONFIGS[0].rerank, CONFIGS[0].agentic) == (False, False, False)
        assert (CONFIGS[1].fts, CONFIGS[1].rerank, CONFIGS[1].agentic) == (True, False, False)
        assert (CONFIGS[2].fts, CONFIGS[2].rerank, CONFIGS[2].agentic) == (True, True, False)
        assert (CONFIGS[3].fts, CONFIGS[3].rerank, CONFIGS[3].agentic) == (True, True, True)

    def test_non_agentic_config_disables_the_loop(self) -> None:
        assert AblationConfig("x", fts=True, rerank=True, agentic=False).max_cycles == 0

    def test_agentic_config_keeps_the_configured_cap(self) -> None:
        assert AblationConfig("x", fts=True, rerank=True, agentic=True).max_cycles >= 1


class TestNoOpReranker:
    def test_keeps_top_k_in_retrieval_order(self) -> None:
        chunks = [_fake_chunk(str(i), score=1.0 - i / 100) for i in range(10)]
        result = NoOpReranker(top_k=8).run("q", chunks, sub_task_id="t1")
        assert result.kept == 8
        assert result.dropped_below_threshold == 2
        # Order preserved (no rerank), and it is the retrieval order.
        assert [e.content for e in result.evidence] == [f"text-{i}" for i in range(8)]
        assert result.evidence[0].sub_task_id == "t1"

    def test_empty_input(self) -> None:
        result = NoOpReranker().run("q", [])
        assert result.kept == 0 and result.evidence == []


class TestChunkToEvidence:
    def test_row_summary_is_sql_result(self) -> None:
        ev = _chunk_to_evidence(_fake_chunk("1", kind="row_summary"), "t1")
        assert ev.evidence_type == EvidenceType.SQL_RESULT

    def test_document_is_document(self) -> None:
        ev = _chunk_to_evidence(_fake_chunk("1", kind="document"), "t1")
        assert ev.evidence_type == EvidenceType.DOCUMENT
        assert ev.score == 0.5  # carries the retrieval score, not a rerank score


class TestDenseOnlyRetriever:
    def test_forces_sparse_weight_zero(self) -> None:
        seen: dict[str, object] = {}

        class _Inner:
            def search_multi(self, queries, *, top_k=50, **kwargs):
                seen.update({"queries": queries, "top_k": top_k, **kwargs})
                return ["chunk"]

        wrapped = DenseOnlyRetriever(_Inner())
        out = wrapped.search_multi(["q"], top_k=30)
        assert out == ["chunk"]
        assert seen["sparse_weight"] == 0.0
        assert seen["top_k"] == 30


class TestRendering:
    def test_render_table_has_header_and_rows(self) -> None:
        rows = [
            {
                "config": "naive",
                "pass_rate": 0.7,
                "citation_validity": 1.0,
                "mean_evidence": 3.2,
                "p50_latency_s": 1.1,
                "replan_rate": 0.0,
            }
        ]
        table = render_table(rows)
        assert "| Config |" in table
        assert "| naive |" in table
        assert table.count("\n") == 2  # header, separator, one data row

    def test_render_report_wraps_the_table(self) -> None:
        rows = [config_metrics("naive", [])]  # n=0 config row
        report = render_report(rows, n=0, generated_at="2026-07-24")
        assert "# Ablation study" in report
        assert "| Config |" in report


class TestConfigMetrics:
    def test_empty_results(self) -> None:
        assert config_metrics("naive", []) == {"config": "naive", "n": 0}
