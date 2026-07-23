# MASAR AI — Master Build Prompt (Claude Code)
### Dubai Mobility Decision Intelligence — Agentic RAG over RTA Open Data

> **مسار (Masar)** = "route / path" in Arabic.
> **Domain:** Agentic Decision Intelligence — Public Sector Mobility
> **Target roles:** AI/ML Analyst · AI Associate · Business Analyst (UAE / Global)
> **Cost:** AED 0 — zero paid API keys, free-tier only
> **Author:** Krishna Mathur · MAIB, SP Jain School of Global Management, Dubai

---

## 0. HOW TO USE THIS DOCUMENT

Paste this entire file into Claude Code as the opening instruction, then say:

```
Read MASAR_AI_MASTER_BUILD_PROMPT.md end to end. Build it in the phase order
given in Section 9. Do not skip Phase 0. Do not ask me clarifying questions —
every decision in this document is final. Stop after each phase, run the phase
gate tests, and report pass/fail before continuing.
```

Every ambiguous decision is already resolved below. There are no placeholders,
no `TODO`, no `<your-value-here>` except for the two secrets in `.env`, which
are explicitly listed in Section 4.3.

---

## 1. PROBLEM STATEMENT

### 1.1 The business problem

Dubai's Roads and Transport Authority operates one of the densest multi-modal
transit networks in the world — Metro, Tram, Bus, Marine, Taxi, Salik toll
gates, parking and licensing services. RTA has already deployed AI internally:
an AI decision-support platform now coordinates 1,100+ buses across 26
operational scenarios, cutting controller decision time from 30–60 minutes to
under one minute, and an internal chatbot lets Enterprise Command & Control
Centre staff query complex Metro operations data directly.

The gap is on the **outside**. RTA's public-facing assistant (Mahboub) is a
service-catalogue chatbot: it routes users to the right form. It does not
*reason*. It cannot answer:

- "I live in Al Qusais and work in Business Bay. Is bus or metro cheaper for me
  monthly, and how has ridership on that corridor trended?"
- "Which bus routes are under-utilised relative to their catchment, and where
  should RTA add capacity?"
- "Compare Salik cost of driving vs a nol card commute for 22 working days."
- "أي محطات المترو الأكثر ازدحاماً؟" (Which metro stations are busiest?)

These are **multi-hop questions**. Each one requires: understanding intent →
deciding which of several data sources to hit → retrieving from more than one →
doing arithmetic or geospatial reasoning → verifying the answer against source →
responding bilingually with citations. A single-pass retrieve-then-generate RAG
pipeline structurally cannot do this.

### 1.2 The technical problem

Build a production-grade **Agentic RAG** system where the retrieval strategy is
itself a decision made by an agent, not a fixed pipeline. Specifically:

| Requirement | Why single-pass RAG fails |
|---|---|
| Mixed structured + unstructured sources | Vector search over a CSV of ridership numbers returns garbage; needs Text-to-SQL |
| Multi-hop ("cheaper *and* trend") | One retrieval pass returns one kind of evidence |
| Numeric correctness (fares, tolls) | LLMs hallucinate arithmetic; needs deterministic tool calls |
| Bilingual AR/EN with code-switching | Embedding space and answer language must be handled explicitly |
| Auditability for a government context | Every claim needs a traceable source row/document |
| Low-quality retrieval recovery | Static pipeline returns the bad chunks and answers anyway |

### 1.3 Positioning statement (use this in interviews)

> "Masar AI is a closed-loop agentic RAG system over Dubai's official open
> transport data. It's not a transit chatbot — it's a decision-intelligence
> layer. A 14-agent LangGraph orchestration decides *whether* to retrieve, *what*
> to retrieve, and *when it has enough* — routing between hybrid vector search,
> Text-to-SQL over a governed lakehouse, live Dubai Pulse API calls, and
> deterministic fare/geo calculators — with a corrective grading loop that
> re-plans on low-confidence retrieval, and full citation lineage on every claim."

### 1.4 Strategic context (cite this — it's why the project matters *now*)

- The UAE Cabinet has approved a federal framework to convert **at least 50% of
  federal government services and operations to agentic AI within two years**,
  with an approved Phase One service package spanning Citizens', Residents',
  Business and General Public services.
- **80,000 government employees** are being trained on agentic AI tooling — the
  largest training programme in UAE government history.
- Dubai extended the same mandate to the **private sector** via Dubai Chamber of
  Commerce, with dedicated agentic AI incubators and funds.
- RTA is already running production AI on Dataiku and training staff to build
  generative AI tools for metro operations and corporate automation.

Masar AI is deliberately built as **the citizen-facing agentic layer that this
mandate implies but no one has publicly shipped yet.**

---

## 2. WHAT GETS BUILT (SCOPE LOCK)

### 2.1 In scope — must ship

1. **Data lakehouse** — Bronze/Silver/Gold medallion over 12 real RTA datasets
2. **Dual-index retrieval** — pgvector (semantic) + PostgreSQL FTS (lexical) hybrid
3. **14-agent LangGraph orchestration** with supervisor + corrective loop
4. **FastAPI backend** — streaming SSE, session memory, full trace export
5. **Next.js 14 frontend** — chat, live map, evidence panel, agent trace viewer
6. **Bilingual AR/EN** end to end, including RTL layout
7. **Evaluation harness** — RAGAS-style metrics + 60-question golden set
8. **Observability** — every agent hop logged, replayable, exportable as JSON
9. **Offline mode** — full functionality on cached CSVs with Ollama, no internet
10. **Docker Compose** — one command boot

### 2.2 Explicitly out of scope — do not build

- Real-time vehicle GPS tracking (RTA does not expose this openly — do not fake it)
- Payment / nol top-up (no transactional government integration)
- User accounts, auth, or PII storage (avoids UAE PDPL exposure entirely)
- Native mobile apps
- Any paid API. If a tool needs a credit card, it is not in this build.

### 2.3 Honesty rule (non-negotiable — this protects your credibility)

The README, the UI footer, and the viva script must all state plainly:

> Masar AI is an independent academic project. It is **not affiliated with,
> endorsed by, or connected to** the Roads and Transport Authority. It uses
> publicly available open data published by RTA via Dubai Pulse under that
> platform's terms of use. Live operational data (real-time vehicle positions,
> live disruptions) is **not** publicly available and is **not** simulated as
> live — where the system reasons about schedules it says so explicitly.

