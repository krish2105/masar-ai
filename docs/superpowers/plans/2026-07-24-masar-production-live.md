# Masar AI — Production-Live Master Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Take Masar AI from *built + UI-only-deployed* to *fully live, portfolio-polished, and production-hardened* — at $0 — by hosting the existing stack unchanged on an Oracle always-free ARM VM, wiring the live Vercel frontend to it, then completing evaluation, ops, GraphRAG, and docs.

**Architecture:** Oracle Cloud A1.Flex ARM (4 OCPU / 24 GB, always-on) runs the existing `docker-compose.yml` unchanged (Postgres+pgvector, Redis, FastAPI + local bge-m3/reranker). Caddy terminates TLS on a free hostname and reverse-proxies the API. Vercel serves the frontend and points `NEXT_PUBLIC_API_BASE` at the live API. Free Groq + Gemini keys feed the existing LiteLLM router; on-VM Ollama is the ultimate fallback. Nothing about the validated retrieval/eval path changes.

**Tech Stack:** Oracle Cloud (OCI), Ubuntu 22.04 ARM64, Docker + Compose, Caddy 2, FastAPI/LangGraph (existing), Next.js 15 on Vercel (existing), Postgres 16 + pgvector, Redis 7, Neo4j 5 (Phase 5), GitHub Actions, RAGAS.

## Global Constraints

- **Budget: strictly $0.** Free-tier / always-free only. A card for identity verification (never charged) is acceptable; no paid resource may be provisioned.
- **Do not re-architect the validated path.** `docker-compose.yml`, the agents, bge-m3/bge-reranker, and the retrieval pipeline stay as-is. No change may force re-measuring the earned metrics (0.746 cross-lingual, 6/6 retrieval probes, 60/60 effective eval).
- **Honesty model is load-bearing and immutable.** Archived-data disclosure, capture dates on every citation, no fabricated live data, RTA non-affiliation — never weaken any of these.
- **No secrets in git.** All keys live in `.env` on the VM (perms `600`) or GitHub Actions secrets. `.env` stays git-ignored.
- **Design language is fixed.** Desert Ink palette, no redesign, no new routes, no 3D. Motion only where it carries information; every animation honors `prefers-reduced-motion`.
- **Bilingual parity.** Every user-facing string added in Phase 2 ships EN + AR, RTL-correct.
- **Frontend env var name is `NEXT_PUBLIC_API_BASE`** (consumed at `frontend/lib/api.ts:21`). Backend CORS is `settings.cors_origin_list` (`backend/main.py:66`, defined in `backend/config/settings.py`).

---

## File Structure

**New (infra / ops):**
- `deploy/Caddyfile` — TLS + reverse proxy + edge rate-limit
- `deploy/docker-compose.prod.yml` — overlay adding Caddy (+ Neo4j in Phase 5)
- `deploy/provision.md` — the exact OCI console + SSH steps (source of truth for Phase 0)
- `deploy/backup.sh` — nightly pg_dump → Object Storage
- `deploy/restore.md` — restore rehearsal runbook
- `.github/workflows/ci.yml` — lint + test on PR
- `.github/workflows/deploy.yml` — SSH deploy on merge to main
- `docs/RUNBOOKS.md` — deploy / rollback / restore / key-rotation / incident
- `docs/SLO.md` — latency + availability targets

**New (code):**
- `frontend/components/WarmupGate.tsx` — cold-backend warm-up + "waking" state
- `frontend/components/ExampleAnswer.tsx` — pre-rendered demo trace on the hero
- `frontend/lib/health.ts` — health/warm-up client
- `frontend/app/opengraph-image.tsx` — generated social card
- `frontend/data/example-answer.ts` — the canned trace fixture
- `backend/graph_rag/` — Neo4j loader + traversal tool (Phase 5)
- `backend/tests/golden/ablation.py` — 4-config ablation harness

**Modified:**
- `backend/config/settings.py` — CORS origins from env; RAGAS + Neo4j settings
- `backend/main.py` — CORS wiring (already present; verify origins)
- `frontend/app/page.tsx`, `frontend/app/layout.tsx` — hero, warm-up gate, meta
- `frontend/components/AgentRail.tsx`, `ChatMessage.tsx`, `EvidencePanel.tsx` — micro-interactions, re-plan moment, a11y
- `frontend/app/trace/*` — trace viewer polish
- `frontend/app/globals.css` — motion tokens, reduced-motion, focus styles
- `README.md`, `docs/EVALUATION.md`, `docs/DEPLOYMENT.md`, `docs/ARCHITECTURE.md`, `docs/GOVERNANCE.md`

**Testing note:** Frontend uses no test runner today. Phase 2 adds Playwright *only* for the a11y/perf gates (Task 2.7/2.6) where an automated check is the deliverable; visual/interaction tasks are verified in-browser via the preview tools and a screenshot, which is the honest verification for motion work. Backend tasks keep the existing pytest TDD loop.

---

# PHASE 0 — Provision & Secrets

Deliverable: a hardened, reachable Oracle ARM VM with Docker and the LLM keys in place. No app yet.

### Task 0.1: Provision & harden the Oracle A1 ARM VM

**Files:**
- Create: `deploy/provision.md`

**Interfaces:**
- Produces: a VM reachable at `ubuntu@<VM_IP>` over SSH key auth; `docker` and `docker compose` on PATH; ports 80/443 open, everything else closed. `<VM_IP>` is referenced by every later infra task.

- [ ] **Step 1: Write `deploy/provision.md`** capturing the exact steps (this file is the runbook, executed by hand in the OCI console + SSH):

```markdown
# Oracle A1 ARM provisioning (always-free)

1. OCI Console → Compute → Instances → Create.
   - Shape: Ampere A1.Flex. Ask for 4 OCPU / 24 GB. If "out of capacity",
     retry other Availability Domains, then other home regions, then drop to
     2 OCPU / 12 GB (still enough). Script the retry with a loop if needed.
   - Image: Canonical Ubuntu 22.04 (aarch64).
   - Add your SSH *public* key. Boot volume 50 GB (free tier allows 200 GB total).
2. Networking → the instance's VCN security list → Ingress rules:
   - Allow TCP 22 from YOUR IP only (not 0.0.0.0/0).
   - Allow TCP 80 and 443 from 0.0.0.0/0.
   - Remove any other ingress.
3. SSH in: `ssh ubuntu@<VM_IP>`.
4. Host firewall (Oracle images ship iptables locked down — open 80/443):
   sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 80 -j ACCEPT
   sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 443 -j ACCEPT
   sudo netfilter-persistent save
5. Harden:
   sudo apt-get update && sudo apt-get -y install ufw fail2ban
   sudo sed -i 's/^#\?PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config
   sudo sed -i 's/^#\?PermitRootLogin.*/PermitRootLogin no/' /etc/ssh/sshd_config
   sudo systemctl restart ssh
   sudo systemctl enable --now fail2ban
6. Install Docker:
   curl -fsSL https://get.docker.com | sudo sh
   sudo usermod -aG docker ubuntu && newgrp docker
7. Swap (safety on 24 GB is plenty, but add 4 GB for build spikes):
   sudo fallocate -l 4G /swapfile && sudo chmod 600 /swapfile
   sudo mkswap /swapfile && sudo swapon /swapfile
   echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

- [ ] **Step 2: Execute the runbook** in the OCI console + SSH session (manual — this is infrastructure).

- [ ] **Step 3: Verify the gate**

Run (from your laptop): `ssh ubuntu@<VM_IP> 'docker --version && docker compose version && free -h && sudo iptables -L INPUT -n | grep -E "80|443"'`
Expected: Docker ≥ 24 and Compose v2 print; ~24G (or 12G) total memory; ACCEPT rules for 80 and 443 shown.

- [ ] **Step 4: Commit**

```bash
git add deploy/provision.md
git commit -m "docs(deploy): Oracle A1 ARM provisioning + hardening runbook"
```

### Task 0.2: Obtain free LLM keys and stage the VM `.env`

**Files:**
- Modify: `.env.example` (document the two keys if not already present)

**Interfaces:**
- Produces: `/home/ubuntu/masar/.env` on the VM (created in Task 1.1 after clone) will contain `GROQ_API_KEY`, `GEMINI_API_KEY`, and `CORS_ORIGINS`. Keys are obtained now and pasted later.

- [ ] **Step 1: Get the keys (manual, no card).**
  - Groq: console.groq.com → API Keys → create. Free tier ~14,400 req/day.
  - Gemini: aistudio.google.com → Get API key → create in a free project. Free tier 1M TPM / 250 req/day.

- [ ] **Step 2: Confirm `.env.example` documents them.** Ensure these lines exist (add any missing):

```bash
GROQ_API_KEY=
GEMINI_API_KEY=
# Comma-separated allowed browser origins for CORS
CORS_ORIGINS=http://localhost:3000
```

- [ ] **Step 3: Verify the keys work** (from your laptop, so the VM stays clean):

Run: `curl -s https://api.groq.com/openai/v1/models -H "Authorization: Bearer $GROQ_API_KEY" | head -c 200`
Expected: a JSON body listing models (not a 401).

