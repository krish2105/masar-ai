"""Arabic text normalisation.

Two representations of every Arabic string are kept, and the distinction matters:

    *_ar       the original, shown to the user exactly as published
    *_ar_norm  the normalised form, indexed for search and never displayed

Normalising for display would corrupt proper nouns; displaying the raw form for
search would make matching fail on orthographic variation that carries no
semantic difference. Postgres ships no Arabic stemmer, so the normalised column
is indexed with the `simple` dictionary — normalisation here does the work a
stemmer would otherwise do.

Pure functions, no dependencies, exhaustively unit-tested.
"""

from __future__ import annotations

import re
import unicodedata

# --- character classes -------------------------------------------------------

# Alef variants: hamza above/below, madda, wasla → bare alef
_ALEF_VARIANTS = str.maketrans(
    {
        "أ": "ا",  # أ  alef with hamza above
        "إ": "ا",  # إ  alef with hamza below
        "آ": "ا",  # آ  alef with madda
        "ٱ": "ا",  # ٱ  alef wasla
        "ٲ": "ا",
        "ٳ": "ا",
    }
)

# Orthographic variants that carry no distinction in transit names
_LETTER_FOLDING = str.maketrans(
    {
        "ى": "ي",  # ى alef maksura → ي yeh
        "ة": "ه",  # ة teh marbuta  → ه heh
        "ؤ": "و",  # ؤ waw with hamza  → و
        "ئ": "ي",  # ئ yeh with hamza  → ي
        "ـ": "",  # ـ tatweel (pure decoration)
    }
)

# Harakat / tanween / superscript alef / quranic marks
_DIACRITICS = re.compile("[ؐ-ًؚ-ٰٟۖ-ۭ]")

# Arabic-Indic (٠-٩) and Eastern Arabic-Indic (۰-۹) digits → ASCII
_DIGIT_MAP = {ord("٠") + i: str(i) for i in range(10)}
_DIGIT_MAP |= {ord("۰") + i: str(i) for i in range(10)}

_ARABIC_BLOCK = re.compile(r"[؀-ۿݐ-ݿࢠ-ࣿﭐ-﷿ﹰ-﻿]")
_LATIN_BLOCK = re.compile(r"[A-Za-z]")
_WHITESPACE = re.compile(r"\s+")


def strip_diacritics(text: str) -> str:
    return _DIACRITICS.sub("", text)


def normalise_arabic(text: str) -> str:
    """Fold orthographic variation for search indexing.

    Applies NFKC (which resolves Arabic presentation forms into their canonical
    letters), unifies alef, folds letter variants, strips tatweel and diacritics,
    converts Arabic-Indic digits to ASCII, and collapses whitespace.

    >>> normalise_arabic("مَحَطَّةُ الإتِّحاد")
    'محطه الاتحاد'
    >>> normalise_arabic("الــراشديـة")
    'الراشديه'
    """
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text)
    text = strip_diacritics(text)
    text = text.translate(_ALEF_VARIANTS)
    text = text.translate(_LETTER_FOLDING)
    text = text.translate(_DIGIT_MAP)
    return _WHITESPACE.sub(" ", text).strip()


def has_arabic(text: str) -> bool:
    return bool(text) and _ARABIC_BLOCK.search(text) is not None


def has_latin(text: str) -> bool:
    return bool(text) and _LATIN_BLOCK.search(text) is not None


def script_of(text: str) -> str:
    """`ar`, `en`, `mixed` or `unknown` — the script signal A2 routes on."""
    arabic, latin = has_arabic(text), has_latin(text)
    if arabic and latin:
        return "mixed"
    if arabic:
        return "ar"
    if latin:
        return "en"
    return "unknown"


def arabic_ratio(text: str) -> float:
    """Share of letters that are Arabic. Used to pick a response language when
    a query code-switches — the dominant script wins."""
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return 0.0
    return sum(1 for c in letters if _ARABIC_BLOCK.match(c)) / len(letters)


