#!/bin/sh
# Same roles as apps/api/db/init/00_roles.sql, with the passwords from deploy/.env instead of the dev-only ones.
# Runs once, when the database volume is first created.
set -eu
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres <<SQL
CREATE ROLE sal_migrator LOGIN PASSWORD '${SAL_MIGRATOR_PASSWORD}' NOSUPERUSER NOBYPASSRLS NOCREATEROLE NOCREATEDB;
CREATE ROLE sal_app      LOGIN PASSWORD '${SAL_APP_PASSWORD}'      NOSUPERUSER NOBYPASSRLS NOCREATEROLE NOCREATEDB;
CREATE ROLE sal_worker   LOGIN PASSWORD '${SAL_WORKER_PASSWORD}'   NOSUPERUSER NOBYPASSRLS NOCREATEROLE NOCREATEDB;
CREATE DATABASE sal OWNER sal_migrator;
\connect sal
REVOKE ALL ON SCHEMA public FROM PUBLIC;
ALTER SCHEMA public OWNER TO sal_migrator;
GRANT USAGE ON SCHEMA public TO sal_app, sal_worker;
CREATE EXTENSION IF NOT EXISTS pgcrypto;
SQL
