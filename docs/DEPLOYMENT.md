# Deployment

## Live deployment status

| Component | Status | URL |
|---|---|---|
| **Source** | ✅ public | https://github.com/krish2105/masar-ai |
| **Front-end (UI)** | ✅ live on Vercel | https://masar-ai-xi.vercel.app |
| **Back-end** | ⚠️ local only — see below | — |

**What the live Vercel link shows:** the front-end UI — the landing page, the
Desert Ink design, the layout, the theme toggle. It renders fully and publicly.

**What it does _not_ do:** answer questions. The chat, `/explore` analytics and
the map all call the back-end API, and the back-end is not on a public host. Why
not:

1. It loads **~3.2 GB of local models** (`bge-m3` embeddings + `bge-reranker-v2-m3`)
   into memory. Free tiers (Vercel functions, Railway/Render 512 MB) cannot hold
   them — the process would OOM on the first retrieval.
2. With **no cloud LLM key**, generation falls back to local Ollama, which is not
   reachable from a cloud host. So even on paid hosting, chat needs either a free
   Groq/Gemini key or a self-hosted model.

A genuinely-live end-to-end demo therefore needs a host with ≥ 4 GB RAM **and** a
free LLM key. Both are one configuration step for the owner; neither is free.
`render.yaml` + `backend/Dockerfile` make the back-end deploy a single dashboard
action once those are in place — then set `NEXT_PUBLIC_API_BASE` in the Vercel
project to the back-end URL and the live site becomes fully functional.

**To see the whole system working now:** run it locally (one command, below). The
landing page on Vercel is the honest public artifact; the GitHub repo is the
runnable one.

> **Note for the owner:** the first Vercel deploy auto-linked to a *pre-existing*
> project named `frontend` (folder-name match) and promoted a production
> deployment there before I moved Masar to its own dedicated `masar-ai` project.
> If that `frontend` project served something else, re-promote its previous
> production deployment from the Vercel dashboard (the older deployments are still
> intact). Masar now lives only in the `masar-ai` project.

## Local

```bash
make setup
```

Creates the Python venv, installs backend and frontend dependencies, and copies
`.env.example` to `.env` if it does not exist.

```bash
make up
```

Starts Postgres 16 (with pgvector) and Redis, and waits for both healthchecks.

> **The database locale matters.** `docker-compose.yml` sets
> `--locale=C.UTF-8`, not `C`. Under `C`, pg_trgm classifies Arabic characters
> as non-word and generates **zero trigrams**, so
> `similarity('الاتحاد','الاتحاد')` returns 0 and every Arabic fuzzy match
> silently fails. If you change this, re-create the volume — `initdb` runs once.

```bash
make etl
```

Runs the full offline pipeline: bronze acquisition from the Internet Archive →
silver transformation with DQ reports → gold star schema loaded into Postgres →
corpus generation, embedding, and hybrid index build.

First run downloads `bge-m3` (~2.1 GB) and `bge-reranker-v2-m3` (~1.1 GB), and
acquisition takes roughly 10 minutes at the Archive's polite rate.

```bash
make dev
```

Runs the API and the frontend together.

### Optional: local inference

```bash
ollama serve
```

```bash
ollama pull qwen2.5:7b
```

Without this and without cloud keys the system still boots and reports its
degraded capabilities, but generation has no provider at all.

## Configuration

Every credential is optional. `Settings.capability_report()` names what each
absent key degrades, the startup log prints it, and `/health/ready` serves it.

| Variable | Effect when absent |
|---|---|
| `GROQ_API_KEY` | Fast routing and grading fall back to Cerebras/Ollama |
| `GEMINI_API_KEY` | Planning, Text-to-SQL and Arabic synthesis lose their strongest model |
| `CEREBRAS_API_KEY` | One fallback tier removed from every chain |
| `DUBAI_PULSE_API_KEY`/`SECRET` | A9 serves archived snapshots only — **the expected default** |
| `LANGSMITH_API_KEY` | Tracing writes to local JSONL instead |

Free keys, no credit card: [console.groq.com](https://console.groq.com/keys) ·
[aistudio.google.com](https://aistudio.google.com/apikey) ·
[cloud.cerebras.ai](https://cloud.cerebras.ai)

## Production notes

### Streaming does not survive a buffering proxy

The Next.js `rewrites()` proxy buffers response bodies. That is invisible for
JSON and fatal for SSE — the whole stream arrives at once, after the turn has
finished, so nothing appears live. The client therefore posts the stream
directly to the backend origin (`NEXT_PUBLIC_API_BASE`), with CORS configured
for it.

Any reverse proxy in front of the API needs the same treatment:

```nginx
location /api/v1/chat/stream {
    proxy_pass http://backend:8000;
    proxy_buffering off;
    proxy_cache off;
    proxy_read_timeout 300s;
    chunked_transfer_encoding on;
}
```

### SSE frames are CRLF-delimited

`sse_starlette` emits `\r\n\r\n` between frames. A client splitting on `\n\n`
parses **zero** events from a stream that looks perfect on the wire. The client
in `lib/api.ts` normalises line endings before framing.

### Read-only role

The Text-to-SQL agent connects as `masar_ro`, which has `SELECT` only,
`default_transaction_read_only = on` and `statement_timeout = 5s`. Change the
password in `scripts/init_db.sql` and `.env` before exposing anything.

`ALTER DEFAULT PRIVILEGES` covers tables created later, and `load_all()`
re-grants after each rebuild.

### Resource requirements

| Component | Memory | Disk |
|---|---|---|
| Postgres + Redis | ~512 MB | ~1 GB |
| Embedding + reranker models | ~2 GB resident | ~3.3 GB |
| Bronze data | — | ~275 MB |
| Backend process | ~1.5 GB with models loaded | — |

The models load lazily on first retrieval, so an idle API is light. In a
multi-worker deployment each worker loads its own copy — either pin one worker
or move embedding behind a dedicated service.

## Hosting

`vercel.json` and `render.yaml` are provided.

**Frontend (Vercel):** root `frontend/`, set `NEXT_PUBLIC_API_BASE` to the
backend URL.

**Backend:** needs persistent Postgres with pgvector and enough memory for the
models. Free tiers with a 512 MB ceiling will not hold `bge-m3`; either use a
paid tier or run retrieval against a hosted embedding endpoint.

**Do not deploy publicly without reading [GOVERNANCE.md](GOVERNANCE.md).** The
affiliation disclaimer must remain visible, and free LLM tiers use submitted
prompts as training data.