# --- Arabizi -----------------------------------------------------------------
# Latin-script Arabic with numerals standing in for letters that have no Latin
# equivalent. Common in Gulf messaging; users type transit queries this way.

_ARABIZI_DIGITS = {
    "2": "ء",  # hamza
    "3": "ع",  # ain
    "5": "خ",  # kha
    "6": "ط",  # tah
    "7": "ح",  # hah
    "8": "غ",  # ghain
    "9": "ص",  # sad
}

# Words that are DISTINCTLY Arabizi — they do not occur in ordinary English.
# Seeing one is strong evidence the user is writing Arabic in Latin script.
_ARABIZI_MARKERS = {
    "3ala": "على",
    "3an": "عن",
    "3and": "عند",
    "wein": "وين",
    "wain": "وين",
    "fein": "فين",
    "shu": "شو",
    "shoo": "شو",
    "kam": "كم",
    "mahatta": "محطة",
    "mahatat": "محطات",
    "sikka": "سكة",
    "tareeq": "طريق",
    "khat": "خط",
    "as3ar": "أسعار",
    "se3r": "سعر",
    "kaif": "كيف",
    "keef": "كيف",
    "aqrab": "أقرب",
    "arkhas": "أرخص",
    "yalla": "يلا",
    "min": "من",
    "ila": "إلى",
}

# Transit loanwords. These are used when transliterating text ALREADY judged to
# be Arabizi, but must never trigger that judgement themselves — "metro", "bus"
# and "taxi" are ordinary English, and treating them as Arabizi markers made
# every English sentence containing "metro" get answered in Arabic.
_ARABIZI_LOANWORDS = {
    "metro": "مترو",
    "bus": "باص",
    "taxi": "تاكسي",
    "tram": "ترام",
    "nol": "نول",
    "salik": "سالك",
}

_ARABIZI_WORDS = {**_ARABIZI_MARKERS, **_ARABIZI_LOANWORDS}

_ARABIZI_TOKEN = re.compile(r"\b[a-z]*[23456789][a-z0-9]*\b", re.IGNORECASE)


def looks_like_arabizi(text: str) -> bool:
    """True when Latin text contains digit-for-letter substitutions.

    Guards against false positives on ordinary alphanumerics: a bare route
    number like "F27" or "13" is not Arabizi, so a digit must sit adjacent to
    letters within a token that is not purely a code.
    """
    if has_arabic(text):
        return False
    lowered = text.lower()
    tokens = {t.strip(".,!?;:") for t in lowered.split()}
    # Only distinctly-Arabizi words count as evidence — see _ARABIZI_LOANWORDS.
    if tokens & set(_ARABIZI_MARKERS):
        return True
    for match in _ARABIZI_TOKEN.finditer(lowered):
        token = match.group()
        letters = sum(c.isalpha() for c in token)
        digits = sum(c.isdigit() for c in token)
        # "3ala" → 3 letters, 1 digit. "F27" → 1 letter, 2 digits (a route code).
        if letters >= 2 and digits >= 1 and letters > digits:
            return True
    return False


def transliterate_arabizi(text: str) -> str:
    """Best-effort Arabizi → Arabic.

    Word-level lookup first (accurate), then digit substitution on the remainder
    (approximate). The result feeds retrieval as an *additional* query variant,
    never as a replacement — a wrong transliteration then costs recall it would
    not otherwise have had, rather than destroying the original query.
    """
    if not text:
        return ""
    output: list[str] = []
    for token in text.split():
        stripped = token.strip(".,!?;:").lower()
        if stripped in _ARABIZI_WORDS:
            output.append(_ARABIZI_WORDS[stripped])
            continue
        if any(ch in _ARABIZI_DIGITS for ch in stripped) and any(c.isalpha() for c in stripped):
            output.append("".join(_ARABIZI_DIGITS.get(ch, ch) for ch in stripped))
            continue
        output.append(token)
    return " ".join(output)
