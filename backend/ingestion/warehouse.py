"""Postgres loader for the gold star schema.

DDL is written out explicitly rather than inferred from the dataframes. The
schema is the contract A8 generates SQL against, so column names and types are
a deliberate design decision, not an artefact of whatever Polars happened to
infer — and explicit DDL is where the indexes and constraints live.

Loading is idempotent: tables are dropped and recreated on every run. The gold
layer is derived data, rebuildable from bronze in minutes, so a clean rebuild is
simpler and safer than incremental upserts.
"""

from __future__ import annotations

import io
from pathlib import Path

import polars as pl
import psycopg

from backend.services.logging import get_logger

log = get_logger(__name__)


DDL = """
-- =============================================================================
-- MASAR AI — gold star schema
-- The only surface the Text-to-SQL agent (A8) is permitted to query.
-- =============================================================================

DROP TABLE IF EXISTS fact_ridership_monthly    CASCADE;
DROP TABLE IF EXISTS fact_modal_split_monthly  CASCADE;
DROP TABLE IF EXISTS bridge_route_stop         CASCADE;
DROP TABLE IF EXISTS dim_salik_tariff          CASCADE;
DROP TABLE IF EXISTS dim_station               CASCADE;
DROP TABLE IF EXISTS dim_stop                  CASCADE;
DROP TABLE IF EXISTS dim_route                 CASCADE;
DROP TABLE IF EXISTS dim_date                  CASCADE;

-- ---------------------------------------------------------------- dimensions
CREATE TABLE dim_station (
    station_key          TEXT PRIMARY KEY,
    station_id           TEXT NOT NULL,
    station_name_en      TEXT,
    station_name_ar      TEXT,
    station_name_ar_norm TEXT,
    mode                 TEXT NOT NULL,
    line_name            TEXT,
    zone_id              INTEGER,
    latitude             DOUBLE PRECISION,
    longitude            DOUBLE PRECISION,
    opened_on            TEXT,
    source_dataset       TEXT NOT NULL,
    source_url           TEXT,
    captured_at          TEXT,
    source_tier          TEXT NOT NULL DEFAULT 'archive',
    is_synthetic         BOOLEAN NOT NULL DEFAULT FALSE
);
COMMENT ON TABLE  dim_station IS 'Station master across Metro, Tram, Bus and Marine. station_id is unique only within a mode; station_key is the surrogate.';
COMMENT ON COLUMN dim_station.zone_id IS 'RTA fare zone. Drives nol fare calculation in A11.';
COMMENT ON COLUMN dim_station.station_name_ar_norm IS 'Arabic normalised for search (alef unified, diacritics stripped). Never displayed.';

CREATE TABLE dim_stop (
    stop_id        TEXT PRIMARY KEY,
    stop_name_en   TEXT,
    stop_name_ar   TEXT,
    mode           TEXT NOT NULL,
    street_name    TEXT,
    latitude       DOUBLE PRECISION,
    longitude      DOUBLE PRECISION,
    stop_type      TEXT,
    source_dataset TEXT NOT NULL,
    source_url     TEXT,
    captured_at    TEXT,
    source_tier    TEXT NOT NULL DEFAULT 'archive',
    is_synthetic   BOOLEAN NOT NULL DEFAULT FALSE
);
COMMENT ON TABLE dim_stop IS 'Bus stop master with WGS84 geometry. Powers nearest-stop and catchment analysis (A10).';

CREATE TABLE dim_route (
    route_key       TEXT PRIMARY KEY,
    route_number    TEXT NOT NULL,
    route_name_en   TEXT,
    route_name_ar   TEXT,
    mode            TEXT NOT NULL,
    route_type      TEXT,
    origin_en       TEXT,
    destination_en  TEXT,
    operator        TEXT,
    route_length_km DOUBLE PRECISION,
    stop_count      INTEGER,
    source_dataset  TEXT NOT NULL,
    source_url      TEXT,
    captured_at     TEXT,
    source_tier     TEXT NOT NULL DEFAULT 'archive',
    is_synthetic    BOOLEAN NOT NULL DEFAULT FALSE
);
COMMENT ON TABLE dim_route IS 'Route master across modes. route_number is the public-facing identifier, e.g. "13", "F27", "Red Metro Line".';

CREATE TABLE dim_date (
    date_key      TEXT PRIMARY KEY,
    full_date     DATE NOT NULL,
    year          INTEGER NOT NULL,
    month         INTEGER NOT NULL,
    month_name_en TEXT NOT NULL,
    month_name_ar TEXT NOT NULL,
    quarter       INTEGER NOT NULL,
    year_month    TEXT NOT NULL
);
COMMENT ON TABLE dim_date IS 'Calendar spine at month grain. date_key is YYYYMM.';

CREATE TABLE dim_salik_tariff (
    date_key       TEXT PRIMARY KEY,
    year           INTEGER,
    month_num      INTEGER,
    month_raw      TEXT,
    fare_aed       DOUBLE PRECISION NOT NULL,
    source_dataset TEXT NOT NULL,
    source_url     TEXT,
    captured_at    TEXT,
    source_tier    TEXT NOT NULL DEFAULT 'archive',
    is_synthetic   BOOLEAN NOT NULL DEFAULT FALSE
);
COMMENT ON TABLE dim_salik_tariff IS 'Salik toll rate by period, in AED per gate crossing.';

-- -------------------------------------------------------------------- bridge
CREATE TABLE bridge_route_stop (
    route_key      TEXT NOT NULL,
    route_number   TEXT NOT NULL,
    mode           TEXT NOT NULL,
    stop_id        TEXT NOT NULL,
    stop_name_en   TEXT,
    stop_order     INTEGER,
    direction      TEXT,
    latitude       DOUBLE PRECISION,
    longitude      DOUBLE PRECISION,
    source_dataset TEXT NOT NULL,
    source_url     TEXT,
    captured_at    TEXT,
    source_tier    TEXT NOT NULL DEFAULT 'archive',
    is_synthetic   BOOLEAN NOT NULL DEFAULT FALSE
);
COMMENT ON TABLE bridge_route_stop IS 'Route to stop, with ordering. The join backbone for multi-modal traversal (A10).';

-- --------------------------------------------------------------------- facts
CREATE TABLE fact_ridership_monthly (
    date_key       TEXT NOT NULL,
    year           INTEGER,
    month_num      INTEGER,
    month_raw      TEXT,
    mode           TEXT NOT NULL,
    grain          TEXT NOT NULL,
    entity_name    TEXT NOT NULL,
    trips              DOUBLE PRECISION NOT NULL,
    period_scale_ratio DOUBLE PRECISION,
    scale_anomaly      BOOLEAN NOT NULL DEFAULT FALSE,
    source_dataset TEXT NOT NULL,
    source_url     TEXT,
    captured_at    TEXT,
    source_tier    TEXT NOT NULL DEFAULT 'archive',
    is_synthetic   BOOLEAN NOT NULL DEFAULT FALSE
);
COMMENT ON TABLE  fact_ridership_monthly IS 'Monthly passenger trips. Grain differs by mode: Bus is per route, Metro/Tram/Marine are per station.';
COMMENT ON COLUMN fact_ridership_monthly.grain IS '"route" or "station" — filter on this rather than inferring from mode.';
COMMENT ON COLUMN fact_ridership_monthly.entity_name IS 'Route number or station name, per grain.';
COMMENT ON COLUMN fact_ridership_monthly.scale_anomaly IS 'TRUE when this period''s magnitude is inconsistent with the rest of its mode (different unit or reporting period at source). ALWAYS exclude these rows from cross-year trends, or state the limitation.';
COMMENT ON COLUMN fact_ridership_monthly.period_scale_ratio IS 'Period per-entity median divided by the mode baseline. ~1.0 is comparable; far from 1.0 is not.';

CREATE TABLE fact_modal_split_monthly (
    date_key       TEXT NOT NULL,
    year           INTEGER,
    month_num      INTEGER,
    month_raw      TEXT,
    transport_type TEXT NOT NULL,
    trips          DOUBLE PRECISION NOT NULL,
    source_dataset TEXT NOT NULL,
    source_url     TEXT,
    captured_at    TEXT,
    source_tier    TEXT NOT NULL DEFAULT 'archive',
    is_synthetic   BOOLEAN NOT NULL DEFAULT FALSE
);
COMMENT ON TABLE fact_modal_split_monthly IS 'Monthly trips by transport type — modal split over time.';
"""

