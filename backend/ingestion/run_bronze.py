"""Phase 1 entrypoint — recover the dataset catalogue into data/bronze/.

python -m backend.ingestion.run_bronze                # all datasets
python -m backend.ingestion.run_bronze --core         # only the §3.3 twelve
python -m backend.ingestion.run_bronze --only metro_stations bus_routes
python -m backend.ingestion.run_bronze --refresh-index
python -m backend.ingestion.run_bronze --max-files 24 # cap snapshot families
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from backend.config.settings import get_settings
from backend.ingestion.bronze import (
    BronzeWriter,
    collect_manifests,
    ingest_dataset,
    summarise,
)
from backend.ingestion.datasets import CORE_DATASETS, DATASETS, get
from backend.ingestion.source import ApiSource, ArchiveSource, LocalCsvSource
from backend.ingestion.wayback import WaybackClient
from backend.services.logging import configure_logging, get_logger

log = get_logger(__name__)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Masar AI — bronze acquisition")
    parser.add_argument("--core", action="store_true", help="only the twelve core datasets")
    parser.add_argument("--only", nargs="+", metavar="ID", help="specific dataset ids")
    parser.add_argument("--refresh-index", action="store_true", help="re-fetch the CDX index")
    parser.add_argument(
        "--max-files",
        type=int,
        default=None,
        help="cap files per snapshot family (newest periods kept)",
    )
    parser.add_argument("--concurrency", type=int, default=3)
    parser.add_argument(
        "--rebuild-manifest",
        action="store_true",
        help="regenerate the run manifest from on-disk per-dataset manifests, no downloads",
    )
    return parser.parse_args(argv)


async def main(argv: list[str] | None = None) -> int:
    configure_logging()
    args = parse_args(argv)
    settings = get_settings()

    if args.rebuild_manifest:
        writer = BronzeWriter(settings.bronze_dir)
        results = collect_manifests(settings.bronze_dir)
        path = writer.write_run_manifest(results)
        print(summarise(results))
        print(f"  run manifest → {path}\n")
        return 0

    if args.only:
        targets = [get(dataset_id) for dataset_id in args.only]
    elif args.core:
        targets = list(CORE_DATASETS)
    else:
        targets = list(DATASETS)

    client = WaybackClient(
        cache_path=settings.bronze_dir / "_index" / "cdx.tsv",
        concurrency=args.concurrency,
    )
    if args.refresh_index:
        await client.fetch_index(refresh=True)

    writer = BronzeWriter(settings.bronze_dir)

    # Order matters: archive first (works with no credentials), then any files a
    # human dropped in, then the live gateway if it is ever granted.
    sources = [
        ArchiveSource(client, max_files_per_dataset=args.max_files),
        LocalCsvSource(settings.repo_root / "data" / "_manual"),
        ApiSource(settings.dubai_pulse_api_key, settings.dubai_pulse_api_secret),
    ]

    log.info("bronze.run.start", datasets=len(targets), ingest_date=writer.ingest_date)

    results = []
    try:
        for dataset in targets:
            results.append(await ingest_dataset(dataset, sources, writer))
    finally:
        # Release the pooled connections even if a dataset raises.
        await client.aclose()

    manifest_path = writer.write_run_manifest(results)
    print(summarise(results))
    print(f"  run manifest → {manifest_path}\n")

    recovered = sum(1 for r in results if r["status"] == "ok")
    # The gate requires every core dataset to land. Supporting datasets may be absent.
    core_ids = {d.id for d in CORE_DATASETS}
    core_failures = [
        r["dataset_id"] for r in results if r["status"] != "ok" and r["dataset_id"] in core_ids
    ]
    if core_failures:
        log.error("bronze.run.core_missing", datasets=core_failures)
        return 1

    log.info("bronze.run.done", recovered=recovered, attempted=len(results))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
