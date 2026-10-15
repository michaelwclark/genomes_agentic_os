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

require_source=${FABRIC_RECOVERY_SETS_ENABLED:-0}
expected_source_sha=
while [ "$#" -gt 0 ]; do
  case "$1" in
    --require-source-provenance) require_source=1; shift ;;
    --source-script-sha256)
      [ "$#" -ge 2 ] || exit 78
      expected_source_sha=$2; shift 2 ;;
    *) echo "unsupported backup qualification argument" >&2; exit 78 ;;
  esac
done
set --
if [ "$require_source" = 1 ]; then
  case "$expected_source_sha" in ''|*[!a-f0-9]*) echo "qualified source backup actor digest is required" >&2; exit 78 ;; esac
  [ "${#expected_source_sha}" -eq 64 ] || exit 78
  source_script="$FABRIC_DEPLOYMENT_DIR/scripts/postgres-backup.sh"
  [ -f "$source_script" ] && [ ! -L "$source_script" ] &&
    [ "$(fabric_sha256 "$source_script")" = "$expected_source_sha" ] || {
    echo "native source backup actor differs from qualification" >&2; exit 75
  }
  set -- -e FABRIC_RECOVERY_REQUIRE_PG_PROVENANCE=1
fi

if [ -n "${FABRIC_SECRETS_DIR:-}" ]; then
  pgpass_file="$FABRIC_SECRETS_DIR/postgres-pgpass"
  if [ -e "$pgpass_file" ] && [ -n "$(find "$pgpass_file" -perm /077 2>/dev/null)" ]; then
    echo "postgres-pgpass secret must not be group/world accessible (mode 0400/0600 required): $pgpass_file" >&2
    exit 78
  fi
fi

run_id="backup-$(date -u +%Y%m%dT%H%M%SZ)-$$"
docker compose \
  --env-file "$FABRIC_RUNTIME_ENV_FILE" \
  -f "$FABRIC_DEPLOYMENT_DIR/compose.genomesbox.yml" \
  --profile primary --profile backup run --rm \
  -e "FABRIC_BACKUP_RUN_ID=$run_id" \
  "$@" \
  postgres-backup

FABRIC_RECOVERY_REQUIRE_PG_PROVENANCE="$require_source" \
  "$script_dir/validate-backup-health-receipt.sh" "$FABRIC_BACKUP_HEALTH_RECEIPT_FILE"
[ "$(jq -r '.runId' "$FABRIC_BACKUP_HEALTH_RECEIPT_FILE")" = "$run_id" ] || {
  echo "backup receipt does not belong to this backup run" >&2
  exit 75
}
printf '%s\n' "$FABRIC_BACKUP_HEALTH_RECEIPT_FILE"
