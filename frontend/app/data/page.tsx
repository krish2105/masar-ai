"use client";

import { useEffect, useState } from "react";
import { motion } from "motion/react";
import { CheckCircle2, XCircle, AlertTriangle, ExternalLink } from "lucide-react";
import { fetchDatasets } from "@/lib/api";
import { formatNumber, formatPeriod } from "@/lib/utils";

interface DatasetRow {
  dataset_id: string;
  dubai_pulse_slug: string;
  landing_page: string;
  domain: string;
  role: string;
  files: number;
  bytes: number;
  data_period_range: [string, string] | null;
  capture_dates: string[];
  coverage_capped: { available: number; retained: number; dropped: number; rationale: string } | null;
  skipped_files: number;
  quality: {
    passed: boolean;
    rows_in: number;
    rows_out: number;
    deduplicated: number;
    quarantined: number;
    coercion_failures: number;
    warnings: string[];
  };
}

interface Ledger {
  acquisition_note: string;
  ingest_date: string;
  datasets_recovered: number;
  datasets_attempted: number;
  total_files: number;
  total_bytes: number;
  datasets: DatasetRow[];
}

/**
 * The provenance ledger.
 *
 * Publishing this as a page rather than burying it in a README is the point:
 * a reader can check for themselves what was ingested, where coverage was
 * capped and why, and whether the quality gate passed — without taking any of
 * it on trust.
 */
export default function DataPage() {
  const [ledger, setLedger] = useState<Ledger | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    fetchDatasets().then((data) => {
      if (data) setLedger(data as unknown as Ledger);
      else setError(true);
    });
  }, []);

  if (error) {
    return (
      <div className="grid flex-1 place-items-center p-8 text-center text-[var(--text-muted)]">
        No ingestion manifest found. Run <code className="mx-1">make ingest</code> first.
      </div>
    );
  }

  if (!ledger) {
    return (
      <div className="mx-auto w-full max-w-[1200px] flex-1 space-y-2 p-4">
        {[0, 1, 2, 3].map((i) => (
          <div key={i} className="shimmer h-20 rounded-lg" />
        ))}
      </div>
    );
  }

  return (
    <main className="mx-auto w-full max-w-[1200px] flex-1 space-y-4 p-4">
      <header>
        <h1 className="text-[var(--text-step-2)] font-semibold">Data provenance</h1>
        <p className="mt-1 max-w-3xl text-[0.82rem] leading-relaxed text-[var(--text-muted)]">
          {ledger.acquisition_note}
        </p>
      </header>

      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        <Tile label="Datasets recovered" value={`${ledger.datasets_recovered}/${ledger.datasets_attempted}`} />
        <Tile label="Files" value={formatNumber(ledger.total_files)} />
        <Tile label="Raw size" value={`${(ledger.total_bytes / 1_048_576).toFixed(0)} MB`} />
        <Tile label="Ingested" value={ledger.ingest_date} />
      </div>

      <div className="space-y-2">
        {ledger.datasets.map((dataset, index) => (
          <motion.article
            key={dataset.dataset_id}
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.35, delay: Math.min(index * 0.03, 0.4) }}
            className="surface p-3"
          >
            <div className="flex flex-wrap items-center gap-2">
              {dataset.quality.passed ? (
                <CheckCircle2 size={15} className="shrink-0 text-[var(--accent)]" />
              ) : (
                <XCircle size={15} className="shrink-0 text-[var(--danger)]" />
              )}
              <h2 className="font-mono text-[0.85rem] font-semibold">{dataset.dataset_id}</h2>
              <span className="chip chip-idle">{dataset.domain}</span>
              {dataset.coverage_capped && (
                <span
                  className="chip chip-loop"
                  title={dataset.coverage_capped.rationale}
                >
                  <AlertTriangle size={10} />
                  capped {dataset.coverage_capped.retained}/{dataset.coverage_capped.available}
                </span>
              )}
              <a
                href={dataset.landing_page}
                target="_blank"
                rel="noopener noreferrer"
                className="ms-auto inline-flex items-center gap-1 text-[0.68rem] text-[var(--accent)] hover:underline"
              >
                original dataset <ExternalLink size={9} />
              </a>
            </div>

            <p className="mt-1 text-[0.78rem] leading-snug text-[var(--text-muted)]">{dataset.role}</p>

            <dl className="mt-2 flex flex-wrap gap-x-5 gap-y-1 text-[0.7rem]">
              <Metric label="files" value={formatNumber(dataset.files)} />
              <Metric label="rows in" value={formatNumber(dataset.quality.rows_in ?? 0)} />
              <Metric label="rows out" value={formatNumber(dataset.quality.rows_out ?? 0)} />
              <Metric label="deduped" value={formatNumber(dataset.quality.deduplicated ?? 0)} />
              <Metric
                label="quarantined"
                value={formatNumber(dataset.quality.quarantined ?? 0)}
                warn={(dataset.quality.quarantined ?? 0) > 0}
              />
              <Metric
                label="coercion failures"
                value={formatNumber(dataset.quality.coercion_failures ?? 0)}
                warn={(dataset.quality.coercion_failures ?? 0) > 0}
              />
              {dataset.data_period_range && (
                <Metric
                  label="period"
                  value={`${formatPeriod(dataset.data_period_range[0].replace(/-/g, "").slice(0, 6))} → ${formatPeriod(
                    dataset.data_period_range[1].replace(/-/g, "").slice(0, 6),
                  )}`}
                />
              )}
            </dl>

            {dataset.coverage_capped && (
              <p className="mt-2 rounded border border-[var(--loop-border)] bg-[var(--loop-soft)] px-2 py-1.5 text-[0.72rem] leading-snug text-[var(--text-muted)]">
                {dataset.coverage_capped.rationale}
              </p>
            )}

            {dataset.quality.warnings?.length > 0 && (
              <ul className="mt-1.5 space-y-0.5">
                {dataset.quality.warnings.map((warning, warningIndex) => (
                  <li key={warningIndex} className="text-[0.7rem] leading-snug text-[var(--text-faint)]">
                    · {warning}
                  </li>
                ))}
              </ul>
            )}
          </motion.article>
        ))}
      </div>
    </main>
  );
}

function Tile({ label, value }: { label: string; value: string }) {
  return (
    <div className="surface p-2.5">
      <p className="text-[0.63rem] uppercase tracking-[0.12em] text-[var(--text-faint)]">{label}</p>
      <p className="mt-0.5 text-[1.2rem] font-semibold tabular-nums leading-none">{value}</p>
    </div>
  );
}

function Metric({ label, value, warn }: { label: string; value: string; warn?: boolean }) {
  return (
    <div className="flex items-baseline gap-1">
      <dt className="text-[var(--text-faint)]">{label}</dt>
      <dd
        className="font-medium tabular-nums"
        style={{ color: warn ? "var(--loop)" : "var(--text)" }}
      >
        {value}
      </dd>
    </div>
  );
}
