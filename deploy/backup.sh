#!/bin/sh
# Back up the service's database (accounts, jobs, billing, audit log). Videos are not backed up:
# they are temporary by design (deleted after a few days).
#
#   BACKUP_DATABASE_URL=postgresql://postgres:...@host:5432/autoedit  deploy/backup.sh [folder]
#
# BACKUP_DATABASE_URL must be an admin user (superuser or BYPASSRLS, e.g. Supabase's "postgres"), NOT
# the service's autoedit_app user: row-level security would hide every row from a dump made as the
# service. Writes <folder>/autoedit-<UTC time>.dump (pg_dump custom format), encrypted to
# <...>.dump.gpg when BACKUP_GPG_RECIPIENT is set, and deletes backups older than BACKUP_KEEP_DAYS
# (default 14). Run it daily (cron / a scheduled task) and copy the folder off the server.
# Test a backup with deploy/restore.sh --check (do that at least monthly).
set -eu
umask 077
: "${BACKUP_DATABASE_URL:?set BACKUP_DATABASE_URL (an admin user, see the top of this file)}"
DIR="${1:-${BACKUP_DIR:-./backups}}"
KEEP="${BACKUP_KEEP_DAYS:-14}"
mkdir -p "$DIR"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUT="$DIR/autoedit-$STAMP.dump"

pg_dump --format=custom --no-owner --no-privileges --compress=6 --file="$OUT.part" "$BACKUP_DATABASE_URL"
# a dump that cannot be listed is not a backup
pg_restore --list "$OUT.part" | grep -q "TABLE DATA .*schema_migrations" \
  || { echo "backup: the dump has no schema_migrations table: wrong database or user?" >&2; rm -f "$OUT.part"; exit 1; }
mv "$OUT.part" "$OUT"

if [ -n "${BACKUP_GPG_RECIPIENT:-}" ]; then
  gpg --batch --yes --trust-model always --recipient "$BACKUP_GPG_RECIPIENT" --output "$OUT.gpg" --encrypt "$OUT"
  rm -f "$OUT"
  OUT="$OUT.gpg"
fi

find "$DIR" -maxdepth 1 -name 'autoedit-*.dump*' -type f -mtime +"$KEEP" -delete
echo "backup: $OUT ($(wc -c < "$OUT") bytes)"
