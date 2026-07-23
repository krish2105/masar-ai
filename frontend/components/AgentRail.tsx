"use client";

import { motion, AnimatePresence, useReducedMotion } from "motion/react";
import { RotateCcw } from "lucide-react";
import type { AgentEvent } from "@/lib/types";
import { cn, formatMs } from "@/lib/utils";

/**
 * The persistent agent rail.
 *
 * The build spec put this in a tabbed panel alongside Evidence and Map. That
 * hides the one thing that makes the architecture legible: a reader who never
 * clicks the third tab never sees that retrieval strategy is a runtime
 * decision. Pinned above the composer it costs ~90px and is unmissable.
 *
 * The amber `A12 → A4 re-plan` chip is the centrepiece. Amber appears nowhere
 * else in the interface, so it needs no legend.
 */

const ORDER = ["A1", "A2", "A3", "A4", "A6", "A8", "A10", "A11", "A12", "A13"];

export function AgentRail({
  events,
  running,
  replanGaps,
}: {
  events: AgentEvent[];
  running: boolean;
  replanGaps?: string[];
}) {
  const reduce = useReducedMotion();
  const seen = new Map<string, AgentEvent>();
  for (const event of events) {
    // Keep the latest occurrence so a re-planned A4 shows its newest cycle.
    seen.set(event.agent_id + (event.cycle > 0 ? `-c${event.cycle}` : ""), event);
  }
  const fired = Array.from(seen.values());
  const cycles = Math.max(0, ...fired.map((e) => e.cycle));
  const totalMs = fired.reduce((sum, e) => sum + e.latency_ms, 0);

  return (
    <div className="rounded-xl border border-[var(--border)] bg-[var(--surface-2)]/60 px-3 py-2.5">
      <div className="mb-2 flex items-center justify-between gap-3">
        <span className="text-[0.63rem] font-semibold uppercase tracking-[0.16em] text-[var(--text-faint)]">
          Agent trace{running ? " · live" : ""}
        </span>
        {fired.length > 0 && (
          <span className="text-[0.65rem] tabular-nums text-[var(--text-faint)]">
            {fired.length} hops · {formatMs(totalMs)}
          </span>
        )}
      </div>

      <div className="flex flex-wrap items-center gap-1.5">
        {fired.length === 0 && !running && (
          <span className="text-[0.72rem] text-[var(--text-faint)]">
            Ask something and the fourteen agents will light up here as they run.
          </span>
        )}

        {ORDER.map((id) => {
          const event = fired.find((e) => e.agent_id === id && e.cycle === 0);
          if (!event) {
            return running ? (
              <span key={id} className="chip chip-idle opacity-50">
                {id}
              </span>
            ) : null;
          }
          return (
            <motion.span
              key={`${id}-0`}
              initial={reduce ? false : { opacity: 0, y: 4, scale: 0.94 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              transition={{ duration: 0.28, ease: [0.16, 1, 0.3, 1] }}
              className="chip chip-accent"
              title={event.decision ?? undefined}
            >
              {id}
              <span className="font-normal opacity-70">{event.label_en.split(" ")[0]}</span>
              <span className="font-normal tabular-nums opacity-55">
                {formatMs(event.latency_ms)}
              </span>
            </motion.span>
          );
        })}

        {/* The corrective loop. Everything above is a straight line; this is the cycle. */}
        <AnimatePresence>
          {cycles > 0 && (
            <motion.span
              key="replan"
              initial={reduce ? false : { opacity: 0, scale: 0.8, x: -8 }}
              animate={{ opacity: 1, scale: 1, x: 0 }}
              exit={{ opacity: 0, scale: 0.9 }}
              transition={{ type: "spring", stiffness: 320, damping: 22 }}
              className={cn("chip chip-loop", running && "chip-loop-active")}
              title={
                replanGaps?.length
                  ? `Gaps identified: ${replanGaps.join(" · ")}`
                  : "The Grader found the evidence insufficient and sent control back to the Planner"
              }
            >
              <RotateCcw size={11} strokeWidth={2.5} />
              A12 → A4 re-plan
              {cycles > 1 && <span className="tabular-nums">×{cycles}</span>}
            </motion.span>
          )}
        </AnimatePresence>

        {running && (
          <motion.span
            className="chip chip-idle"
            animate={reduce ? {} : { opacity: [0.45, 1, 0.45] }}
            transition={{ duration: 1.4, repeat: Infinity, ease: "easeInOut" }}
          >
            working…
          </motion.span>
        )}
      </div>

      {replanGaps && replanGaps.length > 0 && (
        <motion.div
          initial={reduce ? false : { opacity: 0, height: 0 }}
          animate={{ opacity: 1, height: "auto" }}
          className="mt-2 border-t border-[var(--loop-border)] pt-2"
        >
          <p className="text-[0.66rem] font-semibold uppercase tracking-[0.1em] text-[var(--loop)]">
            Gaps that triggered the re-plan
          </p>
          <ul className="mt-1 space-y-0.5">
            {replanGaps.slice(0, 3).map((gap, index) => (
              <li key={index} className="text-[0.72rem] leading-snug text-[var(--text-muted)]">
                · {gap}
              </li>
            ))}
          </ul>
        </motion.div>
      )}
    </div>
  );
}
