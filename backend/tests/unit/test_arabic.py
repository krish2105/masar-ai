"""Arabic normalisation (A2 and the Silver layer).

These functions decide whether an Arabic query matches an Arabic document, so
the cases below are the ones that actually break retrieval in practice:
orthographic variation that carries no meaning, and digit-for-letter Arabizi.
"""

from __future__ import annotations

import pytest

from backend.ingestion.arabic import (
    arabic_ratio,
    has_arabic,
    looks_like_arabizi,
    normalise_arabic,
    script_of,
    strip_diacritics,
    transliterate_arabizi,
)


class TestNormalisation:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("أحمد", "احمد"),          # alef with hamza above
            ("إمارات", "امارات"),      # alef with hamza below
            ("آل", "ال"),               # alef with madda
            ("ٱلله", "الله"),           # alef wasla
        ],
    )
    def test_alef_forms_unify(self, raw: str, expected: str) -> None:
        assert normalise_arabic(raw) == expected

    def test_tatweel_is_stripped(self) -> None:
        assert normalise_arabic("الــــراشدية") == normalise_arabic("الراشدية")

    def test_diacritics_are_stripped(self) -> None:
        assert normalise_arabic("مَحَطَّة") == normalise_arabic("محطة")

    def test_teh_marbuta_folds_to_heh(self) -> None:
        assert normalise_arabic("محطة") == "محطه"

    def test_alef_maksura_folds_to_yeh(self) -> None:
        assert normalise_arabic("على") == "علي"

    def test_arabic_indic_digits_become_ascii(self) -> None:
        assert normalise_arabic("٢٠٢٦") == "2026"
        assert normalise_arabic("۱۲۳") == "123"

    def test_whitespace_collapses(self) -> None:
        assert normalise_arabic("  محطة    الاتحاد  ") == "محطه الاتحاد"

    def test_empty_input_is_safe(self) -> None:
        assert normalise_arabic("") == ""

    def test_normalisation_is_idempotent(self) -> None:
        once = normalise_arabic("مَحَطَّةُ الإتِّحاد")
        assert normalise_arabic(once) == once

    def test_variants_of_the_same_station_collide(self) -> None:
        """The whole point: differently-spelled forms must index identically."""
        variants = ["محطة الإتحاد", "محطه الاتحاد", "مَحَطَّة الإتحاد", "محطــة الاتحاد"]
        assert len({normalise_arabic(v) for v in variants}) == 1

    def test_latin_text_is_untouched_apart_from_whitespace(self) -> None:
        assert normalise_arabic("Union  Metro Station") == "Union Metro Station"


class TestScriptDetection:
    def test_arabic_is_detected(self) -> None:
        assert has_arabic("محطة") is True
        assert script_of("محطة الاتحاد") == "ar"

    def test_english_is_detected(self) -> None:
        assert has_arabic("Union Station") is False
        assert script_of("Union Station") == "en"

    def test_mixed_script_is_detected(self) -> None:
        assert script_of("Union محطة") == "mixed"

    def test_digits_alone_are_unknown(self) -> None:
        assert script_of("2026") == "unknown"

    def test_ratio_reflects_dominant_script(self) -> None:
        assert arabic_ratio("محطة") == 1.0
        assert arabic_ratio("Union") == 0.0
        assert 0.0 < arabic_ratio("Union محطة") < 1.0

    def test_ratio_of_empty_string_is_zero(self) -> None:
        assert arabic_ratio("") == 0.0


class TestArabizi:
    @pytest.mark.parametrize("text", ["3ala", "wein el mahatta", "shu se3r"])
    def test_arabizi_is_recognised(self, text: str) -> None:
        assert looks_like_arabizi(text) is True

    @pytest.mark.parametrize("text", ["F27", "route 13", "Union Station", "2026"])
    def test_route_codes_are_not_arabizi(self, text: str) -> None:
        """A bare route code must not be misread as Arabizi — RTA route names
        are full of digits and mangling them would break exact-match retrieval."""
        assert looks_like_arabizi(text) is False

    def test_arabic_text_is_not_arabizi(self) -> None:
        assert looks_like_arabizi("محطة الاتحاد") is False

    def test_known_words_transliterate(self) -> None:
        assert transliterate_arabizi("3ala") == "على"
        assert transliterate_arabizi("metro") == "مترو"

    def test_transliteration_preserves_unknown_tokens(self) -> None:
        assert "Union" in transliterate_arabizi("Union metro")

    def test_empty_input_is_safe(self) -> None:
        assert transliterate_arabizi("") == ""


class TestDiacritics:
    def test_strip_leaves_letters(self) -> None:
        assert strip_diacritics("مَحَطَّة") == "محطة"

    def test_strip_is_noop_on_plain_text(self) -> None:
        assert strip_diacritics("محطة") == "محطة"
