#!/bin/sh
set -eu

: "${PGHOST:?PGHOST is required}"
: "${PGDATABASE:?PGDATABASE is required}"
: "${PGUSER:?PGUSER is required}"
: "${PGPASSFILE:?PGPASSFILE is required}"

if [ ! -s "$PGPASSFILE" ]; then
  echo "missing postgres pgpass secret" >&2
  exit 78
fi

backup_dir=/var/backups/postgresql/logical
mkdir -p "$backup_dir"
timestamp=$(date -u +%Y%m%dT%H%M%SZ)
temporary="$backup_dir/$PGDATABASE-$timestamp.dump.partial"
complete="$backup_dir/$PGDATABASE-$timestamp.dump"

trap 'rm -f "$temporary"' EXIT HUP INT TERM
pg_dump --format=custom --file="$temporary"
pg_restore --list "$temporary" >/dev/null
mv "$temporary" "$complete"
trap - EXIT HUP INT TERM

retention_days=${FABRIC_BACKUP_RETENTION_DAYS:-14}
find "$backup_dir" -type f -name '*.dump' -mtime "+$retention_days" -delete
printf '%s\n' "$complete"
