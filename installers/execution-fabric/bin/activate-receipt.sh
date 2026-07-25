#!/bin/sh
set -eu

usage() {
  echo "usage: activate-receipt.sh --stdin --expected-leader HOST" >&2
  exit 64
}

from_stdin=false
expected_leader=
while [ "$#" -gt 0 ]; do
  case "$1" in
    --stdin) from_stdin=true ;;
    --expected-leader) shift; [ "$#" -gt 0 ] || usage; expected_leader=$1 ;;
    *) usage ;;
  esac
  shift
done
[ "$from_stdin" = true ] && [ -n "$expected_leader" ] || usage

script_dir=$(CDPATH="" cd -- "$(dirname -- "$0")" && pwd)
. "$script_dir/_lib.sh"
fabric_load_runtime
fabric_require_command curl
fabric_require_command docker
fabric_require_command jq
fabric_require_command node

: "${FABRIC_CLUSTER_ID:?fabric cluster id is required}"
: "${FABRIC_LEADERSHIP_API_BASE:?witness API is required}"
: "${FABRIC_LEADERSHIP_TOKEN_FILE:?witness API token is required}"
: "${FABRIC_LEADERSHIP_PUBLIC_KEY_FILE:?witness public key is required}"
: "${FABRIC_LEADERSHIP_RECEIPT_FILE:?leadership receipt destination is required}"
: "${FABRIC_DEPLOYMENT_DIR:?deployment directory is required}"

receipt_temp=$(mktemp "${TMPDIR:-/tmp}/fabric-activation-receipt.XXXXXX")
status_temp=$(mktemp "${TMPDIR:-/tmp}/fabric-activation-status.XXXXXX")
trap 'rm -f "$receipt_temp" "$status_temp"' EXIT HUP INT TERM
cat >"$receipt_temp"
epoch=$(fabric_json_field "$receipt_temp" '.fabricEpoch')
node "$script_dir/verify-leadership-receipt.mjs" \
  "$receipt_temp" "$FABRIC_LEADERSHIP_PUBLIC_KEY_FILE" \
  "$FABRIC_CLUSTER_ID" "$expected_leader" "$epoch" \
  >"$FABRIC_RUNTIME_STATE_DIR/activation-verification.json"
fabric_api_get_bearer \
  "$FABRIC_LEADERSHIP_API_BASE" \
  "/api/v1/admin/leadership/status" \
  "$FABRIC_LEADERSHIP_TOKEN_FILE" >"$status_temp"
[ "$(fabric_json_field "$status_temp" '.currentLeader')" = "$expected_leader" ] &&
  [ "$(fabric_json_field "$status_temp" '.fabricEpoch')" -eq "$epoch" ] || {
    echo "witness readback does not match activation receipt" >&2
    exit 75
  }
fabric_atomic_write "$FABRIC_LEADERSHIP_RECEIPT_FILE" "$receipt_temp"
compose_file="$FABRIC_DEPLOYMENT_DIR/compose.genomesbox.yml"
fabric_compose "$compose_file" --profile primary up -d postgres
attempt=0
while [ "$attempt" -lt 24 ]; do
  recovery=$(fabric_compose "$compose_file" --profile primary exec -T postgres \
    psql -X -qAt -U "${FABRIC_POSTGRES_USER:-fabric}" \
      -d "${FABRIC_POSTGRES_DB:-execution_fabric}" \
      -c 'SELECT pg_is_in_recovery()' 2>/dev/null || true)
  [ "$recovery" = t ] && break
  attempt=$((attempt + 1))
  sleep 5
done
[ "$recovery" = t ] || {
  echo "failback target is not a PostgreSQL standby; refusing activation" >&2
  exit 75
}
fabric_compose "$compose_file" --profile primary exec -T postgres \
  pg_ctl promote -D /var/lib/postgresql/data -w -t 60
[ "$(fabric_compose "$compose_file" --profile primary exec -T postgres \
  psql -X -qAt -U "${FABRIC_POSTGRES_USER:-fabric}" \
    -d "${FABRIC_POSTGRES_DB:-execution_fabric}" \
    -c 'SELECT pg_is_in_recovery()')" = f ] || {
  echo "PostgreSQL promotion did not complete" >&2
  exit 70
}
standby_slot=$(fabric_replication_slot standby)
fabric_compose "$compose_file" --profile primary exec -T postgres \
  psql -X -v ON_ERROR_STOP=1 -U "${FABRIC_POSTGRES_USER:-fabric}" \
    -d "${FABRIC_POSTGRES_DB:-execution_fabric}" \
    -c "SELECT pg_create_physical_replication_slot('$standby_slot') WHERE NOT EXISTS (SELECT 1 FROM pg_replication_slots WHERE slot_name='$standby_slot')"
fabric_compose "$compose_file" --profile primary restart candidate-reporter
active_report=false
attempt=0
while [ "$attempt" -lt 12 ]; do
  if "$script_dir/candidate-reporter-health.sh" --require-active \
    --receipt "$FABRIC_RUNTIME_STATE_DIR/activation-active-candidate-health.json" \
    >/dev/null 2>&1; then
    active_report=true
    break
  fi
  attempt=$((attempt + 1))
  sleep 5
done
[ "$active_report" = true ] || {
  echo "failback target did not publish a fresh active candidate report" >&2
  exit 70
}
fabric_compose "$compose_file" \
  --profile primary up -d valkey control-plane observer healer scheduler gateway
fabric_atomic_write "$FABRIC_RUNTIME_STATE_DIR/activation.receipt.json" "$receipt_temp"