- [ ] **Step 4: Commit** (only if `.env.example` changed)

```bash
git add .env.example
git commit -m "docs(env): document GROQ/GEMINI keys and CORS_ORIGINS"
```

---

# PHASE 1 — Go Live

Deliverable: a public visitor on `masar-ai-xi.vercel.app` gets a cited answer in seconds.

### Task 1.1: Clone the repo and bring up the core stack on the VM

**Files:** none new (uses existing `docker-compose.yml`, `Makefile`).

**Interfaces:**
- Consumes: `<VM_IP>` (Task 0.1), the two keys (Task 0.2).
- Produces: Postgres + Redis + API containers running on the VM; API healthy on `localhost:8000` *inside the VM*.

- [ ] **Step 1: Clone and configure** (SSH on the VM):

```bash
git clone https://github.com/krish2105/masar-ai.git ~/masar && cd ~/masar
cp .env.example .env
# edit .env: paste GROQ_API_KEY, GEMINI_API_KEY,
# set CORS_ORIGINS=https://masar-ai-xi.vercel.app
chmod 600 .env
```

- [ ] **Step 2: Start Postgres + Redis, then the API**

Run: `make up && docker compose up -d api`
(Or `make up-full` to bring the API up in the same step.)

- [ ] **Step 3: Verify the API is healthy inside the VM**

Run: `curl -s localhost:8000/health` (or the path in `backend/api/routes/health.py`)
Expected: `{"status":"ok",...}` (200). If it 500s on missing tables, that's expected until Task 1.2.

- [ ] **Step 4: Commit** — none (no repo change; this is deployment state).

### Task 1.2: Load the lakehouse on the VM (restore, not re-ingest)

**Files:** none new.

**Interfaces:**
- Consumes: running Postgres from Task 1.1.
- Produces: gold star schema + 869 retrieval chunks present in the VM's Postgres, so chat returns real citations.

- [ ] **Step 1: Dump locally** (on your laptop, where the DB is already built):

Run: `docker compose exec -T postgres pg_dump -U masar masar | gzip > masar_gold.sql.gz`
Expected: a multi-MB gzipped dump.

- [ ] **Step 2: Copy to the VM**

Run: `scp masar_gold.sql.gz ubuntu@<VM_IP>:~/masar/`
Expected: transfer completes.

- [ ] **Step 3: Restore on the VM** (SSH):

```bash
cd ~/masar
gunzip -c masar_gold.sql.gz | docker compose exec -T postgres psql -U masar masar
```
Expected: `COPY`/`CREATE` lines, no fatal errors.

- [ ] **Step 4: Verify data is present**

Run: `docker compose exec -T postgres psql -U masar masar -c "select count(*) from chunks;"`
Expected: ~869 (the indexed chunk count). If the embedding index rebuild is needed, run `make index` on the VM instead of restoring — but restore is preferred (no model download, no 15-min ingest).

- [ ] **Step 5: Smoke-test a real answer inside the VM**

Run: `curl -s -X POST localhost:8000/api/v1/chat/stream -H 'content-type: application/json' -d '{"message":"Which fare zone is Union metro station in?","lang":"en"}' | head -c 400`
Expected: an SSE stream with agent events and a cited answer (Groq-fast, a few seconds).

### Task 1.3: Caddy TLS + reverse proxy on a free hostname

**Files:**
- Create: `deploy/Caddyfile`
- Create: `deploy/docker-compose.prod.yml`

**Interfaces:**
- Consumes: API container on the compose network (service name `api`, port 8000).
- Produces: `https://<HOSTNAME>` publicly serving the API with a valid cert. `<HOSTNAME>` is used by Task 1.4.

- [ ] **Step 1: Pick a free hostname.** Use a DuckDNS subdomain (`masar-api.duckdns.org`) pointed at `<VM_IP>`, or `<VM_IP>.nip.io` for zero-signup. Caddy needs a real hostname for a public cert; nip.io works with Caddy's internal CA only, so prefer DuckDNS for a browser-trusted cert.

- [ ] **Step 2: Write `deploy/Caddyfile`**

```
{$MASAR_HOSTNAME} {
	encode zstd gzip

	# SSE must not be buffered — the corrective loop streams events live.
	reverse_proxy api:8000 {
		flush_interval -1
		header_up Host {host}
		header_up X-Real-IP {remote_host}
	}

	header {
		Strict-Transport-Security "max-age=31536000; includeSubDomains"
		X-Content-Type-Options nosniff
		Referrer-Policy strict-origin-when-cross-origin
	}
}
```

- [ ] **Step 3: Write `deploy/docker-compose.prod.yml`** (overlay that adds Caddy to the existing stack):

```yaml
services:
  caddy:
    image: caddy:2
    restart: unless-stopped
    ports:
      - "80:80"
      - "443:443"
    environment:
      MASAR_HOSTNAME: ${MASAR_HOSTNAME}
    volumes:
      - ./deploy/Caddyfile:/etc/caddy/Caddyfile:ro
      - caddy_data:/data
      - caddy_config:/config
    depends_on:
      - api

volumes:
  caddy_data:
  caddy_config:
```

- [ ] **Step 4: Add `MASAR_HOSTNAME` to `.env` on the VM** and launch with the overlay:

```bash
echo "MASAR_HOSTNAME=masar-api.duckdns.org" >> ~/masar/.env
cd ~/masar && docker compose -f docker-compose.yml -f deploy/docker-compose.prod.yml up -d
```

- [ ] **Step 5: Verify public HTTPS**

