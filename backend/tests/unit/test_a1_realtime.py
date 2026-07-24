"""A1 guardrail — distinguishing live-vehicle questions from static geography.

Found during a per-intent evaluation sweep: "Where is the nearest taxi stand to
Dubai Mall?" was redirected as a real-time query and never reached the graph.
The rule matched `where is …` followed by any transit noun, which cannot tell
"where is this *vehicle* right now" (genuinely unanswerable — RTA publishes no
live feed) from "where is this *station*" (trivially answerable — the warehouse
holds its latitude and longitude).

Blocking a whole answerable question class is a worse failure than the one the
rule was written to prevent, because the redirect is confidently wrong: it tells
the user the data does not exist when it does.

The reverse case matters too — journey *duration* must still be caught, since
Masar holds no timetables and any duration it produced would be invented.
"""

from __future__ import annotations

import pytest

from backend.agents.a1_guardrail import GuardrailAgent


@pytest.fixture
def guard() -> GuardrailAgent:
    return GuardrailAgent()


class TestStaticLocationIsAnswerable:
    """These ask where a fixed thing is. The warehouse has coordinates."""

    @pytest.mark.parametrize(
        "question",
        [
            "Where is Union metro station?",
            "Where is the nearest taxi stand to Dubai Mall?",
            "Where is the nearest bus stop?",
            "Where is BurJuman station located?",
            "Where are the tram stations in Dubai?",
            "أين تقع محطة مترو الاتحاد؟",
            "Where is the Salik gate on Sheikh Zayed Road?",
        ],
    )
    def test_static_location_questions_are_allowed(
        self, guard: GuardrailAgent, question: str
    ) -> None:
        result = guard.check_rules(question)
        assert result.reason != "realtime_unavailable", (
            f"{question!r} asks where a fixed place is — the warehouse holds its "
            f"coordinates. Redirecting it tells the user the data does not exist "
            f"when it does. Matched: {result.matched_rules}"
        )


class TestLiveVehicleIsNotAnswerable:
    """These ask about a moving thing, or about now. RTA publishes no live feed."""

    @pytest.mark.parametrize(
        "question",
        [
            "Where is bus route 13 right now?",
            "Where is my bus?",
            "Track the metro for me",
            "What is the current position of the tram?",
            "When is the next metro at Union?",
            "Is there a delay on the Red Line today?",
            "Show me live bus locations",
        ],
    )
    def test_live_questions_are_redirected(
        self, guard: GuardrailAgent, question: str
    ) -> None:
        result = guard.check_rules(question)
        assert result.reason == "realtime_unavailable", (
            f"{question!r} asks about live state, which RTA does not publish. "
            f"Answering it would mean inventing data. Got: {result.reason}"
        )

    def test_redirect_explains_rather_than_refuses(self, guard: GuardrailAgent) -> None:
        result = guard.check_rules("Where is bus route 13 right now?")
        assert "not publish" in result.redirect_message_en
        assert result.redirect_message_ar
        # It must also offer the alternative, not just decline.
        assert any(w in result.redirect_message_en.lower() for w in ("can do", "routes serve"))


class TestJourneyDuration:
    """Masar holds no timetables. A duration would be fabricated."""

    @pytest.mark.parametrize(
        "question",
        [
            "How long does it take from Union to BurJuman?",
            "How long does the metro take from Deira to Marina?",
            "How long will the bus take?",
            "What is the journey time from Al Qusais to Business Bay?",
            "How many minutes from Union to Airport Terminal 3?",
        ],
    )
    def test_duration_questions_are_redirected(
        self, guard: GuardrailAgent, question: str
    ) -> None:
        result = guard.check_rules(question)
        assert result.reason == "realtime_unavailable", (
            f"{question!r} asks for a journey duration. Masar has no timetables "
            f"or speeds, so any answer would be invented. Got: {result.reason}"
        )

    @pytest.mark.parametrize(
        "question",
        [
            "How long is the Red Line?",
            "How many stops does route 13 have?",
            "How far is Union from BurJuman?",
        ],
    )
    def test_distance_and_count_questions_are_allowed(
        self, guard: GuardrailAgent, question: str
    ) -> None:
        """Length, stop count and distance are all in the warehouse."""
        result = guard.check_rules(question)
        assert result.reason != "realtime_unavailable"


class TestAnswerableQuestionsStillPass:
    @pytest.mark.parametrize(
        "question",
        [
            "Which fare zone is Union metro station in?",
            "Which metro station is busiest?",
            "How much is a 2-zone nol fare?",
            "Which bus routes serve Union metro station?",
            "أي محطة مترو هي الأكثر ازدحاماً؟",
        ],
    )
    def test_core_questions_are_allowed(
        self, guard: GuardrailAgent, question: str
    ) -> None:
        result = guard.check_rules(question)
        assert result.verdict in ("allow", "escalate"), (
            f"{question!r} is a core capability. Got {result.verdict} / {result.reason}"
        )
