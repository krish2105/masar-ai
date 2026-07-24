"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { motion, AnimatePresence } from "motion/react";
import { ArrowUp, Square, PanelRightOpen } from "lucide-react";
import { AgentRail } from "@/components/AgentRail";
import { ChatMessage } from "@/components/ChatMessage";
import { EvidencePanel } from "@/components/EvidencePanel";
import { MobileEvidenceSheet } from "@/components/MobileEvidenceSheet";
import { ConnectionBanner } from "@/components/ConnectionBanner";
import { ExampleTrace } from "@/components/ExampleTrace";
import { streamChat, fetchStations } from "@/lib/api";
import type { AgentEvent, Citation, Message, StationMarker } from "@/lib/types";
import { isArabic } from "@/lib/utils";

const SUGGESTIONS = [
  "Which fare zone is Union metro station in?",
  "Which metro station is busiest?",
  "How much is a monthly 2-zone nol commute?",
  "What's the nearest stop to Dubai Mall?",
  "أي محطة مترو هي الأكثر ازدحاماً؟",
  "Is real-time bus location available?",
];

export default function ChatPage() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [running, setRunning] = useState(false);
  const [agents, setAgents] = useState<AgentEvent[]>([]);
  const [replanGaps, setReplanGaps] = useState<string[]>([]);
  const [citations, setCitations] = useState<Citation[]>([]);
  const [stations, setStations] = useState<StationMarker[]>([]);
  const [activeCitation, setActiveCitation] = useState<string | null>(null);
  const [sheetOpen, setSheetOpen] = useState(false);

  const sessionId = useRef<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const evidenceTriggerRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    fetchStations("Metro").then((data) => {
      if (data?.stations) setStations(data.stations as unknown as StationMarker[]);
    });
  }, []);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages]);

  const send = useCallback(
    async (query: string) => {
      const trimmed = query.trim();
      if (!trimmed || running) return;

      const language = isArabic(trimmed) ? "ar" : "en";
      const userMessage: Message = {
        id: `u-${Date.now()}`,
        role: "user",
        text: trimmed,
        language,
      };
      const assistantId = `a-${Date.now()}`;
      const assistantMessage: Message = {
        id: assistantId,
        role: "assistant",
        text: "",
        language,
        streaming: true,
      };

      setMessages((prev) => [...prev, userMessage, assistantMessage]);
      setInput("");
      setRunning(true);
      setAgents([]);
      setReplanGaps([]);
      setCitations([]);

      const controller = new AbortController();
      abortRef.current = controller;

      await streamChat(
        trimmed,
        sessionId.current,
        {
          onStart: ({ session_id }) => {
            sessionId.current = session_id;
          },
          onAgent: (event) => setAgents((prev) => [...prev, event]),
          onReplan: ({ gaps }) => setReplanGaps(gaps),
          onEvidence: (sources) => setCitations(sources),
          onToken: (text) =>
            setMessages((prev) =>
              prev.map((m) => (m.id === assistantId ? { ...m, text: m.text + text } : m)),
            ),
          onDone: (meta) =>
            setMessages((prev) =>
              prev.map((m) =>
                m.id === assistantId
                  ? { ...m, streaming: false, meta, language: meta.language }
                  : m,
              ),
            ),
          onError: (message) =>
            setMessages((prev) =>
              prev.map((m) =>
                m.id === assistantId ? { ...m, streaming: false, error: message } : m,
              ),
            ),
        },
        controller.signal,
      );

      setRunning(false);
      abortRef.current = null;
    },
    [running],
  );

  function stop() {
    abortRef.current?.abort();
    setRunning(false);
    setMessages((prev) => prev.map((m) => ({ ...m, streaming: false })));
  }

  return (
    <main className="mx-auto flex min-h-0 w-full max-w-[1600px] flex-1 gap-3 p-3">
      {/* ---- conversation + persistent agent rail ---- */}
      <section className="flex min-h-0 min-w-0 flex-1 flex-col gap-3 lg:flex-[6]">
        <div
          ref={scrollRef}
          className="min-h-0 flex-1 space-y-3 overflow-y-auto rounded-xl border border-[var(--border)] bg-[var(--surface)]/40 p-3"
        >
          {messages.length === 0 ? (
            <EmptyState onPick={send} />
          ) : (
            messages.map((message) => (
              <ChatMessage
                key={message.id}
                message={message}
                onCitationHover={setActiveCitation}
              />
            ))
          )}
        </div>

        {/* The rail is pinned here, always visible — see AgentRail's docstring. */}
        <AgentRail events={agents} running={running} replanGaps={replanGaps} />

        <ConnectionBanner />

        {/* Mobile only: the evidence + map live in a bottom sheet, not a column. */}
        <button
          ref={evidenceTriggerRef}
          type="button"
          onClick={() => setSheetOpen(true)}
          className="flex items-center justify-center gap-2 rounded-xl border border-[var(--border)] bg-[var(--surface)] px-3 py-2 text-[0.78rem] font-medium text-[var(--text-muted)] transition-colors hover:text-[var(--accent)] lg:hidden"
        >
          <PanelRightOpen size={14} />
          Evidence &amp; map
          {citations.length > 0 && (
            <span className="chip chip-accent text-[0.62rem]">{citations.length}</span>
          )}
        </button>

        <form
          onSubmit={(event) => {
            event.preventDefault();
            send(input);
          }}
          className="flex items-end gap-2 rounded-xl border border-[var(--border)] bg-[var(--surface)] p-2"
        >
          <textarea
            value={input}
            onChange={(event) => setInput(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                send(input);
              }
            }}
            dir={isArabic(input) ? "rtl" : "ltr"}
            rows={1}
            placeholder="Ask about routes, fares, stations or ridership…"
            aria-label="Your question"
            className="max-h-40 min-h-[2.5rem] flex-1 resize-none bg-transparent px-2 py-2 text-[0.88rem] leading-relaxed outline-none placeholder:text-[var(--text-faint)]"
          />
          {running ? (
            <button
              type="button"
              onClick={stop}
              className="grid h-9 w-9 shrink-0 place-items-center rounded-lg border border-[var(--border-strong)] text-[var(--text-muted)] transition-colors hover:text-[var(--danger)]"
              aria-label="Stop generating"
            >
              <Square size={14} fill="currentColor" />
            </button>
          ) : (
            <button
              type="submit"
              disabled={!input.trim()}
              className="grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-[var(--accent)] text-[var(--bg)] transition-all hover:bg-[var(--accent-hover)] active:scale-95 disabled:cursor-not-allowed disabled:opacity-35"
              aria-label="Send question"
            >
              <ArrowUp size={16} strokeWidth={2.5} />
            </button>
          )}
        </form>
      </section>

      {/* ---- evidence + map (desktop column) ---- */}
      <aside className="hidden min-h-0 lg:flex lg:flex-[4] lg:min-w-[22rem] lg:max-w-[30rem]">
        <EvidencePanel
          citations={citations}
          stations={stations}
          activeCitation={activeCitation}
        />
      </aside>

      {/* ---- evidence + map (mobile bottom sheet) ---- */}
      <MobileEvidenceSheet
        open={sheetOpen}
        onClose={() => {
          setSheetOpen(false);
          // Restore focus to the trigger the sheet came from (WCAG 2.4.3).
          evidenceTriggerRef.current?.focus();
        }}
        citations={citations}
        stations={stations}
        activeCitation={activeCitation}
      />
    </main>
  );
}

