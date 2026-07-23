"""A5 — Query Rewriter.

Produces three variants per sub-task, each targeting a different weakness:

1. **HyDE** — a hypothetical ideal answer paragraph, embedded as the query.
   Documents resemble answers more than they resemble questions, so embedding a
   plausible answer lands nearer the right region of the space than embedding
   the question does.
2. **Keyword expansion** — transit synonyms and the Arabic/English pair for each
   term, aimed at the lexical retriever.
3. **Cross-language mirror** — the query in the other language, so an English
   question can reach the Arabic corpus and vice versa.

All three go to A6 and are fused, so a chunk found by two different phrasings
outranks one found by a single phrasing.

A deterministic path produces variants 2 and 3 with no model at all, which is
what keeps retrieval quality from collapsing when providers are exhausted.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from backend.ingestion.arabic import has_arabic
from backend.services.logging import get_logger

log = get_logger(__name__)

# Bidirectional transit vocabulary. Expansion is what lets "train" find "metro"
# and "محطة" find "station".
_SYNONYMS: dict[str, list[str]] = {
    "metro": ["metro", "rail", "train", "subway", "مترو"],
    "bus": ["bus", "coach", "حافلة", "باص"],
    "tram": ["tram", "streetcar", "ترام"],
    "taxi": ["taxi", "cab", "تاكسي", "أجرة"],
    "marine": ["marine", "abra", "ferry", "water bus", "بحري", "عبرة"],
    "station": ["station", "stop", "halt", "محطة"],
    "stop": ["stop", "station", "محطة", "موقف"],
    "route": ["route", "line", "service", "خط", "مسار"],
    "fare": ["fare", "price", "cost", "tariff", "أجرة", "سعر", "تعرفة"],
    "nol": ["nol", "card", "travel card", "نول", "بطاقة"],
    "salik": ["salik", "toll", "road charge", "سالك", "رسوم"],
    "zone": ["zone", "fare zone", "منطقة"],
    "ridership": ["ridership", "passengers", "trips", "patronage", "ركاب", "رحلات"],
    "busiest": ["busiest", "most used", "highest", "peak", "الأكثر ازدحاما"],
    "cheapest": ["cheapest", "lowest cost", "most affordable", "الأرخص"],
    "nearest": ["nearest", "closest", "adjacent", "أقرب"],
}

_ARABIC_TO_ENGLISH = {
    "مترو": "metro",
    "حافلة": "bus",
    "باص": "bus",
    "ترام": "tram",
    "تاكسي": "taxi",
    "محطة": "station",
    "خط": "route line",
    "أجرة": "fare",
    "سعر": "price fare",
    "نول": "nol card",
    "سالك": "salik toll",
    "منطقة": "zone",
    "ركاب": "passengers ridership",
    "رحلات": "trips",
    "أقرب": "nearest",
    "الأرخص": "cheapest",
    "الأكثر": "most busiest",
    "ازدحاما": "busy crowded",
    "ازدحاماً": "busy crowded",
    "كم": "how much how many",
    "أي": "which",
    "كيف": "how",
    "دبي": "Dubai",
    "مواصلات": "transport",
}

_HYDE_PROMPT = """Write the paragraph that would perfectly answer this question if it
appeared in Dubai transport documentation.

Write it as a factual passage, not as an answer to a person. Do NOT invent
specific numbers — write the shape of the answer, using placeholder phrasing
where a figure would go. Three sentences maximum.

Purpose: this text is embedded and used to search a document index, so it should
read like the source passage, not like a reply."""


@dataclass(slots=True)
class RewriteResult:
    original: str
    variants: list[str] = field(default_factory=list)
    hyde: str | None = None
    keyword_expanded: str | None = None
    cross_language: str | None = None
    method: str = "deterministic"

    def all_queries(self) -> list[str]:
        """Original first, then variants, de-duplicated in order."""
        queries = [self.original, *self.variants]
        seen: set[str] = set()
        return [q for q in queries if q and q.strip() and not (q in seen or seen.add(q))]


def expand_keywords(query: str) -> str:
    """Append synonyms for every recognised transit term.

    Deliberately additive: the original wording is preserved so exact-match
    retrieval still works, and the synonyms only widen recall.
    """
    lowered = query.lower()
    additions: list[str] = []
    for term, synonyms in _SYNONYMS.items():
        if re.search(rf"\b{re.escape(term)}\b", lowered):
            additions.extend(s for s in synonyms if s.lower() != term)
    for arabic, english in _ARABIC_TO_ENGLISH.items():
        if arabic in query:
            additions.append(english)

    unique: list[str] = []
    seen: set[str] = set()
    for word in additions:
        if word.lower() not in seen:
            seen.add(word.lower())
            unique.append(word)

    return f"{query} {' '.join(unique)}".strip() if unique else query


def cross_language_mirror(query: str) -> str | None:
    """A rough mirror of the query in the other language.

    Word-level substitution, not translation. It exists to give the lexical
    retriever something to match in the other language; the embedding model
    already handles semantics across languages on its own.
    """
    if has_arabic(query):
        mirrored = query
        for arabic, english in _ARABIC_TO_ENGLISH.items():
            mirrored = mirrored.replace(arabic, f" {english} ")
        mirrored = re.sub(r"\s+", " ", mirrored).strip()
        return mirrored if mirrored != query else None

    additions = []
    lowered = query.lower()
    for term, synonyms in _SYNONYMS.items():
        if re.search(rf"\b{re.escape(term)}\b", lowered):
            additions.extend(s for s in synonyms if has_arabic(s))
    return f"{query} {' '.join(dict.fromkeys(additions))}" if additions else None


class RewriterAgent:
    def __init__(self, router=None) -> None:
        self.router = router

    async def run(self, query: str, *, use_hyde: bool = True) -> RewriteResult:
        result = RewriteResult(original=query)

        expanded = expand_keywords(query)
        if expanded != query:
            result.keyword_expanded = expanded
            result.variants.append(expanded)

        if mirror := cross_language_mirror(query):
            result.cross_language = mirror
            result.variants.append(mirror)

        if use_hyde and self.router is not None:
            try:
                completion = await self.router.complete(
                    "rewrite",
                    [
                        {"role": "system", "content": _HYDE_PROMPT},
                        {"role": "user", "content": query},
                    ],
                    max_tokens=220,
                )
                hyde = completion.text.strip()
                if hyde and len(hyde) > 20:
                    result.hyde = hyde
                    result.variants.append(hyde)
                    result.method = f"hyde:{completion.provider}"
            except Exception as exc:
                log.warning("rewriter.hyde_failed", error=f"{type(exc).__name__}: {exc}")

        log.info(
            "rewriter.variants",
            count=len(result.all_queries()),
            hyde=bool(result.hyde),
            expanded=bool(result.keyword_expanded),
            mirrored=bool(result.cross_language),
        )
        return result
