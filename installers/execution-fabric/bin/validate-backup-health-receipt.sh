#!/bin/sh
set -eu

script_dir=$(CDPATH="" cd -- "$(dirname -- "$0")" && pwd)
# shellcheck source=_lib.sh
. "$script_dir/_lib.sh"
fabric_load_runtime
fabric_require_command jq

: "${FABRIC_BACKUP_HEALTH_RECEIPT_FILE:?fresh backup health receipt is required}"
receipt=${1:-"$FABRIC_BACKUP_HEALTH_RECEIPT_FILE"}
[ -s "$receipt" ] || {
  echo "backup health receipt is missing: $receipt" >&2
  exit 78
}
jq -e '
  .schemaVersion=="execution-fabric-backup-health/v1" and
  .status=="passed" and
  (.verifiedAt|type=="string") and
  (.backupSha256|test("^[a-f0-9]{64}$")) and
  (.restoreManifestVerified==true)
' "$receipt" >/dev/null || {
  echo "backup health receipt is invalid or lacks restore verification" >&2
  exit 75
}
verified=$(jq -r '.verifiedAt' "$receipt")
verified_epoch=$(date -u -d "$verified" +%s 2>/dev/null ||
  date -j -u -f "%Y-%m-%dT%H:%M:%SZ" "$verified" +%s)
age=$(( $(date +%s) - verified_epoch ))
max_age=${FABRIC_BACKUP_HEALTH_RECEIPT_MAX_AGE_SECONDS:-86400}
[ "$age" -ge 0 ] && [ "$age" -le "$max_age" ] || {
  echo "backup health receipt is stale (${age}s > ${max_age}s)" >&2
  exit 75
}
