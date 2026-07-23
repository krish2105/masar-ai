"""A12 — Grader. The corrective-RAG loop.

Scores the assembled evidence on four axes, each 0–1:

* **coverage** — does the evidence address every part of the question?
* **specificity** — are there concrete figures and named entities, or only
  general prose?
* **recency** — how current is the underlying data relative to what was asked?
* **source_authority** — dataset rows and deterministic calculations outrank
  generated summaries, which outrank generic documentation.

Any axis below the threshold, with cycles remaining, returns
`sufficient: false` plus **named gaps** — and the Supervisor must produce a
different plan addressing them. At the cycle cap the system answers anyway,
flagged low-confidence, with the limitation stated in the answer text.

Threshold tuning is a real trade-off. Too strict and the loop fires on every
query, tripling latency for no quality gain; too loose and it never corrects,
making the loop decorative. 0.7 was chosen against the golden set.

Deterministic pre-scoring runs first. Some judgements need no model at all — an
empty evidence bundle is insufficient, a bundle containing a successful
calculation is specific — and grading is the highest-volume LLM call in the
system, so short-circuiting it matters.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime

from backend.graph.state import Evidence, EvidenceType, GradeReport
from backend.services.logging import get_logger

log = get_logger(__name__)

DEFAULT_THRESHOLD = 0.7

# Evidence carrying a computed or queried fact is stronger than prose about it.
_AUTHORITY: dict[EvidenceType, float] = {
    EvidenceType.CALC_RESULT: 1.0,
    EvidenceType.SQL_RESULT: 0.95,
    EvidenceType.GEO_RESULT: 0.9,
    EvidenceType.API_RESULT: 0.85,
    EvidenceType.DOCUMENT: 0.7,
}

_NUMBER = re.compile(r"\d")
_YEAR = re.compile(r"\b(20[0-2]\d)\b")

_SYSTEM_PROMPT = """You judge whether retrieved evidence is sufficient to answer a
question about Dubai's public transport data.

Return JSON only:
{
  "coverage": 0.0-1.0,
  "specificity": 0.0-1.0,
  "recency": 0.0-1.0,
  "source_authority": 0.0-1.0,
  "sufficient": true|false,
  "gaps": ["specific missing thing", ...],
  "reasoning": "one or two sentences"
}

AXES
coverage         — does the evidence address EVERY part of the question? A
                   two-part question answered in one part scores low.
specificity      — concrete figures, named stations, actual routes? Or only
                   general statements that could apply to anything?
recency          — is the data current enough for what was asked? A trend
                   question needs recent periods; a "what is nol" question does not.
source_authority — database rows and computed figures are strong; generated
                   summaries are moderate; generic prose is weak.

GAPS must be ACTIONABLE. "Need more information" is useless. "No fare zone found
for Al Qusais station" tells the planner exactly what to go and get.

Be strict. A confident answer built on thin evidence is the failure this system
exists to prevent."""


@dataclass(slots=True)
class GradeResult:
    report: GradeReport
    method: str = "deterministic"
    provider: str | None = None
    short_circuited: bool = False
    axis_detail: dict[str, str] = field(default_factory=dict)


def _coverage_score(question: str, evidence: list[Evidence]) -> tuple[float, str]:
    """How much of the question's content vocabulary appears in the evidence."""
    if not evidence:
        return 0.0, "no evidence retrieved"

    stopwords = {
        "the", "a", "an", "is", "are", "was", "were", "and", "or", "of", "to",
        "in", "on", "for", "from", "how", "what", "which", "who", "when", "where",
        "much", "many", "do", "does", "i", "my", "me", "it", "at", "by", "with",
    }
    terms = {
        w for w in re.findall(r"\b\w{3,}\b", question.lower()) if w not in stopwords
    }
    if not terms:
        return 0.6, "question carried no distinctive terms"

    blob = " ".join(e.content for e in evidence).lower()
    found = {t for t in terms if t in blob}
    ratio = len(found) / len(terms)
    missing = sorted(terms - found)[:5]
    detail = f"{len(found)}/{len(terms)} question terms present"
    if missing:
        detail += f"; absent: {', '.join(missing)}"
    return min(1.0, ratio * 1.15), detail


