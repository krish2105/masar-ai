# Masar AI — Production-Live Design Spec

**Date:** 2026-07-24 · **Status:** approved (design) · **Author:** Krishna Mathur (with Claude)

## 1. Goal

Take Masar AI from *built, evaluated, and UI-only-deployed* to **genuinely live,
end-to-end, and production-hardened** — while keeping the whole thing **$0**.

Today: the frontend is live on Vercel (`masar-ai-xi.vercel.app`) but the backend
is local-only, so chat/analytics/map don't work for a public visitor. This spec
makes the deployed URL fully functional and hardens the system to production
standard.

## 2. Constraints (locked with the owner)

| Constraint | Decision |
|---|---|
| Budget | **Strictly $0 / free-tier.** A card for *verification only* (never charged) is acceptable. |
| LLM | **Free Groq + Gemini** keys (no card), into the existing LiteLLM router. |
| Region / residency | Cheapest global region; data is public RTA open data, no PII. PDPL note stays as "what production would require." |
| Scope | **Full production hardening, no rush** — nothing deferred. |
| Frontend | **Polish to portfolio-grade** as a first-class workstream. |
| Architecture | **Keep the validated local models** (bge-m3 + reranker). No re-architecture that would force re-measuring the earned metrics. |

## 3. Target architecture (end state)

```
 Vercel (frontend, already live)
   masar-ai-xi.vercel.app
   NEXT_PUBLIC_API_BASE ──────────▶  https://<host>  (Caddy, auto-HTTPS)
                                          │
   ┌──────────────────────────────────────┴───────────────────────────┐
   │  Oracle Cloud A1.Flex ARM — 4 OCPU / 24 GB — always-free, no sleep │
   │                                                                    │
   │  Caddy  ─▶ masar-api  (FastAPI + bge-m3 + bge-reranker, UNCHANGED) │
   │  Postgres 16 + pgvector      Redis 7                               │
   │  Neo4j (GraphRAG, Phase 5)                                         │
   │  nightly pg_dump ─▶ Oracle Object Storage (20 GB always-free)      │
   └────────────────────────────────────────────────────────────────────┘
                        │ free keys, into the existing router
                        ▼
              Groq (14,400 req/day) + Gemini (1M TPM / 250 req/day)
```

The existing `docker-compose.yml` runs **unchanged**. Externalised nothing;
Postgres/Redis run on the same VM (24 GB is ample). This is the reason Oracle
was chosen over serverless: **zero re-architecture, every validated number
(0.746 cross-lingual, 6/6 retrieval, 60/60 effective eval) stays true.**

### Free-tier stack (all verified, 2026)

| Component | Provider | Free limit | Card? |
|---|---|---|---|
| Compute | Oracle A1.Flex ARM | 4 OCPU / 24 GB, always-on | verify only |
| Postgres+pgvector | on-VM (docker) | disk-bound (data ~a few hundred MB) | no |
| Redis | on-VM (docker) | — | no |
| LLM | Groq + Gemini | 14,400/day · 1M TPM | no |
| GraphRAG | Neo4j (on-VM or AuraDB Free) | 200K nodes / 400K rels | no |
| TLS/host name | Caddy + DuckDNS/nip.io | — | no |
| Uptime | UptimeRobot | 50 monitors | no |
| Logs | Better Stack / Grafana Cloud free | — | no |
| Backups | Oracle Object Storage | 20 GB always-free | verify only |

## 4. Phased roadmap

### Phase 0 — Provision & secrets
Oracle A1 ARM instance (Ubuntu 22.04), SSH-key-only + hardened, `ufw` + Oracle
security list (open 80/443 only), `fail2ban`. Obtain free Groq + Gemini keys.
**Gate:** `ssh` in, `docker --version` works, keys in a `.env` on the VM.

### Phase 1 — Go live
Docker + compose on the VM; clone repo; `make etl` builds the lakehouse on the
VM (or restore a `pg_dump` from local to save the ~15-min ingest). Caddy
reverse-proxy → automatic HTTPS on a free hostname. Point Vercel
`NEXT_PUBLIC_API_BASE` at the live API; update backend CORS to the Vercel origin.
**Gate:** a public visitor asks a question on `masar-ai-xi.vercel.app` and gets a
cited answer in seconds (Groq), with the agent rail and evidence panel live.

### Phase 2 — Frontend polish & demo-readiness
The deployed URL is now functional — make it portfolio-grade. (Detail in §5.)
**Gate:** Lighthouse ≥ 90 across the board; the site looks intentional on mobile;
a first-time visitor understands what it is in 5 seconds and sees a working
answer without typing.

### Phase 3 — Evaluation completeness
With real keys: run the **RAGAS judged metrics** (faithfulness, relevancy,
context precision — currently `unavailable`), the **4-config ablation study**
(naive → hybrid → rerank → full agentic), and re-tune the grader threshold on
cloud-model evidence (the 80% re-plan rate should drop). Publish the complete
`EVALUATION.md` with the ablation table.
**Gate:** faithfulness ≥ 0.80, relevancy ≥ 0.75, context precision ≥ 0.70 (the
§8.2 thresholds that were unmeasurable locally); ablation table published.

### Phase 4 — Production hardening (ops)
GitHub Actions CI/CD: on merge to `main`, build the image and SSH-deploy to the
VM (health-checked, with rollback). Observability: UptimeRobot on `/health`,
log shipping to Better Stack free, LangSmith tracing enabled. Security-review
pass; edge rate-limiting in Caddy; nightly `pg_dump` → Oracle Object Storage;
secrets via `.env` with restricted perms (or Docker secrets). Define and
document p50/p95 latency + availability SLOs.
**Gate:** a green-to-green deploy runs from a PR merge; `/health` monitored;
a restore-from-backup rehearsed; security-review findings triaged.

