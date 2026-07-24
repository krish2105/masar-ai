"""A1 — Guardrail. Deterministic rules first, model second.

Rules run first because they are free, instant and auditable. The model is
consulted only when the rules are inconclusive, which on typical traffic is
rarely — so the guardrail almost never adds latency to a legitimate question.

Four things are blocked:

* **Prompt injection.** Attempts to override instructions or extract the system
  prompt.
* **Personal data about individuals.** Masar holds none and must not appear to.
* **Transactional requests.** Masar cannot top up a nol card or pay a fine, and
  a system that seems willing to try is dangerous.
* **Out-of-scope questions.** Answered with a redirect, never a bare refusal.

It also enforces the honesty rule. A request for live vehicle positions or
disruption status is not refused — it is answered with the truth that RTA
publishes no such open data, plus the schedule-based alternative. That is a
better outcome than either refusing or inventing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

from backend.services.logging import get_logger

log = get_logger(__name__)

Verdict = Literal["allow", "block", "redirect", "escalate"]


@dataclass(slots=True)
class GuardrailResult:
    safe: bool
    verdict: Verdict
    sanitized: str
    reason: str = ""
    redirect_message_en: str = ""
    redirect_message_ar: str = ""
    matched_rules: list[str] = field(default_factory=list)
    used_model: bool = False


# --------------------------------------------------------------- patterns --

_INJECTION = [
    (
        r"ignore\s+(all\s+)?(previous|prior|above|earlier)\s+(instructions?|prompts?|rules?)",
        "injection.ignore_instructions",
    ),
    (
        r"disregard\s+(all\s+)?(previous|prior|your)\s+(instructions?|rules?|guidelines?)",
        "injection.disregard",
    ),
    (
        r"(reveal|show|print|repeat|output)\s+(me\s+)?(your\s+)?(system\s+)?(prompt|instructions)",
        "injection.extract_prompt",
    ),
    (r"you\s+are\s+now\s+(a|an|in)\b", "injection.role_override"),
    (r"\b(developer|admin|god|dan)\s+mode\b", "injection.mode_override"),
    (r"pretend\s+(you\s+are|to\s+be)\b", "injection.pretend"),
    (r"</?(system|instruction|assistant)>", "injection.tag_smuggling"),
    (r"\bBEGIN\s+SYSTEM\b|\bEND\s+SYSTEM\b", "injection.delimiter"),
]

_SQL_WRITE = [
    (r"\b(drop|delete|truncate|alter)\s+(table|database|schema)\b", "sql.ddl"),
    (r"\b(insert\s+into|update\s+\w+\s+set)\b", "sql.dml"),
    (r";\s*(drop|delete|update|insert)\b", "sql.stacked"),
]

_PII = [
    (r"\b(phone|mobile|email|address|passport|emirates\s*id|eid)\s+(of|for)\s+\w+", "pii.lookup"),
    (r"\bwho\s+(is|owns)\s+(the\s+)?(driver|passenger|owner)\b", "pii.identify_person"),
    (
        r"\b(personal|private)\s+(details?|information|data)\s+(of|about|for)\b",
        "pii.personal_details",
    ),
    (r"\b\d{3}-?\d{4}-?\d{7}-?\d\b", "pii.emirates_id_number"),
]

_TRANSACTIONAL = [
    (r"\b(top\s*up|recharge|reload)\s+(my\s+)?(nol|card|balance)", "transaction.topup"),
    (r"\b(pay|settle|clear)\s+(my\s+)?(fine|ticket|salik|toll|fee)", "transaction.payment"),
    (
        r"\b(book|reserve|buy|purchase)\s+(me\s+)?(a\s+)?(taxi|ticket|seat|pass)",
        "transaction.booking",
    ),
    (r"\b(cancel|refund)\s+(my\s+)?(booking|ticket|subscription)", "transaction.cancel"),
    (r"\b(register|renew)\s+(my\s+)?(vehicle|licen[cs]e)", "transaction.registration"),
]

# Places that do not move. A question about where one of these is has an answer
# in the warehouse — latitude and longitude — so it must NOT be treated as a
# live-vehicle question.
_STATIC_PLACE = re.compile(
    r"\b(station|stations|stop|stops|stand|stands|terminal|terminus|"
    r"gate|gates|depot|centre|center|mall|interchange)\b"
    r"|محطة|محطات|موقف|مواقف|بوابة",
    re.IGNORECASE,
)

_VEHICLE = re.compile(
    r"\b(bus|buses|metro|tram|taxi|train|abra|ferry|vehicle|service|route)\b"
    r"|حافلة|باص|مترو|ترام|تاكسي",
    re.IGNORECASE,
)

_WHERE_IS = re.compile(r"\b(where\s+is|where'?s|where\s+are|track|locate)\b|أين", re.IGNORECASE)

# Not blocked — answered honestly. This is the honesty rule in code.
#
# `vehicle_position` is applied conditionally in `_realtime_rules` rather than
# listed here: "where is X" only indicates a live query when X is something that
# moves. Matching it against any transit noun redirected "Where is Union metro
# station?", telling the user data does not exist when the warehouse holds its
# coordinates — a confidently wrong refusal, which is worse than the overclaim
# the rule was written to prevent.
_REALTIME = [
    (r"\b(next|when\s+is\s+the\s+next)\s+(bus|metro|tram|train)\b", "realtime.next_departure"),
    (
        r"\b(delay|delays|disruption|breakdown|service\s+status)\b.*\b(today|now|currently|right\s+now)\b",
        "realtime.disruption",
    ),
    (
        # An optional noun may sit between: "live bus locations", "real-time
        # metro tracking".
        r"\b(real[\s-]?time|live)\s+(\w+\s+)?"
        r"(data|feed|position|positions|location|locations|arrival|arrivals|tracking|map)\b",
        "realtime.generic",
    ),
    (r"\bcurrent\s+(position|location)\b", "realtime.vehicle_position"),
    # Duration: Masar holds no timetables or speeds, so any figure would be
    # invented. The previous pattern required "how long will/does it take" with
    # nothing in between and so missed "how long does the metro take".
    (r"\bhow\s+long\b[^?]{0,40}\b(take|takes|taking)\b", "realtime.duration"),
    (r"\b(journey|travel|trip)\s+time\b", "realtime.duration"),
    (r"\bhow\s+many\s+minutes\b", "realtime.duration"),
    (r"\bwhat\s+time\s+(does|will)\b.*\b(arrive|depart|leave)\b", "realtime.duration"),
]

# Liveness markers that turn an otherwise-static question into a live one.
_LIVENESS = re.compile(
    r"\b(right\s+now|now|currently|at\s+the\s+moment|live|real[\s-]?time|today)\b"
    r"|الآن|حالياً",
    re.IGNORECASE,
)


def _realtime_rules(text: str) -> list[str]:
    """Real-time matches, including the conditional vehicle-position rule."""
    matched = _match(text, _REALTIME)

    # "Where is …" is a live question only when the subject moves. A static
    # place in the sentence means the user is asking for a location the
    # warehouse can supply.
    if _WHERE_IS.search(text) and _VEHICLE.search(text):
        if not _STATIC_PLACE.search(text) or _LIVENESS.search(text):
            matched.append("realtime.vehicle_position")

    return list(dict.fromkeys(matched))


_OUT_OF_SCOPE = [
    (r"\b(weather|forecast|temperature)\b", "scope.weather"),
    (r"\b(restaurant|hotel|movie|cinema|shopping)\s+(recommend|suggest|best)", "scope.lifestyle"),
    (r"\b(visa|immigration|residency|golden\s+visa)\b", "scope.immigration"),
    (r"\b(stock|crypto|bitcoin|invest)\b", "scope.finance"),
    (r"\bwrite\s+(me\s+)?(a\s+)?(poem|essay|story|code|script)\b", "scope.generic_generation"),
]

# In-scope vocabulary. If none of these appears, the query is escalated as
# possibly out of scope. It must therefore include every service the corpus can
# actually answer — otherwise a question Masar *can* answer (because a service
# document was added for it) gets flagged out of scope and never reaches
# retrieval. That is exactly what happened to "what documents do I need to renew
# a driving licence": no word here matched, so it was escalated and the local
# model rejected it, while the licence-renewal service doc sat unused.
_TRANSPORT_TERMS = re.compile(
    r"\b(metro|bus|tram|taxi|nol|salik|rta|station|stop|route|fare|zone|ridership|"
    r"transport|commute|travel|marine|abra|ferry|line|trip|journey|"
    r"licen[cs]e|driving|permit|fine|toll|parking|resident|commuting|توصيل|مترو|"
    r"حافلة|باص|ترام|تاكسي|نول|سالك|محطة|خط|أجرة|رحلة|مواصلات|رخصة|قيادة|مخالفة)\b",
    re.IGNORECASE,
)

REDIRECTS: dict[str, tuple[str, str]] = {
    "realtime": (
        "RTA does not publish real-time vehicle positions, live arrival times or "
        "disruption feeds as open data, so I genuinely cannot see where a vehicle is "
        "right now — and I won't guess. What I can do is tell you which routes serve a "
        "stop, how stations connect, how far apart places are, and how ridership has "
        "behaved historically. For live times, RTA's S'hail app has them.",
        "لا تنشر هيئة الطرق والمواصلات بيانات مباشرة عن مواقع المركبات أو أوقات الوصول "
        "أو الأعطال ضمن البيانات المفتوحة، لذلك لا يمكنني معرفة موقع المركبة الآن — ولن "
        "أخمّن. لكن يمكنني إخبارك بالخطوط التي تخدم محطة ما، وكيفية اتصال المحطات، "
        "والمسافات، واتجاهات أعداد الركاب تاريخياً. لمعرفة الأوقات المباشرة، استخدم تطبيق "
        "S'hail من الهيئة.",
    ),
    "transaction": (
        "I can't carry out transactions — I have no connection to any RTA system and "
        "hold no account data. For nol top-ups, fines, bookings or renewals, use the RTA "
        "app or rta.ae. I can help you work out what something will cost before you go.",
        "لا يمكنني تنفيذ أي معاملات — لا يوجد لدي اتصال بأنظمة الهيئة ولا أحتفظ ببيانات "
        "حسابات. لشحن بطاقة نول أو دفع المخالفات أو الحجز أو التجديد، استخدم تطبيق الهيئة "
        "أو موقع rta.ae. يمكنني مساعدتك في حساب التكلفة قبل ذلك.",
    ),
    "pii": (
        "I don't hold any personal data about individuals and can't look anyone up. "
        "Masar works only with published, aggregated open data about the transport "
        "network itself.",
        "لا أحتفظ بأي بيانات شخصية عن الأفراد ولا يمكنني البحث عن أي شخص. يعمل مسار فقط "
        "على البيانات المفتوحة المنشورة والمجمّعة عن شبكة النقل نفسها.",
    ),
    "scope": (
        "That's outside what I cover. I work with Dubai's published transport data — "
        "metro, bus, tram, marine, taxi, fares and Salik. Ask me about routes, fares, "
        "stations or ridership and I'll cite exactly where the answer came from.",
        "هذا خارج نطاق عملي. أنا أعمل على بيانات النقل المنشورة في دبي — المترو والحافلات "
        "والترام والنقل البحري وسيارات الأجرة والأجور وسالك. اسألني عن الخطوط أو الأجور أو "
        "المحطات أو أعداد الركاب وسأذكر مصدر الإجابة بدقة.",
    ),
    "injection": (
        "I'll stick to what I'm for: answering questions about Dubai's published "
        "transport data, with a citation for every claim. What would you like to know?",
        "سألتزم بمهمتي: الإجابة عن الأسئلة المتعلقة ببيانات النقل المنشورة في دبي، مع ذكر "
        "المصدر لكل معلومة. ما الذي تود معرفته؟",
    ),
}


def _match(text: str, rules: list[tuple[str, str]]) -> list[str]:
    return [name for pattern, name in rules if re.search(pattern, text, re.IGNORECASE)]


def _sanitize(text: str) -> str:
    """Neutralise control sequences without altering the user's actual question."""
    cleaned = re.sub(r"</?(system|instruction|assistant|user)>", "", text, flags=re.IGNORECASE)
    cleaned = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned[:2000]