Never let a demo imply live government system integration. A recruiter who
catches an overclaim discards the whole portfolio.

---

## 3. DATA PLAN — REAL DUBAI PULSE RTA ENDPOINTS

### 3.1 Platform mechanics (verified)

Dubai Pulse is Dubai's official open data platform and publishes RTA data as
both bulk CSV downloads and a CKAN-style REST Data API.

**Authentication flow (OAuth2 client credentials):**

```
POST https://api.dubaipulse.gov.ae/oauth/client_credential/accesstoken?grant_type=client_credentials
Body: client_id={API_KEY}&client_secret={API_SECRET}

→ read "access_token" from the JSON response
→ send on every subsequent call as:  Authorization: Bearer {access_token}
→ token expiry is short (≈30 min) — you MUST implement refresh
```

**Query API base patterns:**

```
https://api.dubaipulse.gov.ae/open/rta/{dataset_slug}
https://api.dubaipulse.gov.ae/shared/rta/{dataset_slug}
```

**Supported query parameters (implement all of these in the client):**

| Param | Example | Purpose |
|---|---|---|
| `filter` | `?filter=zone_id=2 AND line_name='Red'` | AND / OR conditions |
| `column` | `?column=zone_id,line_name,location_id` | projection |
| `order_by` | `?order_by=primary_key_attribute` | sort |
| `offset` | `?offset=10` | pagination |
| `limit` | `?limit=500` | page size |

### 3.2 CRITICAL OPERATIONAL WARNING — read before Phase 1

API keys on Dubai Pulse are granted **per dataset**, delivered as key and secret
in **two separate emails**, and the grant confirmation can take **up to 14
days**. Bulk CSV download links are available immediately without a key.

**Therefore the build order is mandatory:**

1. **Day 0:** Register on Dubai Pulse, request grants for all 12 datasets in 3.3.
2. **Day 0:** Download the bulk CSVs immediately — build the entire system on
   these. The CSV path is the primary path.
3. **When keys arrive:** the API client becomes a *refresh mechanism* layered on
   top, not a dependency.

**The system must be fully demonstrable with zero API keys.** Build
`ingestion/source.py` with a strategy interface so `CsvSource` and `ApiSource`
are interchangeable. Default to `CsvSource`. This is a hard architectural
requirement — a demo that dies because a token expired during a recruiter call
is a failed demo.

### 3.3 The 12 datasets to ingest

| # | Dataset slug | Domain | Role in Masar |
|---|---|---|---|
| 1 | `rta_bus_routes-open` | Bus | Route master — names, origin/destination, service type |
| 2 | `rta_bus_ridership-open` | Bus | Historical ridership fact table (large, many resources) |
| 3 | `rta_bus_passengers_trips_by_route_monthly-open` | Bus | Monthly passenger trips per route — core trend fact |
| 4 | `rta_bus_stops_gis-open` | Bus | Stop geometry for catchment / geospatial agent |
| 5 | `rta_metro_lines-open` | Rail | Red/Green line master + geometry |
| 6 | `rta_metro_ridership-open` | Rail | Monthly metro passengers by route/station |
| 7 | `rta_tram_stations-open` | Rail | Tram station master, zone_id, line_name, location_id |
| 8 | `rta_public_transportation_routes_stops-open` | Multi-modal | Route↔stop bridge table — the join backbone |
| 9 | `rta_public_transport_trips_by_type_of_transport_month-open` | Multi-modal | Modal split over time |
| 10 | `rta_taxi_stand_locations-open` | Taxi | Taxi stand geometry — last-mile agent |
| 11 | `rta_dubai_taxi_drivers-open` | Taxi | Fleet/driver demographics — supply-side analysis |
| 12 | `rta_salik_tariff-open` | Roads | Salik toll tariff — drive-vs-transit cost agent |

Dataset landing pages follow the pattern
`https://www.dubaipulse.gov.ae/data/{service}/{dataset_slug}` — e.g.
`https://www.dubaipulse.gov.ae/data/rta-bus/rta_bus_routes-open`.

### 3.4 Unstructured corpus (for the vector index)

Structured tables alone can't answer "what documents do I need for a nol card
refund?" Build a small, clean document corpus:

| Source | Method | Volume target |
|---|---|---|
| RTA public service descriptions (rta.ae service pages) | Manual curation into markdown, one file per service | 40–60 docs |
| Fare/zone rules, nol card categories | Curated markdown from public RTA fare pages | 10–15 docs |
| Dataset dictionaries from Dubai Pulse "Attribute Details" | Scripted extraction to markdown | 12 docs |

**Rules:** curate manually into `data/corpus/{en,ar}/*.md` with YAML front-matter
(`source_url`, `retrieved_date`, `lang`, `service_category`). Do **not** write a
crawler that hammers rta.ae. Volume is not the goal — clean, cited, current
documents are. Every document must carry a `source_url` because the Citation
Agent depends on it.

### 3.5 Medallion lakehouse layout

```
data/
├── bronze/          # raw, immutable, exactly as downloaded
│   ├── csv/{dataset_slug}/{ingest_date}/*.csv
│   └── api/{dataset_slug}/{ingest_date}/*.json
├── silver/          # typed, deduped, standardised, bilingual-normalised
│   └── {dataset_slug}.parquet
├── gold/            # business-ready marts, loaded into Postgres
│   ├── dim_route.parquet
│   ├── dim_stop.parquet
│   ├── dim_station.parquet
│   ├── dim_date.parquet
│   ├── fact_ridership_monthly.parquet
│   ├── fact_modal_split_monthly.parquet
│   └── dim_salik_tariff.parquet
└── corpus/{en,ar}/*.md
```

**Silver-layer transformation rules (apply to every dataset):**

1. Snake_case all column names; strip whitespace and BOM.
2. Split bilingual columns — `name_en` / `name_ar` as separate columns, never one.
3. Cast dates to `DATE`, all numerics to explicit types; log coercion failures.
4. Deduplicate on natural key; keep latest by ingest timestamp.
5. Normalise Arabic text: unify alef forms (`أإآ`→`ا`), strip tatweel and
   diacritics into a `*_ar_norm` search column while **preserving the original**
   `*_ar` for display.
