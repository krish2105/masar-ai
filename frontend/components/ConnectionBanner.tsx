"use client";

import { motion, AnimatePresence, useReducedMotion } from "motion/react";
import { useBackendStatus } from "@/lib/health";

/**
 * A calm, honest connection affordance. Shows nothing while the backend is
 * reachable. While it is plausibly cold-starting it says "waking"; once it is
 * clearly not there it says so plainly — because on the deployed site, before
 * the backend is hosted, a perpetual "waking the agents" would misrepresent an
 * outage as a warm-up. The example run on the page is real either way, so we
 * point the visitor at it.
 *
 * Deliberately NOT amber — amber means one thing in this interface, the
 * corrective loop, and a connection notice must never borrow that signal.
 */
const COPY = {
  warming: {
    en: "Waking the agents — the backend loads its models on the first request.",
    ar: "جارٍ إيقاظ الوكلاء…",
  },
  offline: {
    en: "The live backend isn't reachable — it runs locally. The run shown above is real, recorded output.",
    ar: "الخادم المباشر غير متاح — يعمل محليًا. المثال أعلاه تشغيل حقيقي مُسجّل.",
  },
} as const;

export function ConnectionBanner() {
  const status = useBackendStatus();
  const reduce = useReducedMotion();

  const visible = status === "warming" || status === "offline";
  const key = status === "warming" ? "warming" : "offline";
  const copy = COPY[key];

  return (
    <AnimatePresence mode="wait">
      {visible && (
        <motion.div
          key={key}
          initial={reduce ? false : { opacity: 0, y: 6 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: 6 }}
          transition={{ duration: 0.3, ease: [0.16, 1, 0.3, 1] }}
          role="status"
          aria-live="polite"
          className="flex flex-wrap items-center justify-center gap-x-2 gap-y-1 rounded-xl border border-[var(--border)] bg-[var(--surface-2)]/70 px-3 py-1.5 text-[0.72rem] text-[var(--text-muted)]"
        >
          {key === "warming" ? (
            // Something is happening → a live pulse.
            <span className="relative flex h-2 w-2" aria-hidden>
              <motion.span
                className="absolute inline-flex h-full w-full rounded-full bg-[var(--accent)]"
                animate={reduce ? {} : { opacity: [0.25, 1, 0.25], scale: [1, 1.7, 1] }}
                transition={{ duration: 1.6, repeat: Infinity, ease: "easeInOut" }}
              />
              <span className="relative inline-flex h-2 w-2 rounded-full bg-[var(--accent)]" />
            </span>
          ) : (
            // Nothing is happening → a still, muted dot. No false sense of motion.
            <span className="h-2 w-2 rounded-full bg-[var(--text-faint)]" aria-hidden />
          )}
          <span>{copy.en}</span>
          <span dir="rtl" lang="ar" className="text-[var(--text-faint)]">
            {copy.ar}
          </span>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
