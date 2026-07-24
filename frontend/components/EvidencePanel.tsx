"use client";

import { useState } from "react";
import dynamic from "next/dynamic";
import { motion } from "motion/react";
import { Database, FileText, MapPin, Calculator, Radio, ExternalLink, AlertTriangle } from "lucide-react";
import type { Citation, StationMarker } from "@/lib/types";
import { cn } from "@/lib/utils";

/**
 * MapLibre and its stylesheet are ~heavy and WebGL-dependent. Loading them
 * eagerly would put them in the home route's first bundle even though the Map
 * tab is not the default view. Deferring the whole panel behind next/dynamic
 * keeps the initial payload small — the map's code only arrives when a visitor
 * actually opens the tab. This is the single biggest home-route Lighthouse win.
 */
const MapPanel = dynamic(() => import("./MapPanel").then((m) => m.MapPanel), {
  ssr: false,
  loading: () => (
    <div className="shimmer h-full min-h-[18rem]" aria-label="Loading map" role="status" />
  ),
});

const ICONS: Record<string, typeof Database> = {
  document: FileText,
  sql_result: Database,
  geo_result: MapPin,
  calc_result: Calculator,
  api_result: Radio,
};

const TYPE_LABELS: Record<string, string> = {
  document: "Document",
  sql_result: "Database",
  geo_result: "Geospatial",
  calc_result: "Calculated",
  api_result: "Live API",
};

type Tab = "evidence" | "map";

export function EvidencePanel({
  citations,
  stations,
  activeCitation,
}: {
  citations: Citation[];
  stations: StationMarker[];
  activeCitation?: string | null;
}) {
  const [tab, setTab] = useState<Tab>("evidence");

  return (
    <div className="flex h-full min-h-0 flex-col rounded-xl border border-[var(--border)] bg-[var(--surface)]">
      <div className="flex shrink-0 gap-1 border-b border-[var(--border)] p-2">
        {(["evidence", "map"] as Tab[]).map((name) => (
          <button
            key={name}
            onClick={() => setTab(name)}
            className={cn(
              "rounded-lg px-3 py-1.5 text-[0.75rem] font-medium capitalize transition-colors",
              tab === name
                ? "bg-[var(--accent-soft)] text-[var(--accent)]"
                : "text-[var(--text-muted)] hover:bg-[var(--surface-2)]",
            )}
          >
            {name}
            {name === "evidence" && citations.length > 0 && (
              <span className="ms-1.5 tabular-nums opacity-65">{citations.length}</span>
            )}
          </button>
        ))}
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto">
        {tab === "evidence" ? (
          <EvidenceList citations={citations} activeCitation={activeCitation} />
        ) : (
          <MapPanel stations={stations} />
        )}
      </div>
    </div>
  );
}

function EvidenceList({
  citations,
  activeCitation,
}: {
  citations: Citation[];
  activeCitation?: string | null;
}) {
  if (citations.length === 0) {
    return (
      <div className="p-4 text-[0.78rem] leading-relaxed text-[var(--text-faint)]">
        Sources appear here once an answer is produced. Every factual claim in an answer
        carries a marker like <span className="chip chip-accent mx-0.5">S1</span> that
        resolves to one of these — a claim that cannot be sourced is deleted rather than
        softened.
      </div>
    );
  }

  return (
    <ul className="space-y-2 p-2">
      {citations.map((citation, index) => {
        const Icon = ICONS[citation.type] ?? FileText;
        const active = activeCitation === citation.id;
        return (
          <motion.li
            key={citation.id}
            id={`citation-${citation.id}`}
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.3, delay: index * 0.04, ease: [0.16, 1, 0.3, 1] }}
            className={cn(
              "rounded-lg border p-2.5 transition-colors",
              active
                ? "border-[var(--accent-border)] bg-[var(--accent-soft)]"
                : "border-[var(--border)] bg-[var(--surface-2)]/50",
            )}
          >
            <div className="mb-1 flex items-center gap-2">
              <span className="chip chip-accent shrink-0">{citation.id}</span>
              <Icon size={13} className="shrink-0 text-[var(--text-faint)]" />
              <span className="text-[0.68rem] uppercase tracking-wide text-[var(--text-faint)]">
                {TYPE_LABELS[citation.type] ?? citation.type}
              </span>
            </div>

            <p className="break-words font-mono text-[0.74rem] leading-snug text-[var(--text)]">
              {citation.dataset_or_doc}
            </p>

            <div className="mt-1.5 flex flex-wrap items-center gap-x-2.5 gap-y-1 text-[0.66rem] text-[var(--text-faint)]">
              {citation.row_id_or_chunk_id && (
                <span className="truncate max-w-[14rem]">{citation.row_id_or_chunk_id}</span>
              )}
              {citation.captured_at && (
                /* Capture date, not "today" — the data is archived, and saying so
                   on every card is what stops it reading as live. */
                <span title="Date this data was captured from the archive">
                  archived {citation.captured_at.slice(0, 10)}
                </span>
              )}
              {citation.source_url && (
                <a
                  href={citation.source_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-1 text-[var(--accent)] hover:underline"
                >
                  source <ExternalLink size={9} />
                </a>
              )}
            </div>

            {citation.is_synthetic && (
              <div className="mt-1.5 flex items-start gap-1.5 rounded border border-[var(--loop-border)] bg-[var(--loop-soft)] px-2 py-1">
                <AlertTriangle size={11} className="mt-px shrink-0 text-[var(--loop)]" />
                <span className="text-[0.66rem] leading-snug text-[var(--loop)]">
                  Not verified against an archived dataset — treat as indicative.
                </span>
              </div>
            )}
          </motion.li>
        );
      })}
    </ul>
  );
}
