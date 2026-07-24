"use client";

import { motion, useReducedMotion } from "motion/react";
import { RotateCcw, CornerDownLeft, CircleCheck } from "lucide-react";
import { EXAMPLE_TRACE } from "@/data/example-trace";

/**
 * The hero's "see it think" element. A faithful, compact rendering of a real
 * recorded run — so a first-time visitor (or a cold backend) still sees the
 * corrective loop, the product's whole point, before typing a thing.
 *
 * Every value here is real (see data/example-trace.ts). The one claim it makes
 * is the honest one: the system re-planned twice and then declined to guess.
 */
export function ExampleTrace() {
  const reduce = useReducedMotion();
  const t = EXAMPLE_TRACE;

  const reveal = (i: number) => ({
    initial: reduce ? false : { opacity: 0, y: 8 },
    animate: { opacity: 1, y: 0 },
    transition: { duration: 0.4, delay: 0.15 + i * 0.08, ease: [0.16, 1, 0.3, 1] as const },
  });

  return (
    <motion.div
      {...reveal(0)}
      className="mx-auto w-full max-w-xl rounded-xl border border-[var(--border)] bg-[var(--surface)]/60 p-3.5 text-start"
      aria-label="Example: a real recorded run where the corrective loop fired twice"
    >
      <div className="mb-2.5 flex items-center justify-between gap-2">
        <span className="text-[0.62rem] font-semibold uppercase tracking-[0.16em] text-[var(--text-faint)]">
          A real recorded run
        </span>
        <span className="chip chip-idle text-[0.62rem]">{t.intent}</span>
      </div>

      {/* Understand — the pipeline prefix that runs once. */}
      <motion.div {...reveal(1)} className="mb-1.5 flex flex-wrap items-center gap-1.5">
        {t.understand.map((id) => (
          <span key={id} className="chip chip-idle">
            {id}
          </span>
        ))}
        <span className="text-[0.66rem] text-[var(--text-faint)]">understand the question</span>
      </motion.div>

      {/* The loop — one row per planning cycle, the re-plan drawn as a return. */}
      <div className="space-y-1">
        {t.cycles.map((cycle, i) => (
          <motion.div key={i} {...reveal(2 + i)} className="rounded-lg bg-[var(--surface-2)]/50 p-2">
            <div className="flex flex-wrap items-center gap-1.5">
              <span className="chip chip-accent">A4</span>
              <span className="text-[0.68rem] text-[var(--text-muted)]">{cycle.plan}</span>
              {cycle.agents.map((id) => (
                <span key={id} className="chip chip-accent">
                  {id}
                </span>
              ))}
            </div>
            <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
              {cycle.loops ? (
                <>
                  <span className="chip chip-loop">
                    <RotateCcw size={11} strokeWidth={2.5} />
                    A12 · {cycle.grader}
                  </span>
                  <span className="inline-flex items-center gap-1 text-[0.66rem] text-[var(--loop)]">
                    <CornerDownLeft size={11} />
                    back to the Planner
                  </span>
                </>
              ) : (
                <>
                  <span className="chip chip-loop">
                    <RotateCcw size={11} strokeWidth={2.5} />
                    A12 · {cycle.grader}
                  </span>
                  <span className="chip chip-accent">
                    <CircleCheck size={11} />
                    A13 answers · {t.confidence} confidence · {t.citations} citations
                  </span>
                </>
              )}
            </div>
          </motion.div>
        ))}
      </div>

      <motion.p {...reveal(6)} className="mt-2.5 text-[0.72rem] leading-relaxed text-[var(--text-muted)]">
        The Grader judged the evidence insufficient <strong className="text-[var(--loop)]">twice</strong> and
        sent it back to re-plan. At the cycle cap it answered with{" "}
        <strong className="text-[var(--text)]">low confidence</strong> rather than inventing facts — that
        restraint is the point.
      </motion.p>
      <motion.p {...reveal(7)} className="mt-1 text-[0.64rem] text-[var(--text-faint)]">
        Local fallback model, ~{t.totalSeconds}s. Cloud providers answer in seconds; the path is identical.
      </motion.p>
    </motion.div>
  );
}
