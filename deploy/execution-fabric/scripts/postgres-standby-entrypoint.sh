#!/bin/sh
set -eu

: "${PGDATA:?PGDATA is required}"
: "${FABRIC_PRIMARY_POSTGRES_HOST:?primary postgres host is required}"

if [ ! -s "$PGPASSFILE" ]; then
  echo "missing replication pgpass secret" >&2
  exit 78
fi

if [ ! -s "$PGDATA/PG_VERSION" ]; then
  if [ -n "$(find "$PGDATA" -mindepth 1 -maxdepth 1 -print -quit 2>/dev/null)" ]; then
    echo "standby data directory is non-empty but has no PG_VERSION; refusing to overwrite" >&2
    exit 70
  fi
  pg_basebackup \
    --host="$FABRIC_PRIMARY_POSTGRES_HOST" \
    --port="${FABRIC_POSTGRES_REPLICATION_PORT:-35432}" \
    --username=fabric_replica \
    --pgdata="$PGDATA" \
    --write-recovery-conf \
    --slot=bigmac_fabric \
    --wal-method=stream \
    --checkpoint=fast \
    --progress
  chmod 0700 "$PGDATA"
fi

exec docker-entrypoint.sh "$@"