Run (from your laptop): `curl -s https://masar-api.duckdns.org/health`
Expected: 200 JSON, valid cert (no `-k` needed). Caddy auto-provisions Let's Encrypt on first hit.

- [ ] **Step 6: Commit**

```bash
git add deploy/Caddyfile deploy/docker-compose.prod.yml
git commit -m "feat(deploy): Caddy TLS + SSE-safe reverse proxy overlay"
```

### Task 1.4: Wire Vercel → live API and verify end-to-end

**Files:**
- Modify: `backend/config/settings.py` (confirm `cors_origin_list` reads `CORS_ORIGINS` env; add if missing)

**Interfaces:**
- Consumes: `<HOSTNAME>` (Task 1.3).
- Produces: the live public URL fully functional.

- [ ] **Step 1: Confirm CORS reads env.** In `backend/config/settings.py`, ensure `cors_origin_list` is derived from a `CORS_ORIGINS` env var (comma-split). If it's hardcoded, change it:

```python
# backend/config/settings.py
cors_origins: str = "http://localhost:3000"

@property
def cors_origin_list(self) -> list[str]:
    return [o.strip() for o in self.cors_origins.split(",") if o.strip()]
```

- [ ] **Step 2: Set the Vercel env var** (Vercel dashboard → masar-ai project → Settings → Environment Variables): `NEXT_PUBLIC_API_BASE = https://masar-api.duckdns.org`. Redeploy the frontend (or `vercel --prod`).

- [ ] **Step 3: Verify CORS from the browser origin**

Run: `curl -s -i -X OPTIONS https://masar-api.duckdns.org/api/v1/chat/stream -H "Origin: https://masar-ai-xi.vercel.app" -H "Access-Control-Request-Method: POST" | grep -i access-control`
Expected: `access-control-allow-origin: https://masar-ai-xi.vercel.app`.

- [ ] **Step 4: End-to-end browser verification.** Open `https://masar-ai-xi.vercel.app`, ask "Which metro station is busiest?", and confirm a cited answer streams with the agent rail live. (Use the preview browser tools: navigate, read_console_messages for errors, screenshot for proof.)
Expected: streamed answer + citations + no console CORS errors.

- [ ] **Step 5: Commit**

```bash
git add backend/config/settings.py
git commit -m "feat(api): CORS origins from CORS_ORIGINS env for live frontend"
```

- [ ] **Step 6: Update the deployment memory + docs pointer.** Update `docs/DEPLOYMENT.md` "live status" so the backend row reads live (URL + cert), and update the memory file `masar-deployment.md`.

---

# PHASE 2 — Frontend Polish & Demo-Readiness

Deliverable: the live URL is portfolio-grade; Lighthouse ≥ 90; a first-time visitor sees a working answer without typing.

### Task 2.1: Cold-backend warm-up gate

**Files:**
- Create: `frontend/lib/health.ts`
- Create: `frontend/components/WarmupGate.tsx`
- Modify: `frontend/app/page.tsx`

**Interfaces:**
- Produces: `pingHealth(): Promise<boolean>` and `<WarmupGate>` that renders a "waking the agents…" state until the backend answers `/health`, then reveals children. Never surfaces a raw fetch error.

- [ ] **Step 1: Write `frontend/lib/health.ts`**

```ts
const BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

export async function pingHealth(timeoutMs = 4000): Promise<boolean> {
  const ctrl = new AbortController();
  const t = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const r = await fetch(`${BASE}/health`, { signal: ctrl.signal, cache: "no-store" });
    return r.ok;
  } catch {
    return false;
  } finally {
    clearTimeout(t);
  }
}
```

- [ ] **Step 2: Write `frontend/components/WarmupGate.tsx`** — pings on mount, retries with backoff, shows a calm bilingual "waking" state, reveals children on success. Honor `prefers-reduced-motion` (no pulsing animation when set).

```tsx
"use client";
import { useEffect, useState } from "react";
import { pingHealth } from "@/lib/health";

const COPY = {
  en: { waking: "Waking the agents…", slow: "Still warming up — the models load on first request." },
  ar: { waking: "جارٍ إيقاظ الوكلاء…", slow: "لا يزال قيد التحضير — تُحمّل النماذج عند أول طلب." },
};

export function WarmupGate({ lang = "en", children }: { lang?: "en" | "ar"; children: React.ReactNode }) {
  const [ready, setReady] = useState(false);
  const [slow, setSlow] = useState(false);

  useEffect(() => {
    let cancelled = false;
    let attempt = 0;
    const tick = async () => {
      if (cancelled) return;
      if (await pingHealth()) { setReady(true); return; }
      attempt += 1;
      if (attempt >= 2) setSlow(true);
      setTimeout(tick, Math.min(1000 * attempt, 5000));
    };
    tick();
    return () => { cancelled = true; };
  }, []);

  if (ready) return <>{children}</>;
  const c = COPY[lang];
  return (
    <div role="status" aria-live="polite" className="warmup-gate" dir={lang === "ar" ? "rtl" : "ltr"}>
      <span className="warmup-dot" aria-hidden />
      <p>{c.waking}</p>
      {slow && <p className="warmup-slow">{c.slow}</p>}
    </div>
  );
}
```

- [ ] **Step 3: Add reduced-motion-safe styles** to `frontend/app/globals.css` for `.warmup-gate` / `.warmup-dot` (a gentle pulse; static when `prefers-reduced-motion: reduce`).

- [ ] **Step 4: Gate the chat input** in `frontend/app/page.tsx` — wrap the interactive chat region in `<WarmupGate>` so the input only enables once the backend answers. The hero + example answer (Task 2.2) render *outside* the gate so the page is never blank.

- [ ] **Step 5: Verify in-browser** with the backend deliberately cold (stop the API container, load the page): the "waking" state shows, then on API start the chat reveals. Screenshot both states.
Expected: no raw error, smooth reveal.

- [ ] **Step 6: Commit**

```bash
git add frontend/lib/health.ts frontend/components/WarmupGate.tsx frontend/app/page.tsx frontend/app/globals.css
git commit -m "feat(web): cold-backend warm-up gate with bilingual waking state"
```

### Task 2.2: Hero + pre-rendered example answer

**Files:**
- Create: `frontend/data/example-answer.ts`
- Create: `frontend/components/ExampleAnswer.tsx`
- Modify: `frontend/app/page.tsx`

**Interfaces:**
- Produces: a static, correct example (question → agent trace → cited answer) rendered on the hero so a visitor sees the product working before typing. Content must be a *real* answer captured from the live system (no fabricated numbers).

- [ ] **Step 1: Capture a real trace.** Ask the live system "Which metro station is busiest?" and copy the actual answer text, the agent sequence, and the real citations (with capture dates).

- [ ] **Step 2: Write `frontend/data/example-answer.ts`** as a typed fixture of that captured trace:

```ts
export const EXAMPLE_ANSWER = {
  question: { en: "Which metro station is busiest?", ar: "أي محطة مترو هي الأكثر ازدحاماً؟" },
  agents: ["A1", "A2", "A3", "A4", "A8", "A12", "A13"], // the real path observed
  answer: {
    en: "<paste the real answer text>",
    ar: "<paste the real Arabic answer text>",
  },
  citations: [
    { source: "metro_ridership", captured_at: "<real date>", detail: "<real detail>" },
  ],
} as const;
```

