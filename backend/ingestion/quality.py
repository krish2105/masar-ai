"""Data quality reporting.

The DQ report is a graded deliverable, not scaffolding. It is the governance
evidence that distinguishes a portfolio project from a demo: it states, per
dataset, exactly what was ingested, what was coerced, what was dropped and why.

One JSON file per dataset per run, written to `reports/dq/`. A run that drops
rows silently is a failed run — everything discarded is counted, categorised and
sampled here.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import polars as pl


@dataclass(slots=True)
class ColumnProfile:
    name: str
    dtype: str
    null_count: int
    null_rate: float
    distinct_count: int
    sample_values: list[str] = field(default_factory=list)
    min_value: str | None = None
    max_value: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "dtype": self.dtype,
            "null_count": self.null_count,
            "null_rate": round(self.null_rate, 4),
            "distinct_count": self.distinct_count,
            "sample_values": self.sample_values,
            "min": self.min_value,
            "max": self.max_value,
        }


@dataclass(slots=True)
class QualityReport:
    dataset_id: str
    source_tier: str
    generated_at: str

    rows_in: int = 0
    rows_out: int = 0
    rows_deduplicated: int = 0
    rows_quarantined: int = 0

    files_read: int = 0
    schema_variants: int = 0

    coercion_failures: dict[str, int] = field(default_factory=dict)
    quarantine_reasons: dict[str, int] = field(default_factory=dict)
    quarantine_samples: list[dict[str, Any]] = field(default_factory=list)
    columns: list[ColumnProfile] = field(default_factory=list)

    data_period_range: list[str] | None = None
    capture_date_range: list[str] | None = None
    natural_key: list[str] = field(default_factory=list)

    warnings: list[str] = field(default_factory=list)

    # ---------------------------------------------------------------- checks --
    @property
    def row_retention(self) -> float:
        return self.rows_out / self.rows_in if self.rows_in else 0.0

    @property
    def passed(self) -> bool:
        """Gate for Phase 2.

        Fails when nothing survives, when more than 5% of rows are quarantined,
        or when any coercion failed without being quarantined — an uncaught
        coercion means a value was silently turned into a null.
        """
        if self.rows_out == 0:
            return False
        if self.rows_in and self.rows_quarantined / self.rows_in > 0.05:
            return False
        return sum(self.coercion_failures.values()) == 0

    def add_coercion_failure(self, column: str, count: int) -> None:
        if count:
            self.coercion_failures[column] = self.coercion_failures.get(column, 0) + count

    def quarantine(self, reason: str, count: int, sample: dict[str, Any] | None = None) -> None:
        if not count:
            return
        self.quarantine_reasons[reason] = self.quarantine_reasons.get(reason, 0) + count
        self.rows_quarantined += count
        if sample is not None and len(self.quarantine_samples) < 10:
            # Sampled rows come straight from Polars and carry dates, decimals
            # and nulls. Stringify at capture time so the report is always
            # serialisable — a DQ report that fails to write is worse than one
            # with slightly lossy samples.
            safe = {k: (None if v is None else str(v)[:200]) for k, v in sample.items()}
            self.quarantine_samples.append({"reason": reason, "row": safe})

    def warn(self, message: str) -> None:
        self.warnings.append(message)

    # ----------------------------------------------------------------- output --
    def to_dict(self) -> dict[str, Any]:
        return {
            "dataset_id": self.dataset_id,
            "source_tier": self.source_tier,
            "generated_at": self.generated_at,
            "passed": self.passed,
            "row_counts": {
                "in": self.rows_in,
                "out": self.rows_out,
                "deduplicated": self.rows_deduplicated,
                "quarantined": self.rows_quarantined,
                "retention": round(self.row_retention, 4),
            },
            "files_read": self.files_read,
            "schema_variants": self.schema_variants,
            "natural_key": self.natural_key,
            "data_period_range": self.data_period_range,
            "capture_date_range": self.capture_date_range,
            "coercion_failures": self.coercion_failures,
            "quarantine": {
                "reasons": self.quarantine_reasons,
                "samples": self.quarantine_samples,
            },
            "columns": [c.to_dict() for c in self.columns],
            "warnings": self.warnings,
        }

    def write(self, directory: Path) -> Path:
        directory.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(tz=UTC).strftime("%Y-%m-%d")
        path = directory / f"{self.dataset_id}_{stamp}.json"
        path.write_text(
            json.dumps(self.to_dict(), indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )
        return path


def profile_frame(frame: pl.DataFrame, *, max_samples: int = 3) -> list[ColumnProfile]:
    """Per-column null rate, cardinality and range."""
    total = frame.height
    profiles: list[ColumnProfile] = []

    for name in frame.columns:
        series = frame.get_column(name)
        null_count = int(series.null_count())

        try:
            distinct = int(series.n_unique())
        except Exception:
            distinct = -1

        samples: list[str] = []
        try:
            non_null = series.drop_nulls()
            for value in non_null.head(max_samples).to_list():
                samples.append(str(value)[:80])
        except Exception:
            pass

        minimum = maximum = None
        if series.dtype.is_numeric() or series.dtype in (pl.Date, pl.Datetime):
            try:
                lo, hi = series.min(), series.max()
                minimum = None if lo is None else str(lo)
                maximum = None if hi is None else str(hi)
            except Exception:
                pass

        profiles.append(
            ColumnProfile(
                name=name,
                dtype=str(series.dtype),
                null_count=null_count,
                null_rate=null_count / total if total else 0.0,
                distinct_count=distinct,
                sample_values=samples,
                min_value=minimum,
                max_value=maximum,
            )
        )
    return profiles


def summarise_reports(reports: list[QualityReport]) -> str:
    """Phase 2 gate report."""
    lines = [
        "",
        "  PHASE 2 GATE — silver transformation + data quality",
        "  " + "─" * 92,
        f"  {'dataset':<32} {'rows in':>9} {'rows out':>9} {'dedup':>7} {'quar':>6} {'coerce':>7}  gate",
        "  " + "─" * 92,
    ]
    for report in sorted(reports, key=lambda r: r.dataset_id):
        coercions = sum(report.coercion_failures.values())
        lines.append(
            f"  {report.dataset_id:<32} {report.rows_in:>9,} {report.rows_out:>9,} "
            f"{report.rows_deduplicated:>7,} {report.rows_quarantined:>6,} {coercions:>7,}  "
            f"{'✓' if report.passed else '✗'}"
        )
    passed = sum(1 for r in reports if r.passed)
    lines += [
        "  " + "─" * 92,
        f"  {passed}/{len(reports)} datasets passed · "
        f"{sum(r.rows_out for r in reports):,} silver rows total",
        "",
    ]
    return "\n".join(lines)
