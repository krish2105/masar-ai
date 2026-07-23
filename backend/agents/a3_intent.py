"""A3 — Intent Router.

Classifies into exactly one of seven intents, with a confidence score. Below
0.6 the query routes to MULTI_HOP, which is the safe default: over-planning
costs one extra retrieval pass, under-planning produces a confidently thin
answer. The asymmetry is the whole reason for the rule.

A keyword pass runs first and short-circuits the model when the signal is
unambiguous — "how much is a 2-zone nol fare" needs no inference. That keeps
the median path fast and means intent routing still works when every provider
is exhausted.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from backend.graph.state import Intent
from backend.services.logging import get_logger

log = get_logger(__name__)

CONFIDENCE_FLOOR = 0.6

# Signals per intent. Arabic terms sit alongside English so the fast path works
# in both languages rather than only for English speakers.
_SIGNALS: dict[Intent, list[str]] = {
    Intent.FARE_COST: [
        r"\bfare\b",
        r"\bcost\b",
        r"\bprice\b",
        r"\bcheap(er|est)?\b",
        r"\bexpensive\b",
        r"\bnol\b",
        r"\bsalik\b",
        r"\btoll\b",
        r"\bzone[s]?\b",
        r"\bAED\b",
        r"\bdirham\b",
        r"\bhow much\b",
        r"\bmonthly (cost|pass)\b",
        r"\bbudget\b",
        r"أجرة",
        r"سعر",
        r"تكلفة",
        r"أرخص",
        r"كم يكلف",
        r"نول",
        r"سالك",
        r"درهم",
    ],
    Intent.NETWORK_ANALYTICS: [
        r"\bridership\b",
        r"\btrend\b",
        r"\bbusiest\b",
        r"\bmost used\b",
        r"\bpassengers?\b",
        r"\bhow many (trips|passengers|people)\b",
        r"\bgrowth\b",
        r"\bcompare\b",
        r"\bmodal split\b",
        r"\butili[sz]ation\b",
        r"\bstatistics\b",
        r"\btop \d+\b",
        r"\bover time\b",
        r"\bper month\b",
        r"\bannual\b",
        r"ازدحام",
        r"الأكثر",
        r"عدد الركاب",
        r"إحصائيات",
        r"اتجاه",
    ],
    Intent.GEOSPATIAL: [
        r"\bnearest\b",
        r"\bclosest\b",
        r"\bnear\b",
        r"\bwithin \d+\s*(km|m|metre)",
        r"\bhow far\b",
        r"\bdistance\b",
        r"\bwalking\b",
        r"\baround\b",
        r"\bcatchment\b",
        r"أقرب",
        r"قريب",
        r"المسافة",
        r"كم تبعد",
    ],
    Intent.JOURNEY_PLANNING: [
        r"\bhow (do|can) i get\b",
        r"\bfrom\b.*\bto\b",
        r"\bconnect(s|ion)?\b",
        r"\broute[s]? (to|from|between)\b",
        r"\bwhich (bus|metro|tram|line)\b",
        r"\binterchange\b",
        r"\btransfer\b",
        r"\bserve[s]?\b",
        r"\bgo(es)? to\b",
        r"كيف أصل",
        r"من .* إلى",
        r"أي خط",
        r"يربط",
    ],
    Intent.SERVICE_INFO: [
        r"\bhow do i (get|apply|replace|renew)\b",
        r"\bwhat documents?\b",
        r"\brequire(d|ment)\b",
        r"\bopening hours\b",
        r"\beligib",
        r"\bcard type\b",
        r"\bwhat is\b.*\b(nol|salik|zone)\b",
        r"\bexplain\b",
        r"\bdifference between\b",
        r"ما هي",
        r"كيف أحصل",
        r"المستندات",
        r"ساعات العمل",
    ],
}

_COMPILED = {
    intent: [re.compile(p, re.IGNORECASE) for p in patterns]
    for intent, patterns in _SIGNALS.items()
}

_SYSTEM_PROMPT = """You classify questions for a Dubai public-transport data assistant.

Return JSON only:
{"intent": "<LABEL>", "confidence": 0.0-1.0, "reasoning": "<one short sentence>"}

Labels:
- JOURNEY_PLANNING  routes, connections, which service goes where, interchanges
- FARE_COST         fares, nol, Salik, zones, cost comparisons, monthly budgets
- SERVICE_INFO      how a service works, what a term means, requirements, eligibility
- NETWORK_ANALYTICS ridership, trends, busiest, modal split, utilisation, statistics
- GEOSPATIAL        nearest/closest, distance, catchment, what is near a place
- MULTI_HOP         needs two or more of the above to answer properly
- OUT_OF_SCOPE      not about Dubai transport at all

