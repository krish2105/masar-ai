"""Silver layer — typed, deduplicated, bilingually normalised.

Applies the §3.5 transformation rules to every dataset:

1. snake_case column names; strip whitespace and BOM
2. split bilingual columns into `*_en` / `*_ar`, never one mixed column
3. cast dates and numerics explicitly, counting every coercion failure
4. deduplicate on the natural key, keeping the newest capture
5. normalise Arabic into a `*_ar_norm` search column, preserving `*_ar` for display
6. standardise geometry to WGS84 float lat/lon, quarantining unparseable rows
7. emit a per-dataset data quality report

Everything is read as strings first. Letting a CSV reader infer types would
silently turn a malformed value into a null and there would be nothing left to
count — the coercion failure metric depends on controlling the cast ourselves.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path

import polars as pl

from backend.ingestion.arabic import has_arabic, normalise_arabic
from backend.ingestion.datasets import Dataset
from backend.ingestion.quality import QualityReport, profile_frame
from backend.services.logging import get_logger

log = get_logger(__name__)

# ---------------------------------------------------------------- naming ----

_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_NON_ALNUM = re.compile(r"[^0-9a-zA-Z]+")
_MULTI_UNDERSCORE = re.compile(r"_{2,}")

_LANGUAGE_SUFFIXES = {
    "english": "en",
    "eng": "en",
    "en": "en",
    "arabic": "ar",
    "ara": "ar",
    "ar": "ar",
}


def snake_case(name: str) -> str:
    """`Location Name English` → `location_name_english`; BOM and stray space stripped."""
    cleaned = name.replace("﻿", "").strip()
    cleaned = _CAMEL_BOUNDARY.sub("_", cleaned)
    cleaned = _NON_ALNUM.sub("_", cleaned)
    cleaned = _MULTI_UNDERSCORE.sub("_", cleaned)
    return cleaned.strip("_").lower()


def standardise_language_suffix(name: str) -> str:
    """`location_name_english` → `location_name_en`, `station_name_arabic` → `*_ar`.

    Uniform suffixes let every downstream component — the star schema, the
    embedder, the citation builder — find the bilingual pair by rule instead of
    by a per-dataset lookup table.
    """
    parts = name.split("_")
    if len(parts) > 1 and parts[-1] in _LANGUAGE_SUFFIXES:
        return "_".join(parts[:-1]) + "_" + _LANGUAGE_SUFFIXES[parts[-1]]
    return name


# -------------------------------------------------------------- detection ----

# `latitiude` and `longitiude` are misspelled in the published RTA marine
# dataset. Matching the typo is not defensive padding — without it the marine
# station geometry is silently dropped.
_LATITUDE_HINTS = ("latitude", "latitiude", "lat", "y_coord", "ycoord")
_LONGITUDE_HINTS = (
    "longitude",
    "longitiude",
    "lon",
    "lng",
    "long",
    "x_coord",
    "xcoord",
)
_DATE_HINTS = ("date", "_at", "opening", "closing", "timestamp", "valid_from", "valid_until")
_NUMERIC_HINTS = (
    "count",
    "trips",
    "passengers",
    "ridership",
    "fare",
    "tariff",
    "amount",
    "total",
    "number",
    "_num",
    "qty",
    "quantity",
    "speed",
    "length",
    "capacity",
    "distance",
    "zone_id",
    "stop_number",
    "value",
    "price",
    "frequency",
)

# Numeric-looking identifiers that must stay strings: leading zeros and route
# codes are meaningful, and casting "07" to 7 loses information irreversibly.
_KEEP_AS_STRING = ("id", "code", "number_plate", "route_name", "route_number")


def _is_geo_column(name: str, hints: tuple[str, ...]) -> bool:
    return any(name == h or name.endswith("_" + h) or h in name.split("_") for h in hints)


def _looks_numeric(name: str) -> bool:
    if any(k in name for k in _KEEP_AS_STRING):
        return False
    return any(h in name for h in _NUMERIC_HINTS)


def _looks_like_date(name: str) -> bool:
    return any(h in name for h in _DATE_HINTS)


# ------------------------------------------------------------------ read ----


def _read_bronze_files(directory: Path) -> tuple[list[pl.DataFrame], dict, int]:
    """Read every CSV in a bronze partition as strings, tagged with provenance."""
    manifest_path = directory / "_manifest.json"
    manifest = (
        json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    )
    by_filename = {f["filename"]: f for f in manifest.get("files", [])}

    frames: list[pl.DataFrame] = []
    schema_signatures: set[tuple[str, ...]] = set()

    for path in sorted(directory.glob("*.csv")):
        entry = by_filename.get(path.name, {})
        try:
            frame = pl.read_csv(
                path,
                infer_schema_length=0,  # everything as Utf8; we control casting
                truncate_ragged_lines=True,
                ignore_errors=True,
                encoding="utf8-lossy",
            )
        except Exception as exc:
            log.warning("silver.read_failed", file=path.name, error=str(exc)[:160])
            continue

        if frame.height == 0:
            continue

        frame = frame.rename({c: standardise_language_suffix(snake_case(c)) for c in frame.columns})
        schema_signatures.add(tuple(frame.columns))

        frame = frame.with_columns(
            pl.lit(entry.get("source_tier", "archive")).alias("_source_tier"),
            pl.lit(entry.get("source_url", "")).alias("_source_url"),
            pl.lit(entry.get("captured_at", "")).alias("_captured_at"),
            pl.lit(entry.get("data_period") or "").alias("_data_period"),
            pl.lit(path.name).alias("_source_file"),
        )
        frames.append(frame)

    return frames, manifest, len(schema_signatures)


def _align_and_concat(frames: list[pl.DataFrame]) -> pl.DataFrame:
    """Union frames whose schemas drifted between snapshots.

    Dubai Pulse changed column sets over the years. Rather than dropping the odd
    snapshot out, every column seen in any file is present in the result, null
    where a given snapshot did not carry it.
    """
    if not frames:
        return pl.DataFrame()
    if len(frames) == 1:
        return frames[0]

    all_columns: list[str] = []
    for frame in frames:
        for column in frame.columns:
            if column not in all_columns:
                all_columns.append(column)

    aligned = [
        frame.with_columns(
            [pl.lit(None, dtype=pl.Utf8).alias(c) for c in all_columns if c not in frame.columns]
        ).select(all_columns)
        for frame in frames
    ]
    return pl.concat(aligned, how="vertical_relaxed")


# ------------------------------------------------------------- transform ----


def _clean_strings(frame: pl.DataFrame) -> pl.DataFrame:
    """Trim whitespace and map empty strings and common null tokens to real nulls."""
    null_tokens = ["", "null", "NULL", "None", "N/A", "n/a", "NA", "-", "--"]
    return frame.with_columns(
        [
            pl.col(c).str.strip_chars().replace(null_tokens, None).alias(c)
            for c in frame.columns
            if frame.schema[c] == pl.Utf8
        ]
    )


# A column whose name suggests a number is only cast if its *contents* agree.
# Below this share of parseable values the column is left as text.
_NUMERIC_PARSE_THRESHOLD = 0.98


def _cast_numerics(frame: pl.DataFrame, report: QualityReport) -> pl.DataFrame:
    """Cast numeric-looking columns, but let the data have the final say.

    Naming alone is not enough. `station_number` in the RTA station master holds
    alphanumeric codes such as ``ABBS``; casting it on the strength of "number"
    in the name silently nulled the identifier for 87 stations. So each
    candidate is probed first: if fewer than 98% of its non-null values parse,
    the column stays text and the decision is recorded as a warning rather than
    being logged as 87 coercion failures the column never deserved.
    """
    for column in list(frame.columns):
        if column.startswith("_") or frame.schema[column] != pl.Utf8:
            continue
        if not _looks_numeric(column):
            continue

        cleaned = (
            pl.col(column)
            .str.replace_all(r"[,\s]", "")
            .str.replace_all(r"^AED", "")
            .cast(pl.Float64, strict=False)
        )

        before = int(frame.get_column(column).is_not_null().sum())
        if before == 0:
            continue

        probe = frame.select(cleaned.alias("probe")).get_column("probe")
        parseable = int(probe.is_not_null().sum())
        ratio = parseable / before

        if ratio < _NUMERIC_PARSE_THRESHOLD:
            report.warn(
                f"column {column!r} looks numeric but only "
                f"{parseable}/{before} values parse ({ratio:.1%}); left as text "
                f"— it is an identifier, not a measure"
            )
            log.info(
                "silver.numeric_declined",
                column=column,
                parseable=parseable,
                total=before,
            )
            continue

        frame = frame.with_columns(cleaned.alias(column))
        lost = before - parseable
        if lost:
            # The column really is numeric; these are genuine bad values.
            report.add_coercion_failure(column, lost)
            log.warning("silver.coercion_failure", column=column, lost=lost, dtype="Float64")
    return frame


def _cast_dates(frame: pl.DataFrame, report: QualityReport) -> pl.DataFrame:
    formats = ["%d/%m/%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"]

    for column in list(frame.columns):
        if column.startswith("_") or frame.schema[column] != pl.Utf8:
            continue
        if not _looks_like_date(column):
            continue

        before = int(frame.get_column(column).is_not_null().sum())
        if before == 0:
            continue

        best: pl.Series | None = None
        best_hits = -1
        for fmt in formats:
            try:
                candidate = frame.get_column(column).str.to_datetime(
                    format=fmt, strict=False, time_unit="us"
                )
            except Exception:
                continue
            hits = int(candidate.is_not_null().sum())
            if hits > best_hits:
                best, best_hits = candidate, hits

        # Only adopt the cast if it recovers most values; a date-ish name on a
        # free-text column should not blank the column out.
        if best is not None and best_hits >= before * 0.8:
            frame = frame.with_columns(best.alias(column))
            if best_hits < before:
                report.add_coercion_failure(column, before - best_hits)
        elif best_hits > 0:
            report.warn(
                f"column {column!r} looks like a date but only "
                f"{best_hits}/{before} values parsed; left as text"
            )
    return frame


def _normalise_arabic_columns(frame: pl.DataFrame, report: QualityReport) -> pl.DataFrame:
    """Add a `*_ar_norm` search column beside every Arabic display column.

    Columns are detected by suffix first, then by sampling content — some
    datasets ship an Arabic column with no language marker in its name.
    """
    for column in list(frame.columns):
        if column.startswith("_") or column.endswith("_ar_norm"):
            continue
        if frame.schema[column] != pl.Utf8:
            continue

        is_arabic_column = column.endswith("_ar")
        if not is_arabic_column:
            sample = frame.get_column(column).drop_nulls().head(25).to_list()
            if sample and sum(1 for v in sample if has_arabic(str(v))) >= max(2, len(sample) // 2):
                is_arabic_column = True
                renamed = f"{column}_ar" if not column.endswith("_ar") else column
                if renamed != column and renamed not in frame.columns:
                    frame = frame.rename({column: renamed})
                    report.warn(
                        f"column {column!r} contains Arabic but carried no language "
                        f"suffix; renamed to {renamed!r}"
                    )
                    column = renamed

        if is_arabic_column:
            frame = frame.with_columns(
                pl.col(column)
                .map_elements(
                    lambda v: normalise_arabic(v) if v is not None else None,
                    return_dtype=pl.Utf8,
                )
                .alias(f"{column}_norm")
            )
    return frame


def _standardise_geometry(frame: pl.DataFrame, report: QualityReport) -> pl.DataFrame:
    """Cast lat/lon to float and quarantine rows outside the UAE envelope.

    Dubai sits near 25.2 N, 55.3 E. Anything outside a generous UAE bounding box
    is a swapped pair, a projected coordinate or a placeholder — never a real
    Dubai stop. Those rows are quarantined and counted, never silently dropped.
    """
    lat_columns = [
        c for c in frame.columns if not c.startswith("_") and _is_geo_column(c, _LATITUDE_HINTS)
    ]
    lon_columns = [
        c for c in frame.columns if not c.startswith("_") and _is_geo_column(c, _LONGITUDE_HINTS)
    ]

    if not (lat_columns and lon_columns):
        return frame

    lat, lon = lat_columns[0], lon_columns[0]

    for column in (lat, lon):
        if frame.schema[column] == pl.Utf8:
            frame = frame.with_columns(pl.col(column).cast(pl.Float64, strict=False).alias(column))

    # Standardised names so A10 never has to guess.
    renames = {}
    if lat != "latitude":
        renames[lat] = "latitude"
    if lon != "longitude":
        renames[lon] = "longitude"
    if renames:
        frame = frame.rename(renames)
    lat, lon = "latitude", "longitude"

    in_uae = pl.col(lat).is_between(22.0, 26.5) & pl.col(lon).is_between(51.0, 57.0)
    has_coords = pl.col(lat).is_not_null() & pl.col(lon).is_not_null()

    invalid = frame.filter(has_coords & ~in_uae)
    if invalid.height:
        sample = invalid.head(1).to_dicts()[0] if invalid.height else None
        report.quarantine("coordinates_outside_uae", invalid.height, sample)
        frame = frame.filter(~(has_coords & ~in_uae))

    missing = int(frame.select(has_coords.not_().sum()).item())
    if missing:
        report.warn(f"{missing} rows have no coordinates; retained (geometry is optional)")

    return frame


def _deduplicate(frame: pl.DataFrame, dataset: Dataset, report: QualityReport) -> pl.DataFrame:
    """Keep the newest capture per natural key.

    Snapshot families legitimately re-publish the same period across captures;
    without this the ridership facts would double-count.
    """
    keys = [k for k in dataset.natural_key if k in frame.columns]
    if not keys:
        before = frame.height
        frame = frame.unique(keep="first")
        removed = before - frame.height
        if removed:
            report.rows_deduplicated += removed
            report.warn(
                f"no natural key declared for {dataset.id!r}; deduplicated on the full row "
                f"({removed} exact duplicates removed)"
            )
        return frame

    report.natural_key = keys
    before = frame.height
    sort_columns = [c for c in ("_captured_at", "_data_period") if c in frame.columns]
    if sort_columns:
        frame = frame.sort(sort_columns, descending=True)
    frame = frame.unique(subset=keys, keep="first", maintain_order=True)
    report.rows_deduplicated = before - frame.height
    return frame


# ------------------------------------------------------------------ main ----


def transform_dataset(
    dataset: Dataset, bronze_root: Path, silver_root: Path
) -> QualityReport | None:
    """Bronze → Silver for one dataset. Returns None when there is no bronze data."""
    dataset_root = bronze_root / dataset.id
    if not dataset_root.is_dir():
        log.warning("silver.no_bronze", dataset=dataset.id)
        return None

    partitions = sorted((p for p in dataset_root.iterdir() if p.is_dir()), reverse=True)
    if not partitions:
        log.warning("silver.no_partition", dataset=dataset.id)
        return None
    partition = partitions[0]

    report = QualityReport(
        dataset_id=dataset.id,
        source_tier="archive",
        generated_at=datetime.now(tz=UTC).isoformat(),
    )

    frames, manifest, schema_variants = _read_bronze_files(partition)
    report.files_read = len(frames)
    report.schema_variants = schema_variants
    report.data_period_range = manifest.get("data_period_range")
    captures = manifest.get("capture_dates") or []
    report.capture_date_range = [captures[0], captures[-1]] if captures else None

    if not frames:
        log.warning("silver.empty", dataset=dataset.id)
        report.write(Path(silver_root).parent.parent / "reports" / "dq")
        return report

    frame = _align_and_concat(frames)
    report.rows_in = frame.height

    frame = _clean_strings(frame)
    frame = _cast_numerics(frame, report)
    frame = _cast_dates(frame, report)
    frame = _normalise_arabic_columns(frame, report)
    frame = _standardise_geometry(frame, report)
    frame = _deduplicate(frame, dataset, report)

    # Rows that are entirely null across every business column are noise.
    business_columns = [c for c in frame.columns if not c.startswith("_")]
    if business_columns:
        all_null = pl.all_horizontal([pl.col(c).is_null() for c in business_columns])
        empty_rows = int(frame.select(all_null.sum()).item())
        if empty_rows:
            report.quarantine("all_business_columns_null", empty_rows)
            frame = frame.filter(~all_null)

    report.rows_out = frame.height
    report.columns = profile_frame(frame)

    silver_root.mkdir(parents=True, exist_ok=True)
    frame.write_parquet(silver_root / f"{dataset.id}.parquet", compression="zstd")

    log.info(
        "silver.written",
        dataset=dataset.id,
        rows_in=report.rows_in,
        rows_out=report.rows_out,
        columns=len(frame.columns),
        passed=report.passed,
    )
    return report
