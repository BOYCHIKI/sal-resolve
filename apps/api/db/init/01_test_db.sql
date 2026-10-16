-- Separate database for pytest, so tests never wipe the dev/demo data in "sal".
-- Runs on first container start; for an existing volume `.\sal setup` runs it again (idempotent).
SELECT 'CREATE DATABASE sal_test OWNER sal_migrator'
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = 'sal_test')\gexec
\connect sal_test
REVOKE ALL ON SCHEMA public FROM PUBLIC;
ALTER SCHEMA public OWNER TO sal_migrator;
GRANT USAGE ON SCHEMA public TO sal_app, sal_worker;
CREATE EXTENSION IF NOT EXISTS pgcrypto;
