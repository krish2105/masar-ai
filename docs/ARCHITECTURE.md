# Architecture

## The problem this shape solves

A single-pass retrieve-then-generate pipeline is a directed acyclic graph:
retrieve, generate, done. That structure cannot answer *"is bus or metro cheaper
from Al Qusais to Business Bay, and which is busier?"*, because answering it
needs four different kinds of evidence — fare rules, station zones, a distance,
and a ridership trend — and the decision about which to gather can only be made
after reading the question.

Masar is a **stateful graph with a cycle**. Retrieval strategy is a runtime
decision, and the system can notice that what it gathered was not enough.

```
query
  │
  ▼
A1 Guardrail ──── blocked ──▶ A2 language ──▶ honest redirect ──▶ END
  │ safe
  ▼
A2 Language & Normalise
  │
  ▼
A3 Intent Router  (confidence < 0.6 → MULTI_HOP)
  │
  ▼
╔══════════════════════╗
║ A4 SUPERVISOR        ║◀────────────────────┐
║ decompose → dispatch ║                     │
╚══════════╤═══════════╝                     │
           │ parallel waves                  │
   ┌───────┼───────┬────────┬────────┐       │
   ▼       ▼       ▼        ▼        ▼       │
 A5→A6→A7  A8     A9      A10      A11       │
 retrieve  SQL    API      geo      calc     │
   └───────┴───────┴────────┴────────┘       │
                   ▼                         │
            A12 GRADER ──── insufficient ────┘
                   │        + named gaps
                   │        (max 3 cycles)
                   ▼ sufficient
            A13 Synthesis + Citation
                   ▼
            A14 Observability (every hop)
```

## Why LangGraph

The corrective loop needs an explicit cycle over typed shared state.
LangChain's `AgentExecutor` hides control flow inside a ReAct loop that cannot
be inspected or constrained; CrewAI is role-play oriented and less
deterministic. LangGraph gives an explicit state machine — which matters
enormously for a system that must be able to explain *why* it produced an
answer.

The cycle is one function, `after_grader` in `graph/builder.py`:

```python
if grade is not None and not grade.sufficient and cycle < max_cycles - 1:
    return "replan"     # → increment_cycle → supervisor
return "synthesis"
```

## The 14 agents

| ID | Agent | Deterministic? | Notes |
|---|---|---|---|
| A1 | Guardrail | rules first, model only if inconclusive | Real-time questions are **answered honestly**, not refused |
| A2 | Language & Normalise | fully | Script-based detection; answer language always mirrors the query |
| A3 | Intent Router | keyword fast path, then model | Below 0.6 confidence → `MULTI_HOP` |
| A4 | Supervisor / Planner | no | Typed sub-task DAG; re-plans against named gaps |
| A5 | Query Rewriter | partly | HyDE + keyword expansion + cross-language mirror |
| A6 | Hybrid Retriever | **fully** | pgvector + Postgres FTS, fused by RRF (k=60) |
| A7 | Reranker | **fully** | Local cross-encoder; drops below 0.35 even if that thins the context |
| A8 | Text-to-SQL | guarded | Four safety layers; one repair attempt, then a named gap |
| A9 | Live API | **fully** | Reports freshness accurately; defers to the archive |
| A10 | Geospatial | **fully** | Distance and interchanges — **never invents a duration** |
| A11 | Numeric Calculator | **fully** | `Decimal` arithmetic; no model touches a money figure |
| A12 | Grader (CRAG) | scores deterministically, then model | Four axes; the lower of the two wins |
| A13 | Synthesis + Citation | no | Unresolvable citations stripped **in code** |
| A14 | Observability | **fully** | Every hop → JSONL + Postgres |

Seven of fourteen are fully deterministic. That is the point: language models
route and phrase, code computes and verifies.

## Parallel execution

`execution_order()` groups sub-tasks into waves by dependency, and each wave
runs under `asyncio.gather`. A plan touching retrieval, SQL and geospatial pays
the cost of its slowest branch, not the sum of all three. A dependency cycle
emits a final wave rather than deadlocking.

## Hybrid retrieval

Dense and sparse retrieval have incomparable score scales — cosine distance
versus `ts_rank_cd` — so they are fused on **rank**:

```
RRF(d) = Σ_r  1 / (k + rank_r(d))          k = 60
```

Both halves are load-bearing. Transit queries are full of exact identifiers
("F27", "Al Qusais", zone 5) that dense embeddings rank below paraphrase, and
full of paraphrase that lexical search misses entirely.

Per-retriever ranks survive into the result, so the trace can say *"found by
lexical at rank 2, missed by dense"* rather than presenting a single opaque
score.

### Making structured data semantically searchable

A table row has no surface for *"which zone is Union in?"* to match. So every
gold row is also rendered as a sentence — *"Union Metro Station is a Metro
station on the Red Metro line in fare zone 5"* — and embedded alongside the
document corpus. **By template, never by a model**: 673 generated summaries, any
one of which could otherwise carry a hallucinated zone number into a cited
answer.

## The four-layer SQL guard

1. `sqlglot` AST parse — reject anything that is not a single `SELECT`
2. keyword denylist applied to the **rendered AST**, so comments cannot smuggle
3. execution under a read-only Postgres role
4. 5-second statement timeout and a forced `LIMIT`

Layers 3 and 4 assume 1 and 2 will eventually be defeated. All eight injection
cases in `tests/unit/test_sql_guard.py` are blocked, and the legitimate-query
tests exist because a guard that rejects everything also passes every injection
test — which is how the CTE-alias false positive (ADR-006) was found.

## Graceful degradation

`LLMRouter` routes by **task class**, walking a fallback chain per class. It
skips providers with no key, an exhausted token bucket, or a penalty from a
recent 429, and falls through to local Ollama with `degraded_mode: true` so the
UI can badge it.

Verified with zero cloud keys: Groq skipped, Cerebras skipped, Ollama answered,
flag set, full attempt chain captured for the trace.

Retrieval degrades differently — it does not. Embedding and reranking are local,
so retrieval quality is unaffected by an exhausted tier. Only generation falls
back.

## Data flow

```
Internet Archive ─▶ bronze (immutable + manifest)
                      │
                      ▼
                   silver (typed, deduped, Arabic-normalised, DQ report)
                      │
                      ▼
                    gold (star schema) ─▶ Postgres ─▶ A8
                      │
                      ├─▶ row summaries ──┐
                      │                   ├─▶ embed ─▶ doc_chunk ─▶ A6
              corpus (generated) ─────────┘
```

Provenance — `source_tier`, `source_url`, `captured_at`, `is_synthetic` — is
carried as columns from raw bytes to the `[S1]` chip in the UI. The evidence
card shows the **capture date**, so archived data is structurally incapable of
being presented as live.

## State

`MasarState` is a `TypedDict` with reducers on the accumulators:

- `evidence` merges across parallel branches, de-duplicating by source and
  keeping the higher score — otherwise duplicates would inflate the Grader's
  coverage signal
- `trace` and `plan_history` append

Making state explicit and typed is the reason LangGraph was chosen over an
opaque loop: every hop is inspectable and replayable.
