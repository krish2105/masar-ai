"""Reciprocal Rank Fusion (A6).

The property that matters for the ablation study in §8.3 is that fusion beats
either retriever alone on documents both agree about, while still surfacing
documents only one of them found. These tests pin that behaviour down.
"""

from __future__ import annotations

import pytest

from backend.retrieval.rrf import DEFAULT_K, reciprocal_rank_fusion, weighted_rrf

ident = lambda x: x  # noqa: E731


class TestFusionBasics:
    def test_single_list_preserves_order(self) -> None:
        fused = reciprocal_rank_fusion({"dense": ["a", "b", "c"]}, key_fn=ident)
        assert [r.key for r in fused] == ["a", "b", "c"]

    def test_document_found_by_both_outranks_one_found_by_one(self) -> None:
        """The core hybrid claim: agreement between retrievers is signal."""
        fused = reciprocal_rank_fusion(
            {"dense": ["shared", "dense_only"], "sparse": ["shared", "sparse_only"]},
            key_fn=ident,
        )
        assert fused[0].key == "shared"
        assert fused[0].found_by_all is True

    def test_exact_match_missed_by_dense_still_surfaces(self) -> None:
        """Route codes like F27 are exactly what dense embeddings miss and
        lexical search nails — the reason hybrid exists at all."""
        fused = reciprocal_rank_fusion(
            {"dense": ["about_buses", "about_metro"], "sparse": ["route_F27"]},
            key_fn=ident,
        )
        assert "route_F27" in [r.key for r in fused]

    def test_scores_are_descending(self) -> None:
        fused = reciprocal_rank_fusion(
            {"dense": ["a", "b", "c", "d"], "sparse": ["d", "c", "b", "a"]},
            key_fn=ident,
        )
        scores = [r.score for r in fused]
        assert scores == sorted(scores, reverse=True)

    def test_score_matches_the_formula(self) -> None:
        fused = reciprocal_rank_fusion({"dense": ["a"], "sparse": ["a"]}, key_fn=ident, k=60)
        assert fused[0].score == pytest.approx(2 * (1 / 61))

    def test_empty_input_returns_empty(self) -> None:
        assert reciprocal_rank_fusion({}, key_fn=ident) == []

    def test_empty_lists_are_tolerated(self) -> None:
        fused = reciprocal_rank_fusion({"dense": [], "sparse": ["a"]}, key_fn=ident)
        assert [r.key for r in fused] == ["a"]


class TestProvenance:
    def test_per_retriever_ranks_are_retained(self) -> None:
        """The trace viewer explains *why* something ranked where it did."""
        fused = reciprocal_rank_fusion({"dense": ["x", "a"], "sparse": ["a", "y"]}, key_fn=ident)
        top = next(r for r in fused if r.key == "a")
        assert top.ranks == {"dense": 2, "sparse": 1}
        assert set(top.retrievers) == {"dense", "sparse"}

    def test_single_retriever_document_is_marked(self) -> None:
        fused = reciprocal_rank_fusion({"dense": ["a"], "sparse": ["b"]}, key_fn=ident)
        assert all(r.found_by_all is False for r in fused)

    def test_contributions_sum_to_score(self) -> None:
        fused = reciprocal_rank_fusion({"dense": ["a", "b"], "sparse": ["b", "a"]}, key_fn=ident)
        for result in fused:
            assert result.score == pytest.approx(sum(result.contributions.values()))


class TestWeighting:
    def test_sparse_weight_promotes_lexical_hits(self) -> None:
        heavy_sparse = weighted_rrf(["dense_hit"], ["sparse_hit"], key_fn=ident, sparse_weight=5.0)
        assert heavy_sparse[0].key == "sparse_hit"

    def test_dense_weight_promotes_semantic_hits(self) -> None:
        heavy_dense = weighted_rrf(["dense_hit"], ["sparse_hit"], key_fn=ident, dense_weight=5.0)
        assert heavy_dense[0].key == "dense_hit"

    def test_equal_weights_are_symmetric(self) -> None:
        fused = weighted_rrf(["a"], ["b"], key_fn=ident)
        assert fused[0].score == pytest.approx(fused[1].score)


class TestKParameter:
    def test_larger_k_flattens_rank_influence(self) -> None:
        small = reciprocal_rank_fusion({"d": ["a", "b"]}, key_fn=ident, k=1)
        large = reciprocal_rank_fusion({"d": ["a", "b"]}, key_fn=ident, k=1000)
        small_gap = small[0].score - small[1].score
        large_gap = large[0].score - large[1].score
        assert large_gap < small_gap

    def test_default_k_is_sixty(self) -> None:
        assert DEFAULT_K == 60

    def test_invalid_k_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="k must be"):
            reciprocal_rank_fusion({"d": ["a"]}, key_fn=ident, k=0)


class TestDeterminism:
    def test_ordering_is_stable_across_runs(self) -> None:
        """The golden set compares against this ordering, so ties must not wobble."""
        lists = {"dense": ["a", "b", "c"], "sparse": ["c", "b", "a"]}
        runs = [[r.key for r in reciprocal_rank_fusion(lists, key_fn=ident)] for _ in range(5)]
        assert all(run == runs[0] for run in runs)

    def test_duplicate_within_one_list_keeps_best_rank(self) -> None:
        fused = reciprocal_rank_fusion({"dense": ["a", "b", "a"]}, key_fn=ident)
        top = next(r for r in fused if r.key == "a")
        assert top.ranks["dense"] == 1


class TestRealisticShape:
    def test_key_fn_deduplicates_structured_items(self) -> None:
        dense = [{"id": 1, "text": "metro"}, {"id": 2, "text": "bus"}]
        sparse = [{"id": 2, "text": "bus"}, {"id": 3, "text": "tram"}]
        fused = reciprocal_rank_fusion({"dense": dense, "sparse": sparse}, key_fn=lambda d: d["id"])
        assert len(fused) == 3
        assert next(r for r in fused if r.key == 2).found_by_all is True

    def test_top_n_truncates(self) -> None:
        fused = reciprocal_rank_fusion({"dense": list("abcdefghij")}, key_fn=ident, top_n=3)
        assert len(fused) == 3
