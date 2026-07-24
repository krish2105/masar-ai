# Restore from backup

`backup.sh` writes a gzipped `pg_dump` to Oracle Object Storage every night. To
restore — after a bad migration, a lost volume, or onto a fresh VM:

## 1. Fetch the latest dump

```bash
cd ~/masar
# List backups, newest last:
oci os object list -bn "${MASAR_BACKUP_BUCKET:-masar-backups}" --query 'data[].name' --output table
# Download one:
oci os object get -bn "${MASAR_BACKUP_BUCKET:-masar-backups}" --name masar_<STAMP>.sql.gz --file /tmp/restore.sql.gz
```

## 2. Restore into Postgres

The container must be up (`docker compose up -d postgres`). Restoring over the
live database drops and recreates its objects, so do this in a maintenance window
or against a scratch database first (below).

```bash
gunzip -c /tmp/restore.sql.gz | docker compose exec -T postgres psql -U masar masar
```

## 3. Verify

```bash
docker compose exec -T postgres psql -U masar masar -c "select count(*) from chunks;"
# Expect ~869 (the indexed chunk count). Then:
curl -fsS http://localhost:8000/health
```

## Rehearse without touching production

Restore into a throwaway database to prove the dump is good, before you ever need
it for real:

```bash
docker compose exec -T postgres psql -U masar -c "create database masar_restore_test;"
gunzip -c /tmp/restore.sql.gz | docker compose exec -T postgres psql -U masar masar_restore_test
docker compose exec -T postgres psql -U masar masar_restore_test -c "select count(*) from chunks;"
docker compose exec -T postgres psql -U masar -c "drop database masar_restore_test;"
```

Record the row count and the date rehearsed here after each drill:

| Date rehearsed | Dump stamp | chunks | Result |
|---|---|---|---|
| _(fill in)_ | | | |