- [ ] **Step 3: Write `frontend/components/ExampleAnswer.tsx`** — renders the fixture in the same visual language as a live answer (agent chips, answer body, citation chips), with a small "Example — try your own below" label so it's never mistaken for live output. Staggered reveal, reduced-motion-safe.

- [ ] **Step 4: Elevate the hero** in `frontend/app/page.tsx`: a restrained split-text headline (CSS-only, reduced-motion-safe), a one-line "what this is," then `<ExampleAnswer>`. This block sits *above* the `<WarmupGate>`-wrapped chat.

- [ ] **Step 5: Verify in-browser** — the hero renders instantly with a working example even while the backend is cold; label is present; AR toggle flips to RTL. Screenshot.

- [ ] **Step 6: Commit**

```bash
git add frontend/data/example-answer.ts frontend/components/ExampleAnswer.tsx frontend/app/page.tsx
git commit -m "feat(web): hero with pre-rendered real example answer"
```

### Task 2.3: The corrective-loop signature interaction

**Files:**
- Modify: `frontend/components/AgentRail.tsx`, `frontend/app/globals.css`

**Interfaces:**
- Consumes: the SSE event stream that already reports A12→A4 re-plan events (`frontend/lib/api.ts`).
- Produces: a visible amber loop-back arrow on the rail when a re-plan fires, plus an expandable one-line "why it re-planned" reason.

- [ ] **Step 1: Detect the re-plan event.** In `AgentRail.tsx`, track when the agent sequence returns to A4 after A12 (a cycle). Add state `replans: {reason: string}[]` populated from the grader event's gap reason.

- [ ] **Step 2: Render the loop-back arrow.** When a re-plan is detected, draw an amber curved arrow from A12 back to A4 with a subtle draw-in animation (SVG stroke-dashoffset), reduced-motion-safe (instant when set). Add `aria-label="Re-planned: <reason>"`.

- [ ] **Step 3: Add the expandable reason.** A one-line amber caption ("Re-planned — coverage gap on <axis>") that expands on click to the grader's named gap.

- [ ] **Step 4: Add styles** to `globals.css` (amber token from Desert Ink, dash-draw keyframes gated behind `@media (prefers-reduced-motion: no-preference)`).

- [ ] **Step 5: Verify in-browser** with a question that triggers a re-plan (grader gap). The amber arrow appears, the reason expands. Screenshot the moment.
Expected: the loop-back is unmissable and explained.

- [ ] **Step 6: Commit**

```bash
git add frontend/components/AgentRail.tsx frontend/app/globals.css
git commit -m "feat(web): signature corrective-loop replan animation on the agent rail"
```

### Task 2.4: Micro-interactions

**Files:**
- Modify: `frontend/components/ChatMessage.tsx`, `frontend/components/EvidencePanel.tsx`, `frontend/app/globals.css`, `frontend/app/explore/*`

**Interfaces:**
- Produces: citation-chip ↔ evidence-card hover linkage, a streaming-token cursor, staggered evidence reveals, animated stat counters on `/explore`. All reduced-motion-safe.

- [ ] **Step 1: Citation ↔ evidence linkage.** Give each citation chip a `data-cite-id` and each evidence card the matching id; on chip hover/focus, add a highlight class to the matching card (and vice-versa). Keyboard-focusable, `aria-describedby` wiring.

- [ ] **Step 2: Streaming cursor.** In `ChatMessage.tsx`, append a blinking caret span while `streaming === true`; remove on completion. Blink only when motion allowed.

- [ ] **Step 3: Staggered evidence reveal.** In `EvidencePanel.tsx`, apply an incremental `transition-delay` per card (CSS custom property `--i`), gated behind `prefers-reduced-motion: no-preference`.

- [ ] **Step 4: Animated stat counters** on `/explore` — count-up on scroll-into-view via IntersectionObserver; show final value immediately when reduced motion is set.

- [ ] **Step 5: Verify in-browser** — hover a citation, confirm the evidence card highlights; watch a stream show the caret; scroll `/explore`. Toggle reduced-motion (resize_window/emulation) and confirm animations disable. Screenshot.

- [ ] **Step 6: Commit**

```bash
git add frontend/components/ChatMessage.tsx frontend/components/EvidencePanel.tsx frontend/app/globals.css frontend/app/explore
git commit -m "feat(web): citation-evidence linkage, streaming cursor, staggered reveals, stat counters"
```

### Task 2.5: Mobile & responsive

**Files:**
- Modify: `frontend/app/page.tsx`, `frontend/components/EvidencePanel.tsx`, `frontend/components/MapPanel.tsx`, `frontend/app/globals.css`

**Interfaces:**
- Produces: the split chat/evidence layout collapses to a single column at ≤ 768 px with the evidence/map as a bottom sheet; the agent rail stays visible.

- [ ] **Step 1: Single-column collapse.** Add a `@media (max-width: 768px)` layout: chat full-width, evidence/map in a slide-up bottom sheet toggled by a "Evidence" button. Agent rail becomes a horizontal strip pinned under the header.

- [ ] **Step 2: Touch targets & map.** Ensure buttons ≥ 44 px; MapPanel gets `touch-action: pan-x pan-y` and a sensible mobile default zoom.

- [ ] **Step 3: Verify at 375 px** with `resize_window({preset: "mobile"})`: no horizontal scroll, bottom sheet opens/closes, rail visible. Screenshot both themes.

- [ ] **Step 4: Commit**

```bash
git add frontend/app/page.tsx frontend/components/EvidencePanel.tsx frontend/components/MapPanel.tsx frontend/app/globals.css
git commit -m "feat(web): mobile single-column layout with evidence bottom sheet"
```

### Task 2.6: Accessibility audit

**Files:**
- Modify: any component with an animation or interactive control; `frontend/app/globals.css`
- Create: `frontend/tests/a11y.spec.ts` (Playwright + axe)

**Interfaces:**
- Produces: zero critical axe violations on `/`, `/explore`, `/data`, `/trace`; every animation behind `prefers-reduced-motion`; visible focus everywhere; contrast ≥ 4.5:1 both themes; RTL correct.

- [ ] **Step 1: Add Playwright + axe** (dev-only): `npm i -D @playwright/test @axe-core/playwright` in `frontend/`.

- [ ] **Step 2: Write the failing a11y test** `frontend/tests/a11y.spec.ts`:

```ts
import { test, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

for (const path of ["/", "/explore", "/data"]) {
  test(`no critical a11y violations on ${path}`, async ({ page }) => {
    await page.goto(path);
    const results = await new AxeBuilder({ page })
      .withTags(["wcag2a", "wcag2aa"]).analyze();
    const critical = results.violations.filter(v => v.impact === "critical" || v.impact === "serious");
    expect(critical, JSON.stringify(critical, null, 2)).toEqual([]);
  });
}
```

- [ ] **Step 3: Run it to see failures**

Run: `cd frontend && npx playwright test tests/a11y.spec.ts`
Expected: FAIL listing real violations (missing labels, contrast, focus).

- [ ] **Step 4: Fix each violation** — ARIA on the live rail (`aria-live="polite"`), `aria-label`s on icon buttons, focus-visible outlines in `globals.css`, contrast fixes on any low-contrast Desert Ink token, `lang`/`dir` on the AR path. Add a global `@media (prefers-reduced-motion: reduce) { *{animation:none!important;transition:none!important} }` backstop.

- [ ] **Step 5: Run until green**