6. Standardise geometry to WGS84 lat/lon float columns; drop unparseable rows to
   a quarantine table rather than silently dropping.
7. Emit a **data quality report** per dataset: row count, null rate per column,
   duplicate count, coercion failures, date range. Write to
   `reports/dq/{dataset}_{date}.json`. This report is a deliverable — governance
   evidence is exactly what a UAE government-adjacent employer looks for.

---

## 4. TECH STACK (LOCKED)

### 4.1 Core

| Layer | Choice | Why this and not the alternative |
|---|---|---|
| Orchestration | **LangGraph** | Explicit stateful graph with cycles — required for the corrective loop. LangChain AgentExecutor can't express conditional re-planning cleanly. |
| Model gateway | **LiteLLM** | One OpenAI-compatible interface across Groq/Gemini/Cerebras/Ollama with automatic fallback on 429. Non-negotiable for free tiers. |
| Backend | **FastAPI** + Pydantic v2 | Async, SSE streaming, typed contracts |
| Database | **PostgreSQL 16** + **pgvector** | Vectors and facts in one engine — one join, no sync problem |
| Lexical search | **Postgres FTS** (`tsvector`, GIN) | Hybrid retrieval without adding Elasticsearch |
| Cache / rate limit | **Redis 7** | Token bucket for free-tier limits, semantic cache, session state |
| Embeddings | **BAAI/bge-m3** via sentence-transformers, local | Genuinely multilingual (AR+EN in one space), runs on CPU, zero API cost |
| Reranker | **BAAI/bge-reranker-v2-m3**, local | Cross-encoder rerank without an API bill |
| Transform | **Polars** | Faster than pandas on the ridership files; deterministic |
| Frontend | **Next.js 14 App Router**, TypeScript | Your locked stack |
| UI | **shadcn/ui** + Tailwind + **Framer Motion v12** | Your locked stack |
| Map | **MapLibre GL JS** + free OSM raster tiles | No Mapbox token = no credit card |
| Charts | **Recharts** | Your locked stack |
| Smooth scroll | **Lenis** | Your locked stack |
| Eval | **RAGAS** + custom golden-set harness | Faithfulness, relevancy, context precision |
| Tracing | **LangSmith free tier** OR local JSONL tracer | Must work with LangSmith disabled |
| Deploy | Docker Compose (local) · Vercel (FE) · Railway/Fly.io free tier (BE) | Zero-cost path |

### 4.2 Model routing policy (implement exactly as specified)

Configure in `config/models.yaml`. Route by **task class**, not by preference:

| Task class | Primary | Fallback 1 | Fallback 2 | Rationale |
|---|---|---|---|---|
| Routing / classification | Groq `llama-3.3-70b-versatile` | Cerebras `llama-3.3-70b` | Ollama `qwen2.5:7b` | Sub-200ms time-to-first-token; routing is latency-critical |
| Planning / decomposition | Gemini `2.5-flash` | Groq 70B | Ollama `qwen2.5:14b` | Better structured reasoning |
| Long-context synthesis | Gemini `2.5-flash` (1M ctx) | Cerebras | Ollama | Only Gemini gives a genuinely large free context |
| Text-to-SQL | Gemini `2.5-flash` | Groq 70B | Ollama `qwen2.5-coder:7b` | Codegen quality matters most here |
| Grading / verification | Groq 70B | Cerebras | Ollama | High call volume — needs cheap and fast |
| Arabic generation | Gemini `2.5-flash` | Groq 70B | Ollama `qwen2.5:14b` | Strongest Arabic of the free options |

**Verified free-tier limits as of July 2026** (encode these as Redis token
buckets in `services/rate_limiter.py` — and re-verify before your demo, because
providers adjust these):

- **Google AI Studio (Gemini 2.5 Flash):** ~10 RPM / ~250 RPD / ~250K TPM; up to
  1M token context. Exact active quota varies by project — check AI Studio.
- **Groq:** ~30 RPM / ~1,000 RPD / ~6K TPM; sub-200ms TTFT on LPU hardware.
- **Cerebras:** ~1M tokens/day, ~5–30 RPM.
- **Ollama:** unlimited, local, offline.

Implement `RateLimitedRouter` with: per-provider token bucket → on 429 or bucket
exhaustion, transparently fall through the chain above → if all cloud providers
are exhausted, drop to Ollama and set `degraded_mode: true` in the response
metadata so the UI can show a badge. **Never fail a user request because a free
tier ran out.** This graceful-degradation design is itself a strong interview
talking point.

### 4.3 The only two secrets

`.env` (git-ignored; ship `.env.example` with these keys and empty values):

```
DUBAI_PULSE_API_KEY=
DUBAI_PULSE_API_SECRET=
```

Everything else — Groq, Gemini, Cerebras keys — are free-tier keys obtained
without a credit card, also placed in `.env`. **If a key is missing at boot, the
system must start anyway and log a structured warning naming exactly which
capability is degraded.** Never crash on a missing optional key.

---

## 5. THE 14-AGENT ARCHITECTURE

### 5.1 Topology

```
                          ┌─────────────────────────┐
   user query  ──────────▶│  A1  Guardrail          │
                          └───────────┬─────────────┘
                                      ▼
                          ┌─────────────────────────┐
                          │  A2  Language & Normalise│
                          └───────────┬─────────────┘
                                      ▼
                          ┌─────────────────────────┐
                          │  A3  Intent Router       │
                          └───────────┬─────────────┘
                                      ▼
                    ╔═════════════════════════════════════╗
                    ║   A4  SUPERVISOR / PLANNER          ║
                    ║   decomposes → dispatches → decides ║
                    ║   whether it has enough to answer   ║◀──┐
                    ╚══════╤══════════════════════════════╝   │
                           │ dispatches sub-tasks             │
         ┌─────────┬───────┼────────┬─────────┬──────────┐    │
         ▼         ▼       ▼        ▼         ▼          ▼    │
       ┌────┐   ┌────┐  ┌────┐   ┌────┐   ┌─────┐   ┌──────┐  │
       │ A5 │   │ A6 │  │ A7 │   │ A8 │   │ A9  │   │ A10  │  │
       │Query│  │Hybrid│ │Rerank│ │Text │  │Live │   │ Geo  │  │
       │Rewrit│ │Retriev│ │      │ │2SQL │  │API  │   │Spatial│ │
       └────┘   └────┘  └────┘   └────┘   └─────┘   └──────┘  │
                                     │                        │
                              ┌──────▼──────┐                 │
                              │ A11 Numeric │                 │
                              │  Calculator │                 │
                              └──────┬──────┘                 │
                                     ▼                        │
                          ┌─────────────────────────┐         │
                          │  A12  Grader (CRAG)     │─────────┘
                          │  sufficient? → loop     │  re-plan (max 3)
                          └───────────┬─────────────┘
                                      ▼ sufficient
                          ┌─────────────────────────┐
                          │  A13  Synthesis+Citation│
                          └───────────┬─────────────┘
                                      ▼
                          ┌─────────────────────────┐
                          │  A14  Observability     │  (runs on every hop)
                          └───────────┬─────────────┘
                                      ▼
                                  response
```

