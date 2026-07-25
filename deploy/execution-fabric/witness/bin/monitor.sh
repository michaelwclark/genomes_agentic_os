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
previous_eligibility=false
if [ -r "$receipt" ] && command -v jq >/dev/null 2>&1; then
  previous=$(jq -r '.availability // .status // "unknown"' "$receipt" 2>/dev/null || printf unknown)
  previous_eligibility=$(jq -r '.automaticPromotionEligible // false' "$receipt" 2>/dev/null || printf false)
fi
now=$(date -u '+%Y-%m-%dT%H:%M:%SZ')
temporary=$(mktemp "${TMPDIR:-/tmp}/witness-health.XXXXXX")
trap 'rm -f "$temporary"' EXIT HUP INT TERM

if [ "${WITNESS_MODE:-}" = manual_fail_closed ]; then
  printf '{"apiVersion":"execution-fabric-witness-health/v2","status":"manual_fail_closed","availability":"intentionally_unavailable","checkedAt":"%s","automaticPromotionEligible":false,"eligibilityReason":"manual_fail_closed"}\n' \
    "$now" >"$temporary"
  witness_atomic_write "$receipt" "$temporary"
  exit 0
fi

if output=$("$script_dir/health.sh" 2>&1); then
  eligibility=false
  eligibility_reason=missing_or_expired_drill_receipt
  eligibility_receipt=${WITNESS_PROMOTION_ELIGIBILITY_RECEIPT:-}
  if [ -n "$eligibility_receipt" ] && [ -r "$eligibility_receipt" ] &&
    jq -e --arg cluster "$WITNESS_CLUSTER_ID" --arg now "$now" '
      .schemaVersion=="execution-fabric-witness-promotion-eligibility/v1" and
      .clusterId==$cluster and .eligible==true and
      (.expiresAt | type=="string") and
      ((.expiresAt | fromdateiso8601) > ($now | fromdateiso8601))
    ' "$eligibility_receipt" >/dev/null 2>&1; then
    eligibility=true
    eligibility_reason=validated_drill_receipt
  fi
  jq -n \
    --arg checkedAt "$now" \
    --argjson automaticPromotionEligible "$eligibility" \
    --arg eligibilityReason "$eligibility_reason" \
    '{apiVersion:"execution-fabric-witness-health/v2",status:"healthy",
      availability:"available",checkedAt:$checkedAt,
      automaticPromotionEligible:$automaticPromotionEligible,
      eligibilityReason:$eligibilityReason}' >"$temporary"
  witness_atomic_write "$receipt" "$temporary"
  if [ "$previous" = unavailable ] || [ "$previous" = critical ]; then
    witness_notify info "Execution Fabric witness recovered" \
      "Independent witness health and durable readiness recovered." \
      "execution-fabric-witness-recovered"
  fi
  if [ "$previous_eligibility" = true ] && [ "$eligibility" != true ]; then
    witness_notify warning "Execution Fabric promotion eligibility expired" \
      "Witness availability is healthy, but automatic promotion is fail-closed until a current drill receipt is installed." \
      "execution-fabric-witness-promotion-ineligible"
  fi
  exit 0
fi

printf '{"apiVersion":"execution-fabric-witness-health/v2","status":"critical","availability":"unavailable","checkedAt":"%s","automaticPromotionEligible":false,"eligibilityReason":"witness_unavailable"}\n' \
  "$now" >"$temporary"
witness_atomic_write "$receipt" "$temporary"
witness_notify critical "Execution Fabric witness unavailable" \
  "Leadership authority is unavailable; promotion remains fail-closed. Inspect the witness host and its health receipt." \
  "execution-fabric-witness-critical"
printf '%s\n' "$output" >&2
exit 1
