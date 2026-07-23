"""A2 — Language detection and normalisation. Deterministic; no LLM.

Detection is script-based rather than model-based. Arabic and Latin occupy
disjoint Unicode blocks, so counting characters is exact, instant and free —
a language classifier here would be slower, cost a call, and be less accurate
on the short strings users actually type.

The agent produces four things:

* `language` — ar, en, mixed or unknown
* `normalized` — Arabic folded for search; the original is never overwritten
* `transliterated` — Arabizi converted to Arabic, as an *additional* retrieval
  variant, never a replacement
* `response_language` — the answer language, always mirroring the query

That last one has no exceptions. Answering an Arabic question in English is the
single most common failure of bilingual systems and it reads as carelessness.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from backend.ingestion.arabic import (
    arabic_ratio,
    has_arabic,
    has_latin,
    looks_like_arabizi,
    normalise_arabic,
    script_of,
    transliterate_arabizi,
)
from backend.services.logging import get_logger

log = get_logger(__name__)

Language = Literal["en", "ar", "mixed", "unknown"]
ResponseLanguage = Literal["en", "ar"]

# Above this share of Arabic letters a mixed query is answered in Arabic.
# Set below 0.5 deliberately: a query like "metro fare من الاتحاد إلى برجمان"
# is an Arabic question containing English transit nouns, and answering it in
# English would be wrong.
ARABIC_DOMINANCE_THRESHOLD = 0.35


@dataclass(slots=True)
class LanguageResult:
    language: Language
    script: str
    normalized: str
    """Arabic-folded text used for lexical search. Never displayed."""

    display_text: str
    """The original, preserved exactly. This is what gets echoed back."""

    response_language: ResponseLanguage
    transliterated: str | None = None
    is_arabizi: bool = False
    arabic_ratio: float = 0.0

    @property
    def is_rtl(self) -> bool:
        return self.response_language == "ar"

    def search_variants(self) -> list[str]:
        """Every form worth issuing to retrieval, de-duplicated in order."""
        variants = [self.display_text]
        if self.normalized and self.normalized != self.display_text:
            variants.append(self.normalized)
        if self.transliterated and self.transliterated != self.display_text:
            variants.append(self.transliterated)
        seen: set[str] = set()
        return [v for v in variants if v and not (v in seen or seen.add(v))]


class LanguageAgent:
    def run(self, text: str) -> LanguageResult:
        display = (text or "").strip()

        if not display:
            return LanguageResult(
                language="unknown",
                script="unknown",
                normalized="",
                display_text="",
                response_language="en",
            )

        script = script_of(display)
        ratio = arabic_ratio(display)
        arabizi = looks_like_arabizi(display)

        transliterated = transliterate_arabizi(display) if arabizi else None
        # If transliteration changed nothing, it adds no retrieval signal.
        if transliterated == display:
            transliterated = None

        if script == "ar":
            language: Language = "ar"
            response: ResponseLanguage = "ar"
        elif script == "mixed":
            language = "mixed"
            response = "ar" if ratio >= ARABIC_DOMINANCE_THRESHOLD else "en"
        elif script == "en":
            # Arabizi is Arabic written in Latin script — the user is writing
            # Arabic, so they get an Arabic answer.
            language = "en"
            response = "ar" if arabizi else "en"
        else:
            language = "unknown"
            response = "en"

        normalized = (
            normalise_arabic(display) if has_arabic(display) else display
        )

        result = LanguageResult(
            language=language,
            script=script,
            normalized=normalized,
            display_text=display,
            response_language=response,
            transliterated=transliterated,
            is_arabizi=arabizi,
            arabic_ratio=ratio,
        )

        log.info(
            "language.detected",
            language=language,
            response_language=response,
            arabic_ratio=round(ratio, 2),
            arabizi=arabizi,
            has_latin=has_latin(display),
        )
        return result
