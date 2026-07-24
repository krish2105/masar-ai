#!/usr/bin/env bash
# Health-gated deploy with rollback. Runs ON THE VM (invoked by hand or by the
# deploy workflow over SSH). Pulls main, rebuilds, and only keeps the new build
# if /health comes back — otherwise it resets to the previous commit and rebuilds
# that, so a bad deploy self-heals instead of leaving the site down.
set -euo pipefail

cd "$(dirname "$0")/.."  # repo root (this script lives in deploy/)

COMPOSE=(docker compose -f docker-compose.yml -f deploy/docker-compose.prod.yml --profile full)
HEALTH_URL="http://localhost:8000/health"

prev="$(git rev-parse HEAD)"
echo "→ current commit ${prev:0:8}"

git fetch --quiet origin main
git reset --hard origin/main
target="$(git rev-parse --short HEAD)"
echo "→ deploying ${target}"

"${COMPOSE[@]}" up -d --build

echo "→ waiting for health…"
for _ in $(seq 1 40); do
	if curl -fsS "$HEALTH_URL" >/dev/null 2>&1; then
		echo "✓ healthy at ${target}"
		exit 0
	fi
	sleep 3
done

echo "✗ ${target} did not become healthy — rolling back to ${prev:0:8}" >&2
git reset --hard "$prev"
"${COMPOSE[@]}" up -d --build
echo "↩ rolled back to ${prev:0:8}" >&2
exit 1
