"""Reciprocal Rank Fusion.

Dense and sparse retrieval produce scores on incomparable scales: pgvector
returns a cosine distance, Postgres FTS returns a `ts_rank_cd` value with no
fixed range. Normalising them against each other requires assumptions that do
not hold across queries — a query with one strong lexical hit and a query with
twenty weak ones would normalise to wildly different distributions.

RRF sidesteps this entirely by fusing on *rank* rather than score:

    RRF(d) = Σ_r  1 / (k + rank_r(d))

Only ordering matters, so no calibration between retrievers is needed. `k`
damps the influence of top ranks; k=60 is the value from the original Cormack
et al. work and the one §5.3 specifies.

Pure functions, no I/O — so the fusion behaviour is testable independently of a
running database.
"""

from __future__ import annotations

from collections.abc import Hashable, Sequence
from dataclasses import dataclass, field
from typing import Generic, TypeVar

DEFAULT_K = 60

T = TypeVar("T")


@dataclass(slots=True)
class FusedResult(Generic[T]):
    """One document with its fused score and the per-retriever ranks behind it.

    The per-retriever detail is retained rather than discarded because the trace
    viewer shows *why* an item ranked where it did — "found by lexical search at
    rank 2, missed entirely by dense" is the kind of explanation that makes the
    hybrid argument concrete instead of asserted.
    """

    key: Hashable
    item: T
    score: float
    ranks: dict[str, int] = field(default_factory=dict)
    contributions: dict[str, float] = field(default_factory=dict)

    @property
    def retrievers(self) -> list[str]:
        return sorted(self.ranks)

    @property
    def found_by_all(self) -> bool:
        return len(self.ranks) > 1


def reciprocal_rank_fusion(
    ranked_lists: dict[str, Sequence[T]],
    *,
    key_fn,
    k: int = DEFAULT_K,
    weights: dict[str, float] | None = None,
    top_n: int | None = None,
) -> list[FusedResult[T]]:
    """Fuse several ranked lists into one.

    Args:
        ranked_lists: retriever name → results, best first.
        key_fn: extracts a stable identity from an item, so the same document
            found by two retrievers is recognised as one document.
        k: RRF damping constant.
        weights: optional per-retriever multiplier. Absent retrievers weigh 1.0.
        top_n: truncate the fused output.

    Returns:
        Results sorted by fused score, descending. Ties break on the best rank
        achieved in any single retriever, so the ordering is deterministic —
        which matters because the golden set compares against it.

    >>> lists = {"dense": ["a", "b", "c"], "sparse": ["c", "a", "d"]}
    >>> [r.key for r in reciprocal_rank_fusion(lists, key_fn=lambda x: x)][:2]
    ['a', 'c']
    """
    if k < 1:
        raise ValueError(f"k must be >= 1, got {k}")

    weights = weights or {}
    accumulator: dict[Hashable, FusedResult[T]] = {}

    for retriever, results in ranked_lists.items():
        weight = weights.get(retriever, 1.0)
        for position, item in enumerate(results, start=1):
            key = key_fn(item)
            contribution = weight / (k + position)

            existing = accumulator.get(key)
            if existing is None:
                accumulator[key] = FusedResult(
                    key=key,
                    item=item,
                    score=contribution,
                    ranks={retriever: position},
                    contributions={retriever: contribution},
                )
            else:
                existing.score += contribution
                # A retriever can legitimately return a duplicate; keep its best rank.
                if position < existing.ranks.get(retriever, position + 1):
                    existing.ranks[retriever] = position
                    existing.contributions[retriever] = contribution
                else:
                    existing.ranks.setdefault(retriever, position)
                    existing.contributions.setdefault(retriever, contribution)

    fused = sorted(
        accumulator.values(),
        key=lambda r: (-r.score, min(r.ranks.values()), str(r.key)),
    )
    return fused[:top_n] if top_n is not None else fused


def weighted_rrf(
    dense: Sequence[T],
    sparse: Sequence[T],
    *,
    key_fn,
    k: int = DEFAULT_K,
    dense_weight: float = 1.0,
    sparse_weight: float = 1.0,
    top_n: int | None = None,
) -> list[FusedResult[T]]:
    """The two-retriever case Masar actually runs.

    Weights default to parity. Tilting toward sparse helps on queries dominated
    by exact identifiers — route "F27", "Al Qusais", a zone id — where dense
    embeddings are reliably fuzzy; tilting toward dense helps on paraphrase.
    A5 sets these per sub-task.
    """
    return reciprocal_rank_fusion(
        {"dense": dense, "sparse": sparse},
        key_fn=key_fn,
        k=k,
        weights={"dense": dense_weight, "sparse": sparse_weight},
        top_n=top_n,
    )
