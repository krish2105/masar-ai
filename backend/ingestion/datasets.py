"""The dataset catalogue.

Every dataset Masar ingests is declared here, once. §3.3 of the build spec names
twelve; this catalogue carries those twelve plus a small number of supporting
datasets that turned out to be archived alongside them and materially improve
the star schema (metro/tram station geometry, tram and marine ridership).

`archive_stem` is the filename prefix used by Dubai Pulse's CKAN resource
downloads, e.g. ``bus_passengers_trips_by_route_monthly_2025-09-20_00-00-00.csv``
has stem ``bus_passengers_trips_by_route_monthly``. Snapshot families share a
stem and differ only by the date suffix, which encodes the *data* period — not
the capture date.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class Domain(StrEnum):
    BUS = "bus"
    RAIL = "rail"
    MARINE = "marine"
    TAXI = "taxi"
    ROADS = "roads"
    MULTIMODAL = "multimodal"


class SourceTier(StrEnum):
    """Provenance tier. Surfaced on every row, every citation, every evidence card."""

    ARCHIVE = "archive"      # recovered from Internet Archive snapshots of Dubai Pulse
    LIVE_API = "live_api"    # fetched from the Dubai Pulse gateway with credentials
    SYNTHETIC = "synthetic"  # generated stand-in — always badged in the UI


@dataclass(frozen=True, slots=True)
class Dataset:
    id: str
    """Masar's stable internal identifier."""

    dubai_pulse_slug: str
    """The original Dubai Pulse dataset slug, retained for citation lineage."""

    archive_stem: str
    """Resource filename prefix used to locate captures in the Wayback CDX index."""

    domain: Domain
    role: str
    """What this dataset contributes to the system — used in DATA_DICTIONARY.md."""

    is_snapshot_family: bool = False
    """True when many dated files stitch into one time series."""

    natural_key: tuple[str, ...] = field(default_factory=tuple)
    """Columns that identify a row uniquely, for Silver-layer deduplication."""

    core: bool = True
    """False for supporting datasets not named in §3.3."""

    max_files: int | None = None
    """Cap on files pulled from a snapshot family, newest periods kept.

    Set only where a family is transaction-grain and enormous while a monthly
    aggregate carries the same analytical signal in kilobytes. Whatever is
    skipped is counted and named in the bronze manifest — a cap that is not
    reported reads as full coverage when it is not.
    """

    cap_rationale: str = ""
    """Why `max_files` is set. Published in DATA_DICTIONARY.md."""

    @property
    def service_area(self) -> str:
        """Dubai Pulse service path segment, for reconstructing landing-page URLs."""
        return {
            Domain.BUS: "rta-bus",
            Domain.RAIL: "rta-rail",
            Domain.MARINE: "rta-marine",
            Domain.TAXI: "roads-and-cars",
            Domain.ROADS: "rta-archive",
            Domain.MULTIMODAL: "rta-public-transport",
        }[self.domain]

    @property
    def landing_page(self) -> str:
        """Original dataset page. Retained for citation display even though the
        host now redirects — it is the canonical identifier of the source."""
        return f"https://www.dubaipulse.gov.ae/data/{self.service_area}/{self.dubai_pulse_slug}"


# =============================================================================
# The catalogue
# =============================================================================

