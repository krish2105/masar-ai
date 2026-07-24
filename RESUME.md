# Resume — where Masar AI stands (2026-07-24)

Read this first when picking the project back up. Everything is committed to git;
nothing below depends on a running process surviving.

## Status: built end to end, one eval re-run pending

All 12 phases are implemented, gated and committed. Latest commit at hand-off:
`f53169a docs(eval): correct two paragraphs left stale by the fix`.

- **Backend:** 168 unit tests passing, ruff clean. 14 agents, LangGraph corrective
  loop, FastAPI SSE.
- **Frontend:** Next.js 15, 5 routes, builds clean.
- **Lakehouse:** 19/19 datasets, gold star schema, 869-chunk hybrid index — all
  rebuildable with `make etl`.

## What was in flight at hand-off

### 1. The 60-question eval — NEEDS RE-RUN
It reached **56/60 (54 pass / 2 fail)** then the app closed, killing the
background process. The aggregated report writes only after all 60 complete, so
it was **not** saved. The 8-question sample IS saved: `reports/eval/2026-07-24_sample8.json`.

To re-run (≈75–90 min on local Ollama, or a few minutes with a Groq key):
```bash
make up                       # ensure postgres + redis
ollama serve &                # ensure local model
make eval                     # full 60-question run → reports/eval/<date>.json
```
Then fill the `<!-- EVAL_RESULTS -->`-adjacent table in `docs/EVALUATION.md` with
the real 60-question numbers (the 8-question before/after table is there now).

### 2. Frontend corruption — FIXED, needs a render re-verify
A file in `frontend/node_modules/next/dist/compiled/@edge-runtime/primitives`
corrupted at rest (disk at 94% under heavy eval load), giving the browser
`Cannot read properties of undefined (reading 'call')` at `app/layout.tsx:45`
`<Nav/>`. Root cause was NOT project code. Fixed with `npm ci` — verified at the
module level (`edge-runtime primitives load OK`). The dev server was **not yet
restarted-and-rendered** after the fix.

To confirm on return:
```bash
cd frontend && rm -rf .next && npm run dev
# then open http://localhost:3000 — the overlay should be gone
```

## Restarting the whole thing
```bash
make up            # postgres + redis (docker)
ollama serve &     # local LLM fallback
make dev           # API :8000 + frontend :3000 together
```
No API keys needed — it runs degraded on Ollama. Add a free Groq/Gemini key to
`.env` for fast, non-degraded turns (and to unlock the judged eval metrics).

## The two open threads (from docs/EVALUATION.md)
1. **Re-plan rate still above the 15–25% target.** The three *scoring* defects
   are fixed (grader abstains where it can't measure). What remains is retrieval
   and corpus coverage — chiefly that `SERVICE_INFO` retrieves zero evidence
   because the corpus has no service-procedure documents (generated-corpus
   design, see GOVERNANCE.md). Adding those docs is the highest-value next step.
2. **Judged metrics (faithfulness/relevancy/precision) unmeasured** without a
   cloud key. A single Groq-key run distinguishes "thin local planning" from a
   real coverage gap and unlocks these.

## Do not
- Present the Salik rate as current (it's the 2018 flat toll; the system says so).
- Claim any live RTA integration.
- Tune the grader threshold to force `SERVICE_INFO` to pass — that's a data gap,
  not a scorer bug, and hiding it makes the loop decorative.
