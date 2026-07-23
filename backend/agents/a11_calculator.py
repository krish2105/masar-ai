"""A11 — Numeric Calculator. Deterministic, zero LLM involvement.

LLMs are unreliable arithmetic engines and fare calculation is correctness-
critical, so every number in a Masar answer that involves money is produced
here, in Python, and A13 is forbidden from regenerating it — it quotes these
outputs verbatim.

Two consequences follow, and both are deliberate:

* Every rate is read from `config/fares.yaml` and returned alongside the source
  and effective date it came from. A calculation whose inputs cannot be cited is
  not shown.
* Every assumption — working days, fuel price, parking — is returned as
  structured data, rendered in the UI, and overridable per query. An assumption
  the user cannot see is an assumption they cannot challenge.

All money is computed in `Decimal` and rounded once, at the end, to two places.
Float arithmetic on currency accumulates error that eventually shows up as a
fils discrepancy in a demo.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import yaml

CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "fares.yaml"

CardType = Literal["silver", "gold", "blue", "red"]


@lru_cache(maxsize=1)
def load_fares() -> dict[str, Any]:
    with CONFIG_PATH.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _money(value: Decimal | float | int) -> Decimal:
    """Round once, at the end, half-up — the convention for currency."""
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


class CalculationError(ValueError):
    """Invalid inputs. A8-style: becomes a named gap for A12, never a wrong number."""


# =============================================================================
# Result envelope
# =============================================================================


@dataclass(slots=True)
class Assumption:
    """A declared input the user should be able to see and challenge."""

    key: str
    value: str
    label_en: str
    label_ar: str
    source: str

    def to_dict(self) -> dict[str, str]:
        return {
            "key": self.key,
            "value": self.value,
            "label_en": self.label_en,
            "label_ar": self.label_ar,
            "source": self.source,
        }


@dataclass(slots=True)
class RateCitation:
    """Where a rate came from and when it took effect."""

    rate: str
    amount: str
    source: str
    effective_from: str
    verified_against_dataset: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "rate": self.rate,
            "amount": self.amount,
            "source": self.source,
            "effective_from": self.effective_from,
            "verified_against_dataset": self.verified_against_dataset,
        }


@dataclass(slots=True)
class Calculation:
    """A11's output. A13 quotes `total` and `breakdown` verbatim."""

    kind: str
    total: Decimal
    currency: str = "AED"
    breakdown: list[dict[str, str]] = field(default_factory=list)
    assumptions: list[Assumption] = field(default_factory=list)
    citations: list[RateCitation] = field(default_factory=list)
    caveats: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "total": str(_money(self.total)),
            "currency": self.currency,
            "breakdown": self.breakdown,
            "assumptions": [a.to_dict() for a in self.assumptions],
            "citations": [c.to_dict() for c in self.citations],
            "caveats": self.caveats,
        }


# =============================================================================
# nol fares
# =============================================================================


def _nol_citation() -> RateCitation:
    nol = load_fares()["nol"]
    return RateCitation(
        rate="nol zone fare",
        amount="see breakdown",
        source=nol["source"],
        effective_from=nol["effective_from"],
        verified_against_dataset=nol["verified_against_dataset"],
    )


def nol_fare(zones: int, card_type: CardType = "silver") -> Calculation:
    """Single-trip nol fare for a journey crossing `zones` zones.

    >>> nol_fare(2).total
    Decimal('5.00')
    >>> nol_fare(2, "gold").total
    Decimal('10.00')
    >>> nol_fare(7).total          # capped at the 3-zone band
    Decimal('7.50')
    """
    fares = load_fares()
    nol = fares["nol"]

    if zones < 1:
        raise CalculationError(f"zones must be at least 1, got {zones}")
    if card_type not in nol["card_types"]:
        raise CalculationError(
            f"unknown card type {card_type!r}; known: {', '.join(nol['card_types'])}"
        )

    banded = min(zones, int(nol["max_zones"]))
    base = Decimal(str(nol["zone_fares"][banded]))
    card = nol["card_types"][card_type]
    multiplier = Decimal(str(card["multiplier"]))
    total = base * multiplier

    caveats: list[str] = []
    if zones > nol["max_zones"]:
        caveats.append(
            f"Journey crosses {zones} zones; RTA does not price beyond "
            f"{nol['max_zones']}, so the {nol['max_zones']}-zone band applies."
        )
    if not nol["verified_against_dataset"]:
        caveats.append(
            "nol fare bands are not present in any archived RTA dataset Masar holds. "
            "This figure is indicative — confirm at rta.ae."
        )

    return Calculation(
        kind="nol_fare",
        total=total,
        breakdown=[
            {"label": f"Base fare, {banded} zone{'s' if banded > 1 else ''}", "amount": str(_money(base))},
            {"label": f"{card['label_en']} multiplier", "amount": f"× {multiplier}"},
            {"label": "Single trip fare", "amount": str(_money(total))},
        ],
        assumptions=[
            Assumption(
                key="zones",
                value=str(zones),
                label_en=f"{zones} zone(s) crossed",
                label_ar=f"عدد المناطق: {zones}",
                source="derived from origin/destination zone_id in dim_station",
            ),
            Assumption(
                key="card_type",
                value=card_type,
                label_en=card["label_en"],
                label_ar=card["label_ar"],
                source="user-specified or Silver nol default",
            ),
        ],
        citations=[_nol_citation()],
        caveats=caveats,
    )


