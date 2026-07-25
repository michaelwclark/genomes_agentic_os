#!/bin/sh
set -eu

script_dir=$(CDPATH="" cd -- "$(dirname -- "$0")" && pwd)
# shellcheck source=_lib.sh
. "$script_dir/_lib.sh"
fabric_load_runtime
fabric_require_command jq

receipt=${1:-"$FABRIC_RUNTIME_STATE_DIR/artifact-replication-health.json"}
[ -s "$receipt" ] || {
  echo "artifact replication health receipt is missing: $receipt" >&2
  exit 78
}
[ "$(jq -r '.schemaVersion' "$receipt")" = \
  execution-fabric-artifact-replication-health/v1 ] || {
  echo "artifact replication health receipt schema is invalid" >&2
  exit 65
}
[ "$(jq -r '.status' "$receipt")" = passed ] || {
  echo "artifact replication is not healthy" >&2
  exit 75
}
sampled=$(jq -r '.sampledAt' "$receipt")
sampled_epoch=$(date -u -d "$sampled" +%s 2>/dev/null ||
  date -j -u -f "%Y-%m-%dT%H:%M:%SZ" "$sampled" +%s)
age=$(( $(date +%s) - sampled_epoch ))
max_age=${FABRIC_ARTIFACT_REPLICATION_RECEIPT_MAX_AGE_SECONDS:-300}
[ "$age" -ge 0 ] && [ "$age" -le "$max_age" ] || {
  echo "artifact replication health receipt is stale (${age}s > ${max_age}s)" >&2
  exit 75
}
jq -e \
  '.directions.primaryToStandby.canaryLagSeconds != null and
   .directions.standbyToPrimary.canaryLagSeconds != null' \
  "$receipt" >/dev/null || {
  echo "artifact replication receipt lacks both canary directions" >&2
  exit 75
}