Run: `cd frontend && npx playwright test tests/a11y.spec.ts`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/tests/a11y.spec.ts frontend/package.json frontend/app frontend/components
git commit -m "test(web): axe a11y gate green; reduced-motion + focus + ARIA fixes"
```

### Task 2.7: Performance / Lighthouse ≥ 90

**Files:**
- Modify: `frontend/app/page.tsx`, `frontend/components/MapPanel.tsx`, any Recharts import site

**Interfaces:**
- Produces: Lighthouse ≥ 90 on perf/a11y/best-practices/SEO for the deployed home route.

- [ ] **Step 1: Lazy-load heavy libs.** `dynamic(() => import(...), { ssr: false })` for `MapPanel` (MapLibre) and any Recharts chart; render a lightweight skeleton meanwhile.

- [ ] **Step 2: Guard CLS on the streaming answer.** Reserve min-height on the answer container so streaming tokens don't shift layout.

- [ ] **Step 3: Run Lighthouse** against the deployed URL:

Run: `npx lighthouse https://masar-ai-xi.vercel.app --only-categories=performance,accessibility,best-practices,seo --quiet --chrome-flags="--headless" --output=json --output-path=./lh.json && node -e "const r=require('./frontend/lh.json||'./lh.json');" ` — simplest: `npx lighthouse https://masar-ai-xi.vercel.app --view`.
Expected: all four categories ≥ 90. If perf < 90, inspect the LH opportunities and address the top one (usually unused JS or the map bundle) then re-run.

- [ ] **Step 4: Commit**

```bash
git add frontend/app/page.tsx frontend/components/MapPanel.tsx
git commit -m "perf(web): lazy-load map/charts, reserve streaming height; Lighthouse >= 90"
```

### Task 2.8: Shareability — OG image + meta + favicon

**Files:**
- Create: `frontend/app/opengraph-image.tsx`
- Modify: `frontend/app/layout.tsx`

**Interfaces:**
- Produces: a generated 1200×630 OG card, Twitter meta, stable favicon, proper title/description — so a shared link looks deliberate.

- [ ] **Step 1: Write `frontend/app/opengraph-image.tsx`** using `next/og` `ImageResponse` in the Desert Ink palette (title مسار · MASAR AI, the one-liner, no external assets):

```tsx
import { ImageResponse } from "next/og";
export const runtime = "edge";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";
export default function OG() {
  return new ImageResponse(
    (
      <div style={{ height: "100%", width: "100%", display: "flex", flexDirection: "column",
        justifyContent: "center", padding: 80, background: "#1a1712", color: "#f3ead9" }}>
        <div style={{ fontSize: 72, fontWeight: 700 }}>مسار · MASAR AI</div>
        <div style={{ fontSize: 32, marginTop: 16, color: "#2ABFB2" }}>
          Dubai Mobility Decision Intelligence — Agentic RAG over RTA open data
        </div>
      </div>
    ), { ...size }
  );
}
```

- [ ] **Step 2: Complete `metadata`** in `layout.tsx` — add `openGraph`, `twitter: { card: "summary_large_image" }`, `metadataBase`, and confirm favicon (`app/icon.png` or existing).

- [ ] **Step 3: Verify** the OG route renders:

Run: navigate to `https://masar-ai-xi.vercel.app/opengraph-image` in the preview browser.
Expected: the card image renders. Also confirm `<meta property="og:image">` is present via read_page/get_page_text on `/`.

- [ ] **Step 4: Commit**

```bash
git add frontend/app/opengraph-image.tsx frontend/app/layout.tsx
git commit -m "feat(web): OG/Twitter social card + complete share meta"
```

### Task 2.9: Trace viewer polish

**Files:**
- Modify: `frontend/app/trace/*`

**Interfaces:**
- Produces: a tightened `/trace/[id]` waterfall — latency bars, grader sub-score chips, the re-plan diff, JSON export.

- [ ] **Step 1: Latency waterfall.** Render each agent hop as a proportional horizontal bar (duration from the trace payload), aligned on a shared time axis, with the total at the top.

- [ ] **Step 2: Grader sub-score chips.** Show each `AxisScore` (value + detail + applicable) as a chip; render abstained axes (`applicable=false`) muted with an "n/a" tag so the abstention design is visible.

- [ ] **Step 3: Re-plan diff.** When a cycle occurred, show plan-v1 → plan-v2 with the changed steps highlighted.

- [ ] **Step 4: JSON export.** A "Download trace JSON" button (client-side blob) for screen-recording/receipts.

- [ ] **Step 5: Verify in-browser** on a real trace id (one that re-planned). Screenshot the waterfall + sub-score chips.

- [ ] **Step 6: Commit**

```bash
git add frontend/app/trace
git commit -m "feat(web): trace viewer — latency waterfall, grader chips, replan diff, JSON export"
```

---

# PHASE 3 — Evaluation Completeness

Deliverable: RAGAS judged metrics + a 4-config ablation table, published, with the grader threshold re-tuned on cloud evidence.

### Task 3.1: RAGAS judged metrics with cloud keys

**Files:**
- Modify: `backend/tests/golden/run_eval.py`, `backend/config/settings.py`

**Interfaces:**
- Consumes: `GEMINI_API_KEY` (RAGAS judge model).
- Produces: `run_eval.py` emits faithfulness, answer-relevancy, context-precision into the eval report when `--ragas` is passed.

- [ ] **Step 1: Add a `--ragas` flag** to the argparse in `run_eval.py` and a settings field `ragas_judge_model` (default a free Gemini model). Wire RAGAS to use the Gemini judge + the local bge-m3 embeddings (already installed) so no paid embedding call is made.

- [ ] **Step 2: Compute the three metrics** per question from `(question, answer, retrieved_contexts, ground_truth)` already assembled in the runner; aggregate mean per metric and per language.

- [ ] **Step 3: Run on a small slice first**

Run: `make eval` equivalent with `python -m backend.tests.golden.run_eval --limit 5 --ragas`
Expected: prints faithfulness/relevancy/precision for 5 questions, no auth errors.

- [ ] **Step 4: Run the full set**

Run: `python -m backend.tests.golden.run_eval --ragas`
Expected: aggregate faithfulness ≥ 0.80, relevancy ≥ 0.75, context precision ≥ 0.70. If a metric misses, record the failing questions for Task 3.3.

- [ ] **Step 5: Commit**

```bash
git add backend/tests/golden/run_eval.py backend/config/settings.py
git commit -m "feat(eval): RAGAS faithfulness/relevancy/precision via free Gemini judge"
```

### Task 3.2: Four-config ablation study

**Files:**
- Create: `backend/tests/golden/ablation.py`
- Modify: `Makefile` (the `ablation` target already exists — point it at this)

**Interfaces:**
- Consumes: the retrieval + graph entry points.
- Produces: a table comparing naive (dense-only, no rerank, single-pass) → hybrid (dense+FTS+RRF) → hybrid+rerank → full agentic (with corrective loop) on the golden set: answer accuracy, citation validity, context precision, p50 latency.

- [ ] **Step 1: Write `backend/tests/golden/ablation.py`** that runs the golden set under four retrieval/orchestration configs by toggling flags on the existing pipeline (no new retrieval code — just disable rerank / disable FTS fusion / disable the corrective loop). Emit a markdown table.

