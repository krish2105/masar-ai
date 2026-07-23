"""Trace and dataset endpoints.

`/api/v1/trace/{turn_id}` returns the full agent waterfall for one turn: every
hop, its model and provider, tokens, latency, decision and cycle. It is what the
`/trace/[id]` page renders and what makes the corrective loop auditable rather
than asserted.

`/api/v1/datasets` exposes the provenance ledger — what was ingested, from
where, when it was captured, and where coverage was capped. Publishing that as
an API rather than burying it in a README is the difference between claiming
governance and demonstrating it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import psycopg
from fastapi import APIRouter, HTTPException, Query

from backend.agents.a14_observability import load_trace
from backend.config.settings import get_settings
from backend.services.logging import get_logger

log = get_logger(__name__)
router = APIRouter(prefix="/api/v1", tags=["trace", "datasets"])


@router.get("/trace/{turn_id}")
async def get_trace(turn_id: str) -> dict[str, Any]:
    settings = get_settings()

    if trace := load_trace(settings.pg_dsn, turn_id):
        return trace

    # Postgres is the primary store, but the JSONL files survive a database
    # rebuild — so a trace is still readable after `make nuke`.
    for path in settings.trace_dir.glob(f"*/{turn_id}.jsonl"):
        hops: list[dict[str, Any]] = []
        summary: dict[str, Any] = {}
        for line in path.read_text(encoding="utf-8").splitlines():
            record = json.loads(line)
            if "_summary" in record:
                summary = record["_summary"]
            else:
                hops.append(record)
        return {"turn_id": turn_id, "source": "jsonl", **summary, "trace": hops}

    raise HTTPException(status_code=404, detail=f"No trace found for turn {turn_id}")


@router.get("/traces")
async def list_traces(
    session_id: str | None = None, limit: int = Query(default=25, ge=1, le=200)
) -> dict[str, Any]:
    settings = get_settings()
    try:
        with psycopg.connect(settings.pg_dsn, connect_timeout=3) as conn, conn.cursor() as cur:
            if session_id:
                cur.execute(
                    """
                    SELECT turn_id, session_id, MIN(ts) AS started,
                           COUNT(*) AS hops, MAX(cycle) AS cycles,
                           SUM(latency_ms) AS total_ms
                    FROM agent_traces WHERE session_id = %s
                    GROUP BY turn_id, session_id ORDER BY started DESC LIMIT %s
                    """,
                    (session_id, limit),
                )
            else:
                cur.execute(
                    """
                    SELECT turn_id, session_id, MIN(ts) AS started,
                           COUNT(*) AS hops, MAX(cycle) AS cycles,
                           SUM(latency_ms) AS total_ms
                    FROM agent_traces
                    GROUP BY turn_id, session_id ORDER BY started DESC LIMIT %s
                    """,
                    (limit,),
                )
            rows = cur.fetchall()
    except Exception as exc:
        log.warning("trace.list_failed", error=f"{type(exc).__name__}: {exc}")
        return {"traces": [], "error": "trace store unavailable"}

    return {
        "traces": [
            {
                "turn_id": r[0],
                "session_id": r[1],
                "started_at": r[2].isoformat() if r[2] else None,
                "hops": r[3],
                "replan_cycles": r[4],
                "total_latency_ms": round(float(r[5] or 0), 1),
            }
            for r in rows
        ]
    }


@router.get("/datasets")
async def list_datasets() -> dict[str, Any]:
    """The provenance ledger — every dataset, its source, coverage and quality."""
    settings = get_settings()
    manifest_path: Path = settings.bronze_dir / "_manifest.json"

    if not manifest_path.exists():
        raise HTTPException(
            status_code=404, detail="No ingestion manifest found. Run `make ingest`."
        )

    run = json.loads(manifest_path.read_text(encoding="utf-8"))
    datasets: list[dict[str, Any]] = []

    for entry in run.get("datasets", []):
        dataset_id = entry["dataset_id"]
        dq_files = sorted(settings.dq_report_dir.glob(f"{dataset_id}_*.json"))
        dq = json.loads(dq_files[-1].read_text(encoding="utf-8")) if dq_files else {}
        coverage = entry.get("coverage") or {}

        datasets.append(
            {
                "dataset_id": dataset_id,
                "dubai_pulse_slug": entry.get("dubai_pulse_slug"),
                "landing_page": entry.get("landing_page"),
                "domain": entry.get("domain"),
                "role": entry.get("role"),
                "files": entry.get("file_count", 0),
                "bytes": entry.get("total_bytes", 0),
                "data_period_range": entry.get("data_period_range"),
                "capture_dates": entry.get("capture_dates", [])[:2],
                "source_tier": "archive",
                "coverage_capped": coverage.get("capped"),
                "skipped_files": coverage.get("skipped_count", 0),
                "quality": {
                    "passed": dq.get("passed"),
                    "rows_in": dq.get("row_counts", {}).get("in"),
                    "rows_out": dq.get("row_counts", {}).get("out"),
                    "deduplicated": dq.get("row_counts", {}).get("deduplicated"),
                    "quarantined": dq.get("row_counts", {}).get("quarantined"),
                    "coercion_failures": sum(dq.get("coercion_failures", {}).values()),
                    "warnings": dq.get("warnings", [])[:3],
                },
            }
        )

    return {
        "acquisition_note": run.get("acquisition_note"),
        "ingest_date": run.get("ingest_date"),
        "datasets_recovered": run.get("datasets_recovered"),
        "datasets_attempted": run.get("datasets_attempted"),
        "total_files": run.get("total_files"),
        "total_bytes": run.get("total_bytes"),
        "datasets": datasets,
    }


@router.get("/stats")
async def warehouse_stats() -> dict[str, Any]:
    """Headline numbers for the analytics dashboard."""
    settings = get_settings()
    stats: dict[str, Any] = {}

    queries = {
        "stations_by_mode": "SELECT mode, COUNT(*) FROM dim_station GROUP BY mode ORDER BY 2 DESC",
        "routes_by_mode": "SELECT mode, COUNT(*) FROM dim_route GROUP BY mode ORDER BY 2 DESC",
        "ridership_by_year": (
            "SELECT year, mode, SUM(trips)::bigint FROM fact_ridership_monthly "
            "WHERE NOT scale_anomaly GROUP BY year, mode ORDER BY year, mode"
        ),
        "modal_split_latest": (
            "SELECT transport_type, trips::bigint FROM fact_modal_split_monthly "
            "WHERE date_key = (SELECT MAX(date_key) FROM fact_modal_split_monthly) "
            "ORDER BY trips DESC"
        ),
        "top_metro_stations": (
            "SELECT entity_name, SUM(trips)::bigint AS total FROM fact_ridership_monthly "
            "WHERE mode='Metro' AND NOT scale_anomaly GROUP BY entity_name "
            "ORDER BY total DESC LIMIT 10"
        ),
        "top_bus_routes": (
            "SELECT entity_name, SUM(trips)::bigint AS total FROM fact_ridership_monthly "
            "WHERE mode='Bus' AND NOT scale_anomaly GROUP BY entity_name "
            "ORDER BY total DESC LIMIT 10"
        ),
        "stations_by_zone": (
            "SELECT zone_id, COUNT(*) FROM dim_station WHERE zone_id IS NOT NULL "
            "GROUP BY zone_id ORDER BY zone_id"
        ),
    }

    try:
        with psycopg.connect(settings.pg_dsn, connect_timeout=5) as conn:
            for name, sql in queries.items():
                with conn.cursor() as cur:
                    cur.execute(sql)
                    stats[name] = [list(r) for r in cur.fetchall()]

            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(DISTINCT date_key) FROM fact_ridership_monthly WHERE scale_anomaly"
                )
                stats["non_comparable_periods"] = cur.fetchone()[0]
                cur.execute("SELECT COUNT(*) FROM doc_chunk")
                stats["indexed_chunks"] = cur.fetchone()[0]
    except Exception as exc:
        log.warning("stats.failed", error=f"{type(exc).__name__}: {exc}")
        raise HTTPException(status_code=503, detail="Warehouse unavailable") from exc

    stats["data_note"] = (
        "Periods flagged as non-comparable are excluded from every total above. "
        "Their source captures report a different unit or reporting period from the "
        "rest of their series."
    )
    return stats


@router.get("/map/stations")
async def map_stations(mode: str | None = None) -> dict[str, Any]:
    """Station geometry for the map panel."""
    settings = get_settings()
    try:
        with psycopg.connect(settings.pg_dsn, connect_timeout=5) as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT station_key, station_name_en, station_name_ar, mode,
                       line_name, zone_id, latitude, longitude
                FROM dim_station
                WHERE latitude IS NOT NULL AND longitude IS NOT NULL
                  AND (%s::text IS NULL OR mode = %s::text)
                ORDER BY mode, station_name_en
                """,
                (mode, mode),
            )
            rows = cur.fetchall()
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Warehouse unavailable") from exc

    return {
        "stations": [
            {
                "id": r[0],
                "name_en": r[1],
                "name_ar": r[2],
                "mode": r[3],
                "line": r[4],
                "zone": r[5],
                "lat": float(r[6]),
                "lon": float(r[7]),
            }
            for r in rows
        ]
    }
