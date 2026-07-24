"""A12 scoring axes.

These tests exist because a real evaluation run had 8 of 8 turns exhaust the
re-plan cap. Investigation found three distinct defects, all sharing one shape:
**a deterministic scorer that cannot measure its axis still returned a number,
and because A12 takes `min(model, deterministic)`, that number overrode a sound
model judgement.**

1. `coverage` measured lexical token overlap between question and evidence. For
   an Arabic question against English evidence — which is precisely what a
   cross-lingual embedding model is *for* — overlap is zero by construction, so
   every Arabic question was guaranteed to exhaust the cap.
2. `recency` on a non-time-sensitive question is not a meaningful axis, but the
   model still scored it (0.5 on "What does a Salik gate crossing cost?") and
   `min()` let that fail an otherwise-strong bundle.
3. English questions lost coverage for framing words the answer has no reason to
   repeat ("options", "reach", "get").

The fix is that a scorer reports whether it is **applicable**. An inapplicable
axis abstains and the other instrument is used alone.
"""

from __future__ import annotations

import pytest

from backend.agents.a12_grader import (
    DEFAULT_THRESHOLD,
    _coverage_score,
    _recency_score,
)
from backend.graph.state import Evidence, EvidenceType, Source


def ev(text: str, kind: EvidenceType = EvidenceType.SQL_RESULT) -> Evidence:
    return Evidence(
        content=text,
        evidence_type=kind,
        source=Source(id="", type=kind, dataset_or_doc="dim_station", source_url=""),
    )


UNION_EN = ev(
    "Union Metro Station is a Metro station in Dubai on the Red Metro line in fare zone 5."
)
ROUTE_EN = ev("Route 13 is a Dubai bus route of type Urban. It serves 42 stops.")
IRRELEVANT = ev("Dubai Taxi Corporation reported 613 limousine drivers in March 2022.")


class TestCoverageApplicability:
    """The defect that guaranteed every Arabic question re-planned."""

    def test_arabic_question_against_english_evidence_abstains(self) -> None:
        score = _coverage_score(
            "ما هي خطوط الحافلات التي تخدم محطة مترو الاتحاد؟", [UNION_EN, ROUTE_EN]
        )
        assert score.applicable is False, (
            "Lexical overlap has no signal across scripts. Reporting a number "
            "here — 0.0 — is what forced every Arabic question to the cycle cap."
        )

    def test_english_question_against_english_evidence_applies(self) -> None:
        score = _coverage_score("Which fare zone is Union metro station in?", [UNION_EN])
        assert score.applicable is True
        assert score.value >= 0.8

    def test_arabic_question_against_arabic_evidence_applies(self) -> None:
        arabic_ev = ev("محطة الاتحاد هي محطة مترو في دبي على الخط الأحمر في منطقة الأجرة 5.")
        score = _coverage_score("ما هي منطقة الأجرة لمحطة الاتحاد؟", [arabic_ev])
        assert score.applicable is True

    def test_abstention_is_not_a_free_pass(self) -> None:
        """Abstaining must not mean 'sufficient' — it means 'use the other
        instrument'. The value is still reported for the trace."""
        score = _coverage_score("ما هي خطوط الحافلات؟", [UNION_EN])
        assert 0.0 <= score.value <= 1.0
        assert score.detail


class TestCoverageFramingWords:
    def test_question_framing_words_do_not_count_against_coverage(self) -> None:
        """ "options", "reach", "using" are how a person phrases a question, not
        content the evidence must echo."""
        score = _coverage_score(
            "What are my options to reach Expo City using public transport?",
            [
                ev("Expo 2020 Metro Station is on the Red Metro line in fare zone 1."),
                ev("Route F55 serves Expo City with 18 stops."),
            ],
        )
        assert score.applicable is True
        assert score.value >= DEFAULT_THRESHOLD, f"scored {score.value:.3f}: {score.detail}"

    def test_get_is_not_a_content_term(self) -> None:
        score = _coverage_score(
            "How do I get to Union station?",
            [ev("Union Metro Station is on the Red Metro line.")],
        )
        assert score.value >= DEFAULT_THRESHOLD

    def test_irrelevant_evidence_still_scores_low(self) -> None:
        """The axis must remain capable of failing, or it is decorative."""
        score = _coverage_score("Which fare zone is Union metro station in?", [IRRELEVANT])
        assert score.applicable is True
        assert score.value < DEFAULT_THRESHOLD


class TestRecencyApplicability:
    """The defect that failed FARE_COST on an otherwise-strong bundle."""

    def test_non_time_sensitive_question_abstains(self) -> None:
        score = _recency_score("What does a Salik gate crossing cost?", [UNION_EN])
        assert score.applicable is False, (
            "Recency is not a meaningful axis for a question that does not ask "
            "about change over time. Scoring it anyway let a 0.5 fail a bundle "
            "with coverage 1.0 and specificity 0.97."
        )

    def test_time_sensitive_question_applies(self) -> None:
        score = _recency_score(
            "How has metro ridership trended recently?",
            [ev("Metro trips in 2026: 1,246,045. Metro trips in 2021: 140,273,450.")],
        )
        assert score.applicable is True

    def test_time_sensitive_question_with_no_dates_scores_low(self) -> None:
        score = _recency_score(
            "What is the current ridership trend?", [ev("Some prose with no dates.")]
        )
        assert score.applicable is True
        assert score.value < DEFAULT_THRESHOLD


class TestDegenerateCases:
    def test_no_evidence_is_zero_and_applicable(self) -> None:
        """No evidence is unambiguously insufficient — that is a real
        measurement, not an abstention."""
        score = _coverage_score("Which metro station is busiest?", [])
        assert score.value == 0.0
        assert score.applicable is True

    def test_empty_question_does_not_crash(self) -> None:
        score = _coverage_score("", [UNION_EN])
        assert 0.0 <= score.value <= 1.0

    def test_scores_are_bounded(self) -> None:
        for question, evidence in [
            ("Which fare zone is Union metro station in?", [UNION_EN, UNION_EN]),
            ("x", [IRRELEVANT]),
            ("", []),
        ]:
            score = _coverage_score(question, evidence)
            assert 0.0 <= score.value <= 1.0


class TestDeterminism:
    def test_same_inputs_give_same_score(self) -> None:
        scores = [
            _coverage_score("Which metro station is busiest?", [UNION_EN, ROUTE_EN]).value
            for _ in range(3)
        ]
        assert all(s == pytest.approx(scores[0], abs=1e-9) for s in scores)
