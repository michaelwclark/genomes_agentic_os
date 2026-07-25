#!/bin/sh
set -eu

script_dir=$(CDPATH="" cd -- "$(dirname -- "$0")" && pwd)
# shellcheck source=_lib.sh
. "$script_dir/_lib.sh"
fabric_load_runtime
fabric_require_command curl

: "${FABRIC_EMERGENCY_BUNDLE_DIR:?emergency bundle directory is required}"
: "${FABRIC_PRIMARY_API_BASE:?primary API base is required}"

"$script_dir/validate-emergency-bundle.sh" "$FABRIC_EMERGENCY_BUNDLE_DIR"
"$script_dir/artifact-replication-health.sh"
"$script_dir/validate-artifact-replication-receipt.sh"
candidate_receipt="$FABRIC_RUNTIME_STATE_DIR/drill-candidate-health.json"
case "${FABRIC_HOST_ID:-}" in
  bigmac)
    "$script_dir/candidate-reporter-health.sh" \
      --require-standby --receipt "$candidate_receipt" >/dev/null
    ;;
  genomesbox)
    "$script_dir/candidate-reporter-health.sh" \
      --require-active --receipt "$candidate_receipt" >/dev/null
    ;;
  *) echo "drill requires FABRIC_HOST_ID genomesbox or bigmac" >&2; exit 78 ;;
esac
fabric_api_get "$FABRIC_PRIMARY_API_BASE" "/healthz" >/dev/null
fabric_api_get "$FABRIC_PRIMARY_API_BASE" "/readyz" >/dev/null

receipt="$FABRIC_RUNTIME_STATE_DIR/drill-$(date -u +%Y%m%dT%H%M%SZ).receipt"
{
  printf 'schema_version=1\n'
  printf 'status=passed\n'
  printf 'completed_at=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  printf 'primary_health=passed\n'
  printf 'primary_readiness=passed\n'
  printf 'bundle_validation=passed\n'
  printf 'artifact_replication=passed\n'
  printf 'candidate_reporter=passed\n'
  printf 'candidate_health_receipt_sha256=%s\n' "$(fabric_sha256 "$candidate_receipt")"
  printf 'promotion_attempted=false\n'
  printf 'failback_mode=manual\n'
} >"$receipt"
printf '%s\n' "$receipt"
