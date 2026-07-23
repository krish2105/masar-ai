"""Internet Archive recovery client for the retired Dubai Pulse platform.

Why this module exists
----------------------
`dubaipulse.gov.ae` was retired and now 301-redirects to `data.dubai`, whose
dataset catalogue sits behind an authentication gate. The legacy API gateway at
`api.dubaipulse.gov.ae` still answers but returns 401 without credentials that
take up to 14 days to be granted. The bulk-CSV path the build spec relied on no
longer resolves.

The data itself survives. Dubai Pulse published CKAN-style resource downloads at

    /dataset/{dataset_uuid}/resource/{resource_uuid}/download/{stem}_{period}.csv

and the Internet Archive holds ~1,270 such captures, several current to
January 2026. This module recovers them.

How it works
------------
1. One CDX query returns every archived URL under the host. That index is cached
   locally, so a full re-ingest costs a single network round trip.
2. For a dataset, all resource URLs sharing its `archive_stem` are selected and
   grouped by filename. Each distinct filename is one data snapshot; the date in
   the filename is the *data* period, not the capture date.
3. For each filename we take the most recent capture and fetch it with the `id_`
   modifier, which returns the original bytes without the Archive's HTML wrapper.

Every download records `source_url`, `archive_url` and `captured_at` so the
provenance chain is intact from raw bytes through to the citation shown in the
UI. Archived data is never presented as live.
"""

from __future__ import annotations

import asyncio
import csv
import io
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import httpx

from backend.services.logging import get_logger

log = get_logger(__name__)

CDX_ENDPOINT = "http://web.archive.org/cdx/search/cdx"
WAYBACK_RAW = "https://web.archive.org/web/{timestamp}id_/{url}"
HOST_PATTERN = "dubaipulse.gov.ae*"

USER_AGENT = (
    "MasarAI/0.1 (academic research project; open-data recovery; "
    "+https://github.com/krish2105)"
)

