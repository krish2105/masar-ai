"use client";

import { useEffect, useState } from "react";

/**
 * Backend reachability, for a graceful cold start.
 *
 * The production backend runs on an always-on VM, but the very first request
 * after a quiet period can be slow while models warm, and during a redeploy the
 * origin is briefly unreachable. A visitor should never meet a dead spinner or a
 * raw fetch error on the landing page — so we ping the shallow `/health`
 * endpoint (always 200 while the process is alive) and surface an honest,
 * bilingual "waking the agents" state instead.
 */
const BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

export async function pingHealth(timeoutMs = 4000): Promise<boolean> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const res = await fetch(`${BASE}/health`, { signal: controller.signal, cache: "no-store" });
    return res.ok;
  } catch {
    return false;
  } finally {
    clearTimeout(timer);
  }
}

export type BackendStatus = "checking" | "online" | "offline";

/**
 * Pings on mount, then — only while offline — retries with a gentle linear
 * backoff so a backend that is still warming eventually flips the UI to online
 * without the visitor doing anything. Stops polling once online to avoid a
 * needless request every few seconds for the whole session.
 */
export function useBackendStatus(): BackendStatus {
  const [status, setStatus] = useState<BackendStatus>("checking");

  useEffect(() => {
    let cancelled = false;
    let attempt = 0;
    let timer: ReturnType<typeof setTimeout>;

    const tick = async () => {
      const ok = await pingHealth();
      if (cancelled) return;
      if (ok) {
        setStatus("online");
        return; // stop polling once reachable
      }
      attempt += 1;
      setStatus("offline");
      timer = setTimeout(tick, Math.min(2000 + attempt * 1500, 8000));
    };

    tick();
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, []);

  return status;
}
