"""A7 — Reranker. Deterministic; local cross-encoder.

Hybrid retrieval optimises for recall: 50 candidates, some of which are wrong.
A cross-encoder reads query and passage *together* rather than comparing two
independently-computed vectors, so it judges relevance far better than the
retrieval score can — at a cost that only makes sense on a shortlist.

Candidates below the relevance threshold are dropped even when that leaves fewer
than `top_k`. Padding the context with weak passages makes the Grader's job
harder and gives the Synthesiser more opportunities to cite something
irrelevant. A thin clean context is the better failure mode, and A12 exists
precisely to notice when the context is genuinely too thin.
"""

from __future__ import annotations

from dataclasses import dataclass

from backend.graph.state import Evidence, EvidenceType, Source
from backend.retrieval.embedder import rerank
from backend.retrieval.hybrid import RetrievedChunk
from backend.services.logging import get_logger

log = get_logger(__name__)


@dataclass(slots=True)
class RerankResult:
    evidence: list[Evidence]
    candidates_in: int
    kept: int
    dropped_below_threshold: int
    threshold: float


class RerankerAgent:
    def __init__(self, *, top_k: int = 8, threshold: float = 0.35) -> None:
        self.top_k = top_k
        self.threshold = threshold

    def run(
        self,
        query: str,
        chunks: list[RetrievedChunk],
        *,
        sub_task_id: str | None = None,
    ) -> RerankResult:
        if not chunks:
            return RerankResult([], 0, 0, 0, self.threshold)

        ranked = rerank(
            query,
            [c.raw_text for c in chunks],
            top_k=self.top_k,
            threshold=self.threshold,
        )

        evidence: list[Evidence] = []
        for index, score in ranked:
            chunk = chunks[index]
            evidence.append(
                Evidence(
                    content=chunk.raw_text,
                    evidence_type=(
                        EvidenceType.SQL_RESULT
                        if chunk.kind == "row_summary"
                        else EvidenceType.DOCUMENT
                    ),
                    source=Source(
                        id="",  # assigned by A13 so numbering is deterministic
                        type=(
                            EvidenceType.SQL_RESULT
                            if chunk.kind == "row_summary"
                            else EvidenceType.DOCUMENT
                        ),
                        dataset_or_doc=chunk.source_table or chunk.title or chunk.doc_id,
                        source_url=chunk.source_url,
                        row_id_or_chunk_id=chunk.row_key or chunk.chunk_id,
                        captured_at=chunk.captured_at,
                        last_updated=chunk.retrieved_date,
                    ),
                    score=score,
                    sub_task_id=sub_task_id,
                    dense_score=chunk.dense_score,
                    sparse_score=chunk.sparse_score,
                    rerank_score=score,
                )
            )

        dropped = len(chunks) - len(evidence)
        log.info(
            "reranker.run",
            candidates=len(chunks),
            kept=len(evidence),
            dropped=dropped,
            threshold=self.threshold,
        )
        return RerankResult(
            evidence=evidence,
            candidates_in=len(chunks),
            kept=len(evidence),
            dropped_below_threshold=dropped,
            threshold=self.threshold,
        )