DATASETS: tuple[Dataset, ...] = (
    # ---- Bus ---------------------------------------------------------------
    Dataset(
        id="bus_routes",
        dubai_pulse_slug="rta_bus_routes-open",
        archive_stem="bus_routes",
        domain=Domain.BUS,
        role="Route master — route number, service type, direction, ordered stop sequence.",
        natural_key=("route_name", "direction", "stop_number"),
    ),
    Dataset(
        id="bus_stops",
        dubai_pulse_slug="rta_bus_stops_gis-open",
        archive_stem="bus_stop_details",
        domain=Domain.BUS,
        role="Stop master with geometry — powers catchment and nearest-stop analysis (A10).",
        natural_key=("stop_id",),
    ),
    Dataset(
        id="bus_ridership",
        dubai_pulse_slug="rta_bus_ridership-open",
        archive_stem="bus_ridership",
        domain=Domain.BUS,
        role="Transaction-grain bus ridership. Sampled — see cap_rationale.",
        is_snapshot_family=True,
        max_files=2,
        cap_rationale=(
            "Each capture is ~35 MB of transaction-grain records from 2018 and there "
            "are 31 of them (~1.0 GB). The analytical signal Masar actually needs is "
            "already in bus_trips_monthly at 5 KB per period and current to 2026. "
            "Two captures are retained for schema fidelity and to demonstrate handling "
            "of large files; the remainder are recorded as skipped in the manifest."
        ),
    ),
    Dataset(
        id="bus_trips_monthly",
        dubai_pulse_slug="rta_bus_passengers_trips_by_route_monthly-open",
        archive_stem="bus_passengers_trips_by_route_monthly",
        domain=Domain.BUS,
        role="Monthly passenger trips per bus route — the core trend fact for NETWORK_ANALYTICS.",
        is_snapshot_family=True,
        natural_key=("year", "month", "route_name"),
    ),
    # ---- Rail --------------------------------------------------------------
    Dataset(
        id="metro_lines",
        dubai_pulse_slug="rta_metro_lines-open",
        archive_stem="metro_lines",
        domain=Domain.RAIL,
        role="Red/Green line master.",
        natural_key=("line_name",),
    ),
    Dataset(
        id="metro_stations",
        dubai_pulse_slug="rta_metro_stations_gis-open",
        archive_stem="metro_stations",
        domain=Domain.RAIL,
        role=(
            "Station master — bilingual names, zone_id, lat/lon, opening date. "
            "The single richest table in the catalogue: it alone supports geospatial, "
            "fare-zone and Arabic-retrieval requirements."
        ),
        natural_key=("location_id",),
    ),
    Dataset(
        id="metro_ridership",
        dubai_pulse_slug="rta_metro_ridership-open",
        archive_stem="metro_ridership",
        domain=Domain.RAIL,
        role="Transaction-grain metro ridership. Sampled — see cap_rationale.",
        is_snapshot_family=True,
        max_files=1,
        cap_rationale=(
            "Each capture is ~194 MB and there are 24 of them (~4.4 GB) — the single "
            "largest item in the catalogue by two orders of magnitude. "
            "metro_trips_by_station_monthly carries the same station-level demand "
            "signal at 2.7 KB per period, current to January 2026. One capture is "
            "retained so the raw grain is inspectable; 23 are recorded as skipped."
        ),
    ),
    Dataset(
        id="metro_trips_by_station_monthly",
        dubai_pulse_slug="rta_metro_ridership-open",
        archive_stem="metro_passengers_trips_by_station_monthly",
        domain=Domain.RAIL,
        role="Monthly passenger trips per metro station — station-level demand, current to Jan 2026.",
        is_snapshot_family=True,
        natural_key=("year", "month", "metro_station"),
    ),
    Dataset(
        id="tram_stations",
        dubai_pulse_slug="rta_tram_stations-open",
        archive_stem="tram_stations",
        domain=Domain.RAIL,
        role="Tram station master — zone_id, line_name, location_id, geometry.",
        natural_key=("location_id",),
    ),
    Dataset(
        id="tram_lines",
        dubai_pulse_slug="rta_tram_lines_gis-open",
        archive_stem="tram_lines",
        domain=Domain.RAIL,
        role="Tram line master.",
        core=False,
    ),
    Dataset(
        id="tram_trips_by_station_monthly",
        dubai_pulse_slug="rta_tram_ridership-open",
        archive_stem="tram_passengers_trips_by_station_monthly",
        domain=Domain.RAIL,
        role="Monthly tram trips per station — completes the rail picture beyond metro.",
        is_snapshot_family=True,
        natural_key=("year", "month", "tram_station"),
        core=False,
    ),
    # ---- Multi-modal -------------------------------------------------------
    Dataset(
        id="routes_stops",
        dubai_pulse_slug="rta_public_transportation_routes_stops-open",
        archive_stem="public_transportation_routes_stops",
        domain=Domain.MULTIMODAL,
        role="Route↔stop bridge table — the join backbone for multi-modal traversal.",
        natural_key=("route_name", "route_direction", "stop_id", "stop_order_number"),
    ),
    Dataset(
        id="transport_stations",
        dubai_pulse_slug="rta_public_transportation_stations-open",
        archive_stem="public_transportation_stations",
        domain=Domain.MULTIMODAL,
        role="Unified station master across modes.",
        core=False,
    ),
    Dataset(
        id="modal_split_monthly",
        dubai_pulse_slug="rta_public_transport_trips_by_type_of_transport_month-open",
        archive_stem="public_transport_trips_by_type_of_transport_month",
        domain=Domain.MULTIMODAL,
        role="Modal split over time — trips by transport type per month.",
        is_snapshot_family=True,
        natural_key=("year", "month", "transport_type"),
    ),
    # ---- Taxi --------------------------------------------------------------
    Dataset(
        id="taxi_stands",
        dubai_pulse_slug="rta_taxi_stand_locations-open",
        archive_stem="taxi_stand_locations",
        domain=Domain.TAXI,
        role="Taxi stand geometry — last-mile leg of GEOSPATIAL answers.",
        natural_key=(),
    ),
    Dataset(
        id="taxi_drivers",
        dubai_pulse_slug="rta_dubai_taxi_drivers-open",
        archive_stem="dubai_taxi_drivers",
        domain=Domain.TAXI,
        role="Fleet and driver demographics — supply-side analysis.",
        is_snapshot_family=True,
    ),
    # ---- Roads -------------------------------------------------------------
    Dataset(
        id="salik_tariff",
        dubai_pulse_slug="rta_salik_tariff-open",
        archive_stem="salik_tariff",
        domain=Domain.ROADS,
        role="Salik toll tariff — the drive-vs-transit cost comparison in A11.",
        is_snapshot_family=True,
        natural_key=("year", "month"),
    ),
    # ---- Marine (supporting) ----------------------------------------------
    Dataset(
        id="marine_stations",
        dubai_pulse_slug="rta_marine_stations_gis-open",
        archive_stem="marine_stations",
        domain=Domain.MARINE,
        role="Marine station geometry — abra, ferry, water bus.",
        core=False,
    ),
    Dataset(
        id="marine_trips_by_station_monthly",
        dubai_pulse_slug="rta_marine_ridership-open",
        archive_stem="marine_passengers_trips_by_station_monthly",
        domain=Domain.MARINE,
        role="Monthly marine trips per station.",
        is_snapshot_family=True,
        core=False,
    ),
)

BY_ID: dict[str, Dataset] = {d.id: d for d in DATASETS}
CORE_DATASETS: tuple[Dataset, ...] = tuple(d for d in DATASETS if d.core)


def get(dataset_id: str) -> Dataset:
    try:
        return BY_ID[dataset_id]
    except KeyError:
        raise KeyError(
            f"Unknown dataset {dataset_id!r}. Known: {', '.join(sorted(BY_ID))}"
        ) from None
