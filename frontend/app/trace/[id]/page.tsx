"use client";

import { use, useEffect, useState } from "react";
import { motion } from "motion/react";
import { Download, RotateCcw, AlertCircle } from "lucide-react";
import { fetchTrace } from "@/lib/api";
import { cn, formatMs } from "@/lib/utils";

interface Hop {
  hop_index: number;
  agent_id: string;
  agent_name: string;
  timestamp: string | null;
  latency_ms: number;
  model_used: string | null;
  provider: string | null;
  tokens_in: number;
  tokens_out: number;
  cost_estimate_usd: number;
  decision: string | null;
  cycle: number;
  error: string | null;
  metadata: Record<string, unknown>;
}

interface Trace {
  turn_id: string;
  hops: number;
  total_latency_ms: number;
  replan_cycles: number;
  agents_used: string[];
  trace: Hop[];
}

export default function TracePage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const [trace, setTrace] = useState<Trace | null>(null);
  const [missing, setMissing] = useState(false);

  useEffect(() => {
    fetchTrace(id).then((data) => {
      if (data) setTrace(data as unknown as Trace);
      else setMissing(true);
    });
  }, [id]);

  if (missing) {
    return (
      <div className="grid min-h-0 flex-1 place-items-center overflow-y-auto p-8 text-center">
        <div className="flex items-center gap-2 text-[var(--text-muted)]">
          <AlertCircle size={16} />
          <span>No trace found for turn <code className="text-[0.85rem]">{id}</code>.</span>
        </div>
      </div>
    );
  }

  if (!trace) {
    return (
      <div className="mx-auto w-full max-w-4xl min-h-0 flex-1 space-y-2 overflow-y-auto p-4">
        {[0, 1, 2, 3, 4].map((i) => (
          <div key={i} className="shimmer h-14 rounded-lg" />
        ))}
      </div>
    );
  }

  const maxLatency = Math.max(1, ...trace.trace.map((h) => h.latency_ms));

  function download() {
    const blob = new Blob([JSON.stringify(trace, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `masar-trace-${id}.json`;
    anchor.click();
    URL.revokeObjectURL(url);
  }

  return (
    <main className="mx-auto w-full max-w-4xl min-h-0 flex-1 space-y-4 overflow-y-auto p-4">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-[var(--text-step-2)] font-semibold">Agent trace</h1>
          <p className="mt-0.5 font-mono text-[0.72rem] text-[var(--text-faint)]">{trace.turn_id}</p>
        </div>
        <button
          onClick={download}
          className="chip chip-idle transition-colors hover:border-[var(--accent-border)] hover:text-[var(--accent)]"
        >
          <Download size={12} />
          Export JSON
        </button>
      </header>

      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        <Stat label="Hops" value={String(trace.hops)} />
        <Stat label="Total latency" value={formatMs(trace.total_latency_ms)} />
        <Stat label="Agents" value={String(trace.agents_used.length)} />
        <Stat
          label="Re-plan cycles"
          value={String(trace.replan_cycles)}
          highlight={trace.replan_cycles > 0}
        />
      </div>

      {trace.replan_cycles > 0 && (
        <motion.div
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          className="flex items-start gap-2 rounded-xl border border-[var(--loop-border)] bg-[var(--loop-soft)] p-3"
        >
          <RotateCcw size={15} className="mt-0.5 shrink-0 text-[var(--loop)]" />
          <p className="text-[0.8rem] leading-relaxed text-[var(--text-muted)]">
            <strong className="text-[var(--loop)]">The corrective loop fired.</strong> The Grader
            judged the assembled evidence insufficient and returned control to the Planner with
            named gaps, {trace.replan_cycles} time{trace.replan_cycles > 1 ? "s" : ""}. This is the
            cycle that distinguishes the system from a linear retrieve-then-generate pipeline —
            below, look for the second <code>A4</code> hop and compare its decision to the first.
          </p>
        </motion.div>
      )}

      <ol className="space-y-1.5">
        {trace.trace.map((hop, index) => {
          const isReplan = hop.agent_id === "A4" && hop.cycle > 0;
          const isGrader = hop.agent_id === "A12";
          const scores = hop.metadata?.scores as Record<string, number> | undefined;
          const gaps = hop.metadata?.gaps as string[] | undefined;

          return (
            <motion.li
              key={index}
              initial={{ opacity: 0, x: -8 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ duration: 0.3, delay: Math.min(index * 0.03, 0.5) }}
              className={cn(
                "rounded-lg border p-2.5",
                isReplan
                  ? "border-[var(--loop-border)] bg-[var(--loop-soft)]"
                  : "border-[var(--border)] bg-[var(--surface)]",
              )}
            >
              <div className="flex flex-wrap items-center gap-2">
                <span
                  className={cn("chip shrink-0", isReplan ? "chip-loop" : "chip-accent")}
                >
                  {isReplan && <RotateCcw size={10} />}
                  {hop.agent_id}
                </span>
                <span className="text-[0.82rem] font-medium">{hop.agent_name}</span>
                {hop.cycle > 0 && (
                  <span className="chip chip-loop">cycle {hop.cycle}</span>
                )}
                {hop.provider && (
                  <span className="chip chip-idle">
                    {hop.provider}
                    {hop.model_used ? ` · ${hop.model_used}` : ""}
                  </span>
                )}
                <span className="ms-auto shrink-0 font-mono text-[0.7rem] tabular-nums text-[var(--text-faint)]">
                  {formatMs(hop.latency_ms)}
                </span>
              </div>

              {/* Latency bar — where the time actually went, at a glance. */}
              <div className="mt-1.5 h-1 overflow-hidden rounded-full bg-[var(--surface-2)]">
                <motion.div
                  initial={{ width: 0 }}
                  animate={{ width: `${(hop.latency_ms / maxLatency) * 100}%` }}
                  transition={{ duration: 0.6, delay: Math.min(index * 0.03, 0.5) }}
                  className="h-full rounded-full"
                  style={{ background: isReplan ? "var(--loop)" : "var(--accent)" }}
                />
              </div>

              {hop.decision && (
                <p className="mt-1.5 text-[0.76rem] leading-snug text-[var(--text-muted)]">
                  {hop.decision}
                </p>
              )}

              {isGrader && scores && (
                <div className="mt-1.5 flex flex-wrap gap-1.5">
                  {Object.entries(scores).map(([axis, score]) => (
                    <span
                      key={axis}
                      className={cn("chip", score >= 0.7 ? "chip-accent" : "chip-loop")}
                      title={`${axis}: ${score.toFixed(2)} (threshold 0.70)`}
                    >
                      {axis} {score.toFixed(2)}
                    </span>
                  ))}
                </div>
              )}

              {gaps && gaps.length > 0 && (
                <ul className="mt-1.5 space-y-0.5 border-s-2 border-[var(--loop-border)] ps-2">
                  {gaps.map((gap, gapIndex) => (
                    <li key={gapIndex} className="text-[0.73rem] leading-snug text-[var(--text-muted)]">
                      {gap}
                    </li>
                  ))}
                </ul>
              )}

              {(hop.tokens_in > 0 || hop.tokens_out > 0) && (
                <p className="mt-1 font-mono text-[0.66rem] tabular-nums text-[var(--text-faint)]">
                  {hop.tokens_in} in · {hop.tokens_out} out · $
                  {hop.cost_estimate_usd.toFixed(6)}
                </p>
              )}

              {hop.error && (
                <p className="mt-1 rounded border border-[var(--danger)]/30 bg-[var(--danger-soft)] px-2 py-1 text-[0.72rem] text-[var(--danger)]">
                  {hop.error}
                </p>
              )}
            </motion.li>
          );
        })}
      </ol>

      <p className="text-[0.72rem] leading-relaxed text-[var(--text-faint)]">
        Cost is shown even though it is zero on the free tier — a cost line that only appears
        once it is non-zero is a cost line nobody trusts.
      </p>
    </main>
  );
}

function Stat({
  label,
  value,
  highlight,
}: {
  label: string;
  value: string;
  highlight?: boolean;
}) {
  return (
    <div className="surface p-2.5">
      <p className="text-[0.63rem] uppercase tracking-[0.12em] text-[var(--text-faint)]">{label}</p>
      <p
        className="mt-0.5 text-[1.25rem] font-semibold tabular-nums leading-none"
        style={{ color: highlight ? "var(--loop)" : "var(--text)" }}
      >
        {value}
      </p>
    </div>
  );
}
