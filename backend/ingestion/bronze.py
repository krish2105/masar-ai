"""Bronze layer — raw, immutable, exactly as acquired.

Nothing is parsed, coerced or cleaned here. Bytes land on disk unchanged and a
manifest records where each file came from and when it was captured. That
manifest is the root of the provenance chain that ends at the `[S1]` citation in
the UI, so it is written even when a dataset fails to acquire — a recorded
failure is evidence; a silent gap is not.

Layout (§3.5):

    data/bronze/
      _index/cdx.tsv                     cached Internet Archive index
      {dataset_id}/{ingest_date}/*.csv   raw files
      {dataset_id}/{ingest_date}/_manifest.json
      _manifest.json                     run-level summary
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from backend.ingestion.datasets import Dataset
from backend.ingestion.source import AcquiredFile, Source
from backend.services.logging import get_logger

log = get_logger(__name__)


class BronzeWriter:
    def __init__(self, root: Path, *, ingest_date: str | None = None) -> None:
        self.root = root
        self.ingest_date = ingest_date or datetime.now(tz=UTC).strftime("%Y-%m-%d")

    def dataset_dir(self, dataset: Dataset) -> Path:
        return self.root / dataset.id / self.ingest_date

    def write(
        self,
        dataset: Dataset,
        files: list[AcquiredFile],
        *,
        skipped: list[dict[str, object]] | None = None,
        cap: dict[str, object] | None = None,
    ) -> dict[str, object]:
        target = self.dataset_dir(dataset)
        target.mkdir(parents=True, exist_ok=True)

        for acquired in files:
            (target / acquired.filename).write_bytes(acquired.payload)

        periods = sorted({f.data_period for f in files if f.data_period})
        captures = sorted({f.captured_at.date().isoformat() for f in files})
        # Column sets can drift between snapshots; record the union and flag drift.
        column_sets = {tuple(f.columns) for f in files if f.columns}

        manifest: dict[str, object] = {
            "dataset_id": dataset.id,
            "dubai_pulse_slug": dataset.dubai_pulse_slug,
            "landing_page": dataset.landing_page,
            "domain": str(dataset.domain),
            "role": dataset.role,
            "core": dataset.core,
            "ingest_date": self.ingest_date,
            "ingested_at": datetime.now(tz=UTC).isoformat(),
            "file_count": len(files),
            "total_bytes": sum(f.size_bytes for f in files),
            "source_tiers": sorted({str(f.source_tier) for f in files}),
            "data_periods": periods,
            "data_period_range": [periods[0], periods[-1]] if periods else None,
            "capture_dates": captures,
            "schema_variants": len(column_sets),
            "columns_union": sorted({c for cols in column_sets for c in cols}),
            # Coverage is stated explicitly. A cap that is not reported reads as
            # full coverage when it is not.
            "coverage": {
                "capped": cap,
                "skipped_files": skipped or [],
                "skipped_count": len(skipped or []),
            },
            "files": [f.manifest_entry() for f in files],
            "status": "ok" if files else "empty",
        }

        (target / "_manifest.json").write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
        )

        log.info(
            "bronze.written",
            dataset=dataset.id,
            files=len(files),
            bytes=manifest["total_bytes"],
            periods=len(periods),
            schema_variants=len(column_sets),
        )
        return manifest

    def write_run_manifest(self, results: list[dict[str, object]]) -> Path:
        recovered = [r for r in results if r["status"] == "ok"]
        summary = {
            "ingest_date": self.ingest_date,
            "generated_at": datetime.now(tz=UTC).isoformat(),
            "acquisition_note": (
                "Dubai Pulse was retired and redirects to data.dubai, whose catalogue "
                "is authentication-gated. Source data is recovered from public Internet "
                "Archive snapshots of the original CKAN resource downloads. Archived "
                "data is never presented as live."
            ),
            "datasets_attempted": len(results),
            "datasets_recovered": len(recovered),
            "datasets_empty": [r["dataset_id"] for r in results if r["status"] != "ok"],
            "total_files": sum(int(r["file_count"]) for r in results),
            "total_bytes": sum(int(r["total_bytes"]) for r in results),
            "datasets": results,
        }
        path = self.root / "_manifest.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
        return path


async def ingest_dataset(
    dataset: Dataset,
    sources: list[Source],
    writer: BronzeWriter,
) -> dict[str, object]:
    """Try each source in order; the first that yields files wins.

    A dataset that yields nothing is recorded with `status: "empty"` rather than
    raising, so one unavailable dataset never aborts the run.
    """
    for source in sources:
        try:
            files = await source.acquire(dataset)
        except Exception as exc:
            log.error(
                "ingest.source_failed",
                dataset=dataset.id,
                source=type(source).__name__,
                error=f"{type(exc).__name__}: {exc}",
            )
            continue
        if files:
            return writer.write(
                dataset,
                files,
                skipped=getattr(source, "last_skipped", None),
                cap=getattr(source, "last_cap", None),
            )

    log.warning("ingest.empty", dataset=dataset.id)
    return writer.write(dataset, [])


def collect_manifests(root: Path) -> list[dict[str, object]]:
    """Rebuild the run-level view from the per-dataset manifests on disk.

    A partial run (`--only`) writes a run manifest covering only its targets.
    Rather than re-downloading everything to regenerate the full picture, the
    per-dataset manifests — which are always authoritative — are re-read.
    """
    results: list[dict[str, object]] = []
    for dataset_dir in sorted(
        p for p in root.iterdir() if p.is_dir() and not p.name.startswith("_")
    ):
        partitions = sorted((p for p in dataset_dir.iterdir() if p.is_dir()), reverse=True)
        for partition in partitions:
            manifest = partition / "_manifest.json"
            if manifest.exists():
                results.append(json.loads(manifest.read_text(encoding="utf-8")))
                break
    return results


def summarise(results: list[dict[str, object]]) -> str:
    """Human-readable gate report for Phase 1."""
    lines = [
        "",
        "  PHASE 1 GATE — bronze acquisition",
        "  " + "─" * 84,
        f"  {'dataset':<34} {'files':>6} {'bytes':>11}  {'period range':<25} status",
        "  " + "─" * 84,
    ]
    capped: list[str] = []
    for result in sorted(results, key=lambda r: str(r["dataset_id"])):
        period_range = result.get("data_period_range")
        period_text = f"{period_range[0]} → {period_range[1]}" if period_range else "static"
        mark = "✓" if result["status"] == "ok" else "✗"
        coverage = result.get("coverage") or {}
        if coverage.get("capped"):
            cap = coverage["capped"]
            mark += f" (capped {cap['retained']}/{cap['available']})"
            capped.append(str(result["dataset_id"]))
        lines.append(
            f"  {result['dataset_id']:<34} {result['file_count']:>6} "
            f"{result['total_bytes']:>11,}  {period_text:<25} {mark}"
        )
    ok = sum(1 for r in results if r["status"] == "ok")
    total_bytes = sum(int(r["total_bytes"]) for r in results)
    total_files = sum(int(r["file_count"]) for r in results)
    lines += [
        "  " + "─" * 84,
        f"  {ok}/{len(results)} datasets recovered · {total_files} files · {total_bytes:,} bytes",
    ]
    if capped:
        lines.append(
            f"  coverage capped on: {', '.join(capped)} — rationale in each _manifest.json"
        )
    lines.append("")
    return "\n".join(lines)
