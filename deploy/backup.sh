#!/usr/bin/env bash
# Nightly Postgres backup → Oracle Object Storage (20 GB always-free). Runs ON
# THE VM from cron:  0 3 * * *  /home/ubuntu/masar/deploy/backup.sh
#
# If the OCI CLI is not configured the dump is kept locally and the script still
# succeeds loudly, so a missing cloud upload never fails silently.
set -euo pipefail

cd "$(dirname "$0")/.."  # repo root

# shellcheck source=/dev/null
[ -f .env ] && set -a && . ./.env && set +a

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
FILE="masar_${STAMP}.sql.gz"
LOCAL="/tmp/${FILE}"
BUCKET="${MASAR_BACKUP_BUCKET:-masar-backups}"
PG_USER="${POSTGRES_USER:-masar}"
PG_DB="${POSTGRES_DB:-masar}"

echo "→ dumping ${PG_DB} → ${LOCAL}"
docker compose exec -T postgres pg_dump -U "$PG_USER" "$PG_DB" | gzip >"$LOCAL"
echo "  dump size: $(du -h "$LOCAL" | cut -f1)"

if command -v oci >/dev/null 2>&1; then
	oci os object put -bn "$BUCKET" --file "$LOCAL" --name "$FILE" --force
	echo "✓ uploaded ${FILE} to bucket ${BUCKET}"
else
	echo "⚠ OCI CLI not found — backup kept at ${LOCAL} (configure 'oci setup config' to upload)" >&2
fi

# Prune local dumps older than 2 days; Object Storage retention is managed there.
find /tmp -maxdepth 1 -name 'masar_*.sql.gz' -mtime +2 -delete 2>/dev/null || true
