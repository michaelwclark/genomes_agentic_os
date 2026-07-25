#!/bin/sh
set -eu

password_file=/run/secrets/postgres-replication-password
if [ ! -s "$password_file" ]; then
  echo "missing postgres replication password secret" >&2
  exit 78
fi

replication_password=$(cat "$password_file")
psql --set=ON_ERROR_STOP=1 \
  --username "$POSTGRES_USER" \
  --dbname "$POSTGRES_DB" \
  --set=replication_password="$replication_password" <<'SQL'
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'fabric_replica') THEN
    CREATE ROLE fabric_replica WITH REPLICATION LOGIN;
  END IF;
END
$$;
SELECT format('ALTER ROLE fabric_replica PASSWORD %L', :'replication_password') \gexec
SELECT pg_create_physical_replication_slot('bigmac_fabric')
WHERE NOT EXISTS (
  SELECT 1 FROM pg_replication_slots WHERE slot_name = 'bigmac_fabric'
);
SQL
