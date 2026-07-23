"""A11 — Numeric Calculator.

§8.2 requires numeric accuracy of exactly 1.00. The calculator is deterministic,
so anything less than every-case-correct is a defect, not a metric. Every
expected value below is computed by hand from config/fares.yaml.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from backend.agents.a11_calculator import (
    CalculationError,
    drive_vs_transit,
    load_fares,
    monthly_commute_cost,
    nol_fare,
    salik_cost,
    zones_between,
)


class TestNolFare:
    @pytest.mark.parametrize(
        ("zones", "expected"),
        [(1, "3.00"), (2, "5.00"), (3, "7.50")],
    )
    def test_silver_by_zone(self, zones: int, expected: str) -> None:
        assert nol_fare(zones).total == Decimal(expected)

    @pytest.mark.parametrize(
        ("zones", "expected"),
        [(1, "6.00"), (2, "10.00"), (3, "15.00")],
    )
    def test_gold_is_double(self, zones: int, expected: str) -> None:
        assert nol_fare(zones, "gold").total == Decimal(expected)

    def test_beyond_three_zones_caps_at_band_three(self) -> None:
        assert nol_fare(7).total == nol_fare(3).total == Decimal("7.50")

    def test_cap_is_disclosed_as_a_caveat(self) -> None:
        """Capping silently would be a wrong answer presented as a right one."""
        result = nol_fare(7)
        assert any("does not price beyond" in c for c in result.caveats)

    def test_zero_zones_is_rejected(self) -> None:
        with pytest.raises(CalculationError):
            nol_fare(0)

    def test_negative_zones_is_rejected(self) -> None:
        with pytest.raises(CalculationError):
            nol_fare(-1)

    def test_unknown_card_type_is_rejected(self) -> None:
        with pytest.raises(CalculationError, match="unknown card type"):
            nol_fare(2, "platinum")  # type: ignore[arg-type]

    def test_every_result_carries_a_citation(self) -> None:
        result = nol_fare(2)
        assert result.citations
        citation = result.citations[0]
        assert citation.source.startswith("http")
        assert citation.effective_from

    def test_unverified_rates_are_flagged(self) -> None:
        """nol bands aren't in any archived dataset — the answer must say so."""
        result = nol_fare(2)
        assert any("indicative" in c for c in result.caveats)


class TestMonthlyCommute:
    def test_default_two_zone_commute(self) -> None:
        # 5.00 × 2 trips × 22 days
        assert monthly_commute_cost(2).total == Decimal("220.00")

    def test_one_zone_commute(self) -> None:
        # 3.00 × 2 × 22
        assert monthly_commute_cost(1).total == Decimal("132.00")

    def test_gold_card_doubles_the_month(self) -> None:
        assert monthly_commute_cost(2, "gold").total == Decimal("440.00")

    def test_custom_working_days(self) -> None:
        # 5.00 × 2 × 20
        assert monthly_commute_cost(2, working_days=20).total == Decimal("200.00")

    def test_one_way_only(self) -> None:
        # 5.00 × 1 × 22
        assert monthly_commute_cost(2, trips_per_day=1).total == Decimal("110.00")

    def test_monthly_pass_is_suggested_when_cheaper(self) -> None:
        """Gold 3-zone: 15 × 2 × 22 = 660 > 350 pass."""
        result = monthly_commute_cost(3, "gold")
        assert result.total == Decimal("660.00")
        assert any("monthly all-zones pass" in c for c in result.caveats)

    def test_pass_not_suggested_when_pay_as_you_go_is_cheaper(self) -> None:
        result = monthly_commute_cost(1)  # 132 < 350
        assert not any("pass at AED" in c for c in result.caveats)

    def test_assumptions_are_returned_and_labelled_bilingually(self) -> None:
        result = monthly_commute_cost(2)
        keys = {a.key for a in result.assumptions}
        assert {"zones", "card_type", "working_days_per_month", "trips_per_day"} <= keys
        assert all(a.label_en and a.label_ar for a in result.assumptions)

    def test_zero_working_days_is_rejected(self) -> None:
        with pytest.raises(CalculationError):
            monthly_commute_cost(2, working_days=0)


