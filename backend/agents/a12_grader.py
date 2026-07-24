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

from backend.ingestion.arabic import has_arabic, has_latin
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


@dataclass(slots=True)
class AxisScore:
    """One axis, plus whether the instrument that produced it had any signal.

    `applicable=False` means "this scorer cannot measure this input" — not
    "this input scored zero". The distinction is load-bearing: an inapplicable
    deterministic score combined with `min()` let a scorer with no signal veto a
    sound model judgement, which is what drove every Arabic question to the
    re-plan cap.
    """

    value: float
    detail: str
    applicable: bool = True


# Words that describe how a question is *asked*, not what it is about. Evidence
# answering "what are my options to reach X" has no reason to contain "options"
# or "reach"; penalising it for that measures the wrong thing.
_FRAMING_WORDS = {
    "the",
    "a",
    "an",
    "is",
    "are",
    "was",
    "were",
    "and",
    "or",
    "of",
    "to",
    "in",
    "on",
    "for",
    "from",
    "how",
    "what",
    "which",
    "who",
    "when",
    "where",
    "much",
    "many",
    "do",
    "does",
    "did",
    "i",
    "my",
    "me",
    "it",
    "at",
    "by",
    "with",
    "get",
    "getting",
    "go",
    "going",
    "reach",
    "take",
    "takes",
    "use",
    "using",
    "options",
    "option",
    "way",
    "ways",
    "there",
    "any",
    "can",
    "could",
    "would",
    "should",
    "please",
    "tell",
    "show",
    "give",
    "know",
    "need",
    "want",
    "about",
    "best",
    "available",
    "possible",
    "public",
    "transport",
    "transportation",
    "dubai",
    "uae",
    "you",
    "your",
}


def _content_terms(text: str) -> set[str]:
    return {w for w in re.findall(r"\b\w{3,}\b", text.lower()) if w not in _FRAMING_WORDS}


def _coverage_score(question: str, evidence: list[Evidence]) -> AxisScore:
    """How much of the question's content appears in the evidence.

    This is a **lexical** measure, and lexical overlap only carries meaning when
    question and evidence share a script. An Arabic question against English
    evidence scores zero by construction — exactly the situation a cross-lingual
    embedding model is designed to produce — so measuring it would penalise the
    architecture working correctly. There, the axis abstains.
    """
    if not evidence:
        # A real measurement, not an abstention: no evidence is insufficient.
        return AxisScore(0.0, "no evidence retrieved", applicable=True)

    blob = " ".join(e.content for e in evidence)
    question_arabic = has_arabic(question)

    if question_arabic and not has_arabic(blob):
        return AxisScore(
            0.0,
            "Arabic question against English evidence — lexical overlap has no "
            "signal across scripts; deferring to the model on this axis",
            applicable=False,
        )
    if not question_arabic and has_arabic(blob) and not has_latin(blob):
        return AxisScore(
            0.0,
            "English question against Arabic-only evidence — lexical overlap has "
            "no signal across scripts; deferring to the model on this axis",
            applicable=False,
        )

    terms = _content_terms(question)
    if not terms:
        return AxisScore(0.0, "question carried no distinctive content terms", applicable=False)

    lowered = blob.lower()
    found = {t for t in terms if t in lowered}
    ratio = len(found) / len(terms)
    missing = sorted(terms - found)[:5]
    detail = f"{len(found)}/{len(terms)} question terms present"
    if missing:
        detail += f"; absent: {', '.join(missing)}"
    return AxisScore(min(1.0, ratio * 1.15), detail)


def _specificity_score(evidence: list[Evidence]) -> AxisScore:
    if not evidence:
        return AxisScore(0.0, "no evidence", applicable=True)
    with_numbers = sum(1 for e in evidence if _NUMBER.search(e.content))
    has_computed = any(
        e.evidence_type in (EvidenceType.CALC_RESULT, EvidenceType.SQL_RESULT) for e in evidence
    )
    ratio = with_numbers / len(evidence)
    value = min(1.0, ratio + (0.3 if has_computed else 0.0))
    detail = f"{with_numbers}/{len(evidence)} items carry figures" + (
        "; includes computed or queried values" if has_computed else ""
    )
    return AxisScore(value, detail)


def _recency_score(question: str, evidence: list[Evidence]) -> AxisScore:
    """Recency, but only where recency is a meaningful question.

    Asking "what does a Salik crossing cost" is not a question about change over
    time, so there is nothing for this axis to measure. It previously returned a
    neutral-high 0.85, which `min()` then let a pessimistic model score of 0.5
    override — failing a bundle whose coverage was 1.0 and specificity 0.97.
    Where the axis does not apply it now abstains outright.
    """
    time_sensitive = bool(
        re.search(
            r"\b(trend|trends|trended|recent|recently|current|currently|latest|now|"
            r"today|trajectory|growth|decline|change|changed|over time|"
            r"20(2[3-9]))\b|اتجاه|حالي|الأخير|تطور",
            question,
            re.IGNORECASE,
        )
    )
    if not time_sensitive:
        return AxisScore(
            1.0,
            "question does not ask about change over time; recency is not a meaningful axis here",
            applicable=False,
        )

    if not evidence:
        return AxisScore(0.0, "no evidence", applicable=True)

    years: list[int] = []
    for item in evidence:
        years.extend(int(y) for y in _YEAR.findall(item.content))
        if item.source.captured_at:
            years.extend(int(y) for y in _YEAR.findall(item.source.captured_at))

    if not years:
        return AxisScore(0.3, "time-sensitive question but evidence carries no dates")

    newest = max(years)
    age = datetime.now(tz=UTC).year - newest
    value = 1.0 if age <= 1 else 0.75 if age <= 2 else 0.5 if age <= 4 else 0.25
    return AxisScore(value, f"newest evidence year {newest} ({age} years old)")


