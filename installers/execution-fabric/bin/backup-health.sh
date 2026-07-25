#!/bin/sh
set -eu

script_dir=$(CDPATH="" cd -- "$(dirname -- "$0")" && pwd)
# shellcheck source=_lib.sh
# shellcheck disable=SC1091
. "$script_dir/_lib.sh"
fabric_load_runtime
fabric_require_command docker
fabric_require_command jq

: "${FABRIC_DEPLOYMENT_DIR:?installed deployment directory is required}"
: "${FABRIC_BACKUP_HEALTH_RECEIPT_FILE:?backup health receipt path is required}"

expected_receipt="${FABRIC_RUNTIME_STATE_DIR%/}/backup-health.json"
[ "$FABRIC_BACKUP_HEALTH_RECEIPT_FILE" = "$expected_receipt" ] || {
  echo "backup health receipt must use the canonical path: $expected_receipt" >&2
  exit 78
}
[ "${FABRIC_DEPLOYMENT_ROLE:-}" = primary ] || {
  echo "verified backups may run only on the configured primary" >&2
  exit 77
}

run_id="backup-$(date -u +%Y%m%dT%H%M%SZ)-$$"
docker compose \
  --env-file "$FABRIC_RUNTIME_ENV_FILE" \
  -f "$FABRIC_DEPLOYMENT_DIR/compose.genomesbox.yml" \
  --profile backup run --rm \
  -e "FABRIC_BACKUP_RUN_ID=$run_id" \
  postgres-backup

"$script_dir/validate-backup-health-receipt.sh" "$FABRIC_BACKUP_HEALTH_RECEIPT_FILE"
[ "$(jq -r '.runId' "$FABRIC_BACKUP_HEALTH_RECEIPT_FILE")" = "$run_id" ] || {
  echo "backup receipt does not belong to this backup run" >&2
  exit 75
}
printf '%s\n' "$FABRIC_BACKUP_HEALTH_RECEIPT_FILE"