```python
CONFIGS = [
    ("naive",         {"fts": False, "rerank": False, "agentic": False}),
    ("hybrid",        {"fts": True,  "rerank": False, "agentic": False}),
    ("hybrid+rerank", {"fts": True,  "rerank": True,  "agentic": False}),
    ("full agentic",  {"fts": True,  "rerank": True,  "agentic": True}),
]
```

- [ ] **Step 2: Point the Makefile `ablation` target** at `python -m backend.tests.golden.ablation` and confirm it writes into `docs/EVALUATION.md` (or a table file the doc includes).

- [ ] **Step 3: Run it**

Run: `make ablation`
Expected: a 4-row table where accuracy/precision improve monotonically (or the exceptions are noted). Full agentic should lead on accuracy; note its latency cost honestly.

- [ ] **Step 4: Commit**

```bash
git add backend/tests/golden/ablation.py Makefile docs/EVALUATION.md
git commit -m "feat(eval): four-config ablation harness + published table"
```

### Task 3.3: Re-tune the grader threshold on cloud evidence

**Files:**
- Modify: `backend/agents/a12_grader.py` (threshold only — not the AxisScore logic)

**Interfaces:**
- Consumes: the RAGAS + re-plan-rate data from Task 3.1.
- Produces: a re-plan rate materially below the local-model 80%, with no regression in citation validity or numeric accuracy.

- [ ] **Step 1: Write the failing test** `backend/tests/unit/test_a12_replan_rate.py` asserting that on the golden set with cloud models the re-plan rate is < 0.40 (sane target) — it will fail at the current threshold.

- [ ] **Step 2: Run it to confirm the current rate**

Run: `pytest backend/tests/unit/test_a12_replan_rate.py -v`
Expected: FAIL showing the actual (high) rate.

- [ ] **Step 3: Adjust the sufficiency threshold** in `a12_grader.py` guided by the RAGAS faithfulness distribution (raise the bar for "insufficient" so genuinely-good answers stop looping), keeping the abstention (`applicable=False`) logic untouched.

- [ ] **Step 4: Run the unit test + the full eval to confirm no regression**

Run: `pytest backend/tests/unit/test_a12_replan_rate.py -v && python -m backend.tests.golden.run_eval --ragas`
Expected: re-plan test PASS; citation validity 1.00 and numeric accuracy 1.00 unchanged.

- [ ] **Step 5: Commit**

```bash
git add backend/agents/a12_grader.py backend/tests/unit/test_a12_replan_rate.py
git commit -m "fix(grader): re-tune sufficiency threshold on cloud-model evidence"
```

### Task 3.4: Publish the complete EVALUATION.md

**Files:**
- Modify: `docs/EVALUATION.md`, `README.md`

**Interfaces:**
- Produces: the eval doc updated with RAGAS numbers, the ablation table, the new re-plan rate, and the honest caveats.

- [ ] **Step 1: Update `docs/EVALUATION.md`** — replace the `unavailable` RAGAS rows with real numbers, insert the ablation table, note the cloud-vs-local re-plan-rate delta, keep the EN/AR parity section.

- [ ] **Step 2: Update the README eval row** to cite the RAGAS + ablation results and link the doc.

- [ ] **Step 3: Verify** the doc renders (no broken table) and numbers match the runner output.

- [ ] **Step 4: Commit**

```bash
git add docs/EVALUATION.md README.md
git commit -m "docs(eval): publish RAGAS metrics + ablation table + re-plan rate"
```

---

# PHASE 4 — Production Hardening (Ops)

Deliverable: CI/CD from a PR merge, monitored uptime, shipped logs, rate-limiting, rehearsed backups, documented SLOs.

### Task 4.1: CI — lint + test on every PR

**Files:**
- Create: `.github/workflows/ci.yml`

**Interfaces:**
- Produces: a required PR check running `make lint` + `make test` (backend) and `npm run build` (frontend).

- [ ] **Step 1: Write `.github/workflows/ci.yml`**

```yaml
name: ci
on: { pull_request: { branches: [main] } }
jobs:
  backend:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: pgvector/pgvector:pg16
        env: { POSTGRES_USER: masar, POSTGRES_PASSWORD: masar, POSTGRES_DB: masar }
        ports: ["5432:5432"]
        options: >-
          --health-cmd "pg_isready -U masar" --health-interval 5s --health-retries 10
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.13" }
      - run: pip install -e ".[dev]" || pip install -r requirements.txt
      - run: make lint
      - run: make test
  frontend:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with: { node-version: "20", cache: "npm", cache-dependency-path: frontend/package-lock.json }
      - run: cd frontend && npm ci && npm run build
```

- [ ] **Step 2: Open a throwaway PR** to confirm the workflow runs and both jobs pass (fix any env assumptions — e.g. tests needing a DB URL point at the `postgres` service).

- [ ] **Step 3: Commit** (on a branch, via the PR)

```bash
git add .github/workflows/ci.yml
git commit -m "ci: lint + test (backend) and build (frontend) on PRs"
```

### Task 4.2: CD — SSH deploy on merge to main, health-checked with rollback

**Files:**
- Create: `.github/workflows/deploy.yml`
- Create: `deploy/deploy.sh` (runs on the VM)

**Interfaces:**
- Consumes: GitHub secrets `VM_SSH_KEY`, `VM_HOST`, `VM_USER`.
- Produces: a merge to main pulls + rebuilds + health-checks on the VM, rolling back to the previous image on failure.

- [ ] **Step 1: Write `deploy/deploy.sh`** (idempotent, health-gated):

```bash
#!/usr/bin/env bash
set -euo pipefail
cd ~/masar
PREV=$(git rev-parse HEAD)
git fetch origin main && git reset --hard origin/main
docker compose -f docker-compose.yml -f deploy/docker-compose.prod.yml up -d --build
for i in $(seq 1 30); do
  if curl -fsS localhost:8000/health >/dev/null; then echo "healthy"; exit 0; fi
  sleep 2
done
echo "UNHEALTHY — rolling back to $PREV"
git reset --hard "$PREV"
docker compose -f docker-compose.yml -f deploy/docker-compose.prod.yml up -d --build
exit 1
```

- [ ] **Step 2: Write `.github/workflows/deploy.yml`**

```yaml
name: deploy
on: { push: { branches: [main] } }
concurrency: { group: deploy, cancel-in-progress: false }
jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: webfactory/ssh-agent@v0.9.0
        with: { ssh-private-key: ${{ secrets.VM_SSH_KEY }} }
      - run: ssh -o StrictHostKeyChecking=accept-new ${{ secrets.VM_USER }}@${{ secrets.VM_HOST }} 'bash ~/masar/deploy/deploy.sh'
```

- [ ] **Step 3: Add the three secrets** in the GitHub repo settings; add the deploy key's public half to the VM's `~/.ssh/authorized_keys`.

- [ ] **Step 4: Verify** a trivial merge triggers a green deploy and the live `/health` still returns 200 after. Confirm rollback by temporarily pushing a broken health check on a branch and watching it revert (then revert the test).

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/deploy.yml deploy/deploy.sh
git commit -m "ci: health-gated SSH deploy with rollback on merge to main"
```

### Task 4.3: Observability — uptime, logs, tracing

**Files:**
- Modify: `backend/config/settings.py` (LangSmith envs), `docs/RUNBOOKS.md` (create)

**Interfaces:**
- Produces: UptimeRobot monitoring `/health`; container logs shipped to Better Stack free; LangSmith tracing on when its key is present.

- [ ] **Step 1: UptimeRobot** — add an HTTP(s) monitor on `https://<HOSTNAME>/health`, 5-min interval, email alert. (Manual; record it in RUNBOOKS.)

