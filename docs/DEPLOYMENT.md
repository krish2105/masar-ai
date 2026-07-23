# Deployment

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