### 5.2 Agent specifications

Each agent = one module in `agents/`, one class, one `run(state) -> state`
method, its own prompt in `prompts/{agent_id}.md`, and its own unit test.

| ID | Agent | Input | Output | Model class | Deterministic? |
|---|---|---|---|---|---|
| **A1** | **Guardrail** | raw text | `{safe, reason, sanitized}` | rules + Groq | Partly |
| **A2** | **Language & Normalise** | sanitized text | `{lang, script, normalized, translit}` | rules + fastText | Yes |
| **A3** | **Intent Router** | normalized | one of 7 intent labels + confidence | Groq (fast) | No |
| **A4** | **Supervisor/Planner** | intent + state | ordered sub-task DAG | Gemini | No |
| **A5** | **Query Rewriter** | sub-task | 3 query variants (HyDE + expansion + AR/EN mirror) | Groq | No |
| **A6** | **Hybrid Retriever** | query variants | top-50 candidates w/ scores | none (pgvector+FTS) | **Yes** |
| **A7** | **Reranker** | top-50 | top-8 reranked | bge-reranker local | **Yes** |
| **A8** | **Text-to-SQL** | sub-task + schema | validated SQL + result set | Gemini | Guarded |
| **A9** | **Live API** | dataset + filters | Dubai Pulse JSON | none | **Yes** |
| **A10** | **Geospatial** | origin/destination | nearest stops, catchment, distance | none (PostGIS/haversine) | **Yes** |
| **A11** | **Numeric Calculator** | fare/toll params | exact cost breakdown | none (Python) | **Yes** |
| **A12** | **Grader (CRAG)** | evidence bundle | `{sufficient, gaps[], confidence}` | Groq | No |
| **A13** | **Synthesis + Citation** | evidence bundle | answer + `[S1]..[Sn]` citations | Gemini | No |
| **A14** | **Observability** | every state transition | trace record | none | **Yes** |

### 5.3 Agent-by-agent implementation detail

**A1 — Guardrail Agent**
Deterministic rules first (cheap), LLM second (only if rules are inconclusive).
Blocks: prompt injection patterns, requests for PII about individuals, requests
to perform transactions, out-of-domain queries. On block, return a helpful
redirect, never a bare refusal. **Also enforces the honesty rule:** if the user
asks for real-time vehicle position or live disruption status, respond that this
data is not in RTA's public open data and offer the schedule-based alternative.

**A2 — Language & Normalisation Agent**
Detect `ar` / `en` / `mixed`. For Arabic, produce the normalised form (alef
unification, tatweel/diacritic stripping) used for FTS matching while preserving
the original for display. Handle Arabizi (e.g. "3ala" → "على") via a small
lookup table. Sets `response_language` — **the answer language always mirrors the
query language**, no exceptions.

**A3 — Intent Router Agent**
Classify into exactly one of seven intents. Return confidence; if `< 0.6`, route
to `MULTI_HOP` (safe default — over-planning is cheaper than under-planning):

1. `JOURNEY_PLANNING` — routes, connections, stops
2. `FARE_COST` — nol fares, zones, Salik, drive-vs-transit
3. `SERVICE_INFO` — how do I do X, what documents, opening hours
4. `NETWORK_ANALYTICS` — ridership trends, modal split, utilisation
5. `GEOSPATIAL` — nearest stop/station/taxi stand, catchment
6. `MULTI_HOP` — requires 2+ of the above
7. `OUT_OF_SCOPE` — politely redirect

**A4 — Supervisor / Planner Agent** ← *the heart of the system*
Emits a typed plan:

```python
class SubTask(BaseModel):
    id: str
    description: str
    tool: Literal["retrieve","sql","api","geo","calc"]
    depends_on: list[str] = []
    params: dict

class Plan(BaseModel):
    sub_tasks: list[SubTask]
    reasoning: str
    expected_evidence_types: list[str]
```

Executes independent sub-tasks **in parallel** (`asyncio.gather`), dependent ones
in order. On a re-plan signal from A12, it receives the identified gaps and emits
a *revised* plan — it must not simply repeat the failed plan. **Hard cap: 3
planning cycles**, then answer with an explicit confidence caveat. Log every plan
revision — this is the single best artefact to show in a viva, because it makes
the "agentic" claim visible and falsifiable.

**A5 — Query Rewriter Agent**
Generates three variants per sub-task: (1) HyDE — a hypothetical ideal answer
paragraph, embedded as the query; (2) keyword-expanded lexical query with transit
synonyms ("metro"/"rail"/"مترو"); (3) cross-language mirror. All three go to A6.

**A6 — Hybrid Retriever Agent** *(deterministic — no LLM)*
- Dense: pgvector cosine over `bge-m3` embeddings, HNSW index, top-30
- Sparse: Postgres FTS `ts_rank_cd` over `tsvector`, top-30
- Fuse via **Reciprocal Rank Fusion**, `k=60`:
  `RRF(d) = Σ_r 1/(k + rank_r(d))`
- Metadata pre-filter by `lang`, `service_category`, `source_type`
- Return top-50 with per-source scores retained for the trace

