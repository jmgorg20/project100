-- The database user for the service (Supabase SQL editor, or psql as an admin on any Postgres).
-- Row-level security does not apply to superusers or BYPASSRLS users, so the service connects as
-- this ordinary user. Replace CHANGE_ME with a long random password, then use
--   SERVICE_DATABASE_URL=postgresql://autoedit_app:<password>@<host>:5432/<database>
-- The service creates its tables itself (as this user) on first start.
CREATE ROLE autoedit_app LOGIN PASSWORD 'CHANGE_ME' NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;
CREATE SCHEMA IF NOT EXISTS autoedit AUTHORIZATION autoedit_app;
ALTER ROLE autoedit_app SET search_path = autoedit;
-- Check: /readyz on the service must say "rls": "enforced".
