#!/bin/sh
set -eu

script_dir=$(CDPATH="" cd -- "$(dirname -- "$0")" && pwd)
# shellcheck source=_lib.sh
. "$script_dir/_lib.sh"
fabric_load_runtime
fabric_require_command curl

api_base=${FABRIC_GATEWAY_API_BASE:-${FABRIC_API_BASE:-}}
: "${api_base:?FABRIC_GATEWAY_API_BASE or FABRIC_API_BASE is required}"
: "${FABRIC_API_TOKEN_FILE:?FABRIC_API_TOKEN_FILE is required}"
snapshot_dir="$FABRIC_RUNTIME_STATE_DIR/snapshots"
mkdir -p "$snapshot_dir"

for resource in queues workers runs reliability; do
  temporary=$(mktemp "${TMPDIR:-/tmp}/fabric-${resource}.XXXXXX")
  trap 'rm -f "$temporary"' EXIT HUP INT TERM
  suffix=
  [ "$resource" = runs ] && suffix='?limit=200'
  fabric_api_get_bearer \
    "$api_base" \
    "/api/v1/snapshots/${resource}${suffix}" \
    "$FABRIC_API_TOKEN_FILE" >"$temporary"
  fabric_atomic_write "$snapshot_dir/${resource}.json" "$temporary"
  rm -f "$temporary"
  trap - EXIT HUP INT TERM
done

metrics_temp=$(mktemp "${TMPDIR:-/tmp}/fabric-metrics.XXXXXX")
trap 'rm -f "$metrics_temp"' EXIT HUP INT TERM
fabric_api_get_bearer \
  "$api_base" \
  "/metrics" \
  "$FABRIC_API_TOKEN_FILE" >"$metrics_temp"
fabric_atomic_write "$snapshot_dir/metrics.prom" "$metrics_temp"
rm -f "$metrics_temp"
trap - EXIT HUP INT TERM
date -u +%Y-%m-%dT%H:%M:%SZ >"$snapshot_dir/last-success-at"
