"use client";

import { motion, AnimatePresence, useReducedMotion } from "motion/react";
import { useBackendStatus } from "@/lib/health";

/**
 * A calm, honest cold-start affordance. Shows nothing while the backend is
 * reachable; when it is not, a soft "waking the agents" line appears instead of
 * letting the visitor discover the outage by sending a question into the void.
 *
 * Deliberately NOT amber — amber means one thing in this interface, the
 * corrective loop, and a connection notice must never borrow that signal.
 */
export function ConnectionBanner() {
  const status = useBackendStatus();
  const reduce = useReducedMotion();

  return (
    <AnimatePresence>
      {status === "offline" && (
        <motion.div
          key="waking"
          initial={reduce ? false : { opacity: 0, y: 6 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: 6 }}
          transition={{ duration: 0.3, ease: [0.16, 1, 0.3, 1] }}
          role="status"
          aria-live="polite"
          className="flex flex-wrap items-center justify-center gap-x-2 gap-y-1 rounded-xl border border-[var(--border)] bg-[var(--surface-2)]/70 px-3 py-1.5 text-[0.72rem] text-[var(--text-muted)]"
        >
          <span className="relative flex h-2 w-2" aria-hidden>
            <motion.span
              className="absolute inline-flex h-full w-full rounded-full bg-[var(--accent)]"
              animate={reduce ? {} : { opacity: [0.25, 1, 0.25], scale: [1, 1.7, 1] }}
              transition={{ duration: 1.6, repeat: Infinity, ease: "easeInOut" }}
            />
            <span className="relative inline-flex h-2 w-2 rounded-full bg-[var(--accent)]" />
          </span>
          <span>Waking the agents — the backend loads its models on the first request.</span>
          <span dir="rtl" lang="ar" className="text-[var(--text-faint)]">
            جارٍ إيقاظ الوكلاء…
          </span>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
