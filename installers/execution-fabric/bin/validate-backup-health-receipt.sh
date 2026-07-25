#!/bin/sh
set -eu

script_dir=$(CDPATH="" cd -- "$(dirname -- "$0")" && pwd)
# shellcheck source=_lib.sh
# shellcheck disable=SC1091
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
  (.runId|type=="string" and length>0) and
  (.verifiedAt|type=="string") and
  (.backupSha256|test("^[a-f0-9]{64}$")) and
  (.restoreManifestVerified==true) and
  (.restoreManifest.schemaVersion=="execution-fabric-postgres-restore-manifest/v1") and
  (.restoreManifest.file|test("^[A-Za-z0-9._-]+$")) and
  (.restoreManifest.sha256|test("^[a-f0-9]{64}$"))
' "$receipt" >/dev/null || {
  echo "backup health receipt is invalid or lacks restore verification" >&2
  exit 75
}
manifest_name=$(jq -r '.restoreManifest.file' "$receipt")
manifest="$(dirname "$receipt")/$manifest_name"
[ -s "$manifest" ] || {
  echo "verified restore manifest is missing: $manifest" >&2
  exit 75
}
manifest_sha=$(fabric_sha256 "$manifest")
[ "$manifest_sha" = "$(jq -r '.restoreManifest.sha256' "$receipt")" ] || {
  echo "verified restore manifest hash does not match the receipt" >&2
  exit 75
}
backup_sha=$(jq -r '.backupSha256' "$receipt")
jq -e --arg backupSha256 "$backup_sha" '
  .schemaVersion=="execution-fabric-postgres-restore-manifest/v1" and
  .backupSha256==$backupSha256 and
  (.backupBytes|type=="number" and .>0) and
  (.archiveManifestSha256|test("^[a-f0-9]{64}$")) and
  (.readbackManifestSha256|test("^[a-f0-9]{64}$")) and
  (.archiveEntryCount|type=="number" and .>=0) and
  (.readbackLineCount|type=="number" and .>0) and
  (.tableCount|type=="number" and .>=0) and
  .restoreDatabaseCreated==true and
  .restoreCompleted==true and
  .readbackCompleted==true and
  .restoreDatabaseDropped==true
' "$manifest" >/dev/null || {
  echo "restore manifest is invalid or does not prove disposable restore readback" >&2
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
