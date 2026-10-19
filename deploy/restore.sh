#!/bin/sh
# Restore a backup made by deploy/backup.sh.
#
#   deploy/restore.sh --check BACKUP_FILE    restore into a new scratch database, check it, drop it
#                                            (the restore test: run it monthly and after upgrades)
#   deploy/restore.sh BACKUP_FILE            restore into RESTORE_DATABASE_URL (must be empty)
#
# RESTORE_DATABASE_URL (or BACKUP_DATABASE_URL) is an admin user (superuser or BYPASSRLS) of the
# target database; the tables are then given to APP_DB_USER (default autoedit_app), the user the
# service connects as, so row-level security applies to the service as before. Encrypted backups
# (.gpg) are decrypted with your gpg key. Stop the service (API and janitor) before a real restore.
set -eu
CHECK=0
if [ "${1:-}" = "--check" ]; then CHECK=1; shift; fi
FILE="${1:?usage: deploy/restore.sh [--check] BACKUP_FILE}"
URL="${RESTORE_DATABASE_URL:-${BACKUP_DATABASE_URL:-}}"
: "${URL:?set RESTORE_DATABASE_URL (an admin user of the target database)}"
APP="${APP_DB_USER:-autoedit_app}"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

case "$FILE" in
  *.gpg) gpg --batch --quiet --output "$TMP/backup.dump" --decrypt "$FILE"; FILE="$TMP/backup.dump" ;;
esac
pg_restore --list "$FILE" > /dev/null

TARGET="$URL"
if [ "$CHECK" = 1 ]; then
  SCRATCH="autoedit_restore_check_$(date -u +%Y%m%d%H%M%S)"
  psql -X -q -v ON_ERROR_STOP=1 "$URL" -c "CREATE DATABASE \"$SCRATCH\""
  TARGET="$(python3 -c 'import sys, urllib.parse as u; p = u.urlsplit(sys.argv[1]); print(u.urlunsplit(p._replace(path="/" + sys.argv[2])))' "$URL" "$SCRATCH")"
else
  if [ "$(psql -X -At "$TARGET" -c "SELECT COUNT(*) FROM pg_tables WHERE tablename = 'schema_migrations'")" != "0" ]; then
    echo "restore: the target database is not empty (it has schema_migrations). Use a new database." >&2
    exit 1
  fi
fi

pg_restore --no-owner --no-privileges --exit-on-error --dbname="$TARGET" "$FILE"

SCHEMA="$(psql -X -At "$TARGET" -c "SELECT schemaname FROM pg_tables WHERE tablename = 'schema_migrations'")"
if psql -X -At "$TARGET" -c "SELECT 1 FROM pg_roles WHERE rolname = '$APP'" | grep -q 1; then
  psql -X -q -v ON_ERROR_STOP=1 -v app="$APP" -v schema="$SCHEMA" "$TARGET" <<'SQL'
SELECT format('ALTER SCHEMA %I OWNER TO %I', :'schema', :'app') \gexec
SELECT format('ALTER TABLE %I.%I OWNER TO %I', schemaname, tablename, :'app') FROM pg_tables WHERE schemaname = :'schema' \gexec
SELECT format('ALTER SEQUENCE %I.%I OWNER TO %I', schemaname, sequencename, :'app') FROM pg_sequences WHERE schemaname = :'schema' \gexec
SQL
else
  echo "restore: no user $APP on this server: the tables stay owned by the admin user (create $APP, see deploy/postgres-app-role.sql, and run this again)" >&2
fi

# the checks: migrations present, every table readable, row-level security still on
MIGRATIONS="$(psql -X -At "$TARGET" -c "SELECT COUNT(*) FROM \"$SCHEMA\".schema_migrations")"
NO_RLS="$(psql -X -At "$TARGET" -c "SELECT string_agg(relname, ',') FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace WHERE n.nspname = '$SCHEMA' AND relname IN ('clients','uploads','jobs','outputs','usage','subscriptions','payments','reports') AND NOT (relrowsecurity AND relforcerowsecurity)")"
echo "restore: $MIGRATIONS migrations"
for t in users clients jobs outputs payments audit_log reports; do
  echo "restore: $t $(psql -X -At "$TARGET" -c "SELECT COUNT(*) FROM \"$SCHEMA\".$t")"
done
STATUS=0
[ "$MIGRATIONS" -gt 0 ] || { echo "restore: FAILED (no migrations)" >&2; STATUS=1; }
[ -z "$NO_RLS" ] || { echo "restore: FAILED (row-level security off on: $NO_RLS)" >&2; STATUS=1; }

if [ "$CHECK" = 1 ]; then
  psql -X -q "$URL" -c "DROP DATABASE \"$SCRATCH\""
fi
[ "$STATUS" = 0 ] && echo "restore: OK"
exit "$STATUS"