Choose MULTI_HOP when the question genuinely needs two different kinds of
evidence — for example a cost comparison AND a ridership trend. Do not choose it
merely because a question is long.

Be honest about confidence. Below 0.6 means you are unsure."""


@dataclass(slots=True)
class IntentResult:
    intent: Intent
    confidence: float
    reasoning: str = ""
    method: str = "keyword"
    signals: dict[str, int] = field(default_factory=dict)
    routed_to_multihop: bool = False
    """True when low confidence forced the safe default — visible in the trace."""


def score_keywords(text: str) -> dict[Intent, int]:
    return {
        intent: sum(1 for pattern in patterns if pattern.search(text))
        for intent, patterns in _COMPILED.items()
    }


class IntentAgent:
    def __init__(self, router=None) -> None:
        self.router = router

    def classify_keywords(self, text: str) -> IntentResult:
        scores = score_keywords(text)
        hits = {i: s for i, s in scores.items() if s > 0}
        signals = {str(i): s for i, s in scores.items() if s > 0}

        if not hits:
            return IntentResult(
                intent=Intent.MULTI_HOP,
                confidence=0.0,
                method="keyword",
                reasoning="no intent signals matched",
                signals=signals,
            )

        ranked = sorted(hits.items(), key=lambda kv: kv[1], reverse=True)
        top_intent, top_score = ranked[0]

        # Two intents both firing strongly is the definition of multi-hop.
        if len(ranked) > 1 and ranked[1][1] >= 2 and top_score >= 2:
            return IntentResult(
                intent=Intent.MULTI_HOP,
                confidence=0.75,
                method="keyword",
                reasoning=f"strong signals for both {ranked[0][0]} and {ranked[1][0]}",
                signals=signals,
            )

        runner_up = ranked[1][1] if len(ranked) > 1 else 0
        margin = top_score - runner_up
        confidence = min(0.95, 0.45 + 0.15 * top_score + 0.1 * margin)

        return IntentResult(
            intent=top_intent,
            confidence=round(confidence, 2),
            method="keyword",
            reasoning=f"{top_score} keyword signals for {top_intent}",
            signals=signals,
        )

    async def run(self, text: str) -> IntentResult:
        keyword_result = self.classify_keywords(text)

        # Confident keyword match: skip the model entirely.
        if keyword_result.confidence >= 0.8 or self.router is None:
            return self._apply_floor(keyword_result)

        try:
            payload, completion = await self.router.complete_json(
                "routing",
                [
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": text},
                ],
            )
            raw = str(payload.get("intent", "")).strip().upper()
            try:
                intent = Intent(raw)
            except ValueError:
                log.warning("intent.unknown_label", label=raw)
                return self._apply_floor(keyword_result)

            confidence = float(payload.get("confidence", 0.5))
            result = IntentResult(
                intent=intent,
                confidence=round(max(0.0, min(1.0, confidence)), 2),
                reasoning=str(payload.get("reasoning", ""))[:200],
                method=f"model:{completion.provider}",
                signals=keyword_result.signals,
            )
            log.info(
                "intent.classified",
                intent=str(intent),
                confidence=result.confidence,
                method=result.method,
            )
            return self._apply_floor(result)

        except Exception as exc:
            log.warning("intent.model_failed", error=f"{type(exc).__name__}: {exc}")
            return self._apply_floor(keyword_result)

    @staticmethod
    def _apply_floor(result: IntentResult) -> IntentResult:
        """Below the floor, plan for more rather than less.

        Over-planning costs one extra retrieval pass. Under-planning produces a
        confident answer built on half the evidence, which is far worse.
        """
        if result.confidence < CONFIDENCE_FLOOR and result.intent != Intent.OUT_OF_SCOPE:
            log.info(
                "intent.below_floor",
                original=str(result.intent),
                confidence=result.confidence,
                routed_to="MULTI_HOP",
            )
            return IntentResult(
                intent=Intent.MULTI_HOP,
                confidence=result.confidence,
                reasoning=(
                    f"confidence {result.confidence} below {CONFIDENCE_FLOOR}; "
                    f"routed from {result.intent} to MULTI_HOP as the safe default"
                ),
                method=result.method,
                signals=result.signals,
                routed_to_multihop=True,
            )
        return result