- [ ] **Step 2: Log shipping** — add the Better Stack (Logtail) Docker logging driver or Vector sidecar in `deploy/docker-compose.prod.yml` for the `api` service, keyed by a `LOGTAIL_TOKEN` env. Keep it optional (no token → local logs only).

- [ ] **Step 3: LangSmith tracing** — ensure the existing LiteLLM/LangGraph tracing envs (`LANGCHAIN_TRACING_V2`, `LANGCHAIN_API_KEY`) are read from settings and no-op when absent.

- [ ] **Step 4: Verify** — kill the API container and confirm an UptimeRobot alert fires; confirm a log line appears in Better Stack; confirm a trace appears in LangSmith for one live query.

- [ ] **Step 5: Commit**

```bash
git add deploy/docker-compose.prod.yml backend/config/settings.py docs/RUNBOOKS.md
git commit -m "feat(ops): uptime monitor + log shipping + optional LangSmith tracing"
```

### Task 4.4: Edge rate-limiting + security-review pass

**Files:**
- Modify: `deploy/Caddyfile`

**Interfaces:**
- Produces: per-IP rate limiting at the edge; a triaged security-review checklist.

- [ ] **Step 1: Add rate-limiting** to the Caddyfile (Caddy `rate_limit` via the `caddy-ratelimit` plugin image, or a simple `@post` matcher with a request cap). Cap the chat endpoint (e.g. 20 req/min/IP) to protect the free LLM budget.

- [ ] **Step 2: Run a security-review pass** over the delta (Caddyfile, compose overlay, deploy scripts, CORS, the read-only DB role for A8). Confirm: no secrets in git, `.env` perms 600, SSH key-only, DB role read-only, HSTS + security headers present, no debug endpoints exposed publicly.

- [ ] **Step 3: Verify rate-limit** — hammer the endpoint past the cap and confirm 429s; confirm normal use is unaffected.

- [ ] **Step 4: Commit**

```bash
git add deploy/Caddyfile
git commit -m "feat(deploy): edge rate-limit on chat endpoint; security-review pass"
```

### Task 4.5: Nightly backups → Object Storage + restore rehearsal

**Files:**
- Create: `deploy/backup.sh`, `deploy/restore.md`

**Interfaces:**
- Produces: a nightly `pg_dump` uploaded to Oracle Object Storage (20 GB always-free), and a rehearsed restore.

- [ ] **Step 1: Write `deploy/backup.sh`**

```bash
#!/usr/bin/env bash
set -euo pipefail
cd ~/masar
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
FILE="masar_${STAMP}.sql.gz"
docker compose exec -T postgres pg_dump -U masar masar | gzip > "/tmp/${FILE}"
oci os object put -bn masar-backups --file "/tmp/${FILE}" --name "${FILE}" --force
find /tmp -name 'masar_*.sql.gz' -mtime +2 -delete
```

- [ ] **Step 2: Install + configure the OCI CLI** on the VM (`oci setup config`, using an API key from the always-free tenancy) and create the `masar-backups` bucket. Add a cron entry: `0 3 * * * /home/ubuntu/masar/deploy/backup.sh`.

- [ ] **Step 3: Write `deploy/restore.md`** — the exact steps to pull the latest object and `psql` it into a fresh DB.

- [ ] **Step 4: Rehearse the restore** into a scratch database on the VM and confirm `select count(*) from chunks;` matches production. Record the outcome in `restore.md`.

- [ ] **Step 5: Commit**

```bash
git add deploy/backup.sh deploy/restore.md
git commit -m "feat(ops): nightly pg_dump to Object Storage + rehearsed restore"
```

### Task 4.6: Define and document SLOs

**Files:**
- Create: `docs/SLO.md`

**Interfaces:**
- Produces: written latency (p50/p95) and availability targets tied to the monitoring in 4.3.

- [ ] **Step 1: Write `docs/SLO.md`** — availability target (e.g. 99% monthly, measured by UptimeRobot), latency targets split by path class (Groq-fast Text-to-SQL p50, corrective-loop p95), and the error budget + what triggers a rollback. Ground the numbers in the real observed live latencies, not aspirations.

- [ ] **Step 2: Verify** the targets match what monitoring actually shows for a day.

- [ ] **Step 3: Commit**

```bash
git add docs/SLO.md
git commit -m "docs(ops): latency + availability SLOs with error budget"
```

---

# PHASE 5 — GraphRAG (Capability Leap)

Deliverable: a 2-interchange reachability question answers correctly with a graph citation, with measured lift over the SQL-bridge approximation.

### Task 5.1: Neo4j service + graph load from gold

**Files:**
- Create: `backend/graph_rag/__init__.py`, `backend/graph_rag/loader.py`
- Modify: `deploy/docker-compose.prod.yml` (add Neo4j; or use Aura Free)
- Modify: `backend/config/settings.py` (Neo4j URI/creds)

**Interfaces:**
- Produces: a Neo4j graph of `(:Station)-[:SERVED_BY]->(:Route)`, `(:Station)-[:IN_ZONE]->(:Zone)`, `(:Station)-[:INTERCHANGE]->(:Station)` loaded from the gold star schema. Loader entry: `load_graph(pg_dsn, neo4j_driver) -> dict[str,int]` returning node/rel counts.

- [ ] **Step 1: Add Neo4j** to the prod compose overlay (community image, on-VM — 24 GB has room), or provision Aura Free. Add `NEO4J_URI/USER/PASSWORD` to settings.

- [ ] **Step 2: Write the failing test** `backend/tests/unit/test_graph_loader.py` — against a test Neo4j (or a mock), assert `load_graph` creates the expected node labels and that a known interchange (e.g. Union) has degree ≥ 2.

- [ ] **Step 3: Run it to fail**

Run: `pytest backend/tests/unit/test_graph_loader.py -v`
Expected: FAIL (loader not implemented).

- [ ] **Step 4: Implement `loader.py`** — read stations/routes/zones/edges from Postgres, MERGE nodes + relationships into Neo4j in batches.

- [ ] **Step 5: Run until green + load for real**

Run: `pytest backend/tests/unit/test_graph_loader.py -v` then a one-off `python -m backend.graph_rag.loader`
Expected: PASS; ~thousands of nodes, ~18K relationships loaded.

- [ ] **Step 6: Commit**

```bash
git add backend/graph_rag backend/tests/unit/test_graph_loader.py backend/config/settings.py deploy/docker-compose.prod.yml
git commit -m "feat(graphrag): Neo4j service + gold->graph loader"
```

### Task 5.2: Graph-traversal tool

**Files:**
- Create: `backend/graph_rag/traversal.py`, `backend/tests/unit/test_graph_traversal.py`

**Interfaces:**
- Produces: `reachable_within(station: str, interchanges: int) -> list[Reachable]` where `Reachable` has `station`, `routes`, `hops`. Deterministic, cited by graph path.

- [ ] **Step 1: Write the failing test** — from a known station, `reachable_within(x, 2)` returns a known reachable station with the correct hop count and does *not* return an unreachable one.

- [ ] **Step 2: Run to fail**