def _specificity_score(evidence: list[Evidence]) -> tuple[float, str]:
    if not evidence:
        return 0.0, "no evidence"
    with_numbers = sum(1 for e in evidence if _NUMBER.search(e.content))
    has_computed = any(
        e.evidence_type in (EvidenceType.CALC_RESULT, EvidenceType.SQL_RESULT)
        for e in evidence
    )
    ratio = with_numbers / len(evidence)
    score = min(1.0, ratio + (0.3 if has_computed else 0.0))
    return score, f"{with_numbers}/{len(evidence)} items carry figures" + (
        "; includes computed or queried values" if has_computed else ""
    )


def _recency_score(question: str, evidence: list[Evidence]) -> tuple[float, str]:
    """Recency matters only when the question is time-sensitive.

    Penalising a "what is a nol card" answer for citing 2022 documentation would
    be nonsense, so the axis is neutral-high unless the question asks about
    trends, current state or a specific recent year.
    """
    time_sensitive = bool(
        re.search(
            r"\b(trend|recent|current|latest|now|today|this year|growth|change|"
            r"20(2[3-9])|اتجاه|حالي|الأخير)\b",
            question,
            re.IGNORECASE,
        )
    )
    if not time_sensitive:
        return 0.85, "question is not time-sensitive"

    years: list[int] = []
    for item in evidence:
        years.extend(int(y) for y in _YEAR.findall(item.content))
        if item.source.captured_at:
            years.extend(int(y) for y in _YEAR.findall(item.source.captured_at))

    if not years:
        return 0.3, "time-sensitive question but evidence carries no dates"

    newest = max(years)
    age = datetime.now(tz=UTC).year - newest
    score = 1.0 if age <= 1 else 0.75 if age <= 2 else 0.5 if age <= 4 else 0.25
    return score, f"newest evidence year {newest} ({age} years old)"


def _authority_score(evidence: list[Evidence]) -> tuple[float, str]:
    if not evidence:
        return 0.0, "no evidence"
    scores = [_AUTHORITY.get(e.evidence_type, 0.5) for e in evidence]
    best = max(scores)
    mean = sum(scores) / len(scores)
    # Weighted toward the strongest item: one authoritative row can carry an
    # answer that a dozen weak documents cannot.
    combined = 0.6 * best + 0.4 * mean
    kinds = ", ".join(sorted({str(e.evidence_type) for e in evidence}))
    return combined, f"evidence types present: {kinds}"