def _authority_score(evidence: list[Evidence]) -> AxisScore:
    if not evidence:
        return AxisScore(0.0, "no evidence", applicable=True)
    scores = [_AUTHORITY.get(e.evidence_type, 0.5) for e in evidence]
    best = max(scores)
    mean = sum(scores) / len(scores)
    # Weighted toward the strongest item: one authoritative row can carry an
    # answer that a dozen weak documents cannot.
    combined = 0.6 * best + 0.4 * mean
    kinds = ", ".join(sorted({str(e.evidence_type) for e in evidence}))
    return AxisScore(combined, f"evidence types present: {kinds}")


class GraderAgent:
    def __init__(self, router=None, threshold: float = DEFAULT_THRESHOLD) -> None:
        self.router = router
        self.threshold = threshold

    def score_axes(self, question: str, evidence: list[Evidence]) -> dict[str, AxisScore]:
        return {
            "coverage": _coverage_score(question, evidence),
            "specificity": _specificity_score(evidence),
            "recency": _recency_score(question, evidence),
            "source_authority": _authority_score(evidence),
        }

    def grade_deterministic(
        self, question: str, evidence: list[Evidence], cycle: int
    ) -> GradeResult:
        axes = self.score_axes(question, evidence)

        gaps: list[str] = []
        if not evidence:
            gaps.append("No evidence was retrieved at all — every sub-task returned empty.")
        else:
            # An inapplicable axis raises no gap. A scorer with no signal has
            # nothing to complain about.
            if axes["coverage"].applicable and axes["coverage"].value < self.threshold:
                gaps.append(
                    f"Evidence does not cover the whole question: {axes['coverage'].detail}."
                )
            if axes["specificity"].applicable and axes["specificity"].value < self.threshold:
                gaps.append(
                    "Evidence is general rather than specific — no concrete figures, "
                    "named stations or routes were retrieved."
                )
            if axes["recency"].applicable and axes["recency"].value < self.threshold:
                gaps.append(
                    f"Evidence may be too old for a time-sensitive question: "
                    f"{axes['recency'].detail}."
                )
            if (
                axes["source_authority"].applicable
                and axes["source_authority"].value < self.threshold
            ):
                gaps.append(
                    "Evidence is documentation only — no database rows or computed "
                    "values support the answer."
                )

        report = GradeReport(
            coverage=round(axes["coverage"].value, 3),
            specificity=round(axes["specificity"].value, 3),
            recency=round(axes["recency"].value, 3),
            source_authority=round(axes["source_authority"].value, 3),
            sufficient=not gaps,
            gaps=gaps,
            reasoning="; ".join(a.detail for a in axes.values())[:500],
            cycle=cycle,
        )
        return GradeResult(
            report=report,
            method="deterministic",
            axis_detail={name: axis.detail for name, axis in axes.items()},
        )

    async def run(self, question: str, evidence: list[Evidence], *, cycle: int = 0) -> GradeResult:
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
        except Exception as exc:
            log.warning("grader.model_failed", error=f"{type(exc).__name__}: {exc}")
            return baseline

        deterministic = self.score_axes(question, evidence)

        def model_axis(name: str, fallback: float) -> float:
            try:
                return max(0.0, min(1.0, float(payload.get(name, fallback))))
            except (TypeError, ValueError):
                return fallback

        def combine(name: str) -> float:
            """Take the lower of model and deterministic — but only where the
            deterministic scorer actually had signal.

            `min()` is the right conservatism when both instruments measure the
            same thing: the deterministic score cannot be talked into optimism,
            and the model catches semantic gaps lexical overlap misses. It is
            the wrong operation when one instrument is measuring nothing. An
            inapplicable axis abstains and the model's value stands alone;
            otherwise a scorer with no signal vetoes a sound judgement, which is
            what sent every Arabic question to the cycle cap.
            """
            det = deterministic[name]
            model_value = model_axis(name, det.value)
            if not det.applicable:
                return model_value
            return min(model_value, det.value)

        scores = {
            "coverage": combine("coverage"),
            "specificity": combine("specificity"),
            "recency": combine("recency"),
            "source_authority": combine("source_authority"),
        }
        coverage = scores["coverage"]
        specificity = scores["specificity"]
        recency = scores["recency"]
        authority = scores["source_authority"]

        gaps = [str(g)[:300] for g in (payload.get("gaps") or []) if str(g).strip()]
        gaps = list(dict.fromkeys([*gaps, *baseline.report.gaps]))[:6]

        # An axis the deterministic scorer could not measure is excluded from
        # the sufficiency decision entirely when the model also had nothing
        # useful to say about it — recency on a question that is not about time
        # is not a bar to clear.
        judged = {
            name: value
            for name, value in scores.items()
            if deterministic[name].applicable or name != "recency"
        }
        sufficient = all(v >= self.threshold for v in judged.values())
        if not sufficient and not gaps:
            weakest = min(scores, key=lambda k: scores[k])
            gaps = [
                f"Evidence scored low on {weakest} ({scores[weakest]:.2f}); needs stronger support."
            ]

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
