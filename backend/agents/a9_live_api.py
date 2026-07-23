"""A9 — Live API. Deterministic.

Wraps the Dubai Pulse gateway. In practice it almost always reports that live
data is unavailable and defers to the archive tier, because the platform was
retired and the surviving gateway returns 401 without a credential grant that
takes up to 14 days.

That is not a stub. Reporting freshness accurately *is* the job here: this agent
is what lets the system distinguish "live" from "cached" from "archived" in
response metadata, so the UI never implies currency the data does not have.
If credentials ever arrive, the same interface starts returning live rows and
nothing downstream changes.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Literal

import httpx

from backend.services.logging import get_logger

log = get_logger(__name__)

TOKEN_URL = (
    "https://api.dubaipulse.gov.ae/oauth/client_credential/accesstoken"
    "?grant_type=client_credentials"
)
BASE_URL = "https://api.dubaipulse.gov.ae/open/rta"

Freshness = Literal["live", "cached", "archived"]


@dataclass(slots=True)
class ApiResult:
    success: bool
    freshness: Freshness = "archived"
    rows: list[dict[str, Any]] = field(default_factory=list)
    dataset: str = ""
    error: str = ""
    gap: str = ""
    latency_ms: float = 0.0
    note: str = ""


class LiveApiAgent:
    """OAuth2 client-credentials client with automatic refresh at 80% of TTL."""

    def __init__(self, api_key: str | None, api_secret: str | None) -> None:
        self._key = api_key
        self._secret = api_secret
        self._token: str | None = None
        self._expires_at: float = 0.0

    @property
    def configured(self) -> bool:
        return bool(self._key and self._secret)

    async def _access_token(self) -> str | None:
        """Fetch or reuse a bearer token. Refreshes at 80% of its lifetime."""
        if not self.configured:
            return None
        if self._token and time.time() < self._expires_at:
            return self._token

        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                response = await client.post(
                    TOKEN_URL,
                    data={"client_id": self._key, "client_secret": self._secret},
                )
                response.raise_for_status()
                payload = response.json()
        except Exception as exc:
            log.warning("api.token_failed", error=f"{type(exc).__name__}: {exc}")
            return None

        token = payload.get("access_token")
        if not token:
            return None

        # Expiry is reported in seconds, sometimes as a string.
        try:
            ttl = float(payload.get("expires_in", 1800))
        except (TypeError, ValueError):
            ttl = 1800.0
        self._token = token
        self._expires_at = time.time() + ttl * 0.8
        log.info("api.token_acquired", ttl_seconds=int(ttl))
        return token

    async def fetch(
        self,
        dataset_slug: str,
        *,
        filters: str | None = None,
        columns: list[str] | None = None,
        order_by: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> ApiResult:
        started = time.perf_counter()

        if not self.configured:
            return ApiResult(
                success=False,
                freshness="archived",
                dataset=dataset_slug,
                gap=(
                    "No Dubai Pulse credentials are configured, so no live data was "
                    "fetched. The answer uses archived snapshots instead."
                ),
                note="expected default — the system is designed to run without these",
                latency_ms=(time.perf_counter() - started) * 1000,
            )

        token = await self._access_token()
        if not token:
            return ApiResult(
                success=False,
                freshness="archived",
                dataset=dataset_slug,
                error="could not obtain an access token",
                gap="Live data was unavailable; archived snapshots were used instead.",
                latency_ms=(time.perf_counter() - started) * 1000,
            )

        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if filters:
            params["filter"] = filters
        if columns:
            params["column"] = ",".join(columns)
        if order_by:
            params["order_by"] = order_by

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(
                    f"{BASE_URL}/{dataset_slug}",
                    params=params,
                    headers={"Authorization": f"Bearer {token}"},
                )
                if response.status_code == 401:
                    # Token rejected — drop it so the next call re-authenticates.
                    self._token = None
                    return ApiResult(
                        success=False,
                        freshness="archived",
                        dataset=dataset_slug,
                        error="gateway returned 401",
                        gap="The Dubai Pulse gateway rejected the credentials; archived data was used.",
                        latency_ms=(time.perf_counter() - started) * 1000,
                    )
                response.raise_for_status()
                payload = response.json()
        except Exception as exc:
            log.warning("api.fetch_failed", dataset=dataset_slug, error=str(exc)[:200])
            return ApiResult(
                success=False,
                freshness="archived",
                dataset=dataset_slug,
                error=f"{type(exc).__name__}: {exc}"[:200],
                gap="The live API call failed; archived data was used instead.",
                latency_ms=(time.perf_counter() - started) * 1000,
            )

        rows = (
            payload if isinstance(payload, list) else payload.get("data", payload.get("result", []))
        )
        rows = rows if isinstance(rows, list) else []

        log.info("api.fetched", dataset=dataset_slug, rows=len(rows))
        return ApiResult(
            success=True,
            freshness="live",
            rows=rows,
            dataset=dataset_slug,
            latency_ms=(time.perf_counter() - started) * 1000,
        )
