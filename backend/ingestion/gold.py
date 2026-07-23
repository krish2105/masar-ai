"""Gold layer — the curated star schema.

This is the only surface the Text-to-SQL agent (A8) is allowed to see. It is
deliberately small: a schema card an LLM can hold in context produces markedly
better SQL than `information_schema` dumped into a prompt, and a bounded schema
means a question outside it becomes a named gap rather than a guess.

    dim_station            unified station master across metro, tram, bus, marine
    dim_stop               bus stop master with geometry
    dim_route              route master across modes
    dim_date               calendar spine
    bridge_route_stop      route ↔ stop, with stop ordering
    fact_ridership_monthly monthly trips, route- or station-grain
    fact_modal_split       monthly trips by transport type
    dim_salik_tariff       toll rate by period

Every dimension and fact carries `source_dataset`, `source_url`, `captured_at`
and `source_tier`, so a citation can be resolved from any row back to the
archived file it came from.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import polars as pl

from backend.ingestion.arabic import normalise_arabic
from backend.services.logging import get_logger

log = get_logger(__name__)

MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}

# The closed domain of `transport_type` in the modal-split dataset.
#
# Several archived captures are corrupt at source: RTA published 6-character
# truncated operator names ("Renaul", "Rehabi", "City C") into this column, one
# file carrying 18,768 rows where a modal split has ~5. Rows outside this
# domain are quarantined and counted rather than being aggregated into a modal
# split that would then be silently wrong.
VALID_TRANSPORT_TYPES = {
    "bus", "metro", "tram", "marine", "taxi", "monorail",
    "water bus", "water taxi", "abra", "ferry", "public bus", "intercity bus",
}

# Ratio beyond which a period's per-entity median is treated as a different
# unit or grain rather than a real change in ridership.
SCALE_ANOMALY_FACTOR = 5.0

MONTH_NAMES_AR = {
    1: "يناير", 2: "فبراير", 3: "مارس", 4: "أبريل", 5: "مايو", 6: "يونيو",
    7: "يوليو", 8: "أغسطس", 9: "سبتمبر", 10: "أكتوبر", 11: "نوفمبر", 12: "ديسمبر",
}
MONTH_NAMES_EN = {
    1: "January", 2: "February", 3: "March", 4: "April", 5: "May", 6: "June",
    7: "July", 8: "August", 9: "September", 10: "October", 11: "November", 12: "December",
}


class GoldBuilder:
    """Reads Silver parquet and emits the star schema.

    A missing silver table is a warning, not an error: the archive did not
    recover every dataset, and the schema degrades to what is actually present
    rather than failing the whole build.
    """

    def __init__(self, silver_dir: Path, gold_dir: Path) -> None:
        self.silver_dir = silver_dir
        self.gold_dir = gold_dir
        self.gold_dir.mkdir(parents=True, exist_ok=True)
        self._cache: dict[str, pl.DataFrame | None] = {}

    # ----------------------------------------------------------------- io ----
    def silver(self, dataset_id: str) -> pl.DataFrame | None:
        if dataset_id not in self._cache:
            path = self.silver_dir / f"{dataset_id}.parquet"
            if path.exists():
                self._cache[dataset_id] = pl.read_parquet(path)
            else:
                log.warning("gold.silver_missing", dataset=dataset_id)
                self._cache[dataset_id] = None
        return self._cache[dataset_id]

    @staticmethod
    def _provenance(frame: pl.DataFrame, dataset_id: str) -> pl.DataFrame:
        """Attach citation-resolvable provenance to every row."""
        return frame.with_columns(
            pl.lit(dataset_id).alias("source_dataset"),
            (
                pl.col("_source_url") if "_source_url" in frame.columns
                else pl.lit("")
            ).alias("source_url"),
            (
                pl.col("_captured_at") if "_captured_at" in frame.columns
                else pl.lit("")
            ).alias("captured_at"),
            (
                pl.col("_source_tier") if "_source_tier" in frame.columns
                else pl.lit("archive")
            ).alias("source_tier"),
            pl.lit(False).alias("is_synthetic"),
        )

    @staticmethod
    def _pick(frame: pl.DataFrame, *candidates: str) -> str | None:
        """First column present from a list of candidates.

        Column names drift across datasets and snapshots; resolving by
        preference order keeps that drift out of the mapping code below.
        """
        for name in candidates:
            if name in frame.columns:
                return name
        return None

    def _write(self, name: str, frame: pl.DataFrame) -> pl.DataFrame:
        frame.write_parquet(self.gold_dir / f"{name}.parquet", compression="zstd")
        log.info("gold.written", table=name, rows=frame.height, columns=len(frame.columns))
        return frame

    # ---------------------------------------------------------- dimensions ----
    def build_dim_station(self) -> pl.DataFrame:
        """Unified station master.

        `transport_stations` is the multi-modal spine — bilingual names, zone_id,
        line_name and geometry across BUS/METRO/TRAM. `metro_stations` is merged
        on top because it carries opening dates and a canonical `location_id`
        that the metro ridership facts join against by name.
        """
        parts: list[pl.DataFrame] = []

        if (frame := self.silver("transport_stations")) is not None:
            name_en = self._pick(frame, "station_name_en", "station_name")
            name_ar = self._pick(frame, "station_name_ar")
            selected = frame.select(
                pl.col(self._pick(frame, "station_number", "station_id") or "station_number")
                .cast(pl.Utf8).alias("station_id"),
                pl.col(name_en).cast(pl.Utf8).alias("station_name_en") if name_en
                else pl.lit(None, pl.Utf8).alias("station_name_en"),
                pl.col(name_ar).cast(pl.Utf8).alias("station_name_ar") if name_ar
                else pl.lit(None, pl.Utf8).alias("station_name_ar"),
                pl.col("transport_mode").cast(pl.Utf8).str.to_titlecase().alias("mode"),
                pl.col("line_name").cast(pl.Utf8).alias("line_name")
                if "line_name" in frame.columns else pl.lit(None, pl.Utf8).alias("line_name"),
                pl.col("zone_id").cast(pl.Float64).cast(pl.Int32, strict=False).alias("zone_id")
                if "zone_id" in frame.columns else pl.lit(None, pl.Int32).alias("zone_id"),
                pl.col("latitude").cast(pl.Float64).alias("latitude")
                if "latitude" in frame.columns else pl.lit(None, pl.Float64).alias("latitude"),
                pl.col("longitude").cast(pl.Float64).alias("longitude")
                if "longitude" in frame.columns else pl.lit(None, pl.Float64).alias("longitude"),
                pl.lit(None, pl.Utf8).alias("opened_on"),
            )
            parts.append(self._provenance(selected, "transport_stations"))

        if (frame := self.silver("metro_stations")) is not None:
            opened = self._pick(frame, "station_opening_date")
            selected = frame.select(
                pl.col("location_id").cast(pl.Utf8).alias("station_id"),
                pl.col("location_name_en").cast(pl.Utf8).alias("station_name_en"),
                pl.col("location_name_ar").cast(pl.Utf8).alias("station_name_ar"),
                pl.lit("Metro").alias("mode"),
                pl.col("line_name").cast(pl.Utf8).alias("line_name"),
                pl.col("zone_id").cast(pl.Float64).cast(pl.Int32, strict=False).alias("zone_id"),
                pl.col("latitude").cast(pl.Float64).alias("latitude"),
                pl.col("longitude").cast(pl.Float64).alias("longitude"),
                (pl.col(opened).cast(pl.Utf8) if opened else pl.lit(None, pl.Utf8)).alias("opened_on"),
            )
            parts.append(self._provenance(selected, "metro_stations"))

        if (frame := self.silver("marine_stations")) is not None:
            selected = frame.select(
                pl.col("station_id").cast(pl.Utf8).alias("station_id"),
                pl.col("station_name").cast(pl.Utf8).alias("station_name_en"),
                pl.lit(None, pl.Utf8).alias("station_name_ar"),
                pl.lit("Marine").alias("mode"),
                pl.col("route_name").cast(pl.Utf8).alias("line_name")
                if "route_name" in frame.columns else pl.lit(None, pl.Utf8).alias("line_name"),
                pl.lit(None, pl.Int32).alias("zone_id"),
                pl.col("latitude").cast(pl.Float64).alias("latitude")
                if "latitude" in frame.columns else pl.lit(None, pl.Float64).alias("latitude"),
                pl.col("longitude").cast(pl.Float64).alias("longitude")
                if "longitude" in frame.columns else pl.lit(None, pl.Float64).alias("longitude"),
                pl.lit(None, pl.Utf8).alias("opened_on"),
            )
            parts.append(self._provenance(selected, "marine_stations"))

        if not parts:
            return self._write("dim_station", _empty_station())

        stations = pl.concat(parts, how="vertical_relaxed")
        stations = stations.with_columns(
            pl.col("station_name_ar")
            .map_elements(lambda v: normalise_arabic(v) if v else None, return_dtype=pl.Utf8)
            .alias("station_name_ar_norm"),
            # A surrogate key: station_id is only unique within a mode.
            (pl.col("mode").str.to_lowercase() + "_" + pl.col("station_id")).alias("station_key"),
        )
        stations = stations.filter(
            pl.col("station_name_en").is_not_null() | pl.col("station_name_ar").is_not_null()
        ).unique(subset=["station_key"], keep="first", maintain_order=True)

        # The two station sources identify the same physical station by
        # different schemes — `metro_stations.location_id` versus
        # `transport_stations.station_number` — so keying on id alone yields two
        # rows per station (110 "metro stations" against a network of ~53).
        # Collapse on a normalised name within mode instead, preferring the
        # richer source, which is the one carrying a fare zone and geometry.
        source_rank = {"metro_stations": 0, "transport_stations": 1, "marine_stations": 2}
        stations = stations.with_columns(
            pl.col("station_name_en")
            .fill_null("")
            .str.to_lowercase()
            .str.replace_all(r"\b(metro|tram|bus|marine)\b", "")
            .str.replace_all(r"\b(station|stop|terminal)\b", "")
            .str.replace_all(r"[^a-z0-9]+", "")
            .alias("_name_key"),
            pl.col("source_dataset")
            .replace_strict(source_rank, default=9, return_dtype=pl.Int32)
            .alias("_rank"),
            # A row with a zone and coordinates is more useful than one without.
            (
                pl.col("zone_id").is_not_null().cast(pl.Int32)
                + pl.col("latitude").is_not_null().cast(pl.Int32)
                + pl.col("station_name_ar").is_not_null().cast(pl.Int32)
            ).alias("_completeness"),
        )

        before = stations.height
        stations = (
            stations.sort(["_completeness", "_rank"], descending=[True, False])
            .unique(subset=["mode", "_name_key"], keep="first", maintain_order=True)
            .drop(["_name_key", "_rank", "_completeness"])
        )
        collapsed = before - stations.height
        if collapsed:
            log.info("gold.station_dedup", collapsed=collapsed, remaining=stations.height)

        return self._write("dim_station", stations)

    def build_dim_stop(self) -> pl.DataFrame:
        frame = self.silver("bus_stops")
        if frame is None:
            return self._write("dim_stop", _empty_stop())

        selected = frame.select(
            pl.col("stop_id").cast(pl.Utf8).alias("stop_id"),
            pl.col("stop_name").cast(pl.Utf8).alias("stop_name_en"),
            pl.lit(None, pl.Utf8).alias("stop_name_ar"),
            pl.lit("Bus").alias("mode"),
            pl.col("street_name").cast(pl.Utf8).alias("street_name")
            if "street_name" in frame.columns else pl.lit(None, pl.Utf8).alias("street_name"),
            pl.col("latitude").cast(pl.Float64).alias("latitude")
            if "latitude" in frame.columns else pl.lit(None, pl.Float64).alias("latitude"),
            pl.col("longitude").cast(pl.Float64).alias("longitude")
            if "longitude" in frame.columns else pl.lit(None, pl.Float64).alias("longitude"),
            pl.col("bus_stop_type").cast(pl.Utf8).alias("stop_type")
            if "bus_stop_type" in frame.columns else pl.lit(None, pl.Utf8).alias("stop_type"),
        )
        stops = self._provenance(selected, "bus_stops")
        stops = stops.filter(pl.col("stop_id").is_not_null()).unique(
            subset=["stop_id"], keep="first", maintain_order=True
        )
        return self._write("dim_stop", stops)

    def build_dim_route(self) -> pl.DataFrame:
        """Route master.

        `routes_stops` is preferred over `bus_routes` where both describe a
        route, because it carries mode, endpoints, length and frequency rather
        than just a stop sequence.
        """
        parts: list[pl.DataFrame] = []

        if (frame := self.silver("routes_stops")) is not None:
            aggregated = frame.group_by(["route_name", "transport_mode"]).agg(
                pl.col("first_stop").drop_nulls().first().alias("origin_en"),
                pl.col("last_stop").drop_nulls().first().alias("destination_en"),
                pl.col("route_type").drop_nulls().first().alias("route_type"),
                pl.col("depot_name").drop_nulls().first().alias("operator")
                if "depot_name" in frame.columns else pl.lit(None).first().alias("operator"),
                pl.col("route_length").drop_nulls().first().alias("route_length_km")
                if "route_length" in frame.columns else pl.lit(None).first().alias("route_length_km"),
                pl.col("stop_id").n_unique().alias("stop_count"),
                pl.col("_source_url").first().alias("_source_url")
                if "_source_url" in frame.columns else pl.lit("").first().alias("_source_url"),
                pl.col("_captured_at").first().alias("_captured_at")
                if "_captured_at" in frame.columns else pl.lit("").first().alias("_captured_at"),
            )
            selected = aggregated.select(
                pl.col("route_name").cast(pl.Utf8).alias("route_number"),
                pl.col("route_name").cast(pl.Utf8).alias("route_name_en"),
                pl.lit(None, pl.Utf8).alias("route_name_ar"),
                pl.col("transport_mode").cast(pl.Utf8).str.to_titlecase().alias("mode"),
                pl.col("route_type").cast(pl.Utf8).alias("route_type"),
                pl.col("origin_en").cast(pl.Utf8).alias("origin_en"),
                pl.col("destination_en").cast(pl.Utf8).alias("destination_en"),
                pl.col("operator").cast(pl.Utf8).alias("operator"),
                pl.col("route_length_km").cast(pl.Float64, strict=False).alias("route_length_km"),
                pl.col("stop_count").cast(pl.Int32).alias("stop_count"),
                pl.col("_source_url"),
                pl.col("_captured_at"),
            )
            parts.append(self._provenance(selected, "routes_stops"))

        if (frame := self.silver("bus_routes")) is not None:
            aggregated = frame.group_by("route_name").agg(
                pl.col("route_type").drop_nulls().first().alias("route_type"),
                pl.col("direction").drop_nulls().first().alias("direction"),
                pl.col("stop_number").count().alias("stop_count"),
                pl.col("_source_url").first().alias("_source_url")
                if "_source_url" in frame.columns else pl.lit("").first().alias("_source_url"),
                pl.col("_captured_at").first().alias("_captured_at")
                if "_captured_at" in frame.columns else pl.lit("").first().alias("_captured_at"),
            )
            selected = aggregated.select(
                pl.col("route_name").cast(pl.Utf8).alias("route_number"),
                pl.col("route_name").cast(pl.Utf8).alias("route_name_en"),
                pl.lit(None, pl.Utf8).alias("route_name_ar"),
                pl.lit("Bus").alias("mode"),
                pl.col("route_type").cast(pl.Utf8).alias("route_type"),
                # "GSBS9 -> QSDH11" encodes both endpoints in one field.
                pl.col("direction").cast(pl.Utf8).str.split(" -> ").list.first().alias("origin_en"),
                pl.col("direction").cast(pl.Utf8).str.split(" -> ").list.last().alias("destination_en"),
                pl.lit(None, pl.Utf8).alias("operator"),
                pl.lit(None, pl.Float64).alias("route_length_km"),
                pl.col("stop_count").cast(pl.Int32).alias("stop_count"),
                pl.col("_source_url"),
                pl.col("_captured_at"),
            )
            parts.append(self._provenance(selected, "bus_routes"))

        for dataset_id, mode in (("metro_lines", "Metro"), ("tram_lines", "Tram")):
            if (frame := self.silver(dataset_id)) is None:
                continue
            selected = frame.select(
                pl.col("line_name").cast(pl.Utf8).alias("route_number"),
                pl.col("line_name").cast(pl.Utf8).alias("route_name_en"),
                pl.lit(None, pl.Utf8).alias("route_name_ar"),
                pl.lit(mode).alias("mode"),
                pl.lit("Line").alias("route_type"),
                pl.lit(None, pl.Utf8).alias("origin_en"),
                pl.lit(None, pl.Utf8).alias("destination_en"),
                pl.lit("RTA").alias("operator"),
                pl.lit(None, pl.Float64).alias("route_length_km"),
                pl.lit(None, pl.Int32).alias("stop_count"),
                pl.col("_source_url") if "_source_url" in frame.columns else pl.lit(""),
                pl.col("_captured_at") if "_captured_at" in frame.columns else pl.lit(""),
            )
            parts.append(self._provenance(selected, dataset_id))

        if not parts:
            return self._write("dim_route", _empty_route())

        routes = pl.concat(parts, how="vertical_relaxed").drop(["_source_url", "_captured_at"])
        routes = routes.with_columns(
            (pl.col("mode").str.to_lowercase() + "_" + pl.col("route_number")).alias("route_key")
        )
        routes = routes.filter(pl.col("route_number").is_not_null()).unique(
            subset=["route_key"], keep="first", maintain_order=True
        )
        return self._write("dim_route", routes)

    def build_bridge_route_stop(self) -> pl.DataFrame:
        """Route ↔ stop, with ordering. The join backbone for A10 traversal."""
        frame = self.silver("routes_stops")
        if frame is None:
            return self._write("bridge_route_stop", _empty_bridge())

        selected = frame.select(
            pl.col("route_name").cast(pl.Utf8).alias("route_number"),
            pl.col("transport_mode").cast(pl.Utf8).str.to_titlecase().alias("mode"),
            pl.col("stop_id").cast(pl.Utf8).alias("stop_id"),
            pl.col("stop_name").cast(pl.Utf8).alias("stop_name_en"),
            pl.col("stop_order_number").cast(pl.Float64).cast(pl.Int32, strict=False).alias("stop_order")
            if "stop_order_number" in frame.columns else pl.lit(None, pl.Int32).alias("stop_order"),
            pl.col("route_direction").cast(pl.Utf8).alias("direction")
            if "route_direction" in frame.columns else pl.lit(None, pl.Utf8).alias("direction"),
            pl.col("latitude").cast(pl.Float64).alias("latitude")
            if "latitude" in frame.columns else pl.lit(None, pl.Float64).alias("latitude"),
            pl.col("longitude").cast(pl.Float64).alias("longitude")
            if "longitude" in frame.columns else pl.lit(None, pl.Float64).alias("longitude"),
        )
        bridge = self._provenance(selected, "routes_stops").with_columns(
            (pl.col("mode").str.to_lowercase() + "_" + pl.col("route_number")).alias("route_key")
        )
        bridge = bridge.filter(
            pl.col("route_number").is_not_null() & pl.col("stop_id").is_not_null()
        )
        return self._write("bridge_route_stop", bridge)

    # --------------------------------------------------------------- facts ----
    def build_fact_ridership(self) -> pl.DataFrame:
        """Monthly trips, unioned across modes.

        Grain differs by source — bus is per route, rail and marine are per
        station — so `grain` and `entity_name` are explicit columns rather than
        being implied by which rows are populated. A8 can then filter on grain
        instead of guessing.
        """
        sources = [
            ("bus_trips_monthly", "Bus", "route", "route_name"),
            ("metro_trips_by_station_monthly", "Metro", "station", "metro_station"),
            ("tram_trips_by_station_monthly", "Tram", "station", "tram_station"),
            ("marine_trips_by_station_monthly", "Marine", "station", "station_name"),
        ]
        parts: list[pl.DataFrame] = []

        for dataset_id, mode, grain, entity_hint in sources:
            frame = self.silver(dataset_id)
            if frame is None:
                continue
            entity = self._pick(
                frame, entity_hint, "station_name", "metro_station", "tram_station", "route_name"
            )
            trips = self._pick(frame, "trips", "passengers", "trip_count")
            if entity is None or trips is None or "year" not in frame.columns:
                log.warning("gold.fact_skipped", dataset=dataset_id, reason="missing columns")
                continue

            selected = frame.select(
                pl.col("year").cast(pl.Float64).cast(pl.Int32, strict=False).alias("year"),
                pl.col("month").cast(pl.Utf8).alias("month_raw"),
                pl.lit(mode).alias("mode"),
                pl.lit(grain).alias("grain"),
                pl.col(entity).cast(pl.Utf8).alias("entity_name"),
                pl.col(trips).cast(pl.Float64).alias("trips"),
            )
            parts.append(self._provenance(selected, dataset_id))

        if not parts:
            return self._write("fact_ridership_monthly", _empty_ridership())

        facts = pl.concat(parts, how="vertical_relaxed")
        facts = _add_date_key(facts)
        facts = facts.filter(
            pl.col("trips").is_not_null()
            & pl.col("entity_name").is_not_null()
            & pl.col("date_key").is_not_null()
        )
        # Snapshot families republish the same period; keep one row per grain.
        facts = facts.unique(
            subset=["date_key", "mode", "grain", "entity_name"], keep="first", maintain_order=True
        )
        facts = _flag_scale_anomalies(facts)

        anomalous = int(facts.filter(pl.col("scale_anomaly")).height)
        if anomalous:
            log.warning(
                "gold.scale_anomaly",
                rows=anomalous,
                detail="periods whose per-entity median differs from the mode baseline "
                "by more than %sx — probably a different unit or reporting period"
                % SCALE_ANOMALY_FACTOR,
            )
        return self._write("fact_ridership_monthly", facts)

    def build_fact_modal_split(self) -> pl.DataFrame:
        frame = self.silver("modal_split_monthly")
        if frame is None:
            return self._write("fact_modal_split_monthly", _empty_modal())

        selected = frame.select(
            pl.col("year").cast(pl.Float64).cast(pl.Int32, strict=False).alias("year"),
            pl.col("month").cast(pl.Utf8).alias("month_raw"),
            pl.col("transport_type").cast(pl.Utf8).alias("transport_type"),
            pl.col("trips").cast(pl.Float64).alias("trips"),
        )
        facts = _add_date_key(self._provenance(selected, "modal_split_monthly"))
        facts = facts.filter(pl.col("trips").is_not_null() & pl.col("date_key").is_not_null())

        # Enforce the closed domain. Several archived captures are corrupt at
        # source and carry truncated operator names here.
        before = facts.height
        facts = facts.filter(
            pl.col("transport_type").str.strip_chars().str.to_lowercase().is_in(
                list(VALID_TRANSPORT_TYPES)
            )
        )
        rejected = before - facts.height
        if rejected:
            log.warning(
                "gold.transport_type_rejected",
                rows=rejected,
                kept=facts.height,
                detail="values outside the closed transport_type domain — corrupt upstream captures",
            )

        facts = facts.with_columns(
            pl.col("transport_type").str.strip_chars().str.to_titlecase().alias("transport_type")
        )
        # Corrupt captures also duplicate a legitimate label across many rows,
        # so aggregate to one row per period and type rather than trusting
        # first-wins deduplication.
        provenance = ["source_dataset", "source_url", "captured_at", "source_tier", "is_synthetic"]
        facts = (
            facts.group_by(["date_key", "year", "month_num", "month_raw", "transport_type"])
            .agg(
                pl.col("trips").max().alias("trips"),
                *[pl.col(c).first().alias(c) for c in provenance],
            )
            .sort(["date_key", "transport_type"])
        )
        return self._write("fact_modal_split_monthly", facts)

    def build_dim_salik_tariff(self) -> pl.DataFrame:
        frame = self.silver("salik_tariff")
        if frame is None:
            return self._write("dim_salik_tariff", _empty_salik())

        selected = frame.select(
            pl.col("year").cast(pl.Float64).cast(pl.Int32, strict=False).alias("year"),
            pl.col("month").cast(pl.Utf8).alias("month_raw"),
            pl.col("fare").cast(pl.Float64).alias("fare_aed"),
        )
        tariff = _add_date_key(self._provenance(selected, "salik_tariff"))
        tariff = tariff.filter(pl.col("fare_aed").is_not_null())
        tariff = tariff.unique(subset=["date_key"], keep="first", maintain_order=True)
        return self._write("dim_salik_tariff", tariff)

    def build_dim_date(self, facts: list[pl.DataFrame]) -> pl.DataFrame:
        """Calendar spine covering every period present in the facts."""
        keys: set[str] = set()
        for frame in facts:
            if frame.height and "date_key" in frame.columns:
                keys.update(frame.get_column("date_key").drop_nulls().to_list())

        if not keys:
            return self._write("dim_date", _empty_date())

        rows = []
        for key in sorted(keys):
            year, month = int(key[:4]), int(key[4:6])
            rows.append(
                {
                    "date_key": key,
                    "full_date": f"{year:04d}-{month:02d}-01",
                    "year": year,
                    "month": month,
                    "month_name_en": MONTH_NAMES_EN[month],
                    "month_name_ar": MONTH_NAMES_AR[month],
                    "quarter": (month - 1) // 3 + 1,
                    "year_month": f"{year:04d}-{month:02d}",
                }
            )
        return self._write("dim_date", pl.DataFrame(rows))

    # ------------------------------------------------------ taxi and roads ----
    def build_dim_taxi_stand(self) -> pl.DataFrame:
        frame = self.silver("taxi_stands")
        if frame is None:
            return self._write("dim_taxi_stand", _empty_taxi_stand())

        name = self._pick(frame, "stand_name", "name", "location_name", "taxi_stand_name")
        identifier = self._pick(frame, "stand_id", "id", "location_id")
        selected = frame.select(
            (pl.col(identifier).cast(pl.Utf8) if identifier else pl.lit(None, pl.Utf8)).alias("stand_id"),
            (pl.col(name).cast(pl.Utf8) if name else pl.lit(None, pl.Utf8)).alias("stand_name_en"),
            pl.col("latitude").cast(pl.Float64).alias("latitude")
            if "latitude" in frame.columns else pl.lit(None, pl.Float64).alias("latitude"),
            pl.col("longitude").cast(pl.Float64).alias("longitude")
            if "longitude" in frame.columns else pl.lit(None, pl.Float64).alias("longitude"),
        )
        stands = self._provenance(selected, "taxi_stands")
        # Some stands carry no id in the source; a row index keeps the key unique.
        stands = stands.with_row_index("_row").with_columns(
            pl.coalesce([pl.col("stand_id"), pl.lit("stand_") + pl.col("_row").cast(pl.Utf8)]).alias("stand_id")
        ).drop("_row")
        return self._write("dim_taxi_stand", stands)

    def build_dim_taxi_driver_profile(self) -> pl.DataFrame:
        frame = self.silver("taxi_drivers")
        if frame is None:
            return self._write("dim_taxi_driver_profile", _empty_taxi_driver())

        operator = self._pick(frame, "operator_name", "operator", "company")
        count = self._pick(frame, "drivers_num", "drivers", "count")
        selected = frame.select(
            pl.col("report_date").cast(pl.Utf8).alias("report_date")
            if "report_date" in frame.columns else pl.lit(None, pl.Utf8).alias("report_date"),
            pl.col("operator_type").cast(pl.Utf8).alias("operator_type")
            if "operator_type" in frame.columns else pl.lit(None, pl.Utf8).alias("operator_type"),
            (pl.col(operator).cast(pl.Utf8) if operator else pl.lit(None, pl.Utf8)).alias("operator_name"),
            (pl.col(count).cast(pl.Float64) if count else pl.lit(None, pl.Float64)).alias("driver_count"),
        )
        return self._write("dim_taxi_driver_profile", self._provenance(selected, "taxi_drivers"))

    def build_dim_salik_gate(self) -> pl.DataFrame:
        frame = self.silver("salik_gates")
        if frame is None:
            return self._write("dim_salik_gate", _empty_salik_gate())

        name_en = self._pick(frame, "gate_name_en", "gate_name", "name_en", "toll_gate_name", "name")
        name_ar = self._pick(frame, "gate_name_ar", "name_ar")
        selected = frame.select(
            (pl.col(name_en).cast(pl.Utf8) if name_en else pl.lit(None, pl.Utf8)).alias("gate_name_en"),
            (pl.col(name_ar).cast(pl.Utf8) if name_ar else pl.lit(None, pl.Utf8)).alias("gate_name_ar"),
            pl.col("latitude").cast(pl.Float64).alias("latitude")
            if "latitude" in frame.columns else pl.lit(None, pl.Float64).alias("latitude"),
            pl.col("longitude").cast(pl.Float64).alias("longitude")
            if "longitude" in frame.columns else pl.lit(None, pl.Float64).alias("longitude"),
        )
        gates = self._provenance(selected, "salik_gates").with_row_index("gate_id")
        return self._write(
            "dim_salik_gate", gates.with_columns(pl.col("gate_id").cast(pl.Utf8))
        )

    # ----------------------------------------------------------------- run ----
    def build_all(self) -> dict[str, pl.DataFrame]:
        tables = {
            "dim_station": self.build_dim_station(),
            "dim_stop": self.build_dim_stop(),
            "dim_route": self.build_dim_route(),
            "bridge_route_stop": self.build_bridge_route_stop(),
            "fact_ridership_monthly": self.build_fact_ridership(),
            "fact_modal_split_monthly": self.build_fact_modal_split(),
            "dim_salik_tariff": self.build_dim_salik_tariff(),
            "dim_taxi_stand": self.build_dim_taxi_stand(),
            "dim_taxi_driver_profile": self.build_dim_taxi_driver_profile(),
            "dim_salik_gate": self.build_dim_salik_gate(),
        }
        tables["dim_date"] = self.build_dim_date(
            [
                tables["fact_ridership_monthly"],
                tables["fact_modal_split_monthly"],
                tables["dim_salik_tariff"],
            ]
        )
        return tables


# ------------------------------------------------------------------ helpers --


def _add_date_key(frame: pl.DataFrame) -> pl.DataFrame:
    """`year` + a month name like "Nov" → a sortable `YYYYMM` key.

    Month names arrive abbreviated, full, and occasionally numeric. Mapping via
    a lookup rather than a locale-dependent parse keeps this deterministic.
    """
    month_number = (
        pl.col("month_raw")
        .cast(pl.Utf8)
        .str.strip_chars()
        .str.to_lowercase()
        .replace_strict(MONTHS, default=None, return_dtype=pl.Int32)
    )
    # Some snapshots carry a numeric month instead of a name.
    numeric_fallback = pl.col("month_raw").cast(pl.Utf8).cast(pl.Int32, strict=False)
    resolved = pl.coalesce([month_number, numeric_fallback]).alias("month_num")

    frame = frame.with_columns(resolved)
    return frame.with_columns(
        pl.when(pl.col("year").is_not_null() & pl.col("month_num").is_between(1, 12))
        .then(
            pl.col("year").cast(pl.Utf8).str.zfill(4)
            + pl.col("month_num").cast(pl.Utf8).str.zfill(2)
        )
        .otherwise(None)
        .alias("date_key")
    )


def _flag_scale_anomalies(facts: pl.DataFrame) -> pl.DataFrame:
    """Mark periods whose magnitude is inconsistent with the rest of their mode.

    The archived metro ridership series is not internally comparable: 2021–22
    captures report ~14–23 million trips per month across 53 stations, while
    2025–26 captures report ~1.0–1.2 million across the *same* 53 stations. A
    20x drop in Dubai Metro ridership did not happen; the later captures use a
    different unit or reporting period, which the published schema does not
    state.

    Silently summing across that boundary yields a confidently wrong trend —
    exactly the failure this system exists to avoid. Rather than guessing at a
    conversion factor there is no evidence for, each row is flagged with the
    ratio of its period's per-entity median to the mode's overall median. A8 can
    filter on it, A12 sees it as a recency/authority signal, and A13 states the
    limitation in the answer.
    """
    if facts.height == 0:
        return facts.with_columns(
            pl.lit(None, pl.Float64).alias("period_scale_ratio"),
            pl.lit(False).alias("scale_anomaly"),
        )

    period_median = facts.group_by(["mode", "date_key"]).agg(
        pl.col("trips").median().alias("_period_median")
    )
    mode_median = period_median.group_by("mode").agg(
        pl.col("_period_median").median().alias("_mode_median")
    )

    enriched = facts.join(period_median, on=["mode", "date_key"], how="left").join(
        mode_median, on="mode", how="left"
    )
    return (
        enriched.with_columns(
            (pl.col("_period_median") / pl.col("_mode_median")).alias("period_scale_ratio")
        )
        .with_columns(
            (
                pl.col("period_scale_ratio").is_not_null()
                & (
                    (pl.col("period_scale_ratio") > SCALE_ANOMALY_FACTOR)
                    | (pl.col("period_scale_ratio") < 1 / SCALE_ANOMALY_FACTOR)
                )
            ).alias("scale_anomaly")
        )
        .drop(["_period_median", "_mode_median"])
    )


def _empty(columns: dict[str, pl.DataType]) -> pl.DataFrame:
    return pl.DataFrame(schema=columns)


def _empty_station() -> pl.DataFrame:
    return _empty({
        "station_key": pl.Utf8, "station_id": pl.Utf8, "station_name_en": pl.Utf8,
        "station_name_ar": pl.Utf8, "station_name_ar_norm": pl.Utf8, "mode": pl.Utf8,
        "line_name": pl.Utf8, "zone_id": pl.Int32, "latitude": pl.Float64,
        "longitude": pl.Float64, "opened_on": pl.Utf8, "source_dataset": pl.Utf8,
        "source_url": pl.Utf8, "captured_at": pl.Utf8, "source_tier": pl.Utf8,
        "is_synthetic": pl.Boolean,
    })


def _empty_stop() -> pl.DataFrame:
    return _empty({
        "stop_id": pl.Utf8, "stop_name_en": pl.Utf8, "stop_name_ar": pl.Utf8,
        "mode": pl.Utf8, "street_name": pl.Utf8, "latitude": pl.Float64,
        "longitude": pl.Float64, "stop_type": pl.Utf8, "source_dataset": pl.Utf8,
        "source_url": pl.Utf8, "captured_at": pl.Utf8, "source_tier": pl.Utf8,
        "is_synthetic": pl.Boolean,
    })


def _empty_route() -> pl.DataFrame:
    return _empty({
        "route_key": pl.Utf8, "route_number": pl.Utf8, "route_name_en": pl.Utf8,
        "route_name_ar": pl.Utf8, "mode": pl.Utf8, "route_type": pl.Utf8,
        "origin_en": pl.Utf8, "destination_en": pl.Utf8, "operator": pl.Utf8,
        "route_length_km": pl.Float64, "stop_count": pl.Int32,
        "source_dataset": pl.Utf8, "source_url": pl.Utf8, "captured_at": pl.Utf8,
        "source_tier": pl.Utf8, "is_synthetic": pl.Boolean,
    })


def _empty_bridge() -> pl.DataFrame:
    return _empty({
        "route_key": pl.Utf8, "route_number": pl.Utf8, "mode": pl.Utf8,
        "stop_id": pl.Utf8, "stop_name_en": pl.Utf8, "stop_order": pl.Int32,
        "direction": pl.Utf8, "latitude": pl.Float64, "longitude": pl.Float64,
        "source_dataset": pl.Utf8, "source_url": pl.Utf8, "captured_at": pl.Utf8,
        "source_tier": pl.Utf8, "is_synthetic": pl.Boolean,
    })


def _empty_ridership() -> pl.DataFrame:
    return _empty({
        "date_key": pl.Utf8, "year": pl.Int32, "month_num": pl.Int32,
        "month_raw": pl.Utf8, "mode": pl.Utf8, "grain": pl.Utf8,
        "entity_name": pl.Utf8, "trips": pl.Float64, "source_dataset": pl.Utf8,
        "source_url": pl.Utf8, "captured_at": pl.Utf8, "source_tier": pl.Utf8,
        "is_synthetic": pl.Boolean, "period_scale_ratio": pl.Float64,
        "scale_anomaly": pl.Boolean,
    })


def _empty_modal() -> pl.DataFrame:
    return _empty({
        "date_key": pl.Utf8, "year": pl.Int32, "month_num": pl.Int32,
        "month_raw": pl.Utf8, "transport_type": pl.Utf8, "trips": pl.Float64,
        "source_dataset": pl.Utf8, "source_url": pl.Utf8, "captured_at": pl.Utf8,
        "source_tier": pl.Utf8, "is_synthetic": pl.Boolean,
    })


def _empty_salik() -> pl.DataFrame:
    return _empty({
        "date_key": pl.Utf8, "year": pl.Int32, "month_num": pl.Int32,
        "month_raw": pl.Utf8, "fare_aed": pl.Float64, "source_dataset": pl.Utf8,
        "source_url": pl.Utf8, "captured_at": pl.Utf8, "source_tier": pl.Utf8,
        "is_synthetic": pl.Boolean,
    })


def _empty_taxi_stand() -> pl.DataFrame:
    return _empty({
        "stand_id": pl.Utf8, "stand_name_en": pl.Utf8, "latitude": pl.Float64,
        "longitude": pl.Float64, "source_dataset": pl.Utf8, "source_url": pl.Utf8,
        "captured_at": pl.Utf8, "source_tier": pl.Utf8, "is_synthetic": pl.Boolean,
    })


def _empty_taxi_driver() -> pl.DataFrame:
    return _empty({
        "report_date": pl.Utf8, "operator_type": pl.Utf8, "operator_name": pl.Utf8,
        "driver_count": pl.Float64, "source_dataset": pl.Utf8, "source_url": pl.Utf8,
        "captured_at": pl.Utf8, "source_tier": pl.Utf8, "is_synthetic": pl.Boolean,
    })


def _empty_salik_gate() -> pl.DataFrame:
    return _empty({
        "gate_id": pl.Utf8, "gate_name_en": pl.Utf8, "gate_name_ar": pl.Utf8,
        "latitude": pl.Float64, "longitude": pl.Float64, "source_dataset": pl.Utf8,
        "source_url": pl.Utf8, "captured_at": pl.Utf8, "source_tier": pl.Utf8,
        "is_synthetic": pl.Boolean,
    })


def _empty_date() -> pl.DataFrame:
    return _empty({
        "date_key": pl.Utf8, "full_date": pl.Utf8, "year": pl.Int64, "month": pl.Int64,
        "month_name_en": pl.Utf8, "month_name_ar": pl.Utf8, "quarter": pl.Int64,
        "year_month": pl.Utf8,
    })


def summarise(tables: dict[str, pl.DataFrame]) -> str:
    lines = [
        "",
        "  PHASE 3 GATE — gold star schema",
        "  " + "─" * 72,
        f"  {'table':<30} {'rows':>10} {'columns':>9}   status",
        "  " + "─" * 72,
    ]
    for name, frame in tables.items():
        mark = "✓" if frame.height else "✗ empty"
        lines.append(f"  {name:<30} {frame.height:>10,} {len(frame.columns):>9}   {mark}")
    populated = sum(1 for f in tables.values() if f.height)
    lines += [
        "  " + "─" * 72,
        f"  {populated}/{len(tables)} tables populated · "
        f"{sum(f.height for f in tables.values()):,} rows total",
        "",
    ]
    return "\n".join(lines)
