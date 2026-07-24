# Deploy — Oracle always-free VM

Everything needed to take the backend live at **$0** on an Oracle always-free A1
ARM VM (4 OCPU / 24 GB, always-on), running the existing `docker-compose` stack
**unchanged** behind Caddy for automatic HTTPS. The Vercel frontend already
deploys itself from `main`; this directory is only the backend.

| File | What it is |
|---|---|
| [`provision.md`](provision.md) | One-time manual VM setup + hardening (Phase 0) |
| [`Caddyfile`](Caddyfile) | TLS + SSE-safe reverse proxy + security headers |
| [`docker-compose.prod.yml`](docker-compose.prod.yml) | Overlay adding Caddy; closes the API's public port |
| [`deploy.sh`](deploy.sh) | Health-gated deploy with automatic rollback (runs on the VM) |
| [`backup.sh`](backup.sh) | Nightly `pg_dump` → Oracle Object Storage |
| [`restore.md`](restore.md) | Restore-from-backup runbook + rehearsal |

CI (`.github/workflows/ci.yml`) lints + tests the backend and builds the frontend
on every PR. CD (`.github/workflows/deploy.yml`) runs `deploy.sh` over SSH — manual
by default; enable its `push` trigger once the VM secrets are set.

## Going live

After [`provision.md`](provision.md) (VM created, Docker installed, repo cloned to
`~/masar`, `.env` filled), from `~/masar` on the VM:

```bash
# 1. Build the lakehouse in Postgres (or restore a pg_dump from local — faster).
make etl

# 2. (optional) Load the reachability graph.
docker compose --profile graph up -d neo4j
python -m backend.graph_rag.loader

# 3. Bring up the full stack behind Caddy (auto-HTTPS on $MASAR_HOSTNAME).
docker compose -f docker-compose.yml -f deploy/docker-compose.prod.yml \
  --profile full up -d --build
```

Then, once (Vercel side): set `NEXT_PUBLIC_API_BASE=https://<MASAR_HOSTNAME>` in
the `masar-ai` Vercel project and redeploy, and confirm `CORS_ORIGINS` in the VM's
`.env` includes `https://masar-ai-xi.vercel.app`.

**Gate:** a public visitor asks a question on the live URL and gets a cited answer
in seconds.

```bash
curl -fsS https://<MASAR_HOSTNAME>/health
curl -s -i -X OPTIONS https://<MASAR_HOSTNAME>/api/v1/chat/stream \
  -H "Origin: https://masar-ai-xi.vercel.app" \
  -H "Access-Control-Request-Method: POST" | grep -i access-control
```

## Ongoing

```bash
# Deploy the latest main (health-gated, self-rolling-back):
bash ~/masar/deploy/deploy.sh

# Nightly backups (cron):
( crontab -l 2>/dev/null; echo '0 3 * * * /home/ubuntu/masar/deploy/backup.sh' ) | crontab -

# Watch logs:
docker compose -f docker-compose.yml -f deploy/docker-compose.prod.yml --profile full logs -f caddy api
```

## CD secrets (for the deploy workflow)

Set in the GitHub repo (Settings → Secrets → Actions), then uncomment the `push`
trigger in `.github/workflows/deploy.yml`:

- `VM_SSH_KEY` — a deploy private key (its public half in the VM's `~/.ssh/authorized_keys`)
- `VM_HOST` — the VM's IP or hostname
- `VM_USER` — `ubuntu`

## Not here yet (Phase 4)

Edge rate-limiting (needs a custom Caddy build with `caddy-ratelimit`), log
shipping, and UptimeRobot monitoring — the ops-hardening phase.
