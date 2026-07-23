import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export const cn = (...inputs: ClassValue[]) => twMerge(clsx(inputs));

export function formatMs(ms: number): string {
  if (ms < 1000) return `${Math.round(ms)}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

export function formatNumber(value: number): string {
  return new Intl.NumberFormat("en-US").format(Math.round(value));
}

export function formatCompact(value: number): string {
  return new Intl.NumberFormat("en-US", {
    notation: "compact",
    maximumFractionDigits: 1,
  }).format(value);
}

/** `202601` → `Jan 2026`. The warehouse uses YYYYMM keys throughout. */
export function formatPeriod(dateKey: string): string {
  if (!/^\d{6}$/.test(dateKey)) return dateKey;
  const year = dateKey.slice(0, 4);
  const month = parseInt(dateKey.slice(4), 10);
  const names = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
  return `${names[month - 1] ?? month} ${year}`;
}

export function isArabic(text: string): boolean {
  return /[؀-ۿ]/.test(text);
}

/**
 * Splits an answer into text and citation markers so `[S1]` can be rendered as
 * an interactive chip rather than literal brackets. Keeping this in one place
 * means the chat bubble and the trace viewer can never disagree about what
 * counts as a citation.
 */
export function splitCitations(text: string): Array<{ type: "text" | "cite"; value: string }> {
  const parts: Array<{ type: "text" | "cite"; value: string }> = [];
  const pattern = /\[S(\d+)\]/g;
  let last = 0;
  let match: RegExpExecArray | null;
  while ((match = pattern.exec(text)) !== null) {
    if (match.index > last) parts.push({ type: "text", value: text.slice(last, match.index) });
    parts.push({ type: "cite", value: `S${match[1]}` });
    last = match.index + match[0].length;
  }
  if (last < text.length) parts.push({ type: "text", value: text.slice(last) });
  return parts;
}

export const MODE_COLORS: Record<string, string> = {
  Metro: "#2abfb2",
  Bus: "#e6a03c",
  Tram: "#7c9cf5",
  Marine: "#5fd9ce",
};
