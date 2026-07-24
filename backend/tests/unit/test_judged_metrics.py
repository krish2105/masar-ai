"""Native RAGAS-style judged metrics.

The pure aggregation is checked directly; the async metric functions are checked
against a fake judge and fake embedder, so the prompt → parse → aggregate flow is
proven with no cloud call and no model download.
"""

from __future__ import annotations

import pytest

from backend.tests.golden.judged_metrics import (
    Sample,
    answer_relevancy,
    average_precision,
    context_precision,
    cosine,
    evaluate_samples,
    faithfulness,
    faithfulness_from_verdicts,
    relevancy_from_cosines,
)


class TestPureAggregation:
    def test_faithfulness_ratio(self) -> None:
        assert faithfulness_from_verdicts([True, True, False]) == pytest.approx(2 / 3)
        assert faithfulness_from_verdicts([True, True]) == 1.0
        assert faithfulness_from_verdicts([]) == 0.0  # nothing to stand on

    def test_average_precision_rewards_early_relevance(self) -> None:
        # [rel, not, rel] → (1/1 + 2/3) / 2
        assert average_precision([True, False, True]) == pytest.approx((1.0 + 2 / 3) / 2)
        assert average_precision([True, True]) == 1.0
        assert average_precision([False, False]) == 0.0
        assert average_precision([]) == 0.0
        # A relevant context ranked last scores worse than ranked first.
        assert average_precision([False, True]) < average_precision([True, False])

    def test_cosine(self) -> None:
        assert cosine([1, 0], [1, 0]) == pytest.approx(1.0)
        assert cosine([1, 0], [0, 1]) == pytest.approx(0.0)
        assert cosine([0, 0], [1, 1]) == 0.0  # zero vector guarded

    def test_relevancy_mean_clamped(self) -> None:
        assert relevancy_from_cosines([0.8, 0.6]) == pytest.approx(0.7)
        assert relevancy_from_cosines([]) == 0.0
        assert relevancy_from_cosines([-0.5, -0.5]) == 0.0  # clamped to >= 0


# ---- fakes -----------------------------------------------------------------


def _fake_judge(responses: dict[str, object]):
    """A judge that returns a canned payload chosen by the system prompt."""

    async def judge(task_class: str, messages: list[dict[str, str]]):
        system = messages[0]["content"].lower()
        if "atomic factual claims" in system:
            return responses["faith"], None
        if "questions it most directly answers" in system:
            return responses["relevancy"], None
        if "useful for answering" in system:
            return responses["precision"], None
        raise AssertionError(f"unexpected judge prompt: {system[:40]}")

    return judge


def _fake_embed_identical(texts):
    # Every text maps to the same vector → cosine 1.0 with the question.
    return [[1.0, 0.0, 0.0] for _ in texts]


@pytest.mark.asyncio
async def test_faithfulness_from_judge() -> None:
    judge = _fake_judge(
        {
            "faith": {
                "claims": [{"claim": "a", "supported": True}, {"claim": "b", "supported": False}]
            }
        }
    )
    s = Sample(question="q", answer="a and b", contexts=["ctx"])
    assert await faithfulness(judge, s) == 0.5


@pytest.mark.asyncio
async def test_faithfulness_empty_answer_abstains() -> None:
    judge = _fake_judge({})  # must not be called
    assert await faithfulness(judge, Sample(question="q", answer="   ", contexts=["c"])) == 0.0


@pytest.mark.asyncio
async def test_answer_relevancy_from_embeddings() -> None:
    judge = _fake_judge({"relevancy": {"questions": ["q1", "q2"]}})
    s = Sample(question="q", answer="an answer", contexts=[])
    got = await answer_relevancy(judge, _fake_embed_identical, s)
    assert got == pytest.approx(1.0)  # identical embeddings → perfect relevancy


@pytest.mark.asyncio
async def test_context_precision_from_judge() -> None:
    judge = _fake_judge({"precision": {"relevant": [True, False, True]}})
    s = Sample(question="q", answer="a", contexts=["c1", "c2", "c3"])
    assert await context_precision(judge, s) == pytest.approx((1.0 + 2 / 3) / 2)


@pytest.mark.asyncio
async def test_context_precision_empty_contexts_abstains() -> None:
    judge = _fake_judge({})
    assert await context_precision(judge, Sample("q", "a", [])) == 0.0


@pytest.mark.asyncio
async def test_evaluate_samples_aggregates_by_language() -> None:
    judge = _fake_judge(
        {
            "faith": {"claims": [{"claim": "a", "supported": True}]},
            "relevancy": {"questions": ["q1"]},
            "precision": {"relevant": [True]},
        }
    )
    samples = [
        Sample("qa", "ans", ["c"], lang="en"),
        Sample("qb", "ans", ["c"], lang="ar"),
    ]
    out = await evaluate_samples(judge, _fake_embed_identical, samples)
    assert out["faithfulness"] == 1.0
    assert out["context_precision"] == 1.0
    assert out["n"] == 2
    assert set(out["by_language"]) == {"en", "ar"}
    assert out["by_language"]["ar"]["n"] == 1
