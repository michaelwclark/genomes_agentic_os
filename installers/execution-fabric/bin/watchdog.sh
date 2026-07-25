#!/bin/sh
set -eu

script_dir=$(CDPATH="" cd -- "$(dirname -- "$0")" && pwd)
# shellcheck source=_lib.sh
. "$script_dir/_lib.sh"
fabric_load_runtime
fabric_require_command curl
fabric_require_command jq

: "${FABRIC_PRIMARY_API_BASE:?FABRIC_PRIMARY_API_BASE is required}"
: "${FABRIC_PRIMARY_HOST_ID:?primary host id is required}"
: "${FABRIC_STANDBY_HOST_ID:?standby host id is required}"
threshold=${FABRIC_FAILURE_THRESHOLD:-2}
case "$threshold" in
  ''|*[!0-9]*) echo "FABRIC_FAILURE_THRESHOLD must be an integer" >&2; exit 78 ;;
esac

counter_file="$FABRIC_RUNTIME_STATE_DIR/primary-failure-count"
incident_file="$FABRIC_RUNTIME_STATE_DIR/primary-outage.receipt"
count=0
[ -r "$counter_file" ] && count=$(cat "$counter_file")

degraded_receipt="$FABRIC_RUNTIME_STATE_DIR/degraded-primary.receipt.json"
if [ -s "$degraded_receipt" ] &&
  [ "$(jq -r '.status // "invalid"' "$degraded_receipt")" = active ]; then
  degraded_until=$(jq -r '.degradedUntil' "$degraded_receipt")
  fabric_notify critical \
    "Execution Fabric remains DEGRADED" \
    "$FABRIC_STANDBY_HOST_ID is authoritative without redundancy until $degraded_until. Reseed $FABRIC_PRIMARY_HOST_ID now; mutation policy will fence at expiry." \
    "execution-fabric-degraded-primary"
fi

if fabric_api_get "$FABRIC_PRIMARY_API_BASE" "/readyz" >/dev/null 2>&1; then
  if [ "$count" -ge "$threshold" ]; then
    fabric_notify info \
      "Execution Fabric primary recovered" \
      "$FABRIC_PRIMARY_HOST_ID readiness recovered; failback remains an operator decision." \
      "execution-fabric-primary-recovered"
  fi
  printf '0\n' >"$counter_file"
  exit 0
fi

count=$((count + 1))
printf '%s\n' "$count" >"$counter_file"
if [ "$count" -lt "$threshold" ]; then
  exit 0
fi

{
  printf 'schema_version=1\n'
  printf 'detected_at=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  printf 'primary_api=%s\n' "$FABRIC_PRIMARY_API_BASE"
  printf 'consecutive_failures=%s\n' "$count"
  printf 'auto_failover=%s\n' "${FABRIC_AUTO_FAILOVER:-false}"
} >"${incident_file}.tmp"
mv "${incident_file}.tmp" "$incident_file"

fabric_notify critical \
  "Execution Fabric primary unavailable" \
  "$FABRIC_PRIMARY_HOST_ID failed $count readiness probes. $FABRIC_STANDBY_HOST_ID is checking fenced takeover prerequisites." \
  "execution-fabric-primary-down"

if [ "${FABRIC_AUTO_FAILOVER:-false}" = true ]; then
  if ! "$script_dir/promote.sh" --apply --incident-receipt "$incident_file"; then
    fabric_notify critical \
      "Execution Fabric takeover blocked" \
      "Automatic takeover failed closed. Inspect the local HA receipt and leadership API prerequisites." \
      "execution-fabric-takeover-blocked"
    exit 1
  fi
fi