def monthly_commute_cost(
    zones: int,
    card_type: CardType = "silver",
    working_days: int | None = None,
    trips_per_day: int | None = None,
) -> Calculation:
    """Monthly public-transport commute cost.

    >>> monthly_commute_cost(2).total     # 5.00 × 2 trips × 22 days
    Decimal('220.00')
    """
    fares = load_fares()
    defaults = fares["commute_defaults"]
    days = working_days if working_days is not None else int(defaults["working_days_per_month"])
    trips = trips_per_day if trips_per_day is not None else int(defaults["trips_per_working_day"])

    if days < 1:
        raise CalculationError(f"working_days must be at least 1, got {days}")
    if trips < 1:
        raise CalculationError(f"trips_per_day must be at least 1, got {trips}")

    single = nol_fare(zones, card_type)
    total = single.total * trips * days

    # A monthly pass is often cheaper; not saying so would be a worse answer.
    caveats = list(single.caveats)
    passes = fares["nol"]["passes"]
    pass_price = Decimal(str(passes["monthly_all_zones"]))
    if total > pass_price:
        caveats.append(
            f"A monthly all-zones pass at AED {_money(pass_price)} would be cheaper "
            f"than paying per trip at AED {_money(total)}."
        )

    return Calculation(
        kind="monthly_commute_cost",
        total=total,
        breakdown=[
            *single.breakdown,
            {"label": f"× {trips} trips per day", "amount": str(_money(single.total * trips))},
            {"label": f"× {days} working days", "amount": str(_money(total))},
        ],
        assumptions=[
            *single.assumptions,
            Assumption(
                key="working_days_per_month",
                value=str(days),
                label_en=f"{days} working days per month",
                label_ar=f"{days} يوم عمل شهرياً",
                source="Masar default (5-day week); overridable",
            ),
            Assumption(
                key="trips_per_day",
                value=str(trips),
                label_en=f"{trips} trips per day (return journey)",
                label_ar=f"{trips} رحلة يومياً",
                source="Masar default; overridable",
            ),
        ],
        citations=single.citations,
        caveats=caveats,
    )


# =============================================================================
# Salik
# =============================================================================


def salik_cost(
    crossings_per_day: int,
    working_days: int | None = None,
) -> Calculation:
    """Monthly Salik toll cost.

    >>> salik_cost(2).total       # 4.00 × 2 × 22
    Decimal('176.00')
    """
    fares = load_fares()
    salik = fares["salik"]
    days = working_days if working_days is not None else int(fares["commute_defaults"]["working_days_per_month"])

    if crossings_per_day < 0:
        raise CalculationError(f"crossings_per_day cannot be negative, got {crossings_per_day}")
    if days < 1:
        raise CalculationError(f"working_days must be at least 1, got {days}")

    rate = Decimal(str(salik["flat_rate_per_crossing"]))
    total = rate * crossings_per_day * days

    return Calculation(
        kind="salik_cost",
        total=total,
        breakdown=[
            {"label": "Rate per gate crossing", "amount": str(_money(rate))},
            {"label": f"× {crossings_per_day} crossings per day", "amount": str(_money(rate * crossings_per_day))},
            {"label": f"× {days} working days", "amount": str(_money(total))},
        ],
        assumptions=[
            Assumption(
                key="crossings_per_day",
                value=str(crossings_per_day),
                label_en=f"{crossings_per_day} Salik gate crossings per day",
                label_ar=f"{crossings_per_day} عبور بوابة سالك يومياً",
                source="user-specified or derived from route geometry",
            ),
            Assumption(
                key="working_days_per_month",
                value=str(days),
                label_en=f"{days} working days per month",
                label_ar=f"{days} يوم عمل شهرياً",
                source="Masar default; overridable",
            ),
        ],
        citations=[
            RateCitation(
                rate="Salik per-crossing toll",
                amount=str(_money(rate)),
                source=salik["source"],
                effective_from=salik["effective_from"],
                verified_against_dataset=salik["verified_against_dataset"],
            )
        ],
        caveats=[
            f"Rate is the AED {_money(rate)} flat toll effective {salik['effective_from']}, "
            "taken from the archived RTA tariff dataset. RTA later introduced variable "
            "peak pricing, which is not present in any dataset Masar holds — so a "
            "present-day peak-hour cost would be higher than this figure."
        ],
    )