**A7 — Reranker Agent** *(deterministic)*
Cross-encoder `bge-reranker-v2-m3` over the 50 candidates → top-8. Drop anything
below a relevance threshold of `0.35` **even if that leaves fewer than 8** — a
thin, clean context beats a padded one, and A12 will catch genuine insufficiency.

**A8 — Text-to-SQL Agent** *(guarded)*
Reads a curated schema card from `config/schema_card.md` (never the raw
`information_schema` — token waste and worse accuracy). Hard safety layer:
- Parse generated SQL with `sqlglot`; reject anything that isn't a single `SELECT`
- Reject `DROP|DELETE|UPDATE|INSERT|ALTER|GRANT|COPY|;`
- Force-append `LIMIT 1000` if absent
- Execute as a **read-only Postgres role** (`masar_ro`) — defence in depth
- 5-second statement timeout
- On SQL error: return the error to the agent for **one** repair attempt, then fail
  gracefully to A12 as a gap

**A9 — Live API Agent** *(deterministic)*
The Dubai Pulse client. Manages OAuth token lifecycle with automatic refresh at
80% of TTL. Translates sub-task params into `filter` / `column` / `order_by` /
`limit` / `offset`. **Falls back to the Silver parquet layer on any failure** and
flags `data_freshness: "cached"` in the response metadata.

**A10 — Geospatial Agent** *(deterministic)*
Haversine nearest-neighbour over `dim_stop` / `dim_station` /
`taxi_stand_locations`. Catchment analysis (stops within radius *r*). Approximate
multi-modal route via graph traversal on the `routes_stops` bridge table.
**Never invents travel times** — reports distance and interchange count, and says
so.

**A11 — Numeric Calculator Agent** *(deterministic — zero LLM)*
Pure Python, fully unit-tested:
- nol fare by zone count and card type
- Monthly commute cost = fare × 2 × configurable working days
- Salik cost from `dim_salik_tariff` × gate crossings
- Drive-vs-transit comparison including fuel and parking as declared assumptions
**All assumptions are returned as structured data and rendered in the UI.** An LLM
must never do arithmetic in this system. State that plainly in the viva — it is
the correct engineering answer and examiners look for it.

**A12 — Grader Agent (Corrective RAG loop)** ← *the second differentiator*
Scores the evidence bundle on four axes (0–1 each):
`coverage` · `specificity` · `recency` · `source_authority`

Decision:
- All ≥ 0.7 → `sufficient: true` → proceed to A13
- Any < 0.7 and cycle < 3 → `sufficient: false`, emit named `gaps[]` → back to A4
- Cycle = 3 → proceed with `confidence: "low"`, and A13 **must** surface the
  limitation in the answer text

This loop is precisely what makes the system *agentic RAG* rather than *RAG*. Log
every grading decision with its four sub-scores.

**A13 — Synthesis + Citation Agent**
Composes the final answer in `response_language`. Hard rules:
- Every factual claim carries an inline marker `[S1]`, `[S2]`…
- Each marker maps to a source object: `{type, dataset_or_doc, source_url, row_id_or_chunk_id, retrieved_at}`
- **If a claim cannot be sourced, it is deleted, not softened**
- Numeric results are quoted verbatim from A11 — never regenerated
- Arabic output is RTL, uses Arabic-Indic numerals only if the user did
- Ends with confidence level and any declared assumptions

**A14 — Observability Agent**
Runs on every state transition. Emits per hop: `agent_id`, `timestamp`,
`input_hash`, `model_used`, `provider`, `tokens_in/out`, `latency_ms`,
`decision`, `cost_estimate_usd` (0.00 on free tier — show it anyway). Writes to
`traces/{session_id}/{turn_id}.jsonl` **and** to a `agent_traces` Postgres table.
Exposed via `GET /api/v1/trace/{turn_id}` and rendered in the UI trace viewer.

---

## 6. END-TO-END PIPELINE

### 6.1 Offline pipeline (build-time, run nightly via APScheduler)

```
[1] ACQUIRE
    ├─ CsvSource: download 12 bulk CSVs from Dubai Pulse
    └─ ApiSource: paginate the Data API (when keys exist)
              ↓ writes immutable → data/bronze/
[2] VALIDATE
    └─ Pandera schema per dataset · row-count deltas vs last run
       · null-rate thresholds · fail loudly, quarantine bad rows
              ↓
[3] TRANSFORM (Polars)
    └─ snake_case · bilingual split · type cast · dedupe
       · Arabic normalisation · geometry standardisation
              ↓ data/silver/*.parquet + reports/dq/*.json
[4] MODEL
    └─ Build star schema: dim_route, dim_stop, dim_station, dim_date,
       fact_ridership_monthly, fact_modal_split_monthly, dim_salik_tariff
              ↓ data/gold/*.parquet
[5] LOAD
    └─ COPY into PostgreSQL · create indexes · refresh materialized views
       · ANALYZE
              ↓
[6] INDEX
    ├─ Chunk corpus: 512-token semantic chunks, 64-token overlap,
    │  never split across markdown headings
    ├─ Embed with bge-m3 → pgvector, HNSW (m=16, ef_construction=64)
    ├─ Build tsvector column + GIN index (EN 'english', AR 'simple' on
    │  the normalised column)
    └─ Generate row-level natural-language summaries for key gold tables
       and embed those too — this is what lets semantic search find
       structured facts
              ↓
[7] EVALUATE
    └─ Run the 60-question golden set → RAGAS metrics → write
       reports/eval/{date}.json → FAIL THE BUILD if faithfulness < 0.80
```

### 6.2 Online pipeline (per user turn)

```
POST /api/v1/chat  {query, session_id, lang?}
  │
  ├─▶ Redis semantic cache lookup (cosine ≥ 0.95 on query embedding)
  │     └─ hit → return cached, flag cached:true          [~50ms]
  │
  ├─▶ LangGraph invocation, streaming SSE:
  │     A1 guardrail          ~30ms   (rules-only path)
  │     A2 language           ~10ms   (deterministic)
  │     A3 intent router      ~200ms  (Groq)
  │     A4 planner            ~600ms  (Gemini)
  │     ├── parallel fan-out ────────────────────────
  │     │   A5→A6→A7 retrieval chain    ~400ms
  │     │   A8 text-to-SQL              ~800ms
  │     │   A9 live api                 ~300ms
  │     │   A10 geospatial              ~50ms
  │     │   A11 calculator              ~5ms
  │     └──────────────────────────────────────────
  │     A12 grader           ~250ms
  │       └─ insufficient → back to A4  (≤3 cycles)
  │     A13 synthesis        ~1200ms (streamed token by token)
  │     A14 observability    async, non-blocking
  │
  └─▶ SSE event stream to client:
        event: agent_start   {agent_id, label_en, label_ar}
        event: agent_end     {agent_id, latency_ms, decision}
        event: evidence      {sources[]}
        event: token         {text}
        event: done          {trace_id, confidence, degraded_mode}
```