Run: `pytest backend/tests/unit/test_graph_traversal.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement `traversal.py`** — a bounded Cypher variable-length path query, returning typed results with the path for citation.

- [ ] **Step 4: Run until green**

Run: `pytest backend/tests/unit/test_graph_traversal.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/graph_rag/traversal.py backend/tests/unit/test_graph_traversal.py
git commit -m "feat(graphrag): bounded reachability traversal with cited paths"
```

### Task 5.3: Wire the graph tool into the planner + A10

**Files:**
- Modify: `backend/agents/a4_supervisor.py` (tool registry), `backend/agents/a10_*.py` (geospatial agent)

**Interfaces:**
- Consumes: `reachable_within` (Task 5.2).
- Produces: the Supervisor can route multi-hop reachability questions to the graph tool; A10 invokes it and returns graph-cited evidence.

- [ ] **Step 1: Write the failing test** `backend/tests/unit/test_graph_tool_routing.py` — a reachability question ("which stations are within 2 interchanges of Union?") routes to the graph tool and produces evidence with a graph citation.

- [ ] **Step 2: Run to fail**

Run: `pytest backend/tests/unit/test_graph_tool_routing.py -v`
Expected: FAIL.

- [ ] **Step 3: Register the tool** in the Supervisor's tool set and call it from A10; format results as evidence with `source="graph"` and the path as the citation detail.

- [ ] **Step 4: Run until green**

Run: `pytest backend/tests/unit/test_graph_tool_routing.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/agents/a4_supervisor.py backend/agents/a10_*.py backend/tests/unit/test_graph_tool_routing.py
git commit -m "feat(graphrag): route multi-hop reachability to the graph tool via A10"
```

### Task 5.4: Golden multi-hop questions + lift measurement

**Files:**
- Modify: `questions.yaml`, `docs/EVALUATION.md`

**Interfaces:**
- Produces: new golden questions for multi-hop traversal and a measured lift of the graph tool over the prior SQL-bridge approximation.

- [ ] **Step 1: Add 5–8 multi-hop questions** to `questions.yaml` with reference answers derived from the graph (verified by hand).

- [ ] **Step 2: Run the eval on just those** with graph on vs off

Run: `python -m backend.tests.golden.run_eval --intent reachability` (graph on), then temporarily disable and re-run.
Expected: accuracy higher with the graph tool; capture both numbers.

- [ ] **Step 3: Publish the lift** in `docs/EVALUATION.md` (a small before/after table).

- [ ] **Step 4: Commit**

```bash
git add questions.yaml docs/EVALUATION.md
git commit -m "eval(graphrag): multi-hop golden questions + measured lift"
```

---

# PHASE 6 — Cost Model, Runbooks, Docs

Deliverable: $0 proven; every runbook rehearsed; docs match the live system.

### Task 6.1: Free-tier headroom view

**Files:**
- Create: `frontend/app/data/costs section` (extend existing `/data`) or a small card component
- Modify: `backend/api/routes/*` (a `/api/v1/usage` endpoint reading the router's token-bucket counters)

**Interfaces:**
- Produces: a live view of Groq/Gemini request counts vs their free limits, proving the system runs within $0.

- [ ] **Step 1: Write the failing test** for a `/api/v1/usage` endpoint that returns `{groq: {used, limit}, gemini: {used, limit}}` from the existing Redis token buckets.

- [ ] **Step 2: Run to fail, implement, run to pass** (standard TDD loop against the route).

- [ ] **Step 3: Render the headroom card** on `/data` — progress bars vs limits, with a "$0 inference cost" statement tied to real counters (not a static badge).

- [ ] **Step 4: Verify** the numbers move after a few live queries.

- [ ] **Step 5: Commit**

```bash
git add backend/api/routes frontend/app/data backend/tests
git commit -m "feat: free-tier usage endpoint + headroom view proving $0"
```

### Task 6.2: Runbooks

**Files:**
- Modify: `docs/RUNBOOKS.md`

**Interfaces:**
- Produces: rehearsed runbooks for deploy, rollback, restore, key-rotation, incident.

- [ ] **Step 1: Write each runbook** as numbered, copy-pasteable steps referencing the real scripts (`deploy/deploy.sh`, `deploy/backup.sh`, `deploy/restore.md`). Key-rotation: how to swap a leaked Groq/Gemini key with zero downtime. Incident: the "backend down" path (UptimeRobot alert → SSH → `docker compose ps` → restart/rollback).

- [ ] **Step 2: Rehearse each once** on the live VM and note the actual outcome/time in the doc.

- [ ] **Step 3: Commit**

```bash
git add docs/RUNBOOKS.md
git commit -m "docs(ops): rehearsed deploy/rollback/restore/key-rotation/incident runbooks"
```

### Task 6.3: Docs + README refresh for the live topology

**Files:**
- Modify: `README.md`, `docs/DEPLOYMENT.md`, `docs/ARCHITECTURE.md`, `docs/GOVERNANCE.md`

**Interfaces:**
- Produces: docs that match the live system; README live badges refreshed; the honesty model intact and the "backend is local-only" caveat replaced with the live truth.

- [ ] **Step 1: Update the README** — the live-link caveat block (lines ~18–21) now says the backend is live; add the GraphRAG capability to the feature table; refresh the eval row with RAGAS/ablation.

- [ ] **Step 2: Update `DEPLOYMENT.md`** to the Oracle-VM topology (the diagram from the spec), and `ARCHITECTURE.md` to add the graph tool. Confirm `GOVERNANCE.md` still leads with the archived-data disclosure.

- [ ] **Step 3: Verify** every claim against the running system (each link resolves, each number matches a runner output).

- [ ] **Step 4: Commit**

```bash
git add README.md docs/DEPLOYMENT.md docs/ARCHITECTURE.md docs/GOVERNANCE.md
git commit -m "docs: refresh for live Oracle-VM topology + GraphRAG; honest caveats intact"
```

---

## Self-Review (completed)

- **Spec coverage:** every §4 phase (0–6) and every §5 frontend-polish item (1–9) maps to a task — cold-backend grace → 2.1, hero/example → 2.2, corrective-loop moment → 2.3, micro-interactions → 2.4, mobile → 2.5, a11y → 2.6, perf → 2.7, shareability → 2.8, trace polish → 2.9. §6 success criteria and §7 risks are all addressed (RAGAS 3.1/3.4, ablation 3.2, CI/CD 4.1/4.2, uptime/backup 4.3/4.5, GraphRAG 5.x, Lighthouse 2.7, $0 proof 6.1, honesty preserved throughout).
- **Placeholder scan:** the only literal `<...>` tokens are deliberate fill-ins that must be captured from the real live system (VM IP, hostname, real answer text, real citation dates) — these are *instructions to capture real values*, never fabricated content, per the honesty constraint. All code steps carry runnable code.
- **Type consistency:** `pingHealth`, `WarmupGate`, `EXAMPLE_ANSWER`, `load_graph`, `reachable_within`/`Reachable`, `/api/v1/usage` shape, and the `CONFIGS` ablation flags are named identically wherever referenced.

---

## Execution Handoff

Phases are strictly ordered (0 → 6); within a phase, tasks are mostly sequential (Phase 2 polish tasks can parallelize after 2.1). Recommend executing one phase at a time with a review checkpoint at each phase boundary, since Phases 0/1/4/5 involve real infrastructure and secrets that a human must drive.
