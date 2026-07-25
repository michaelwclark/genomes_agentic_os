#!/bin/sh
set -eu

usage() {
  echo "usage: enable-postgres-durable-primary.sh --apply --expected-leader HOST [--degraded-primary]" >&2
  exit 64
}

apply=false
expected_leader=
degraded_primary=false
while [ "$#" -gt 0 ]; do
  case "$1" in
    --apply) apply=true ;;
    --expected-leader) shift; [ "$#" -gt 0 ] || usage; expected_leader=$1 ;;
    --degraded-primary) degraded_primary=true ;;
    *) usage ;;
  esac
  shift
done
[ "$apply" = true ] && [ -n "$expected_leader" ] || usage

script_dir=$(CDPATH="" cd -- "$(dirname -- "$0")" && pwd)
. "$script_dir/_lib.sh"
fabric_load_runtime
fabric_require_command curl
fabric_require_command docker
fabric_require_command jq

: "${FABRIC_HOST_ID:?local fabric host id is required}"
: "${FABRIC_PRIMARY_HOST_ID:?primary fabric host id is required}"
: "${FABRIC_STANDBY_HOST_ID:?standby fabric host id is required}"
: "${FABRIC_DEPLOYMENT_DIR:?installed deployment directory is required}"
: "${FABRIC_LEADERSHIP_API_BASE:?independent witness API is required}"
: "${FABRIC_LEADERSHIP_TOKEN_FILE:?witness reader token is required}"
[ "$FABRIC_HOST_ID" = "$expected_leader" ] || {
  echo "local host does not match expected leader" >&2
  exit 75
}

if [ "$FABRIC_HOST_ID" = "$FABRIC_PRIMARY_HOST_ID" ]; then
    compose_file="$FABRIC_DEPLOYMENT_DIR/compose.genomesbox.yml"
    compose_profile=primary
elif [ "$FABRIC_HOST_ID" = "$FABRIC_STANDBY_HOST_ID" ]; then
    compose_file="$FABRIC_DEPLOYMENT_DIR/compose.bigmac.yml"
    compose_profile=promoted
else
    echo "unsupported durable primary host: $FABRIC_HOST_ID" >&2
    exit 75
fi
status_temp=$(mktemp "${TMPDIR:-/tmp}/fabric-durability-status.XXXXXX")
receipt_temp=$(mktemp "${TMPDIR:-/tmp}/fabric-durability-receipt.XXXXXX")
trap 'rm -f "$status_temp" "$receipt_temp"' EXIT HUP INT TERM

fabric_api_get_bearer \
  "$FABRIC_LEADERSHIP_API_BASE" \
  "/api/v1/admin/leadership/status" \
  "$FABRIC_LEADERSHIP_TOKEN_FILE" >"$status_temp"
[ "$(fabric_json_field "$status_temp" '.currentLeader')" = "$expected_leader" ] || {
  echo "witness does not name this host as current leader" >&2
  exit 75
}

psql_primary() {
  fabric_compose "$compose_file" --profile "$compose_profile" exec -T postgres \
    psql -X -qAt -v ON_ERROR_STOP=1 \
      -U "${FABRIC_POSTGRES_USER:-fabric}" \
      -d "${FABRIC_POSTGRES_DB:-execution_fabric}" "$@"
}

[ "$(psql_primary -c 'SELECT pg_is_in_recovery()')" = f ] || {
  echo "durability activation requires a promoted PostgreSQL primary" >&2
  exit 75
}

