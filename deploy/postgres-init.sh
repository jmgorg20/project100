#!/bin/sh
# Runs once, when the Postgres container first creates its data folder (docker-entrypoint-initdb.d).
# The service must NOT connect as the superuser: row-level security does not apply to superusers.
# This makes an ordinary user, autoedit_app, that owns the database (it runs the migrations, and
# FORCE ROW LEVEL SECURITY then applies to it too). For an existing database or Supabase, run
# deploy/postgres-app-role.sql by hand instead.
set -eu
psql -v ON_ERROR_STOP=1 -v pw="$APP_DB_PASSWORD" -v db="$POSTGRES_DB" --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<'SQL'
CREATE ROLE autoedit_app LOGIN PASSWORD :'pw' NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;
ALTER DATABASE :"db" OWNER TO autoedit_app;
ALTER SCHEMA public OWNER TO autoedit_app;
SQL