INDEXES = """
-- Dimension lookups
CREATE INDEX idx_station_mode        ON dim_station (mode);
CREATE INDEX idx_station_zone        ON dim_station (zone_id);
CREATE INDEX idx_station_line        ON dim_station (line_name);
CREATE INDEX idx_station_geo         ON dim_station (latitude, longitude);
CREATE INDEX idx_stop_geo            ON dim_stop    (latitude, longitude);
CREATE INDEX idx_route_mode          ON dim_route   (mode);
CREATE INDEX idx_route_number        ON dim_route   (route_number);

-- Bridge traversal
CREATE INDEX idx_bridge_route        ON bridge_route_stop (route_key);
CREATE INDEX idx_bridge_stop         ON bridge_route_stop (stop_id);
CREATE INDEX idx_bridge_route_order  ON bridge_route_stop (route_key, stop_order);

-- Fact scans
CREATE INDEX idx_ridership_date      ON fact_ridership_monthly (date_key);
CREATE INDEX idx_ridership_mode      ON fact_ridership_monthly (mode, grain);
CREATE INDEX idx_ridership_entity    ON fact_ridership_monthly (entity_name);
CREATE INDEX idx_modal_date          ON fact_modal_split_monthly (date_key);

-- Trigram indexes for fuzzy name matching. Station names arrive spelled several
-- ways ("Union", "Union Metro Station", "BurJuman"), and exact equality misses
-- all but one of them.
CREATE INDEX idx_station_name_trgm   ON dim_station USING gin (station_name_en gin_trgm_ops);
CREATE INDEX idx_station_ar_trgm     ON dim_station USING gin (station_name_ar_norm gin_trgm_ops);
CREATE INDEX idx_stop_name_trgm      ON dim_stop    USING gin (stop_name_en gin_trgm_ops);
CREATE INDEX idx_ridership_ent_trgm  ON fact_ridership_monthly USING gin (entity_name gin_trgm_ops);
"""