if [ "$degraded_primary" = true ]; then
  [ "${FABRIC_ALLOW_DEGRADED_PRIMARY:-false}" = true ] || {
    echo "degraded-primary durability is disabled" >&2
    exit 75
  }
  psql_primary -c "ALTER SYSTEM SET synchronous_standby_names = ''"
  psql_primary -c "ALTER SYSTEM SET synchronous_commit = 'on'"
  psql_primary -c "SELECT pg_reload_conf()"
  verification=$(psql_primary -F '|' -c \
    "SELECT current_setting('synchronous_commit'),
            current_setting('fsync'),
            current_setting('full_page_writes'),
            current_setting('archive_mode')")
  commit_mode=$(printf '%s' "$verification" | cut -d '|' -f 1)
  fsync_mode=$(printf '%s' "$verification" | cut -d '|' -f 2)
  full_page_writes=$(printf '%s' "$verification" | cut -d '|' -f 3)
  archive_mode=$(printf '%s' "$verification" | cut -d '|' -f 4)
  [ "$commit_mode" = on ] &&
    [ "$fsync_mode" = on ] &&
    [ "$full_page_writes" = on ] &&
    [ "$archive_mode" = on ] || {
    echo "degraded-primary local durability readback failed" >&2
    exit 75
  }
  jq -n \
    --arg hostId "$FABRIC_HOST_ID" \
    --arg expectedLeader "$expected_leader" \
    --arg synchronousCommit "$commit_mode" \
    --arg fsync "$fsync_mode" \
    --arg fullPageWrites "$full_page_writes" \
    --arg archiveMode "$archive_mode" \
    --arg verifiedAt "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    '{schemaVersion:"execution-fabric-postgres-durability-receipt/v1",
      hostId:$hostId,expectedLeader:$expectedLeader,
      authorityMode:"degraded_primary",
      synchronousCommit:$synchronousCommit,fsync:$fsync,
      fullPageWrites:$fullPageWrites,archiveMode:$archiveMode,
      mutationDurabilityReady:true,verifiedAt:$verifiedAt}' >"$receipt_temp"
  fabric_atomic_write \
    "$FABRIC_RUNTIME_STATE_DIR/postgres-durability.receipt.json" \
    "$receipt_temp"
  cat "$receipt_temp"
  exit 0
fi

# Establish a synchronous target first. The control plane remains fenced while
# this setting converges, so no fabric mutation can slip through the bootstrap.
psql_primary -c "ALTER SYSTEM SET synchronous_standby_names = 'FIRST 1 (*)'"
psql_primary -c "SELECT pg_reload_conf()"

ready=false
attempt=0
while [ "$attempt" -lt 24 ]; do
  sync_count=$(psql_primary -c \
    "SELECT count(*) FROM pg_stat_replication WHERE state='streaming' AND sync_state='sync'")
  if [ "$sync_count" -ge 1 ]; then
    ready=true
    break
  fi
  attempt=$((attempt + 1))
  sleep 5
done
[ "$ready" = true ] || {
  echo "no streaming synchronous standby became eligible; mutation plane remains fenced" >&2
  exit 75
}

psql_primary -c "ALTER SYSTEM SET synchronous_commit = 'remote_apply'"
psql_primary -c "SELECT pg_reload_conf()"
verification=$(psql_primary -F '|' -c \
  "SELECT current_setting('synchronous_commit'),
          current_setting('synchronous_standby_names'),
          (SELECT count(*) FROM pg_stat_replication
            WHERE state='streaming' AND sync_state='sync')")
commit_mode=$(printf '%s' "$verification" | cut -d '|' -f 1)
standby_names=$(printf '%s' "$verification" | cut -d '|' -f 2)
sync_count=$(printf '%s' "$verification" | cut -d '|' -f 3)
[ "$commit_mode" = remote_apply ] &&
  [ -n "$standby_names" ] &&
  [ "$sync_count" -ge 1 ] || {
  echo "PostgreSQL durable-primary readback failed; mutation plane remains fenced" >&2
  exit 75
}

jq -n \
  --arg hostId "$FABRIC_HOST_ID" \
  --arg expectedLeader "$expected_leader" \
  --arg synchronousCommit "$commit_mode" \
  --arg synchronousStandbyNames "$standby_names" \
  --argjson synchronousStandbyCount "$sync_count" \
  --arg verifiedAt "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  '{schemaVersion:"execution-fabric-postgres-durability-receipt/v1",
    hostId:$hostId,expectedLeader:$expectedLeader,
    synchronousCommit:$synchronousCommit,
    synchronousStandbyNames:$synchronousStandbyNames,
    synchronousStandbyCount:$synchronousStandbyCount,
    mutationDurabilityReady:true,verifiedAt:$verifiedAt}' >"$receipt_temp"
fabric_atomic_write \
  "$FABRIC_RUNTIME_STATE_DIR/postgres-durability.receipt.json" \
  "$receipt_temp"
# A standby-side launchd invocation may have exited before promotion. Starting
# the scheduler here binds its lifecycle to the measured remote_apply gate,
# while the degraded-primary branch above keeps it stopped.
fabric_compose "$compose_file" \
  --profile "$compose_profile" up -d --no-deps scheduler
cat "$receipt_temp"