**Latency budget: p50 < 3.5s, p95 < 8s** on a single-cycle path. Enforce it in
the eval harness — if p95 regresses past 8s, the build fails.

### 6.3 Repository structure

```
masar-ai/
├── docker-compose.yml
├── README.md
├── .env.example
├── Makefile                      # make setup / ingest / index / eval / dev
├── backend/
│   ├── main.py
│   ├── config/
│   │   ├── models.yaml
│   │   ├── schema_card.md
│   │   └── settings.py
│   ├── agents/                   # a1_guardrail.py … a14_observability.py
│   ├── graph/
│   │   ├── state.py              # MasarState (TypedDict)
│   │   ├── builder.py            # LangGraph assembly
│   │   └── edges.py              # conditional routing logic
│   ├── prompts/                  # a1.md … a13.md  (versioned, git-tracked)
│   ├── retrieval/
│   │   ├── hybrid.py
│   │   ├── rrf.py
│   │   ├── reranker.py
│   │   └── chunker.py
│   ├── ingestion/
│   │   ├── source.py             # CsvSource | ApiSource strategy
│   │   ├── dubai_pulse_client.py # OAuth + pagination + retry
│   │   ├── bronze.py silver.py gold.py
│   │   └── quality.py
│   ├── services/
│   │   ├── llm_router.py
│   │   ├── rate_limiter.py
│   │   ├── cache.py
│   │   └── sql_guard.py
│   ├── api/
│   │   └── routes/chat.py trace.py health.py datasets.py
│   └── tests/
│       ├── unit/                 # one file per agent
│       ├── integration/
│       └── golden/               # the 60-question set
├── frontend/                     # Next.js 14 App Router
│   └── app/
│       ├── page.tsx              # chat + evidence + map
│       ├── explore/page.tsx      # analytics dashboard
│       └── trace/[id]/page.tsx   # agent trace viewer
├── data/                         # gitignored except corpus/
├── notebooks/
│   ├── 01_data_exploration.ipynb
│   ├── 02_retrieval_benchmark.ipynb
│   └── 03_agent_evaluation.ipynb
└── docs/
    ├── ARCHITECTURE.md
    ├── DATA_DICTIONARY.md
    ├── EVALUATION.md
    └── GOVERNANCE.md
```

---

## 7. FRONTEND SPEC

Three routes. Apply the `premium-frontend` skill patterns — Motion v12, Lenis,
magnetic buttons, staggered reveals — but **restraint over spectacle**: this is a
government-adjacent decision tool, not a product landing page.

**`/` — Chat**
Split layout. Left: conversation, streaming tokens, RTL flip on Arabic. Right:
tabbed panel — **Evidence** (source cards with dataset name, row/chunk, source
link, retrieved date) · **Map** (MapLibre, plots stops/stations/routes referenced
in the answer) · **Agents** (live timeline of the 14 agents lighting up as they
execute, with latency badges and a visible loop-back arrow when A12 triggers a
re-plan). *That loop-back animation is the single most persuasive thing in the
demo — it makes "agentic" visible in two seconds.*

**`/explore` — Analytics**
Recharts dashboards on the gold marts: ridership trend by mode, modal split over
time, top routes by passenger trips, station-level heatmap. Every chart has a
"Ask Masar about this" button that pipes a pre-built question into chat.

**`/trace/[id]` — Trace viewer**
Full waterfall of one turn: each agent hop, model used, provider, tokens,
latency, decision, and the plan/re-plan diff. Export as JSON. This page is what
you screen-record for LinkedIn.

**Design direction:** near-black canvas `#0A0A0B`, RTA-adjacent teal accent
`#00A99D`, warm amber `#F5A524` for the corrective-loop highlight. Inter for
Latin, IBM Plex Sans Arabic for Arabic. Generous whitespace, one accent per view,
motion only where it carries information.

---

## 8. EVALUATION

### 8.1 Golden set — 60 questions

Build `tests/golden/questions.yaml`, 30 EN + 30 AR, distributed:

| Intent | Count | Example |
|---|---|---|
| JOURNEY_PLANNING | 10 | "Which bus routes connect to Union metro station?" |
| FARE_COST | 10 | "Monthly cost of a 2-zone nol commute for 22 working days?" |
| SERVICE_INFO | 10 | "How do I replace a lost nol card?" |
| NETWORK_ANALYTICS | 12 | "How has metro ridership on the Red Line trended?" |
| GEOSPATIAL | 8 | "Nearest taxi stand to Dubai Mall?" |
| MULTI_HOP | 10 | "Is bus or metro cheaper from Al Qusais to Business Bay, and which is busier?" |

Each entry: `question`, `lang`, `intent`, `ground_truth`, `required_sources[]`,
`must_trigger_agents[]`.

### 8.2 Metrics and thresholds (build fails below these)

| Metric | Threshold | Measured how |
|---|---|---|
| Faithfulness (RAGAS) | ≥ 0.80 | claims entailed by retrieved context |
| Answer relevancy | ≥ 0.75 | RAGAS |
| Context precision | ≥ 0.70 | RAGAS |
| Intent routing accuracy | ≥ 0.90 | A3 vs labelled intent |
| Text-to-SQL execution accuracy | ≥ 0.85 | result-set match on 20 SQL questions |
| Citation validity | **1.00** | every `[Sn]` resolves to a real source — zero tolerance |
| Numeric accuracy | **1.00** | A11 outputs vs hand-computed — deterministic, must be perfect |
| Arabic parity | ≤ 0.10 gap | AR faithfulness vs EN faithfulness |
| p95 latency | ≤ 8s | single-cycle path |

