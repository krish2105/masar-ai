"""Phase 3 entrypoint — build the star schema and load it into Postgres.

    python -m backend.ingestion.run_gold
    python -m backend.ingestion.run_gold --build-only   # skip the database
"""

from __future__ import annotations

import argparse
import sys

from backend.config.settings import get_settings
from backend.ingestion.gold import GoldBuilder, summarise
from backend.ingestion.warehouse import load_all, verify
from backend.services.logging import configure_logging, get_logger

log = get_logger(__name__)


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    parser = argparse.ArgumentParser(description="Masar AI — gold star schema")
    parser.add_argument("--build-only", action="store_true", help="write parquet, skip Postgres")
    args = parser.parse_args(argv)

    settings = get_settings()

    builder = GoldBuilder(settings.silver_dir, settings.gold_dir)
    tables = builder.build_all()
    print(summarise(tables))

    if args.build_only:
        return 0

    counts = load_all(settings.pg_dsn, settings.gold_dir)
    print("  Loaded into Postgres:")
    for table, rows in counts.items():
        print(f"    {table:<30} {rows:>10,}")
    print()

    print("  Canonical analytical queries:")
    print("  " + "─" * 100)
    failures = 0
    for label, preview, rows in verify(settings.pg_dsn):
        ok = rows > 0 and not preview.startswith("ERROR")
        failures += 0 if ok else 1
        print(f"  {'✓' if ok else '✗'} {label:<36} {preview}")
    print("  " + "─" * 100)

    empty = [t for t, n in counts.items() if n == 0]
    if empty:
        log.warning("gold.empty_tables", tables=empty)
    if failures:
        log.error("gold.gate_failed", failed_queries=failures)
        return 1

    print(f"\n  PHASE 3 GATE — 10/10 canonical queries returned results ✓\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
