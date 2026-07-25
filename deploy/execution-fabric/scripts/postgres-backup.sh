#!/bin/sh
set -eu
umask 077

: "${PGHOST:?PGHOST is required}"
: "${PGDATABASE:?PGDATABASE is required}"
: "${PGUSER:?PGUSER is required}"
: "${PGPASSFILE:?PGPASSFILE is required}"
: "${FABRIC_BACKUP_HEALTH_RECEIPT_FILE:?FABRIC_BACKUP_HEALTH_RECEIPT_FILE is required}"

if [ ! -s "$PGPASSFILE" ]; then
  echo "missing postgres pgpass secret" >&2
  exit 78
fi

for required_command in pg_dump pg_restore psql createdb dropdb; do
  command -v "$required_command" >/dev/null 2>&1 || {
    echo "required backup command is unavailable: $required_command" >&2
    exit 69
  }
done

sha256_file() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | awk '{print $1}'
  elif command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$1" | awk '{print $1}'
  else
    echo "sha256sum or shasum is required" >&2
    exit 69
  fi
}

backup_dir=${FABRIC_BACKUP_DIR:-/var/backups/postgresql/logical}
receipt=$FABRIC_BACKUP_HEALTH_RECEIPT_FILE
receipt_dir=$(dirname "$receipt")
manifest_name=backup-health.restore-manifest.json
manifest="$receipt_dir/$manifest_name"
mkdir -p "$backup_dir" "$receipt_dir"
timestamp=$(date -u +%Y%m%dT%H%M%SZ)
verified_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)
run_id=${FABRIC_BACKUP_RUN_ID:-"backup-$timestamp-$$"}
case "$run_id" in
  ""|*[!A-Za-z0-9._-]*)
    echo "FABRIC_BACKUP_RUN_ID must contain only letters, numbers, dot, underscore, or dash" >&2
    exit 78
    ;;
esac
temporary="$backup_dir/$PGDATABASE-$timestamp.dump.partial"
complete="$backup_dir/$PGDATABASE-$timestamp.dump"
archive_list="$backup_dir/$PGDATABASE-$timestamp.archive-list.partial"
readback="$backup_dir/$PGDATABASE-$timestamp.readback.partial"
manifest_temporary="$manifest.partial.$$"
receipt_temporary="$receipt.partial.$$"
restore_database="fabric_restore_$(printf '%s' "$timestamp" | tr -cd '0-9')_$$"
restore_created=false

cleanup() {
  status=$?
  trap - EXIT HUP INT TERM
  if [ "$restore_created" = true ]; then
    dropdb --if-exists "$restore_database" >/dev/null 2>&1 || true
  fi
  rm -f "$temporary" "$archive_list" "$readback" \
    "$manifest_temporary" "$receipt_temporary"
  exit "$status"
}
trap cleanup EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

pg_dump --format=custom --file="$temporary"
pg_restore --list "$temporary" >"$archive_list"
[ -s "$archive_list" ] || {
  echo "backup archive manifest is empty" >&2
  exit 75
}

# Restore into a unique database on the same PostgreSQL server. The source
# database is never selected as a restore target.
createdb --template=template0 "$restore_database"
restore_created=true
pg_restore --exit-on-error --no-owner --no-privileges \
  --dbname="$restore_database" "$temporary"

# Read restored catalog objects and every restored table. pg_restore success
# alone is not treated as proof that the restored database can be queried.
psql --no-psqlrc --set=ON_ERROR_STOP=1 --dbname="$restore_database" \
  --tuples-only --no-align --field-separator='|' >"$readback" <<'SQL'
SELECT 'READBACK', current_database() IS NOT NULL;
SELECT 'SCHEMA', encode(convert_to(nspname, 'UTF8'), 'hex')
FROM pg_namespace
WHERE nspname NOT LIKE 'pg_%' AND nspname <> 'information_schema'
ORDER BY nspname;
SELECT 'RELATION',
       encode(convert_to(n.nspname || '.' || c.relname, 'UTF8'), 'hex'),
       c.relkind
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname NOT LIKE 'pg_%'
  AND n.nspname <> 'information_schema'
  AND c.relkind IN ('r', 'p', 'v', 'm', 'S', 'f')
ORDER BY n.nspname, c.relname, c.relkind;
SELECT format(
  'SELECT %L, count(*)::bigint FROM %I.%I;',
  'ROWCOUNT|' || encode(convert_to(n.nspname || '.' || c.relname, 'UTF8'), 'hex'),
  n.nspname,
  c.relname
)
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname NOT LIKE 'pg_%'
  AND n.nspname <> 'information_schema'
  AND c.relkind IN ('r', 'p')
ORDER BY n.nspname, c.relname
\gexec
SQL

if [ ! -s "$readback" ] || ! grep -q '^READBACK|t$' "$readback"; then
  echo "restored database readback failed" >&2
  exit 75
fi

archive_sha=$(sha256_file "$archive_list")
readback_sha=$(sha256_file "$readback")
backup_sha=$(sha256_file "$temporary")
backup_bytes=$(wc -c <"$temporary" | tr -d ' ')
archive_entries=$(awk 'substr($0,1,1)!=";" && NF {count++} END {print count+0}' "$archive_list")
readback_lines=$(wc -l <"$readback" | tr -d ' ')
table_count=$(awk -F '|' '$1=="ROWCOUNT" {count++} END {print count+0}' "$readback")

dropdb "$restore_database"
restore_created=false
dropped=$(psql --no-psqlrc --set=ON_ERROR_STOP=1 --dbname="$PGDATABASE" \
  --tuples-only --no-align --set=restore_database="$restore_database" <<'SQL'
SELECT NOT EXISTS (
  SELECT 1 FROM pg_database WHERE datname = :'restore_database'
);
SQL
)
[ "$dropped" = t ] || {
  echo "disposable restore database was not removed" >&2
  exit 75
}

mv "$temporary" "$complete"
[ "$(sha256_file "$complete")" = "$backup_sha" ] || {
  echo "completed backup hash differs from verified backup" >&2
  exit 75
}

cat >"$manifest_temporary" <<EOF
{"schemaVersion":"execution-fabric-postgres-restore-manifest/v1","runId":"$run_id","backupFile":"$(basename "$complete")","backupSha256":"$backup_sha","backupBytes":$backup_bytes,"archiveManifestSha256":"$archive_sha","archiveEntryCount":$archive_entries,"readbackManifestSha256":"$readback_sha","readbackLineCount":$readback_lines,"tableCount":$table_count,"restoreDatabaseCreated":true,"restoreCompleted":true,"readbackCompleted":true,"restoreDatabaseDropped":true}
EOF
mv "$manifest_temporary" "$manifest"
manifest_sha=$(sha256_file "$manifest")

cat >"$receipt_temporary" <<EOF
{"schemaVersion":"execution-fabric-backup-health/v1","status":"passed","runId":"$run_id","verifiedAt":"$verified_at","backupFile":"$(basename "$complete")","backupSha256":"$backup_sha","restoreManifestVerified":true,"restoreManifest":{"schemaVersion":"execution-fabric-postgres-restore-manifest/v1","file":"$manifest_name","sha256":"$manifest_sha"}}
EOF
mv "$receipt_temporary" "$receipt"

retention_days=${FABRIC_BACKUP_RETENTION_DAYS:-14}
find "$backup_dir" -type f -name '*.dump' -mtime "+$retention_days" -delete
rm -f "$archive_list" "$readback"
trap - EXIT HUP INT TERM
printf '%s\n' "$receipt"
