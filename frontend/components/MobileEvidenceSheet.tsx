"use client";

import { useEffect, useRef } from "react";
import { motion, AnimatePresence, useReducedMotion } from "motion/react";
import { X } from "lucide-react";
import type { Citation, StationMarker } from "@/lib/types";
import { EvidencePanel } from "./EvidencePanel";

/**
 * On desktop the evidence + map sit in a persistent right column. On a phone
 * there is no room for two columns, and the earlier build simply hid the whole
 * panel below `lg` — so a mobile visitor could never see the sources or the map
 * at all. This restores them as a bottom sheet the agent rail stays above.
 */
export function MobileEvidenceSheet({
  open,
  onClose,
  citations,
  stations,
  activeCitation,
}: {
  open: boolean;
  onClose: () => void;
  citations: Citation[];
  stations: StationMarker[];
  activeCitation?: string | null;
}) {
  const reduce = useReducedMotion();
  const dialogRef = useRef<HTMLDivElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);

  // Full dialog focus management (WCAG 2.4.3): move focus into the sheet on
  // open, trap Tab within it, and lock body scroll. Restoring focus to the
  // trigger on close is done by the owner via onClose — a button is not
  // reliably focused by a click across browsers, so capturing activeElement
  // here would restore to <body>, not the trigger.
  useEffect(() => {
    if (!open) return;

    const raf = requestAnimationFrame(() => closeRef.current?.focus());

    const focusable = () =>
      Array.from(
        dialogRef.current?.querySelectorAll<HTMLElement>(
          'a[href], button:not([disabled]), textarea, input, select, [tabindex]:not([tabindex="-1"])',
        ) ?? [],
      ).filter((el) => el.offsetParent !== null);

    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        onClose();
        return;
      }
      if (e.key !== "Tab") return;
      const items = focusable();
      if (items.length === 0) {
        e.preventDefault();
        return;
      }
      const first = items[0];
      const last = items[items.length - 1];
      const active = document.activeElement as HTMLElement | null;
      const inside = dialogRef.current?.contains(active) ?? false;
      if (e.shiftKey && (!inside || active === first)) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && (!inside || active === last)) {
        e.preventDefault();
        first.focus();
      }
    };

    document.addEventListener("keydown", onKey);
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    return () => {
      cancelAnimationFrame(raf);
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = prevOverflow;
    };
  }, [open, onClose]);

  return (
    <AnimatePresence>
      {open && (
        <div className="fixed inset-0 z-50 lg:hidden" role="dialog" aria-modal="true" aria-label="Evidence and map">
          <motion.div
            className="absolute inset-0 bg-black/45"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={onClose}
          />
          <motion.div
            ref={dialogRef}
            className="absolute inset-x-0 bottom-0 flex max-h-[85vh] flex-col rounded-t-2xl border-t border-[var(--border-strong)] bg-[var(--bg)] p-3 shadow-[var(--shadow-lg)]"
            initial={reduce ? { opacity: 0 } : { y: "100%" }}
            animate={reduce ? { opacity: 1 } : { y: 0 }}
            exit={reduce ? { opacity: 0 } : { y: "100%" }}
            transition={{ type: "spring", stiffness: 320, damping: 34 }}
          >
            <div className="relative flex items-center justify-end pb-2">
              <span
                className="absolute left-1/2 top-0 h-1 w-10 -translate-x-1/2 rounded-full bg-[var(--border-strong)]"
                aria-hidden
              />
              <button
                ref={closeRef}
                onClick={onClose}
                aria-label="Close evidence"
                className="grid h-8 w-8 place-items-center rounded-lg text-[var(--text-muted)] transition-colors hover:bg-[var(--surface-2)]"
              >
                <X size={16} />
              </button>
            </div>
            <div className="min-h-0 flex-1 overflow-hidden">
              <EvidencePanel citations={citations} stations={stations} activeCitation={activeCitation} />
            </div>
          </motion.div>
        </div>
      )}
    </AnimatePresence>
  );
}
