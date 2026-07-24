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

export type BackendStatus = "checking" | "online" | "warming" | "offline";

/**
 * How many failed pings still count as a plausible cold start. Up to this many,
 * the UI says "waking"; beyond it, the backend is treated as genuinely
 * unreachable and the UI stops implying it is about to come up.
 */
const WARMING_MAX_ATTEMPTS = 2;

/**
 * Pings on mount and distinguishes three failure regimes so the UI can be
 * honest: a plausible cold start ("warming"), and a backend that simply is not
 * there ("offline") — important on the deployed site before the backend is
 * hosted, where "waking the agents" forever would read as a warm-up when it is
 * really an outage. Keeps slow-polling while offline so a later go-live is
 * picked up automatically, without hammering an absent origin.
 */
export function useBackendStatus(): BackendStatus {
  const [status, setStatus] = useState<BackendStatus>("checking");

  useEffect(() => {
    let cancelled = false;
    let attempt = 0;
    let timer: ReturnType<typeof setTimeout>;

    const tick = async () => {
      const ok = await pingHealth(3000);
      if (cancelled) return;
      if (ok) {
        setStatus("online");
        return; // stop polling once reachable
      }
      attempt += 1;
      const warming = attempt <= WARMING_MAX_ATTEMPTS;
      setStatus(warming ? "warming" : "offline");
      // Quick retries while plausibly warming; a slow poll once we conclude the
      // backend is absent, so a Phase-1 go-live still flips the UI to online.
      timer = setTimeout(tick, warming ? 2500 : 20000);
    };

    tick();
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, []);

  return status;
}
