"""RAGAS-style judged metrics, computed natively.

faithfulness, answer relevancy and context precision — the three judged metrics
§8.2 requires — implemented directly against the LLM router and a local embedding
model rather than the `ragas` package. Two reasons: the judge then walks the same
free-tier fallback chain (Groq → Gemini → …) as the rest of the system, and the
aggregation is unit-testable with a stub judge — no cloud call, no model download.

Methodology follows RAGAS:
    faithfulness      = supported claims / total claims in the answer
    answer_relevancy  = mean cosine(question, questions the answer would answer)
    context_precision = mean average precision of relevant contexts, in rank order

Every metric abstains to 0.0 on an empty answer / empty context rather than
inventing a passing score — the same rule the deterministic metrics follow.
"""

from __future__ import annotations

import math
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Any

# (task_class, messages) -> (parsed_json, completion) — matches router.complete_json.
JudgeFn = Callable[[str, list[dict[str, str]]], Awaitable[tuple[dict[str, Any], Any]]]
# texts -> one embedding vector per text.
EmbedFn = Callable[[Sequence[str]], list[list[float]]]

TASK = "judge"


@dataclass
class Sample:
    question: str
    answer: str
    contexts: list[str]
    lang: str = "en"


# =============================================================================
# Pure aggregation — no I/O, unit-tested directly
# =============================================================================


def faithfulness_from_verdicts(verdicts: list[bool]) -> float:
    """Supported fraction of the answer's claims. No claims ⇒ 0.0 (nothing to
    stand on is not faithfulness)."""
    if not verdicts:
        return 0.0
    return sum(1 for v in verdicts if v) / len(verdicts)


def average_precision(relevances: list[bool]) -> float:
    """RAGAS context precision: mean of precision@k over the relevant positions,
    which rewards relevant contexts ranked *early*."""
    hits = 0
    precisions: list[float] = []
    for rank, relevant in enumerate(relevances, start=1):
        if relevant:
            hits += 1
            precisions.append(hits / rank)
    if not precisions:
        return 0.0
    return sum(precisions) / len(precisions)


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def relevancy_from_cosines(cosines: list[float]) -> float:
    if not cosines:
        return 0.0
    return max(0.0, sum(cosines) / len(cosines))


# =============================================================================
# Per-sample metrics — one judge/embed call each
# =============================================================================

_FAITH_SYS = (
    "You verify whether an answer is grounded in its evidence. Break the answer "
    "into atomic factual claims, then judge each claim ONLY against the provided "
    "context. A claim is supported only if the context states or directly implies "
    "it. Ignore hedging, questions, and citation markers like [S1]."
)


def _faith_user(sample: Sample) -> str:
    context = "\n\n".join(f"[{i + 1}] {c}" for i, c in enumerate(sample.contexts)) or "(none)"
    return (
        f"CONTEXT:\n{context}\n\nANSWER:\n{sample.answer}\n\n"
        'Return JSON: {"claims": [{"claim": "<text>", "supported": true|false}, ...]}. '
        "If the answer makes no factual claim, return an empty claims list."
    )


async def faithfulness(judge: JudgeFn, sample: Sample) -> float:
    if not sample.answer.strip():
        return 0.0
    payload, _ = await judge(
        TASK,
        [
            {"role": "system", "content": _FAITH_SYS},
            {"role": "user", "content": _faith_user(sample)},
        ],
    )
    claims = payload.get("claims", [])
    verdicts = [bool(c.get("supported")) for c in claims if isinstance(c, dict)]
    return faithfulness_from_verdicts(verdicts)


_RELEVANCY_SYS = (
    "Given an answer, produce the questions it most directly answers. Return only "
    "questions that the answer fully addresses — a relevant answer yields questions "
    "close to the user's original."
)


async def answer_relevancy(judge: JudgeFn, embed: EmbedFn, sample: Sample, *, n: int = 3) -> float:
    if not sample.answer.strip():
        return 0.0
    payload, _ = await judge(
        TASK,
        [
            {"role": "system", "content": _RELEVANCY_SYS},
            {
                "role": "user",
                "content": (
                    f"ANSWER:\n{sample.answer}\n\n"
                    f'Return JSON: {{"questions": ["<q1>", ... up to {n}]}}.'
                ),
            },
        ],
    )
    generated = [q for q in payload.get("questions", []) if isinstance(q, str) and q.strip()][:n]
    if not generated:
        return 0.0
    vectors = embed([sample.question, *generated])
    origin = vectors[0]
    return relevancy_from_cosines([cosine(origin, v) for v in vectors[1:]])


_PRECISION_SYS = (
    "For each numbered context, decide whether it is useful for answering the "
    "question. Judge each independently. Order of the output must match the input."
)


async def context_precision(judge: JudgeFn, sample: Sample) -> float:
    if not sample.contexts:
        return 0.0
    numbered = "\n\n".join(f"[{i + 1}] {c}" for i, c in enumerate(sample.contexts))
    payload, _ = await judge(
        TASK,
        [
            {"role": "system", "content": _PRECISION_SYS},
            {
                "role": "user",
                "content": (
                    f"QUESTION:\n{sample.question}\n\nCONTEXTS:\n{numbered}\n\n"
                    'Return JSON: {"relevant": [true|false, ...]} — one boolean per '
                    "context, in the same order."
                ),
            },
        ],
    )
    flags = payload.get("relevant", [])
    relevances = [bool(x) for x in flags][: len(sample.contexts)]
    return average_precision(relevances)


# =============================================================================
# Aggregate
# =============================================================================


async def evaluate_samples(judge: JudgeFn, embed: EmbedFn, samples: list[Sample]) -> dict[str, Any]:
    """Run all three metrics over every sample and aggregate (overall + by language)."""
    per_sample: list[dict[str, Any]] = []
    for sample in samples:
        per_sample.append(
            {
                "id_lang": sample.lang,
                "faithfulness": await faithfulness(judge, sample),
                "answer_relevancy": await answer_relevancy(judge, embed, sample),
                "context_precision": await context_precision(judge, sample),
            }
        )

    def mean(metric: str, subset: list[dict[str, Any]] | None = None) -> float | None:
        rows = subset if subset is not None else per_sample
        values = [r[metric] for r in rows]
        return round(sum(values) / len(values), 3) if values else None

    by_language: dict[str, dict[str, float | None]] = {}
    for lang in ("en", "ar"):
        rows = [r for r in per_sample if r["id_lang"] == lang]
        if rows:
            by_language[lang] = {
                "faithfulness": mean("faithfulness", rows),
                "answer_relevancy": mean("answer_relevancy", rows),
                "context_precision": mean("context_precision", rows),
                "n": len(rows),
            }

    return {
        "faithfulness": mean("faithfulness"),
        "answer_relevancy": mean("answer_relevancy"),
        "context_precision": mean("context_precision"),
        "n": len(per_sample),
        "by_language": by_language,
        "judge": "native RAGAS-style — router task class 'judge', local bge-m3 embeddings",
    }