### Phase 5 — GraphRAG (capability leap)
Neo4j over route↔stop↔zone (~18K relationships, fits Aura Free / on-VM). A
graph-traversal tool ("routes reachable within 2 interchanges of X") added to
the planner's tool set and A10. New golden questions for multi-hop traversal;
lift measured against the ablation baseline.
**Gate:** a 2-interchange reachability question answers correctly with a graph
citation; measured lift over the SQL-bridge approximation.

### Phase 6 — Cost model, runbooks, docs
A free-tier headroom view (Groq/Gemini/Neon usage vs limits, proving $0).
Runbooks: deploy, rollback, restore, key-rotation, incident. Update
ARCHITECTURE / DEPLOYMENT / GOVERNANCE for the live topology; refresh the README
live badges and the DEMO script for the now-working URL.
**Gate:** every runbook rehearsed once; docs match the live system.

## 5. Frontend polish (Phase 2, expanded)

The current frontend is functional Desert Ink; polish elevates it to the
Awwwards-adjacent, restraint-over-spectacle bar the design brief set, and makes
the live URL convert.

1. **Cold-backend grace.** Oracle is always-on, but the first request after a
   quiet period can be slow. Add a warm-up ping on page load and a tasteful
   "waking the agents…" state so a visitor never sees a dead spinner. Never show
   a raw error on the landing page.
2. **Hero & empty state.** Elevate the landing: a restrained animated headline
   (split-text reveal, reduced-motion safe), a one-line "what this is," and a
   **pre-rendered example answer** (a canned trace + citations) so a visitor
   sees the product working *before typing* — critical when the backend is cold
   or a recruiter is skimming.
3. **The corrective-loop moment.** Make the `A12 → A4 re-plan` amber animation
   the signature interaction — a visible loop-back arrow on the agent rail, a
   one-line "why it re-planned" that expands. This is the single most persuasive
   two seconds; it must be unmissable.
4. **Micro-interactions.** Magnetic send button, citation chips that highlight
   the matching evidence card on hover, smooth streaming-token cursor, staggered
   evidence-card reveals, animated stat counters on `/explore`.
5. **Mobile & responsive.** The split chat/evidence layout must collapse cleanly
   to a single column with the evidence/map as a bottom sheet; the agent rail
   stays visible. Test at 375 px.
6. **Accessibility.** `prefers-reduced-motion` honored on every animation (audit
   all of them), visible focus, ARIA on the live-updating rail, contrast ≥ 4.5:1
   in both themes, Arabic RTL correctness.
7. **Performance.** Lighthouse ≥ 90 (perf/a11y/best-practices/SEO); lazy-load
   MapLibre and Recharts; `next/font` already in place; check CLS on the
   streaming answer.
8. **Shareability.** OG/Twitter meta + a generated social card, a stable favicon,
   a proper `<title>`/description — so a shared link looks deliberate (portfolio).
9. **Trace viewer polish.** The `/trace/[id]` waterfall is the "receipts" page —
   tighten the latency bars, the grader sub-score chips, the re-plan diff, and
   the JSON export. This is what gets screen-recorded.

**Non-goals for polish:** no redesign of the Desert Ink system, no new routes,
no 3D. Restraint over spectacle — motion only where it carries information.

## 6. Success criteria (the whole plan)

- A public visitor gets a **cited, correct answer in seconds** on the live URL.
- **RAGAS thresholds met** (faithfulness ≥ 0.80, relevancy ≥ 0.75, precision ≥ 0.70).
- **Ablation table published** — the research deliverable.
- **CI/CD** deploys from a merge; **uptime monitored**; **backups** rehearsed.
- **GraphRAG** answers a 2-interchange question with measured lift.
- **Lighthouse ≥ 90**; mobile-clean; a11y audited.
- **$0 proven** via the free-tier headroom view.
- Every claim in the docs matches the live system; the honesty rule intact
  (archived-data disclosure, no fabricated live data, RTA non-affiliation).

## 7. Risks & mitigations

| Risk | Mitigation |
|---|---|
| Oracle ARM free capacity scarce in a region | Try multiple regions/ADs; `A1.Flex` with 2 OCPU/12 GB is enough if 4/24 unavailable; script the retry. |
| Free LLM tier exhausted mid-demo | The router's Groq→Gemini→(local on-VM Ollama) fallback chain already handles this; on-VM Ollama is the ultimate backstop since we have 24 GB. |
| Gemini 250 req/day cap | Route only planning/synthesis/Arabic to Gemini; Groq (14,400/day) carries routing+grading. Already the task-class design. |
| VM compromise | SSH-key-only, `ufw`, `fail2ban`, Caddy TLS, read-only DB role for A8 (already built), no secrets in git. |
| Backend cold/slow first hit | Frontend warm-up ping + graceful "waking" state + pre-rendered example answer. |
| Re-plan rate still high on cloud model | Phase 3 re-tunes the threshold with real evidence; documented either way. |

## 8. What this spec deliberately excludes

- Paid hosting, paid LLMs, GPU.
- The Jina/serverless re-architecture (rejected — would force re-validating the
  earned metrics).
- Multi-emirate, voice, forecasting, MCP-server wrapper (README roadmap items —
  future specs, not this one).
- Any change to the Desert Ink design language or the honesty model.