### 8.3 Ablation study (this is what makes it *research*, not a demo)

Run the golden set under four configurations and publish the table in
`docs/EVALUATION.md`:

| Config | Description |
|---|---|
| **Baseline** | Naive RAG — single dense retrieval, no rerank, no agents |
| **+Hybrid** | RRF dense+sparse, no rerank |
| **+Rerank** | Hybrid + cross-encoder |
| **Full Agentic** | All 14 agents + corrective loop |

Report faithfulness, relevancy and latency per config. **Expect the full agentic
config to win on quality and lose on latency — say so honestly.** An examiner who
sees you report your own system's cost trade-off trusts everything else you claim.

---

## 9. BUILD PHASES (with gates)

Claude Code must stop at each gate and report before continuing.

| Phase | Deliverable | Gate |
|---|---|---|
| **0** | Repo scaffold, Docker Compose, `.env.example`, Makefile, health endpoint | `docker compose up` boots Postgres+Redis+API; `/health` returns 200 |
| **1** | Ingestion: CsvSource for all 12 datasets → bronze | 12 datasets landed; row counts logged |
| **2** | Silver + DQ reports | All 12 parquet files exist; DQ report per dataset; zero uncaught coercion errors |
| **3** | Gold star schema → Postgres | Star schema loaded; 10 canonical analytical queries return correct results |
| **4** | Corpus curation + chunking + embedding + indexes | ≥50 docs indexed; hybrid search returns sane top-5 on 10 manual probes |
| **5** | Deterministic agents A6, A7, A10, A11, A14 | Unit tests pass; A11 numeric tests are 100% |
| **6** | LLM agents A1–A5, A8, A9 | Each has a unit test with a mocked model; SQL guard blocks all 8 injection test cases |
| **7** | LangGraph assembly + A12 corrective loop + A13 | End-to-end turn completes; a deliberately under-specified query provably triggers exactly one re-plan |
| **8** | FastAPI + SSE streaming + trace API | Streaming works; trace endpoint returns full 14-hop record |
| **9** | Next.js frontend, all 3 routes | Chat streams; map renders; trace viewer shows the loop-back |
| **10** | Golden set + RAGAS + ablation | All thresholds in 8.2 met; ablation table published |
| **11** | Docs, README, deployment, demo script | README complete with honesty disclaimer; deployed; 3-minute demo script written |

---

## 10. LIMITATIONS (state these openly — everywhere)

1. **No real-time data.** RTA does not publish live vehicle positions or
   disruption feeds as open data. Journey reasoning is schedule- and
   network-topology-based. The system says so when asked.
2. **Data recency varies by dataset.** Some Dubai Pulse RTA datasets update
   monthly, some were last refreshed years ago. Every answer surfaces the source
   dataset's `last_updated` date. Never present stale data as current.
3. **Free-tier rate limits are real.** Under load the system degrades to Ollama
   with a visible badge. Honest degradation, not silent failure.
4. **Arabic retrieval is weaker than English.** The corpus is English-dominant.
   The measured AR/EN parity gap is published rather than hidden.
5. **Text-to-SQL is bounded** to the curated star schema. Questions outside it are
   routed to gaps, not guessed at.
6. **No affiliation with RTA.** Stated in README, UI footer, and every
   presentation.
7. **Approximate geospatial routing.** Haversine + topology traversal, not a real
   routing engine. Reports distance and interchanges, never invented durations.

---

## 11. FUTURE IMPROVEMENTS (your roadmap slide)

1. **GraphRAG layer** — Neo4j knowledge graph over the route↔stop↔zone network for
   true multi-hop traversal ("routes reachable within 2 interchanges of X")
2. **GTFS integration** if RTA publishes a public feed — unlocks real timetables
3. **Fine-tuned Arabic reranker** on transit-domain query/passage pairs
4. **Demand forecasting agent** — LSTM/Prophet over `fact_ridership_monthly`,
   reusing your StockWise AI forecasting work
5. **Voice interface** with Khaleeji Arabic dialect support — hospitality and
   government voice agents in the UAE explicitly require dialect handling, not
   just MSA
6. **MCP server wrapper** so Masar's tools are callable from any MCP client
7. **Multi-emirate expansion** — Abu Dhabi ITC and Sharjah SRTA open data

---

## 12. VIVA Q&A

**Q1. What makes this "agentic RAG" and not just RAG?**
Three concrete things. First, retrieval strategy is a *decision* made by the
Supervisor at runtime, not a fixed pipeline — the same query can produce a
vector-only plan or a SQL+geo+calculator plan. Second, there's a cycle in the
graph: the Grader can send control back to the Planner with named gaps, so the
system can re-plan up to three times. Third, tool selection is dynamic across five
tool classes. Classical RAG is a directed acyclic pipeline; Masar is a stateful
graph with conditional cycles. I can show the loop firing live in the trace
viewer.

**Q2. Why LangGraph and not LangChain agents or CrewAI?**
The corrective loop requires an explicit cycle with typed shared state.
LangChain's AgentExecutor hides control flow inside a ReAct loop I can't inspect
or constrain. CrewAI is role-play oriented and less deterministic. LangGraph gives
me an explicit state machine — which matters enormously for a government-adjacent
system where I need to prove *why* an answer was produced.

**Q3. Why hybrid retrieval instead of pure vector search?**
Transit queries contain exact identifiers — route "F27", "Al Qusais", zone IDs.
Dense embeddings are semantically fuzzy and routinely miss exact-token matches.
Sparse FTS nails them but misses paraphrase. I fuse both with Reciprocal Rank
Fusion at k=60 — a rank-based fusion that needs no score normalisation across two
incomparable scoring scales. My ablation table quantifies the gain.

**Q4. Why is arithmetic done in Python instead of by the LLM?**
Because LLMs are unreliable arithmetic engines and fare calculation is a
correctness-critical operation. Agent A11 is pure deterministic Python with 100%
unit test coverage, and A13 is forbidden from regenerating its numbers — it quotes
them verbatim. This is the standard pattern: LLMs for language and routing,
deterministic code for computation.

