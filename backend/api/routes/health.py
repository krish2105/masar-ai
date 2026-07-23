"""Health and readiness.

`/health` is deliberately shallow and always 200 while the process is alive —
it answers "is the API up?", which is what a container orchestrator asks.

`/health/ready` is deep: it probes Postgres and Redis and reports which LLM
providers are usable. A missing optional credential is reported as a *named
degradation*, never as an unhealthy status, because running without cloud keys
is a supported mode of operation, not a fault.
"""

from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter

from backend.config.settings import get_settings

router = APIRouter(tags=["health"])

_STARTED_AT = time.time()


@router.get("/health")
async def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "service": "masar-ai",
        "version": "0.1.0",
        "uptime_seconds": round(time.time() - _STARTED_AT, 1),
    }


async def _probe_postgres() -> dict[str, Any]:
    try:
        import psycopg

        settings = get_settings()
        started = time.perf_counter()
        with psycopg.connect(settings.pg_dsn, connect_timeout=3) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
                cur.execute("SELECT extname FROM pg_extension WHERE extname = 'vector'")
                has_vector = cur.fetchone() is not None
        return {
            "status": "ok",
            "latency_ms": round((time.perf_counter() - started) * 1000, 1),
            "pgvector": has_vector,
        }
    except Exception as exc:
        return {"status": "unavailable", "error": f"{type(exc).__name__}: {exc}"}


async def _probe_redis() -> dict[str, Any]:
    try:
        import redis.asyncio as aioredis

        settings = get_settings()
        started = time.perf_counter()
        client = aioredis.from_url(settings.redis_url, socket_connect_timeout=3)
        try:
            await client.ping()
        finally:
            await client.aclose()
        return {
            "status": "ok",
            "latency_ms": round((time.perf_counter() - started) * 1000, 1),
        }
    except Exception as exc:
        return {"status": "unavailable", "error": f"{type(exc).__name__}: {exc}"}


@router.get("/health/ready")
async def readiness() -> dict[str, Any]:
    settings = get_settings()
    postgres = await _probe_postgres()
    redis_status = await _probe_redis()
    capabilities = settings.capability_report()

    # Datastores are required; LLM credentials are not.
    ready = postgres["status"] == "ok" and redis_status["status"] == "ok"

    return {
        "ready": ready,
        "environment": settings.app_env,
        "dependencies": {"postgres": postgres, "redis": redis_status},
        "capabilities": capabilities,
    }
