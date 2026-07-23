"use client";

import { motion, useReducedMotion } from "motion/react";
import { AlertCircle, ShieldCheck, ShieldAlert, Shield } from "lucide-react";
import type { Message } from "@/lib/types";
import { cn, formatMs, splitCitations } from "@/lib/utils";

const CONFIDENCE_STYLES = {
  high: { icon: ShieldCheck, className: "chip-accent", label: "high confidence" },
  medium: { icon: Shield, className: "chip-idle", label: "medium confidence" },
  low: { icon: ShieldAlert, className: "chip-loop", label: "low confidence" },
} as const;

export function ChatMessage({
  message,
  onCitationHover,
}: {
  message: Message;
  onCitationHover?: (id: string | null) => void;
}) {
  const reduce = useReducedMotion();
  const rtl = message.language === "ar";

  if (message.role === "user") {
    return (
      <motion.div
        initial={reduce ? false : { opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.28, ease: [0.16, 1, 0.3, 1] }}
        className="flex justify-end"
      >
        <div
          dir={rtl ? "rtl" : "ltr"}
          lang={message.language}
          className="max-w-[85%] rounded-2xl rounded-ee-md border border-[var(--border-strong)] bg-[var(--surface-2)] px-3.5 py-2.5 text-[0.88rem] leading-relaxed"
        >
          {message.text}
        </div>
      </motion.div>
    );
  }

  const confidence = message.meta?.confidence
    ? CONFIDENCE_STYLES[message.meta.confidence]
    : null;
  const ConfidenceIcon = confidence?.icon;

  return (
    <motion.div
      initial={reduce ? false : { opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, ease: [0.16, 1, 0.3, 1] }}
      className="flex justify-start"
    >
      <div className="w-full max-w-[92%]">
        <div
          dir={rtl ? "rtl" : "ltr"}
          lang={message.language}
          className={cn(
            "surface prose-masar px-4 py-3 text-[0.88rem]",
            rtl && "text-right",
          )}
        >
          {message.error ? (
            <div className="flex items-start gap-2 text-[var(--danger)]">
              <AlertCircle size={15} className="mt-0.5 shrink-0" />
              <span>{message.error}</span>
            </div>
          ) : (
            <AnswerBody text={message.text} onCitationHover={onCitationHover} />
          )}

          {message.streaming && (
            <motion.span
              className="ms-0.5 inline-block h-[1em] w-[2px] translate-y-[2px] bg-[var(--accent)]"
              animate={reduce ? {} : { opacity: [1, 0.15, 1] }}
              transition={{ duration: 1, repeat: Infinity }}
            />
          )}
        </div>

        {message.meta && !message.streaming && (
          <div className="mt-1.5 flex flex-wrap items-center gap-1.5 px-1">
            {confidence && ConfidenceIcon && (
              <span className={cn("chip", confidence.className)}>
                <ConfidenceIcon size={11} />
                {confidence.label}
              </span>
            )}
            {message.meta.replan_cycles > 0 && (
              <span className="chip chip-loop" title="The Grader sent control back to the Planner">
                ↺ {message.meta.replan_cycles} re-plan
                {message.meta.replan_cycles > 1 ? "s" : ""}
              </span>
            )}
            <span className="chip chip-idle">{message.meta.intent}</span>
            <span className="chip chip-idle tabular-nums">
              {message.meta.evidence_count} evidence · {formatMs(message.meta.latency_ms)}
            </span>
            {message.meta.degraded_mode && (
              <span
                className="chip chip-loop"
                title="No cloud provider was available; a local model produced this answer"
              >
                degraded mode
              </span>
            )}
            {message.meta.trace_id && (
              <a
                href={`/trace/${message.meta.trace_id}`}
                className="chip chip-idle hover:text-[var(--accent)]"
              >
                view full trace →
              </a>
            )}
          </div>
        )}
      </div>
    </motion.div>
  );
}

/**
 * Renders the answer with `[S1]` markers as interactive chips.
 *
 * Deliberately not a full markdown renderer for the citation pass — the markers
 * must survive intact and stay hoverable, and running them through a markdown
 * AST is where they get mangled. Bold and line breaks are handled inline, which
 * covers everything A13 actually emits.
 */
function AnswerBody({
  text,
  onCitationHover,
}: {
  text: string;
  onCitationHover?: (id: string | null) => void;
}) {
  const blocks = text.split("\n");

  return (
    <>
      {blocks.map((block, blockIndex) => {
        if (!block.trim()) return <div key={blockIndex} className="h-2" />;
        if (block.trim() === "---") {
          return <hr key={blockIndex} className="my-2 border-[var(--border)]" />;
        }

        const isListItem = /^\s*[-*·]\s+/.test(block);
        const content = isListItem ? block.replace(/^\s*[-*·]\s+/, "") : block;

        const rendered = splitCitations(content).map((part, index) => {
          if (part.type === "cite") {
            return (
              <button
                key={index}
                onMouseEnter={() => onCitationHover?.(part.value)}
                onMouseLeave={() => onCitationHover?.(null)}
                onClick={() =>
                  document
                    .getElementById(`citation-${part.value}`)
                    ?.scrollIntoView({ behavior: "smooth", block: "center" })
                }
                className="mx-0.5 inline-flex translate-y-[-1px] items-center rounded border border-[var(--accent-border)] bg-[var(--accent-soft)] px-1 py-px align-middle text-[0.62rem] font-semibold text-[var(--accent)] transition-colors hover:bg-[var(--accent)] hover:text-[var(--bg)]"
                title="Jump to this source"
              >
                {part.value}
              </button>
            );
          }
          return <Inline key={index} text={part.value} />;
        });

        return isListItem ? (
          <div key={blockIndex} className="flex gap-2 py-0.5">
            <span className="select-none text-[var(--text-faint)]">·</span>
            <span className="flex-1">{rendered}</span>
          </div>
        ) : (
          <p key={blockIndex} className="mb-1.5">
            {rendered}
          </p>
        );
      })}
    </>
  );
}

function Inline({ text }: { text: string }) {
  const parts = text.split(/(\*\*[^*]+\*\*|\*[^*]+\*|`[^`]+`)/g);
  return (
    <>
      {parts.map((part, index) => {
        if (part.startsWith("**") && part.endsWith("**")) {
          return (
            <strong key={index} className="font-semibold text-[var(--text)]">
              {part.slice(2, -2)}
            </strong>
          );
        }
        if (part.startsWith("`") && part.endsWith("`")) {
          return (
            <code key={index} className="rounded bg-[var(--surface-2)] px-1 py-px font-mono text-[0.82em]">
              {part.slice(1, -1)}
            </code>
          );
        }
        if (part.startsWith("*") && part.endsWith("*") && part.length > 2) {
          return (
            <em key={index} className="text-[var(--text-muted)]">
              {part.slice(1, -1)}
            </em>
          );
        }
        return <span key={index}>{part}</span>;
      })}
    </>
  );
}