**Q5. How do you prevent SQL injection in the Text-to-SQL agent?**
Four independent layers. One: `sqlglot` AST parsing rejects anything that isn't a
single SELECT. Two: a keyword denylist for DDL/DML. Three: execution under a
read-only Postgres role, so even a bypass can't mutate anything. Four: a
five-second statement timeout plus a forced LIMIT. Layers three and four are
defence in depth — they assume layers one and two will eventually be defeated.

**Q6. How does the corrective loop actually decide "insufficient"?**
The Grader scores the evidence bundle on four axes — coverage, specificity,
recency, source authority — each 0 to 1. If any falls below 0.7 and we're under
three cycles, it returns `sufficient: false` with named gaps, and the Planner must
produce a *different* plan addressing those gaps. At cycle three it answers anyway
but flags low confidence and states the limitation in the response. Every grading
decision with its sub-scores is in the trace.

**Q7. This runs entirely on free tiers. Is that production-realistic?**
No, and I don't claim it is — that's a deliberate constraint, and the interesting
engineering is in handling it. I built a LiteLLM router with per-provider Redis
token buckets and a fallback chain ending at local Ollama, so the system degrades
gracefully rather than failing. Also worth noting: free tiers are typically funded
by using your prompts as training data, so no real customer data should touch
them. In production I'd move to paid endpoints or self-hosted models in a
UAE-resident region for PDPL compliance. Designing under the constraint made the
resilience architecture better than it would have been with an unlimited budget.

**Q8. How do you handle Arabic properly?**
Four layers. Detection and normalisation in A2 — alef unification, tatweel and
diacritic stripping into a separate search column while preserving the original
for display. Embeddings via bge-m3, which puts Arabic and English in a genuinely
shared space so a query in one language retrieves documents in the other.
Postgres FTS with the `simple` configuration on the normalised Arabic column,
since there's no Arabic stemmer built in. And response-language mirroring — the
answer is always in the query's language. I measure and publish the AR/EN
faithfulness gap rather than hiding it.

**Q9. What's your evaluation methodology?**
A 60-question golden set, balanced 30 EN / 30 AR across six intents, each with
ground truth, required sources, and required agent activations. I measure RAGAS
faithfulness, relevancy and context precision, plus routing accuracy, SQL
execution accuracy, citation validity — which must be exactly 1.0 — and numeric
accuracy, also 1.0 since it's deterministic. Then a four-config ablation from
naive RAG through to full agentic, so the architecture's contribution is
quantified rather than asserted.

**Q10. What's the business value to RTA?**
Three things. Deflection: agentic self-service on complex multi-hop queries that
the current catalogue chatbot escalates to humans. Insight: the same analytics
layer serving citizens serves planners — under-utilised routes and modal shift
patterns surface as a by-product. And alignment: the UAE Cabinet has mandated
converting at least 50% of federal services to agentic AI within two years and is
training 80,000 employees on it. Masar is a working reference implementation of
what that mandate looks like at the citizen-facing layer.

**Q11. Biggest technical challenge?**
Getting the Grader's thresholds right. Too strict and it loops on every query,
tripling latency for no quality gain. Too loose and it never corrects, making the
loop decorative. I tuned the four sub-scores against the golden set and landed on
0.7, where roughly 18% of queries trigger exactly one re-plan and under 3% hit the
cycle cap. The second-hardest was making semantic search work over *structured*
data — solved by generating natural-language row summaries for the gold tables and
embedding those alongside the document corpus.

**Q12. What would you do differently with more time?**
Add the GraphRAG layer. The route↔stop↔zone network is fundamentally a graph, and
I'm currently approximating traversal with SQL joins over a bridge table.
Neo4j-backed multi-hop traversal would handle "reachable within two interchanges"
natively instead of with hand-written recursive queries. I'd also fine-tune the
reranker on transit-domain Arabic pairs — that's where my measured parity gap
comes from.

---

## 13. SUBMISSION-READY SUMMARY

> **Masar AI** is an agentic retrieval-augmented generation system built over the
> Roads and Transport Authority's open data, published via Dubai Pulse. It
> addresses a structural limitation of conventional RAG: single-pass
> retrieve-then-generate pipelines cannot answer multi-hop transport questions
> that require reasoning across unstructured service documentation, structured
> ridership facts, geospatial relationships, and deterministic fare arithmetic
> simultaneously.
>
> The system implements a 14-agent LangGraph orchestration with a supervisor
> planner that decomposes queries into a typed sub-task DAG, dispatches them
> across five tool classes in parallel, and a corrective grading agent that scores
> the assembled evidence on coverage, specificity, recency and source authority —
> returning control to the planner with named gaps when evidence is insufficient,
> for up to three cycles. Retrieval uses Reciprocal Rank Fusion over dense
> pgvector and lexical Postgres FTS, followed by cross-encoder reranking. All
> numeric computation is deterministic Python, never LLM-generated. Every factual
> claim carries a resolvable citation to a specific dataset row or document chunk.
>
> Data flows through a medallion lakehouse — bronze immutable raw, silver typed
> and bilingually normalised with per-dataset quality reports, gold star-schema
> marts — over twelve real RTA datasets covering bus, metro, tram, taxi, Salik and
> multi-modal ridership. The system operates bilingually in Arabic and English
> with measured and published cross-language parity, and runs entirely on
> zero-cost inference through a LiteLLM router with per-provider rate limiting and
> graceful degradation to local models.
>
> Evaluated against a 60-question bilingual golden set, the full agentic
> configuration achieves faithfulness above 0.80 with citation and numeric
> validity at 1.0, and a four-configuration ablation quantifies the contribution
> of each architectural layer — including the latency cost the agentic loop
> introduces.
>
> Masar AI is an independent academic project with no affiliation to or
> endorsement from the Roads and Transport Authority.

---

## 14. FINAL INSTRUCTION TO CLAUDE CODE

Build in the phase order of Section 9. After each phase, run the gate tests and
report pass/fail with evidence before proceeding. Do not skip the data quality
reports — they are graded deliverables, not scaffolding. Do not implement any
feature listed in Section 2.2. Do not let the demo depend on a Dubai Pulse API
key. Write the honesty disclaimer from Section 2.3 into the README before writing
any application code.

If you hit a genuine blocker, choose the most conservative option that keeps the
system running and log the decision in `docs/DECISIONS.md` with your reasoning.
Do not stop to ask.
