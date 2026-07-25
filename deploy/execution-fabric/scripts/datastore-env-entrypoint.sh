#!/bin/sh
set -eu

# The control-plane image still consumes conventional connection URLs. Build
# them only inside the container process from mounted secret files so Compose
# configuration and runtime.env never contain datastore passwords.
database_password_file=${FABRIC_DATABASE_PASSWORD_FILE:-/run/secrets/postgres-password}
[ -s "$database_password_file" ] || {
  echo "missing PostgreSQL application password secret" >&2
  exit 78
}

database_password=$(cat "$database_password_file")
case "$database_password" in
  ''|*[!A-Za-z0-9._~-]*)
    echo "PostgreSQL application password must be a URL-safe token" >&2
    exit 78
    ;;
esac

database_user=${FABRIC_POSTGRES_USER:-fabric}
database_host=${FABRIC_DATABASE_HOST:-postgres}
database_port=${FABRIC_DATABASE_PORT:-5432}
database_name=${FABRIC_POSTGRES_DB:-execution_fabric}
FABRIC_DATABASE_URL="postgresql://${database_user}:${database_password}@${database_host}:${database_port}/${database_name}"
export FABRIC_DATABASE_URL
unset database_password

if [ -n "${FABRIC_VALKEY_PASSWORD_FILE:-}" ]; then
  [ -s "$FABRIC_VALKEY_PASSWORD_FILE" ] || {
    echo "missing Valkey application password secret" >&2
    exit 78
  }
  valkey_password=$(cat "$FABRIC_VALKEY_PASSWORD_FILE")
  case "$valkey_password" in
    ''|*[!A-Za-z0-9._~-]*)
      echo "Valkey application password must be a URL-safe token" >&2
      exit 78
      ;;
  esac
  valkey_user=${FABRIC_VALKEY_USER:-fabric}
  valkey_host=${FABRIC_VALKEY_HOST:-valkey}
  valkey_port=${FABRIC_VALKEY_PORT:-6379}
  valkey_database=${FABRIC_VALKEY_DATABASE:-0}
  FABRIC_VALKEY_URL="redis://${valkey_user}:${valkey_password}@${valkey_host}:${valkey_port}/${valkey_database}"
  export FABRIC_VALKEY_URL
  unset valkey_password
fi

exec "$@"