# The read-only role must see tables created after init_db.sql ran.
GRANTS = """
GRANT SELECT ON ALL TABLES IN SCHEMA public TO masar_ro;
"""

TABLE_ORDER = (
    "dim_date",
    "dim_station",
    "dim_stop",
    "dim_route",
    "dim_salik_tariff",
    "bridge_route_stop",
    "fact_ridership_monthly",
    "fact_modal_split_monthly",
)


def _column_order(conn: psycopg.Connection, table: str) -> list[str]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT column_name FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = %s
            ORDER BY ordinal_position
            """,
            (table,),
        )
        return [row[0] for row in cur.fetchall()]


def load_table(conn: psycopg.Connection, table: str, frame: pl.DataFrame) -> int:
    """COPY one gold table in.

    The frame is projected onto the table's real column order first — the DDL is
    authoritative, not whatever order the builder happened to emit — and any
    column the table does not have is dropped rather than causing a mismatch.
    """
    if frame.height == 0:
        log.warning("warehouse.empty_table", table=table)
        return 0

    columns = _column_order(conn, table)
    missing = [c for c in columns if c not in frame.columns]
    for name in missing:
        frame = frame.with_columns(pl.lit(None).alias(name))
    projected = frame.select(columns)

    buffer = io.StringIO()
    projected.write_csv(buffer, include_header=False)
    buffer.seek(0)

    column_list = ", ".join(f'"{c}"' for c in columns)
    with conn.cursor() as cur:
        with cur.copy(
            f'COPY {table} ({column_list}) FROM STDIN WITH (FORMAT csv, NULL \'\')'
        ) as copy:
            copy.write(buffer.read())

    log.info("warehouse.loaded", table=table, rows=projected.height, filled_nulls=missing)
    return projected.height


def load_all(dsn: str, gold_dir: Path) -> dict[str, int]:
    """Rebuild the warehouse from data/gold/*.parquet."""
    counts: dict[str, int] = {}

    with psycopg.connect(dsn, autocommit=False) as conn:
        log.info("warehouse.ddl")
        with conn.cursor() as cur:
            cur.execute(DDL)
        conn.commit()

        for table in TABLE_ORDER:
            path = gold_dir / f"{table}.parquet"
            if not path.exists():
                log.warning("warehouse.missing_parquet", table=table)
                counts[table] = 0
                continue
            counts[table] = load_table(conn, table, pl.read_parquet(path))
        conn.commit()

        log.info("warehouse.indexes")
        with conn.cursor() as cur:
            cur.execute(INDEXES)
            cur.execute(GRANTS)
            cur.execute("ANALYZE")
        conn.commit()

    return counts


def verify(dsn: str) -> list[tuple[str, str, int]]:
    """Ten canonical analytical queries — the Phase 3 gate.

    These are the shapes A8 will actually generate: joins across the star,
    aggregation over time, geospatial filtering, and the bridge traversal. If
    any returns zero rows the schema is loaded but not usable, which is a
    failure the row counts alone would not reveal.
    """
    queries: list[tuple[str, str]] = [
        (
            "stations by mode",
            "SELECT mode, COUNT(*) FROM dim_station GROUP BY mode ORDER BY 2 DESC",
        ),
        (
            "metro stations with a fare zone",
            "SELECT COUNT(*) FROM dim_station WHERE mode = 'Metro' AND zone_id IS NOT NULL",
        ),
        (
            "bilingual station coverage",
            "SELECT COUNT(*) FROM dim_station WHERE station_name_ar IS NOT NULL",
        ),
        (
            "busiest metro stations, latest month",
            """
            SELECT entity_name, trips FROM fact_ridership_monthly
            WHERE mode = 'Metro' AND grain = 'station'
              AND date_key = (SELECT MAX(date_key) FROM fact_ridership_monthly WHERE mode='Metro')
            ORDER BY trips DESC LIMIT 5
            """,
        ),
        (
            "metro trend, comparable periods only",
            """
            SELECT year, SUM(trips)::bigint FROM fact_ridership_monthly
            WHERE mode = 'Metro' AND NOT scale_anomaly
            GROUP BY year ORDER BY year
            """,
        ),
        (
            "periods flagged as non-comparable",
            """
            SELECT mode, COUNT(DISTINCT date_key) AS periods,
                   ROUND(MIN(period_scale_ratio)::numeric, 3) AS min_ratio
            FROM fact_ridership_monthly WHERE scale_anomaly
            GROUP BY mode
            """,
        ),
        (
            "modal split, latest month",
            """
            SELECT transport_type, trips FROM fact_modal_split_monthly
            WHERE date_key = (SELECT MAX(date_key) FROM fact_modal_split_monthly)
            ORDER BY trips DESC
            """,
        ),
        (
            "ridership joined to the date spine",
            """
            SELECT d.year, d.month_name_en, SUM(f.trips)::bigint
            FROM fact_ridership_monthly f JOIN dim_date d USING (date_key)
            WHERE f.mode = 'Metro' GROUP BY d.year, d.month_name_en, d.month
            ORDER BY d.year DESC, d.month DESC LIMIT 5
            """,
        ),
        (
            "routes with the most stops",
            """
            SELECT r.route_number, r.mode, COUNT(b.stop_id) AS stops
            FROM dim_route r JOIN bridge_route_stop b USING (route_key)
            GROUP BY r.route_number, r.mode ORDER BY stops DESC LIMIT 5
            """,
        ),
        (
            "stops within ~2km of Burj Khalifa",
            """
            SELECT COUNT(*) FROM dim_stop
            WHERE latitude BETWEEN 25.177 AND 25.213
              AND longitude BETWEEN 55.256 AND 55.296
            """,
        ),
        (
            "salik tariff history",
            "SELECT date_key, fare_aed FROM dim_salik_tariff ORDER BY date_key DESC LIMIT 3",
        ),
    ]

    results: list[tuple[str, str, int]] = []
    with psycopg.connect(dsn) as conn:
        for label, sql in queries:
            with conn.cursor() as cur:
                try:
                    cur.execute(sql)
                    rows = cur.fetchall()
                    preview = "; ".join(
                        ", ".join(str(v) for v in row) for row in rows[:3]
                    )
                    results.append((label, preview[:110], len(rows)))
                except Exception as exc:  # noqa: BLE001
                    results.append((label, f"ERROR: {type(exc).__name__}: {exc}"[:110], 0))
    return results