class TestSalik:
    def test_two_crossings_per_day(self) -> None:
        # 4.00 × 2 × 22
        assert salik_cost(2).total == Decimal("176.00")

    def test_four_crossings_per_day(self) -> None:
        assert salik_cost(4).total == Decimal("352.00")

    def test_zero_crossings_is_free(self) -> None:
        assert salik_cost(0).total == Decimal("0.00")

    def test_negative_crossings_is_rejected(self) -> None:
        with pytest.raises(CalculationError):
            salik_cost(-1)

    def test_rate_is_verified_against_the_archived_dataset(self) -> None:
        citation = salik_cost(2).citations[0]
        assert citation.verified_against_dataset is True
        assert citation.effective_from == "2018-11-01"

    def test_variable_peak_pricing_gap_is_disclosed(self) -> None:
        """Masar holds only the 2018 flat tariff. Presenting it as current
        would be exactly the overclaim the honesty rule forbids."""
        assert any("peak pricing" in c for c in salik_cost(2).caveats)


class TestDriveVsTransit:
    def test_arithmetic_is_exact(self) -> None:
        result = drive_vs_transit(zones=2, distance_km_one_way=20.0, salik_crossings_per_day=2)
        # transit: 5.00 × 2 × 22                      = 220.00
        # km:      20 × 2 × 22                        = 880 km
        # fuel:    880 × 9/100 = 79.2 L × 2.90        = 229.68
        # salik:   4.00 × 2 × 22                      = 176.00
        # parking: 15.00 × 22                         = 330.00
        # drive:   229.68 + 176.00 + 330.00           = 735.68
        # delta:   735.68 − 220.00                    = 515.68
        assert result.total == Decimal("515.68")

    def test_parking_can_be_excluded(self) -> None:
        result = drive_vs_transit(
            zones=2,
            distance_km_one_way=20.0,
            salik_crossings_per_day=2,
            include_parking=False,
        )
        # 229.68 + 176.00 = 405.68 − 220.00 = 185.68
        assert result.total == Decimal("185.68")

    def test_no_salik_route(self) -> None:
        result = drive_vs_transit(zones=1, distance_km_one_way=5.0)
        # transit: 3 × 2 × 22 = 132.00
        # km: 5 × 2 × 22 = 220; fuel: 19.8 L × 2.90 = 57.42
        # parking: 330.00 → drive 387.42 → delta 255.42
        assert result.total == Decimal("255.42")

    def test_depreciation_gap_is_disclosed(self) -> None:
        result = drive_vs_transit(zones=2, distance_km_one_way=20.0)
        assert any("depreciation" in c for c in result.caveats)

    def test_driving_assumptions_are_all_declared(self) -> None:
        result = drive_vs_transit(zones=2, distance_km_one_way=20.0)
        keys = {a.key for a in result.assumptions}
        assert {"fuel_price_per_litre", "fuel_consumption", "parking_per_day"} <= keys

    def test_zero_distance_is_rejected(self) -> None:
        with pytest.raises(CalculationError):
            drive_vs_transit(zones=2, distance_km_one_way=0)


class TestZonesBetween:
    @pytest.mark.parametrize(
        ("origin", "destination", "expected"),
        [(1, 1, 1), (1, 2, 2), (2, 1, 2), (1, 3, 3), (5, 5, 1)],
    )
    def test_zone_counting(self, origin: int, destination: int, expected: int) -> None:
        assert zones_between(origin, destination) == expected

    @pytest.mark.parametrize(
        ("origin", "destination"),
        [(None, 2), (1, None), ("abc", 2), (None, None)],
    )
    def test_missing_or_invalid_zones_default_to_one(self, origin, destination) -> None:
        """Defaulting low means a thin answer that A12 can catch, rather than an
        inflated fare presented confidently."""
        assert zones_between(origin, destination) == 1

    def test_string_zone_ids_are_accepted(self) -> None:
        assert zones_between("1", "3") == 3


class TestSerialisation:
    def test_result_serialises_for_the_api(self) -> None:
        payload = monthly_commute_cost(2).to_dict()
        assert payload["total"] == "220.00"
        assert payload["currency"] == "AED"
        assert payload["breakdown"] and payload["assumptions"] and payload["citations"]

    def test_totals_are_two_decimal_places(self) -> None:
        for calculation in (nol_fare(2), monthly_commute_cost(3), salik_cost(3)):
            assert payload_places(calculation.to_dict()["total"]) == 2


def payload_places(amount: str) -> int:
    return len(amount.split(".")[1]) if "." in amount else 0


class TestConfig:
    def test_fares_config_declares_provenance_for_every_rate_block(self) -> None:
        fares = load_fares()
        for block in ("nol", "salik", "driving_assumptions"):
            assert "source" in fares[block]
            assert "verified_against_dataset" in fares[block]
