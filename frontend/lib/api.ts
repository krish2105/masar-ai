import type { AgentDescriptor, AgentEvent, Citation, TurnMeta } from "./types";

/**
 * SSE client for the chat stream.
 *
 * EventSource cannot POST, so this reads the response body directly and parses
 * the SSE frames. That is slightly more work than using EventSource and worth
 * it: the query has to go in a body, not a query string, and the parsing is
 * fifteen lines.
 */

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
    response = await fetch("/api/v1/chat/stream", {
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
      buffer += decoder.decode(value, { stream: true });

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
  try {
    const response = await fetch(path);
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