class GuardrailAgent:
    """Rules-only by default; `router` enables model escalation when supplied."""

    def __init__(self, router=None) -> None:
        self.router = router

    def check_rules(self, text: str) -> GuardrailResult:
        sanitized = _sanitize(text)

        if not sanitized:
            return GuardrailResult(
                safe=False,
                verdict="block",
                sanitized="",
                reason="empty query",
                redirect_message_en="I didn't catch a question there — what would you like to know about Dubai transport?",
                redirect_message_ar="لم أتلقَّ سؤالاً — ما الذي تود معرفته عن النقل في دبي؟",
            )

        for rules, category in (
            (_INJECTION, "injection"),
            (_SQL_WRITE, "injection"),
            (_PII, "pii"),
            (_TRANSACTIONAL, "transaction"),
        ):
            if matched := _match(sanitized, rules):
                en, ar = REDIRECTS[category]
                log.info("guardrail.blocked", category=category, rules=matched)
                return GuardrailResult(
                    safe=False,
                    verdict="redirect",
                    sanitized=sanitized,
                    reason=category,
                    redirect_message_en=en,
                    redirect_message_ar=ar,
                    matched_rules=matched,
                )

        # Real-time is answered, not blocked — the honesty rule.
        if matched := _realtime_rules(sanitized):
            en, ar = REDIRECTS["realtime"]
            log.info("guardrail.realtime_redirect", rules=matched)
            return GuardrailResult(
                safe=False,
                verdict="redirect",
                sanitized=sanitized,
                reason="realtime_unavailable",
                redirect_message_en=en,
                redirect_message_ar=ar,
                matched_rules=matched,
            )

        if matched := _match(sanitized, _OUT_OF_SCOPE):
            if not _TRANSPORT_TERMS.search(sanitized):
                en, ar = REDIRECTS["scope"]
                log.info("guardrail.out_of_scope", rules=matched)
                return GuardrailResult(
                    safe=False,
                    verdict="redirect",
                    sanitized=sanitized,
                    reason="out_of_scope",
                    redirect_message_en=en,
                    redirect_message_ar=ar,
                    matched_rules=matched,
                )

        # No rule fired and no transport vocabulary present — genuinely ambiguous.
        if not _TRANSPORT_TERMS.search(sanitized):
            return GuardrailResult(
                safe=True,
                verdict="escalate",
                sanitized=sanitized,
                reason="no transport terms detected",
            )

        return GuardrailResult(safe=True, verdict="allow", sanitized=sanitized)

    async def run(self, text: str) -> GuardrailResult:
        result = self.check_rules(text)
        if result.verdict != "escalate" or self.router is None:
            if result.verdict == "escalate":
                # No model available: allow. Over-blocking a legitimate question
                # is a worse failure than passing an odd one to the router, which
                # will classify it OUT_OF_SCOPE anyway.
                result.verdict = "allow"
            return result

        try:
            payload, completion = await self.router.complete_json(
                "guardrail",
                [
                    {
                        "role": "system",
                        "content": (
                            "You screen questions for a Dubai public-transport data "
                            "assistant. Reply with JSON only: "
                            '{"in_scope": true|false, "reason": "<short>"}. '
                            "In scope: metro, bus, tram, marine, taxi, routes, stops, "
                            "stations, fares, nol, Salik, zones, ridership, commuting "
                            "costs. Out of scope: everything else."
                        ),
                    },
                    {"role": "user", "content": result.sanitized},
                ],
            )
            result.used_model = True
            if not payload.get("in_scope", True):
                en, ar = REDIRECTS["scope"]
                result.safe = False
                result.verdict = "redirect"
                result.reason = f"model: {payload.get('reason', 'out of scope')}"
                result.redirect_message_en = en
                result.redirect_message_ar = ar
            else:
                result.verdict = "allow"
            log.info(
                "guardrail.escalated",
                in_scope=payload.get("in_scope"),
                provider=completion.provider,
            )
        except Exception as exc:
            log.warning("guardrail.escalation_failed", error=f"{type(exc).__name__}: {exc}")
            result.verdict = "allow"

        return result
