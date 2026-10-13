-- Runs once when the local dev container is first created (as the postgres superuser).
-- Least-privilege roles (SAL v1.1 §6.3). None of them is superuser or BYPASSRLS.
-- Passwords are dev-only; deployed databases get their own secrets.

CREATE ROLE sal_migrator LOGIN PASSWORD 'migrator_dev_only' NOSUPERUSER NOBYPASSRLS NOCREATEROLE NOCREATEDB;
CREATE ROLE sal_app      LOGIN PASSWORD 'app_dev_only'      NOSUPERUSER NOBYPASSRLS NOCREATEROLE NOCREATEDB;
CREATE ROLE sal_worker   LOGIN PASSWORD 'worker_dev_only'   NOSUPERUSER NOBYPASSRLS NOCREATEROLE NOCREATEDB;

CREATE DATABASE sal OWNER sal_migrator;
\connect sal
REVOKE ALL ON SCHEMA public FROM PUBLIC;
ALTER SCHEMA public OWNER TO sal_migrator;
GRANT USAGE ON SCHEMA public TO sal_app, sal_worker;
CREATE EXTENSION IF NOT EXISTS pgcrypto;