# ``bus_passengers_trips_by_route_monthly_2025-09-20_00-00-00.csv`` → period 2025-09-20
_PERIOD_RE = re.compile(r"_(\d{4}-\d{2}-\d{2})_\d{2}-\d{2}-\d{2}\.csv$", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class ArchivedResource:
    """One recoverable file: the newest capture of one Dubai Pulse resource."""

    original_url: str
    timestamp: str          # CDX capture stamp, YYYYMMDDhhmmss
    filename: str
    mimetype: str
    dataset_uuid: str
    resource_uuid: str

    @property
    def archive_url(self) -> str:
        return WAYBACK_RAW.format(timestamp=self.timestamp, url=self.original_url)

    @property
    def captured_at(self) -> datetime:
        return datetime.strptime(self.timestamp, "%Y%m%d%H%M%S").replace(tzinfo=UTC)

    @property
    def data_period(self) -> str | None:
        """The period the data covers, parsed from the filename. None for static tables."""
        match = _PERIOD_RE.search(self.filename)
        return match.group(1) if match else None

    @property
    def stem(self) -> str:
        """Filename with the period suffix removed — the snapshot family key."""
        return _PERIOD_RE.sub("", self.filename).removesuffix(".csv")


class WaybackClient:
    """Reads the CDX index and fetches archived resources.

    Concurrency is capped and failures are retried with backoff. The Internet
    Archive is a free public service run on donations; hammering it would be
    both rude and counterproductive.
    """

    def __init__(
        self,
        cache_path: Path,
        *,
        concurrency: int = 3,
        timeout: float = 300.0,
        max_retries: int = 4,
        max_bytes_per_file: int = 250 * 1024 * 1024,
    ) -> None:
        self.cache_path = cache_path
        self.concurrency = concurrency
        self.timeout = timeout
        self.max_retries = max_retries
        self.max_bytes_per_file = max_bytes_per_file
        self._http: httpx.AsyncClient | None = None

    # ------------------------------------------------------------ transport --
    def _client(self) -> httpx.AsyncClient:
        """One pooled client for the whole run.

        Creating a client per request opens a fresh TLS connection every time.
        Across a few hundred files that exhausts local sockets and the Archive's
        per-client connection budget, which surfaces as
        `ConnectError: All connection attempts failed` rather than an HTTP
        status — so it is invisible to status-code-based retry logic. Pooling
        and keep-alive fix it at the source.
        """
        if self._http is None or self._http.is_closed:
            self._http = httpx.AsyncClient(
                timeout=httpx.Timeout(self.timeout, connect=30.0),
                headers={"User-Agent": USER_AGENT},
                follow_redirects=True,
                limits=httpx.Limits(
                    max_connections=self.concurrency + 2,
                    max_keepalive_connections=self.concurrency,
                    keepalive_expiry=30.0,
                ),
            )
        return self._http

    async def aclose(self) -> None:
        if self._http is not None and not self._http.is_closed:
            await self._http.aclose()
        self._http = None

    async def __aenter__(self) -> WaybackClient:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.aclose()

    # ---------------------------------------------------------------- index --
    async def fetch_index(self, *, refresh: bool = False) -> list[tuple[str, str, str]]:
        """Return `(original_url, timestamp, mimetype)` for every archived URL.

        Cached on disk. One request covers the entire host catalogue.
        """
        if self.cache_path.exists() and not refresh:
            log.info("wayback.index.cached", path=str(self.cache_path))
            return self._read_cache()

        log.info("wayback.index.fetch", host=HOST_PATTERN)
        params = {
            "url": HOST_PATTERN,
            "output": "text",
            "fl": "original,timestamp,mimetype",
            "collapse": "urlkey",
            "filter": "statuscode:200",
            "limit": "20000",
        }

        async with httpx.AsyncClient(
            timeout=httpx.Timeout(180.0), headers={"User-Agent": USER_AGENT}
        ) as client:
            response = await client.get(CDX_ENDPOINT, params=params)
            response.raise_for_status()
            body = response.text

        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache_path.write_text(body, encoding="utf-8")
        log.info("wayback.index.cached", rows=body.count("\n"), path=str(self.cache_path))
        return self._read_cache()

    def _read_cache(self) -> list[tuple[str, str, str]]:
        rows: list[tuple[str, str, str]] = []
        for line in self.cache_path.read_text(encoding="utf-8").splitlines():
            parts = line.split()
            if len(parts) >= 3:
                rows.append((parts[0], parts[1], parts[2]))
        return rows

    # ------------------------------------------------------------ selection --
    @staticmethod
    def select_resources(
        index: list[tuple[str, str, str]], archive_stem: str
    ) -> list[ArchivedResource]:
        """All resource files for one dataset, newest capture per distinct filename.

        Matching is anchored on ``/download/{stem}`` and requires the next
        character to be ``_`` or ``.``, so ``bus_routes`` cannot swallow
        ``bus_routes_gis`` and ``metro_lines`` cannot match
        ``metro_lines_network_length``.
        """
        anchor = f"/download/{archive_stem.lower()}"
        newest: dict[str, ArchivedResource] = {}

        for original, timestamp, mimetype in index:
            lowered = original.lower()
            position = lowered.find(anchor)
            if position == -1:
                continue
            following = lowered[position + len(anchor) : position + len(anchor) + 1]
            if following not in ("_", "."):
                continue

            filename = original.rsplit("/download/", 1)[-1]
            if not filename.lower().endswith(".csv"):
                continue

            try:
                _, remainder = original.split("/dataset/", 1)
                dataset_uuid, remainder = remainder.split("/resource/", 1)
                resource_uuid = remainder.split("/", 1)[0]
            except ValueError:
                continue

            candidate = ArchivedResource(
                original_url=original,
                timestamp=timestamp,
                filename=filename,
                mimetype=mimetype,
                dataset_uuid=dataset_uuid,
                resource_uuid=resource_uuid,
            )
            existing = newest.get(filename)
            if existing is None or candidate.timestamp > existing.timestamp:
                newest[filename] = candidate

        return sorted(newest.values(), key=lambda r: (r.data_period or "", r.filename))

    # ------------------------------------------------------------- download --
    async def download(self, resource: ArchivedResource) -> bytes | None:
        """Fetch one archived file. Returns None when it is unrecoverable."""
        client = self._client()
        delay = 3.0

        for attempt in range(1, self.max_retries + 1):
            try:
                response = await client.get(resource.archive_url)
                if response.status_code == 200 and response.content:
                    return response.content
                # 404 means this capture genuinely is not held; retrying wastes
                # a request. 429 and 5xx are transient.
                if response.status_code == 404:
                    log.warning(
                        "wayback.download.missing", file=resource.filename, status=404
                    )
                    return None
                log.warning(
                    "wayback.download.retry",
                    file=resource.filename,
                    status=response.status_code,
                    attempt=attempt,
                )
            except (httpx.HTTPError, httpx.TimeoutException) as exc:
                log.warning(
                    "wayback.download.error",
                    file=resource.filename,
                    error=f"{type(exc).__name__}: {exc}",
                    attempt=attempt,
                )
            if attempt < self.max_retries:
                await asyncio.sleep(delay)
                delay *= 2

        log.error("wayback.download.failed", file=resource.filename)
        return None

    async def content_length(self, resource: ArchivedResource) -> int | None:
        """Size of an archived file without transferring it.

        Used to skip files above `max_bytes_per_file` before spending the
        bandwidth. Returns None when the Archive does not advertise a length.
        """
        try:
            response = await self._client().head(resource.archive_url)
            raw = response.headers.get("content-length")
            return int(raw) if raw and raw.isdigit() else None
        except (httpx.HTTPError, ValueError):
            # An unknown size is not a reason to skip; the download itself will
            # surface any real problem.
            return None

    async def download_many(
        self, resources: list[ArchivedResource]
    ) -> tuple[dict[str, bytes], list[dict[str, object]]]:
        """Download concurrently, capped by `self.concurrency`.

        Returns the payloads and a list of skip records. Skips are returned
        rather than logged-and-forgotten so the bronze manifest can name every
        file that did not land and why.
        """
        semaphore = asyncio.Semaphore(self.concurrency)
        results: dict[str, bytes] = {}
        skipped: list[dict[str, object]] = []

        async def worker(resource: ArchivedResource) -> None:
            async with semaphore:
                size = await self.content_length(resource)
                if size is not None and size > self.max_bytes_per_file:
                    log.warning(
                        "wayback.download.oversize",
                        file=resource.filename,
                        bytes=size,
                        limit=self.max_bytes_per_file,
                    )
                    skipped.append(
                        {
                            "filename": resource.filename,
                            "reason": "exceeds_max_bytes_per_file",
                            "bytes": size,
                            "limit": self.max_bytes_per_file,
                        }
                    )
                    return

                payload = await self.download(resource)
                if payload is None:
                    skipped.append(
                        {"filename": resource.filename, "reason": "download_failed"}
                    )
                elif _looks_like_csv(payload):
                    results[resource.filename] = payload
                else:
                    log.warning("wayback.download.not_csv", file=resource.filename)
                    skipped.append(
                        {"filename": resource.filename, "reason": "not_csv"}
                    )

        await asyncio.gather(*(worker(r) for r in resources))
        return results, skipped


def _looks_like_csv(payload: bytes) -> bool:
    """Reject Archive error pages that return 200 with HTML.

    The Archive occasionally serves a "page not archived" document with a 200
    status. Sniffing the first bytes for markup is cheaper and more reliable
    than trusting the status code alone.
    """
    head = payload[:400].lstrip().lower()
    if head.startswith((b"<!doctype", b"<html", b"<?xml")):
        return False
    try:
        text = payload[:8192].decode("utf-8-sig", errors="strict")
    except UnicodeDecodeError:
        try:
            text = payload[:8192].decode("windows-1256")
        except UnicodeDecodeError:
            return False
    first_line = text.splitlines()[0] if text.splitlines() else ""
    if not first_line:
        return False
    dialect_hits = sum(first_line.count(sep) for sep in (",", ";", "\t"))
    return dialect_hits >= 1


def decode_csv(payload: bytes) -> str:
    """Decode with a BOM-aware UTF-8 first pass, falling back to Arabic legacy encodings."""
    for encoding in ("utf-8-sig", "utf-8", "windows-1256", "cp1252"):
        try:
            return payload.decode(encoding)
        except UnicodeDecodeError:
            continue
    return payload.decode("utf-8", errors="replace")


def sniff_header(payload: bytes) -> list[str]:
    """Column names from the first row, for the bronze manifest."""
    text = decode_csv(payload)
    reader = csv.reader(io.StringIO(text))
    try:
        return [column.strip() for column in next(reader)]
    except StopIteration:
        return []