class GraderAgent:
    def __init__(self, router=None, threshold: float = DEFAULT_THRESHOLD) -> None:
        self.router = router
        self.threshold = threshold

    def grade_deterministic(
        self, question: str, evidence: list[Evidence], cycle: int
    ) -> GradeResult:
        coverage, coverage_detail = _coverage_score(question, evidence)
        specificity, specificity_detail = _specificity_score(evidence)
        recency, recency_detail = _recency_score(question, evidence)
        authority, authority_detail = _authority_score(evidence)

        gaps: list[str] = []
        if not evidence:
            gaps.append("No evidence was retrieved at all — every sub-task returned empty.")
        else:
            if coverage < self.threshold:
                gaps.append(f"Evidence does not cover the whole question: {coverage_detail}.")
            if specificity < self.threshold:
                gaps.append(
                    "Evidence is general rather than specific — no concrete figures, "
                    "named stations or routes were retrieved."
                )
            if recency < self.threshold:
                gaps.append(f"Evidence may be too old for a time-sensitive question: {recency_detail}.")
            if authority < self.threshold:
                gaps.append(
                    "Evidence is documentation only — no database rows or computed "
                    "values support the answer."
                )

        report = GradeReport(
            coverage=round(coverage, 3),
            specificity=round(specificity, 3),
            recency=round(recency, 3),
            source_authority=round(authority, 3),
            sufficient=not gaps,
            gaps=gaps,
            reasoning="; ".join(
                [coverage_detail, specificity_detail, recency_detail, authority_detail]
            )[:500],
            cycle=cycle,
        )
        return GradeResult(
            report=report,
            method="deterministic",
            axis_detail={
                "coverage": coverage_detail,
                "specificity": specificity_detail,
                "recency": recency_detail,
                "source_authority": authority_detail,
            },
        )

    async def run(
        self, question: str, evidence: list[Evidence], *, cycle: int = 0
    ) -> GradeResult:
        baseline = self.grade_deterministic(question, evidence, cycle)

        # No evidence is unambiguously insufficient; asking a model wastes a call.
        if not evidence:
            baseline.short_circuited = True
            log.info("grader.short_circuit", reason="no evidence", cycle=cycle)
            return baseline

        if self.router is None:
            return baseline

        bundle = "\n\n".join(
            f"[{i}] type={e.evidence_type} source={e.source.dataset_or_doc} "
            f"captured={e.source.captured_at or 'n/a'}\n{e.content[:600]}"
            for i, e in enumerate(evidence[:12], 1)
        )

        try:
            payload, completion = await self.router.complete_json(
                "grading",
                [
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": f"QUESTION\n{question}\n\nEVIDENCE\n{bundle}",
                    },
                ],
            )
        except Exception as exc:  # noqa: BLE001 — deterministic scores stand
            log.warning("grader.model_failed", error=f"{type(exc).__name__}: {exc}")
            return baseline

        def axis(name: str, fallback: float) -> float:
            try:
                return max(0.0, min(1.0, float(payload.get(name, fallback))))
            except (TypeError, ValueError):
                return fallback

        # Take the lower of model and deterministic on every axis. The
        # deterministic scores cannot be talked into optimism, and the model
        # catches semantic gaps keyword overlap misses — so the conservative
        # combination is stricter than either alone.
        coverage = min(axis("coverage", baseline.report.coverage), baseline.report.coverage)
        specificity = min(axis("specificity", baseline.report.specificity), baseline.report.specificity)
        recency = min(axis("recency", baseline.report.recency), baseline.report.recency)
        authority = min(axis("source_authority", baseline.report.source_authority), baseline.report.source_authority)

        gaps = [str(g)[:300] for g in (payload.get("gaps") or []) if str(g).strip()]
        gaps = list(dict.fromkeys([*gaps, *baseline.report.gaps]))[:6]

        scores = {
            "coverage": coverage,
            "specificity": specificity,
            "recency": recency,
            "source_authority": authority,
        }
        sufficient = all(v >= self.threshold for v in scores.values())
        if not sufficient and not gaps:
            weakest = min(scores, key=lambda k: scores[k])
            gaps = [f"Evidence scored low on {weakest} ({scores[weakest]:.2f}); needs stronger support."]

        report = GradeReport(
            coverage=round(coverage, 3),
            specificity=round(specificity, 3),
            recency=round(recency, 3),
            source_authority=round(authority, 3),
            sufficient=sufficient,
            gaps=[] if sufficient else gaps,
            reasoning=str(payload.get("reasoning", ""))[:500] or baseline.report.reasoning,
            cycle=cycle,
        )

        log.info(
            "grader.scored",
            cycle=cycle,
            sufficient=sufficient,
            weakest=report.weakest_axis,
            scores={k: round(v, 2) for k, v in scores.items()},
            gaps=len(report.gaps),
            provider=completion.provider,
        )
        return GradeResult(
            report=report,
            method=f"model:{completion.provider}",
            provider=completion.provider,
            axis_detail=baseline.axis_detail,
        )
