<div align="center">

# مسار · MASAR AI

**Dubai Mobility Decision Intelligence — Agentic RAG over RTA Open Data**

*Masar (مسار) — "route" or "path" in Arabic.*

![Python](https://img.shields.io/badge/Python-3.13-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-async%20SSE-009688?logo=fastapi&logoColor=white)
![LangGraph](https://img.shields.io/badge/LangGraph-14%20agents-1C3C3C)
![Next.js](https://img.shields.io/badge/Next.js-15-000000?logo=nextdotjs&logoColor=white)
![Postgres](https://img.shields.io/badge/Postgres%2016-pgvector-4169E1?logo=postgresql&logoColor=white)
![Cost](https://img.shields.io/badge/inference%20cost-AED%200-2ABFB2)

</div>

---

## ⚠️ Disclaimer — please read first

> **Masar AI is an independent academic project. It is not affiliated with, endorsed by, or
> connected to the Roads and Transport Authority (RTA).**
>
> It uses publicly available open data published by RTA via the Dubai Pulse platform, under that
> platform's terms of use.
>
> **Live operational data — real-time vehicle positions, live disruption feeds — is not publicly
> available and is not simulated as live.** Where the system reasons about journeys it does so from
> published schedules and network topology, and it says so explicitly in its answers.
>
> **Data provenance:** the Dubai Pulse platform was retired and now redirects to `data.dubai`, whose
> dataset catalogue sits behind an authentication gate. Masar's source data is therefore recovered
> from **public Internet Archive snapshots of Dubai Pulse**, not fetched live from RTA. Every row
> carries its `source_tier`, `source_url` and `captured_at`, and every citation in the UI displays
> the capture date rather than presenting archived data as current. See
> [`docs/GOVERNANCE.md`](docs/GOVERNANCE.md).

---

## 1. What this is

Dubai's RTA runs one of the densest multi-modal transit networks in the world. Its public-facing
assistant is a service-catalogue chatbot: it routes you to the right form. It does not reason.

It cannot answer questions like:

- *"I live in Al Qusais and work in Business Bay. Is bus or metro cheaper for me monthly, and how has ridership on that corridor trended?"*
- *"Which bus routes are under-utilised relative to their catchment?"*
- *"أي محطات المترو الأكثر ازدحاماً؟"*

These are **multi-hop** questions. Each one requires understanding intent, deciding which of several
data sources to hit, retrieving from more than one, doing arithmetic or geospatial reasoning,
verifying the answer against source, and responding bilingually with citations.

A single-pass retrieve-then-generate RAG pipeline structurally cannot do this. **Masar is built as a
stateful graph with conditional cycles instead.**

## 2. What makes it agentic, not just RAG

| | Classical RAG | Masar AI |
|---|---|---|
| **Retrieval strategy** | Fixed pipeline | A **runtime decision** by the Supervisor (A4) |
| **Control flow** | Directed acyclic | **Cyclic** — the Grader (A12) returns control to the Planner with named gaps |
| **Tools** | One vector index | **Five tool classes** — hybrid retrieval, Text-to-SQL, live API, geospatial, deterministic calculator |
| **Arithmetic** | LLM-generated | **Pure Python**, unit-tested, quoted verbatim — never regenerated |
| **Failure mode** | Answers anyway | Re-plans up to 3× , then answers with an explicit low-confidence caveat |

## 3. Architecture at a glance

```
query → A1 guardrail → A2 language → A3 intent router → ╔═ A4 SUPERVISOR ═╗ ←──┐
                                                        ╚════════╤════════╝     │
                     ┌──────────┬──────────┬─────────────────────┼──────┐       │
                     ▼          ▼          ▼          ▼          ▼      ▼       │
                   A5→A6→A7   A8 SQL    A9 API    A10 geo   A11 calc          │
                     └──────────┴──────────┴──────────┴──────────┘              │
                                          ▼                                     │
                                   A12 GRADER ── insufficient ──────────────────┘
                                          ▼ sufficient                    (max 3 cycles)
                                   A13 synthesis + citations → response
                                   A14 observability (every hop)
```

Full detail in [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## 4. Quick start

```bash
make setup
```

```bash
make up
```

```bash
make ingest
```

```bash
make dev
```

Backend on `http://localhost:8000`, frontend on `http://localhost:3000`.
The system boots and answers **with zero API keys** — it falls back to local Ollama and shows a
`degraded_mode` badge in the UI rather than failing.

## 5. Stack

| Layer | Choice | Why |
|---|---|---|
| Orchestration | LangGraph | Explicit stateful graph **with cycles** — required for the corrective loop |
| Model gateway | LiteLLM | One interface across Groq / Gemini / Cerebras / Ollama, automatic fallback on 429 |
| Backend | FastAPI + Pydantic v2 | Async, SSE streaming, typed contracts |
| Storage | PostgreSQL 16 + pgvector | Vectors *and* facts in one engine — one join, no sync problem |
| Lexical search | Postgres FTS (`tsvector` + GIN) | Hybrid retrieval without adding Elasticsearch |
| Embeddings | `BAAI/bge-m3` (local) | Genuinely multilingual AR+EN in one space, CPU-capable, zero cost |
| Reranker | `BAAI/bge-reranker-v2-m3` (local) | Cross-encoder rerank with no API bill |
| Frontend | Next.js 15 · React 19 · Tailwind v4 | App Router, streaming SSE, CSS-first theme tokens |
| Map | MapLibre GL + OSM raster | No Mapbox token — no credit card |

## 6. Known limitations

These are stated openly because a system that hides them cannot be trusted with the ones it doesn't
know about.

1. **No real-time data.** RTA publishes no open live vehicle or disruption feed. Journey reasoning is
   schedule- and topology-based, and the system says so when asked.
2. **Data is archived, not live.** Recovered from Internet Archive snapshots of the retired Dubai
   Pulse platform. Every answer surfaces its capture date.
3. **Recency varies by dataset.** Metro ridership runs to Jan 2026; Salik tariff to 2022. Never
   presented as current.
4. **Free-tier rate limits are real.** Under load the system degrades to local Ollama with a visible
   badge — honest degradation, not silent failure.
5. **Arabic retrieval is weaker than English.** The corpus is English-dominant. The measured AR/EN
   parity gap is published in [`docs/EVALUATION.md`](docs/EVALUATION.md) rather than hidden.
6. **Text-to-SQL is bounded** to the curated star schema. Questions outside it become named gaps, not
   guesses.
7. **Approximate geospatial routing.** Haversine + topology traversal, not a routing engine. Reports
   distance and interchange count — never invented durations.
8. **No affiliation with RTA.** Stated above, in the UI footer, and in every presentation.

## 7. Documentation

| Document | Contents |
|---|---|
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | The 14 agents, graph topology, state contract |
| [`docs/DATA_DICTIONARY.md`](docs/DATA_DICTIONARY.md) | Every dataset, column, provenance tier |
| [`docs/EVALUATION.md`](docs/EVALUATION.md) | Golden-set results, RAGAS metrics, ablation study |
| [`docs/GOVERNANCE.md`](docs/GOVERNANCE.md) | Provenance, data quality, terms of use, PDPL posture |
| [`docs/DECISIONS.md`](docs/DECISIONS.md) | Architecture decision log |

---

<div align="center">
<sub>Built by <b>Krishna Mathur</b> · MAIB, SP Jain School of Global Management, Dubai</sub><br>
<sub>Independent academic project · not affiliated with or endorsed by RTA</sub>
</div>