# =============================================================================
# Drive vs transit
# =============================================================================


def drive_vs_transit(
    zones: int,
    distance_km_one_way: float,
    salik_crossings_per_day: int = 0,
    card_type: CardType = "silver",
    working_days: int | None = None,
    include_parking: bool = True,
) -> Calculation:
    """Monthly cost comparison: driving against public transport.

    Reports both totals and the delta. Every driving input is an explicit,
    challengeable assumption — the comparison is only honest if the reader can
    see what it assumed about fuel and parking.
    """
    fares = load_fares()
    driving = fares["driving_assumptions"]
    days = working_days if working_days is not None else int(fares["commute_defaults"]["working_days_per_month"])

    if distance_km_one_way <= 0:
        raise CalculationError(
            f"distance_km_one_way must be positive, got {distance_km_one_way}"
        )

    transit = monthly_commute_cost(zones, card_type, working_days=days)

    km_per_month = Decimal(str(distance_km_one_way)) * 2 * days
    litres = km_per_month * Decimal(str(driving["fuel_consumption_l_per_100km"])) / Decimal(100)
    fuel = litres * Decimal(str(driving["fuel_price_per_litre"]))

    salik = salik_cost(salik_crossings_per_day, working_days=days) if salik_crossings_per_day else None
    salik_total = salik.total if salik else Decimal(0)

    parking = Decimal(str(driving["parking_per_day"])) * days if include_parking else Decimal(0)

    drive_total = fuel + salik_total + parking
    delta = drive_total - transit.total
    cheaper = "public transport" if delta > 0 else "driving"

    breakdown = [
        {"label": "— Public transport —", "amount": ""},
        {"label": "Monthly nol cost", "amount": str(_money(transit.total))},
        {"label": "— Driving —", "amount": ""},
        {"label": f"Distance ({distance_km_one_way} km × 2 × {days} days)", "amount": f"{_money(km_per_month)} km"},
        {"label": f"Fuel ({_money(litres)} L @ AED {driving['fuel_price_per_litre']}/L)", "amount": str(_money(fuel))},
    ]
    if salik:
        breakdown.append({"label": "Salik tolls", "amount": str(_money(salik_total))})
    if include_parking:
        breakdown.append({"label": f"Parking ({days} days)", "amount": str(_money(parking))})
    breakdown += [
        {"label": "Driving total", "amount": str(_money(drive_total))},
        {"label": "— Difference —", "amount": ""},
        {"label": f"{cheaper.capitalize()} is cheaper by", "amount": str(_money(abs(delta)))},
    ]

    assumptions = [
        *transit.assumptions,
        Assumption(
            key="fuel_price_per_litre",
            value=str(driving["fuel_price_per_litre"]),
            label_en=f"Fuel at AED {driving['fuel_price_per_litre']}/litre",
            label_ar=f"سعر الوقود {driving['fuel_price_per_litre']} درهم/لتر",
            source=driving["source"],
        ),
        Assumption(
            key="fuel_consumption",
            value=str(driving["fuel_consumption_l_per_100km"]),
            label_en=f"Consumption {driving['fuel_consumption_l_per_100km']} L/100km",
            label_ar=f"استهلاك الوقود {driving['fuel_consumption_l_per_100km']} لتر/100 كم",
            source=driving["source"],
        ),
    ]
    if include_parking:
        assumptions.append(
            Assumption(
                key="parking_per_day",
                value=str(driving["parking_per_day"]),
                label_en=f"Parking AED {driving['parking_per_day']}/day",
                label_ar=f"موقف سيارات {driving['parking_per_day']} درهم/يوم",
                source=driving["source"],
            )
        )

    caveats = [
        *transit.caveats,
        "Driving costs exclude vehicle depreciation, insurance, registration and "
        "maintenance, so the real cost of driving is higher than shown.",
    ]
    if salik:
        caveats.extend(salik.caveats)

    return Calculation(
        kind="drive_vs_transit",
        total=abs(delta),
        breakdown=breakdown,
        assumptions=assumptions,
        citations=[*transit.citations, *(salik.citations if salik else [])],
        caveats=caveats,
    )


def zones_between(origin_zone: int | str | None, destination_zone: int | str | None) -> int:
    """Zones crossed between two stations.

    RTA counts the zones a journey *touches*, so travel within one zone is one
    zone and adjacent zones are two. Missing zone data returns 1 rather than
    guessing high — and A12 will see thin evidence and can re-plan.
    """
    try:
        origin = int(origin_zone) if origin_zone is not None else None
        destination = int(destination_zone) if destination_zone is not None else None
    except (TypeError, ValueError):
        return 1
    if origin is None or destination is None:
        return 1
    return abs(destination - origin) + 1
