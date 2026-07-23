-- =============================================================================
-- MASAR AI — database bootstrap
-- Runs once, on first container start, via docker-entrypoint-initdb.d.
--
-- Creates the extensions and the read-only role that the Text-to-SQL agent (A8)
-- executes under. The read-only role is layer three of A8's four-layer guard:
-- even if sqlglot parsing and the keyword denylist are both defeated, the
-- connection itself cannot mutate anything.
-- =============================================================================

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS unaccent;

-- ---------------------------------------------------------------------------
-- Read-only role for A8 (Text-to-SQL)
-- ---------------------------------------------------------------------------
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'masar_ro') THEN
        CREATE ROLE masar_ro LOGIN PASSWORD 'masar_ro_dev_password';
    END IF;
END
$$;

GRANT CONNECT ON DATABASE masar TO masar_ro;
GRANT USAGE ON SCHEMA public TO masar_ro;

-- Applies to tables that exist now...
GRANT SELECT ON ALL TABLES IN SCHEMA public TO masar_ro;
-- ...and to every table the ETL creates later.
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO masar_ro;

-- Belt and braces: explicitly strip write capability.
REVOKE CREATE ON SCHEMA public FROM masar_ro;
REVOKE ALL ON DATABASE masar FROM PUBLIC;

-- A8 enforces a 5s statement timeout in application code too; this is the
-- backstop that survives a client that forgets to set it.
ALTER ROLE masar_ro SET statement_timeout = '5s';
ALTER ROLE masar_ro SET default_transaction_read_only = on;

-- ---------------------------------------------------------------------------
-- Arabic full-text search configuration
-- Postgres ships no Arabic stemmer, so we index the normalised Arabic column
-- (alef unified, tatweel + diacritics stripped) with the 'simple' dictionary.
-- Normalisation happens in the Silver layer; see backend/ingestion/silver.py.
-- ---------------------------------------------------------------------------
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_ts_config WHERE cfgname = 'arabic_simple') THEN
        CREATE TEXT SEARCH CONFIGURATION arabic_simple (COPY = simple);
    END IF;
END
$$;
