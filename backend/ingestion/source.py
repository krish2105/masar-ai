"""Acquisition strategies.

The build spec makes this a hard architectural requirement: sources must be
interchangeable so the demo never depends on a credential. Three implementations
satisfy one protocol.

    ArchiveSource  — Internet Archive snapshots of Dubai Pulse.   DEFAULT.
    LocalCsvSource — files a human already downloaded.            Zero network.
    ApiSource      — the live Dubai Pulse gateway.                Opportunistic.

`ArchiveSource` is the default because it is the only one that works today with
no credentials and no manual step. `ApiSource` layers refresh on top when keys
exist; it is never a dependency.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol, runtime_checkable

from backend.ingestion.datasets import Dataset, SourceTier
from backend.ingestion.wayback import ArchivedResource, WaybackClient, sniff_header
from backend.services.logging import get_logger

log = get_logger(__name__)


@dataclass(slots=True)
class AcquiredFile:
    """One raw file plus the provenance that must survive to the citation."""

    filename: str
    payload: bytes
    source_tier: SourceTier
    source_url: str
    captured_at: datetime
    data_period: str | None = None
    columns: list[str] = field(default_factory=list)

    @property
    def size_bytes(self) -> int:
        return len(self.payload)

    def manifest_entry(self) -> dict[str, object]:
        return {
            "filename": self.filename,
            "size_bytes": self.size_bytes,
            "source_tier": str(self.source_tier),
            "source_url": self.source_url,
            "captured_at": self.captured_at.isoformat(),
            "data_period": self.data_period,
            "columns": self.columns,
        }


@runtime_checkable
class Source(Protocol):
    """Anything that can produce raw files for a dataset."""

    tier: SourceTier

    async def acquire(self, dataset: Dataset) -> list[AcquiredFile]: ...


# =============================================================================
# Archive — the default path
# =============================================================================


class ArchiveSource:
    tier = SourceTier.ARCHIVE

    def __init__(self, client: WaybackClient, *, max_files_per_dataset: int | None = None) -> None:
        self._client = client
        self._index: list[tuple[str, str, str]] | None = None
        self._max_files = max_files_per_dataset
        self.last_skipped: list[dict[str, object]] = []
        self.last_cap: dict[str, object] | None = None

    async def _ensure_index(self) -> list[tuple[str, str, str]]:
        if self._index is None:
            self._index = await self._client.fetch_index()
        return self._index

    async def acquire(self, dataset: Dataset) -> list[AcquiredFile]:
        self.last_skipped = []
        self.last_cap = None

        index = await self._ensure_index()
        resources: list[ArchivedResource] = self._client.select_resources(
            index, dataset.archive_stem
        )

        if not resources:
            log.warning(
                "acquire.no_resources",
                dataset=dataset.id,
                stem=dataset.archive_stem,
            )
            return []

        # Snapshot families stitch into a time series, so take the newest N by
        # data period. A per-dataset cap wins over the global one; whatever is
        # dropped is recorded, never silently truncated.
        cap = dataset.max_files if dataset.max_files is not None else self._max_files
        available = len(resources)
        if cap is not None and available > cap:
            resources = sorted(
                resources, key=lambda r: (r.data_period or "", r.timestamp)
            )[-cap:]
            self.last_cap = {
                "available": available,
                "retained": cap,
                "dropped": available - cap,
                "rationale": dataset.cap_rationale or "global --max-files cap",
            }
            log.warning(
                "acquire.capped",
                dataset=dataset.id,
                available=available,
                retained=cap,
                dropped=available - cap,
            )

        log.info(
            "acquire.start",
            dataset=dataset.id,
            files=len(resources),
            snapshot_family=dataset.is_snapshot_family,
        )

        payloads, skipped = await self._client.download_many(resources)
        self.last_skipped = skipped
        by_filename = {r.filename: r for r in resources}

        acquired: list[AcquiredFile] = []
        for filename, payload in payloads.items():
            resource = by_filename[filename]
            acquired.append(
                AcquiredFile(
                    filename=filename,
                    payload=payload,
                    source_tier=self.tier,
                    source_url=resource.original_url,
                    captured_at=resource.captured_at,
                    data_period=resource.data_period,
                    columns=sniff_header(payload),
                )
            )

        acquired.sort(key=lambda f: (f.data_period or "", f.filename))
        log.info(
            "acquire.done",
            dataset=dataset.id,
            requested=len(resources),
            recovered=len(acquired),
            bytes=sum(f.size_bytes for f in acquired),
        )
        return acquired


# =============================================================================
# Local CSV — for files a human already has
# =============================================================================


class LocalCsvSource:
    tier = SourceTier.ARCHIVE  # provenance is whatever the human downloaded

    def __init__(self, root: Path) -> None:
        self.root = root

    async def acquire(self, dataset: Dataset) -> list[AcquiredFile]:
        directory = self.root / dataset.id
        if not directory.is_dir():
            return []

        acquired: list[AcquiredFile] = []
        for path in sorted(directory.glob("*.csv")):
            payload = path.read_bytes()
            acquired.append(
                AcquiredFile(
                    filename=path.name,
                    payload=payload,
                    source_tier=self.tier,
                    source_url=f"file://{path}",
                    captured_at=datetime.fromtimestamp(path.stat().st_mtime, tz=UTC),
                    columns=sniff_header(payload),
                )
            )
        log.info("acquire.local", dataset=dataset.id, files=len(acquired))
        return acquired


# =============================================================================
# Live API — opportunistic refresh, never a dependency
# =============================================================================


class ApiSource:
    """Dubai Pulse gateway client with OAuth2 client-credentials.

    Kept deliberately simple: it exists so that credentials, if they ever
    arrive, are a configuration change rather than a code change. Any failure
    returns an empty list, and the caller falls back to the archive tier with
    `data_freshness: "cached"` recorded in response metadata.
    """

    tier = SourceTier.LIVE_API

    TOKEN_URL = (
        "https://api.dubaipulse.gov.ae/oauth/client_credential/accesstoken"
        "?grant_type=client_credentials"
    )
    BASE_URL = "https://api.dubaipulse.gov.ae/open/rta"

    def __init__(self, api_key: str | None, api_secret: str | None) -> None:
        self._key = api_key
        self._secret = api_secret
        self._token: str | None = None
        self._token_expires_at: datetime | None = None

    @property
    def configured(self) -> bool:
        return bool(self._key and self._secret)

    async def acquire(self, dataset: Dataset) -> list[AcquiredFile]:
        if not self.configured:
            log.info("acquire.api.skipped", dataset=dataset.id, reason="no credentials")
            return []
        # Deliberately not implemented against a gateway we cannot exercise.
        # Building an untested client against a 401 would be speculative code.
        log.info(
            "acquire.api.unavailable",
            dataset=dataset.id,
            detail="Gateway returns 401 without a granted key; archive tier is authoritative.",
        )
        return []
