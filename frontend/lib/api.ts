import type { AgentDescriptor, AgentEvent, Citation, TurnMeta } from "./types";

/**
 * SSE client for the chat stream.
 *
 * EventSource cannot POST, so this reads the response body directly and parses
 * the SSE frames. That is slightly more work than using EventSource and worth
 * it: the query has to go in a body, not a query string, and the parsing is
 * fifteen lines.
 */

/**
 * Streaming requests go straight to the backend origin, not through the
 * Next.js rewrite. `rewrites()` buffers the response body, which is invisible
 * for JSON and fatal for SSE — the whole stream arrives at once, after the turn
 * has already finished, so nothing ever appears live. CORS on the backend is
 * configured for exactly this.
 *
 * Non-streaming JSON still uses the rewrite (same-origin, no preflight).
 */
const STREAM_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

export interface StreamHandlers {
  onStart?: (payload: { session_id: string; turn_id: string; agents: AgentDescriptor[] }) => void;
  onAgent?: (event: AgentEvent) => void;
  onReplan?: (payload: { cycles: number; gaps: string[]; scores: Record<string, number> }) => void;
  onEvidence?: (sources: Citation[]) => void;
  onToken?: (text: string) => void;
  onDone?: (meta: TurnMeta) => void;
  onError?: (message: string) => void;
}

export async function streamChat(
  query: string,
  sessionId: string | null,
  handlers: StreamHandlers,
  signal?: AbortSignal,
): Promise<void> {
  let response: Response;
  try {
    response = await fetch(`${STREAM_BASE}/api/v1/chat/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query, session_id: sessionId }),
      signal,
    });
  } catch (error) {
    if ((error as Error).name === "AbortError") return;
    handlers.onError?.("Could not reach the Masar backend. Is it running on port 8000?");
    return;
  }

  if (!response.ok || !response.body) {
    handlers.onError?.(`Backend returned ${response.status}.`);
    return;
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      // Normalise line endings before framing. sse_starlette emits CRLF, so
      // splitting on "\n\n" matches nothing and every frame is silently
      // swallowed — a stream that looks perfect on the wire and delivers
      // nothing to the UI.
      buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, "\n");

      // SSE frames are separated by a blank line.
      const frames = buffer.split("\n\n");
      buffer = frames.pop() ?? "";

      for (const frame of frames) {
        let eventName = "message";
        const dataLines: string[] = [];
        for (const line of frame.split("\n")) {
          if (line.startsWith("event:")) eventName = line.slice(6).trim();
          else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
        }
        if (!dataLines.length) continue;

        let payload: unknown;
        try {
          payload = JSON.parse(dataLines.join("\n"));
        } catch {
          continue;
        }

        switch (eventName) {
          case "start":
            handlers.onStart?.(payload as never);
            break;
          case "agent_end":
            handlers.onAgent?.(payload as AgentEvent);
            break;
          case "replan":
            handlers.onReplan?.(payload as never);
            break;
          case "evidence":
            handlers.onEvidence?.((payload as { sources: Citation[] }).sources);
            break;
          case "token":
            handlers.onToken?.((payload as { text: string }).text);
            break;
          case "done":
            handlers.onDone?.(payload as TurnMeta);
            break;
          case "error":
            handlers.onError?.((payload as { message: string }).message);
            break;
        }
      }
    }
  } catch (error) {
    if ((error as Error).name !== "AbortError") {
      handlers.onError?.("The stream ended unexpectedly.");
    }
  }
}

async function getJson<T>(path: string): Promise<T | null> {
  // Hit the backend origin directly (with CORS), NOT the Next.js `/api/*`
  // rewrite. The rewrite targets 127.0.0.1:8000, which exists only in local
  // dev; on the deployed frontend it points at nothing, so every non-streaming
  // call (stats, datasets, map, trace) would silently fail — which is exactly
  // why the Explore/Data pages showed "could not reach the warehouse" in
  // production while the SSE chat (which already used STREAM_BASE) worked.
  try {
    const response = await fetch(`${STREAM_BASE}${path}`, { cache: "no-store" });
    if (!response.ok) return null;
    return (await response.json()) as T;
  } catch {
    return null;
  }
}

export const fetchStats = () => getJson<Record<string, never>>("/api/v1/stats");
export const fetchDatasets = () => getJson<Record<string, never>>("/api/v1/datasets");
export const fetchTrace = (turnId: string) => getJson<Record<string, never>>(`/api/v1/trace/${turnId}`);
export const fetchStations = (mode?: string) =>
  getJson<{ stations: never[] }>(`/api/v1/map/stations${mode ? `?mode=${mode}` : ""}`);
export const fetchHealth = () => getJson<Record<string, never>>("/health/ready");
