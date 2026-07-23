"""Phase 2 entrypoint — bronze → silver, with a data quality report per dataset.

    python -m backend.ingestion.run_silver
    python -m backend.ingestion.run_silver --only metro_stations
"""

from __future__ import annotations

import argparse
import sys

from backend.config.settings import get_settings
from backend.ingestion.datasets import DATASETS, get
from backend.ingestion.quality import summarise_reports
from backend.ingestion.silver import transform_dataset
from backend.services.logging import configure_logging, get_logger

log = get_logger(__name__)


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    parser = argparse.ArgumentParser(description="Masar AI — silver transformation")
    parser.add_argument("--only", nargs="+", metavar="ID")
    parser.add_argument(
        "--allow-failures",
        action="store_true",
        help="report quality failures without failing the phase gate",
    )
    args = parser.parse_args(argv)

    settings = get_settings()
    targets = [get(i) for i in args.only] if args.only else list(DATASETS)

    reports = []
    for dataset in targets:
        report = transform_dataset(dataset, settings.bronze_dir, settings.silver_dir)
        if report is None:
            continue
        report.write(settings.dq_report_dir)
        reports.append(report)

    print(summarise_reports(reports))
    print(f"  DQ reports → {settings.dq_report_dir}\n")

    failures = [r.dataset_id for r in reports if not r.passed]
    if failures and not args.allow_failures:
        log.error("silver.gate_failed", datasets=failures)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