function EmptyState({ onPick }: { onPick: (query: string) => void }) {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-6 px-4 py-10 text-center">
      <div className="max-w-xl">
        <motion.h1
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6, ease: [0.16, 1, 0.3, 1] }}
          className="text-[var(--text-step-3)] font-semibold leading-tight"
        >
          Dubai mobility, answered with{" "}
          <span className="text-[var(--accent)]">its sources</span>.
        </motion.h1>
        <motion.p
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6, delay: 0.12, ease: [0.16, 1, 0.3, 1] }}
          className="mx-auto mt-3 max-w-lg text-[0.88rem] leading-relaxed text-[var(--text-muted)]"
        >
          Masar plans how to answer each question, gathers evidence across documents,
          the analytical database, geography and deterministic fare arithmetic — then
          grades that evidence and re-plans if it falls short. Every claim carries a
          citation you can open.
        </motion.p>
      </div>

      <div className="flex max-w-2xl flex-wrap justify-center gap-2">
        {SUGGESTIONS.map((suggestion, index) => (
          <motion.button
            key={suggestion}
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.4, delay: 0.2 + index * 0.05 }}
            onClick={() => onPick(suggestion)}
            dir={isArabic(suggestion) ? "rtl" : "ltr"}
            className="rounded-full border border-[var(--border)] bg-[var(--surface)] px-3.5 py-1.5 text-[0.78rem] text-[var(--text-muted)] transition-all hover:border-[var(--accent-border)] hover:text-[var(--accent)] active:scale-[0.98]"
          >
            {suggestion}
          </motion.button>
        ))}
      </div>

      {/* A real recorded run, so the corrective loop is visible before typing —
          and so a cold backend still shows the product working. */}
      <ExampleTrace />

      <AnimatePresence>
        <motion.p
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 0.6 }}
          className="max-w-md text-[0.72rem] leading-relaxed text-[var(--text-faint)]"
        >
          Ask the last one to see how it handles a question the data genuinely cannot
          answer.
        </motion.p>
      </AnimatePresence>
    </div>
  );
}
