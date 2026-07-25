#!/bin/sh
set -eu

script_dir=$(CDPATH="" cd -- "$(dirname -- "$0")" && pwd)
# shellcheck source=_lib.sh
. "$script_dir/_lib.sh"
witness_load_environment

state_dir=${WITNESS_RUNTIME_STATE_DIR:-${WITNESS_STATE_DIR:-/var/lib/genomes-agentic-os/execution-fabric-witness}/monitor}
mkdir -p "$state_dir"
receipt="$state_dir/health.json"
previous=unknown
if [ -r "$receipt" ] && command -v jq >/dev/null 2>&1; then
  previous=$(jq -r '.status // "unknown"' "$receipt" 2>/dev/null || printf unknown)
fi
now=$(date -u '+%Y-%m-%dT%H:%M:%SZ')
temporary=$(mktemp "${TMPDIR:-/tmp}/witness-health.XXXXXX")
trap 'rm -f "$temporary"' EXIT HUP INT TERM

if [ "${WITNESS_MODE:-}" = manual_fail_closed ]; then
  printf '{"apiVersion":"execution-fabric-witness-health/v1","status":"manual_fail_closed","checkedAt":"%s","automaticPromotion":false}\n' \
    "$now" >"$temporary"
  witness_atomic_write "$receipt" "$temporary"
  exit 0
fi

if output=$("$script_dir/health.sh" 2>&1); then
  printf '{"apiVersion":"execution-fabric-witness-health/v1","status":"healthy","checkedAt":"%s","automaticPromotion":true}\n' \
    "$now" >"$temporary"
  witness_atomic_write "$receipt" "$temporary"
  if [ "$previous" = critical ]; then
    witness_notify info "Execution Fabric witness recovered" \
      "Independent witness health and durable readiness recovered." \
      "execution-fabric-witness-recovered"
  fi
  exit 0
fi

printf '{"apiVersion":"execution-fabric-witness-health/v1","status":"critical","checkedAt":"%s","automaticPromotion":false}\n' \
  "$now" >"$temporary"
witness_atomic_write "$receipt" "$temporary"
witness_notify critical "Execution Fabric witness unavailable" \
  "Leadership authority is unavailable; promotion remains fail-closed. Inspect the witness host and its health receipt." \
  "execution-fabric-witness-critical"
printf '%s\n' "$output" >&2
exit 1
