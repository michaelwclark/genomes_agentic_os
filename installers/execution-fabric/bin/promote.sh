#!/bin/sh
set -eu

usage() {
  echo "usage: promote.sh --apply --incident-receipt PATH" >&2
  exit 64
}

apply=false
incident_receipt=
while [ "$#" -gt 0 ]; do
  case "$1" in
    --apply) apply=true ;;
    --incident-receipt) shift; [ "$#" -gt 0 ] || usage; incident_receipt=$1 ;;
    *) usage ;;
  esac
  shift
done

script_dir=$(CDPATH="" cd -- "$(dirname -- "$0")" && pwd)
# shellcheck source=_lib.sh
. "$script_dir/_lib.sh"
fabric_load_runtime
fabric_require_command curl
fabric_require_command jq
fabric_require_command docker
fabric_require_command node

[ "$apply" = true ] || {
  echo "promotion is plan-only without --apply" >&2
  exit 64
}
[ "${FABRIC_ENABLE_PROMOTION:-false}" = true ] || {
  echo "promotion is disabled by FABRIC_ENABLE_PROMOTION" >&2
  exit 77
}
[ -s "$incident_receipt" ] || {
  echo "a non-empty outage incident receipt is required" >&2
  exit 78
}

: "${FABRIC_LEADERSHIP_API_BASE:?independent leadership API is required}"
: "${FABRIC_LEADERSHIP_TOKEN_FILE:?leadership API token file is required}"
: "${FABRIC_LEADERSHIP_ADMIN_TOKEN_FILE:?leadership admin token file is required}"
: "${FABRIC_EMERGENCY_BUNDLE_DIR:?validated emergency bundle is required}"
: "${FABRIC_DEPLOYMENT_DIR:?installed deployment directory is required}"
: "${FABRIC_TAILSCALE_IP:?standby Tailscale IP is required}"
: "${FABRIC_CLUSTER_ID:?fabric cluster id is required}"
: "${FABRIC_PRIMARY_HOST_ID:?primary host id is required}"
: "${FABRIC_STANDBY_HOST_ID:?standby host id is required}"
: "${FABRIC_LEADERSHIP_PUBLIC_KEY_FILE:?witness public key is required}"
: "${FABRIC_LEADERSHIP_RECEIPT_FILE:?leadership receipt destination is required}"

promotion_journal="$FABRIC_RUNTIME_STATE_DIR/promotion.operation.json"
status_temp=$(mktemp "${TMPDIR:-/tmp}/fabric-leadership-status.XXXXXX")
receipt_temp=$(mktemp "${TMPDIR:-/tmp}/fabric-promotion-receipt.XXXXXX")
evidence_temp=$(mktemp "${TMPDIR:-/tmp}/fabric-promotion-evidence.XXXXXX")
journal_temp=$(mktemp "${TMPDIR:-/tmp}/fabric-promotion-journal.XXXXXX")
trap 'rm -f "$status_temp" "$receipt_temp" "$evidence_temp" "$journal_temp"' EXIT HUP INT TERM

promotion_journal_phase() {
  phase=$1
  jq --arg phase "$phase" --arg updatedAt "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" \
    '.phase=$phase | .updatedAt=$updatedAt' "$promotion_journal" >"$journal_temp"
  fabric_atomic_write "$promotion_journal" "$journal_temp"
}

# A failed leader may have committed a prepared policy to synchronously
# replicated PostgreSQL without receiving the witness response. Finish that
# exact signed rotation before evaluating normal promotion eligibility.
if ! "$script_dir/rotate-policy.sh" --resume \
  >"$FABRIC_RUNTIME_STATE_DIR/policy-rotation-resume.log"
then
  fabric_notify critical \
    "Execution Fabric takeover blocked by policy recovery" \
    "A prepared policy rotation could not be safely resumed on $FABRIC_HOST_ID." \
    "execution-fabric-policy-rotation-recovery"
  exit 75
fi

"$script_dir/validate-emergency-bundle.sh" "$FABRIC_EMERGENCY_BUNDLE_DIR"
"$script_dir/validate-artifact-replication-receipt.sh"
"$script_dir/validate-backup-health-receipt.sh"
incident_sha=$(fabric_sha256 "$incident_receipt")
[ "${FABRIC_ALLOW_DEGRADED_PRIMARY:-false}" = true ] || {
  echo "promotion requires a synchronous standby unless FABRIC_ALLOW_DEGRADED_PRIMARY=true" >&2
  exit 75
}

receipt_replayed=false
request=
if [ -s "$promotion_journal" ]; then
  jq -e \
    --arg incidentSha "$incident_sha" \
    --arg candidate "$FABRIC_STANDBY_HOST_ID" \
    --arg leader "$FABRIC_PRIMARY_HOST_ID" '
      .schemaVersion=="execution-fabric-promotion-operation/v1" and
      .incidentReceiptSha256==$incidentSha and
      .request.candidate==$candidate and .request.expectedLeader==$leader and
      (.request.promotionId | type=="string")
    ' "$promotion_journal" >/dev/null || {
    echo "existing promotion journal belongs to another incident or topology" >&2
    exit 75
  }
  request=$(jq -cer '.request' "$promotion_journal")
  promotion_id=$(jq -er '.request.promotionId' "$promotion_journal")
  admin_token=$(fabric_bearer_token "$FABRIC_LEADERSHIP_ADMIN_TOKEN_FILE")
  lookup_status=$(curl --silent --show-error \
    --connect-timeout 5 --max-time 20 \
    --header "Authorization: Bearer $admin_token" \
    --output "$receipt_temp" --write-out '%{http_code}' \
    "${FABRIC_LEADERSHIP_API_BASE%/}/api/v1/admin/leadership/promotions/$promotion_id")
  case "$lookup_status" in
    200) receipt_replayed=true ;;
    404) ;;
    *) echo "promotion receipt lookup returned HTTP $lookup_status" >&2; exit 75 ;;
  esac
fi

if [ "$receipt_replayed" != true ]; then
  candidate_health="$FABRIC_RUNTIME_STATE_DIR/promotion-candidate-health.json"
  "$script_dir/candidate-reporter-health.sh" \
    --require-standby --receipt "$candidate_health" >/dev/null
  fabric_api_get_bearer \
    "$FABRIC_LEADERSHIP_API_BASE" \
    "/api/v1/admin/leadership/status" \
    "$FABRIC_LEADERSHIP_TOKEN_FILE" >"$status_temp"

  current_leader=$(fabric_json_field "$status_temp" '.currentLeader')
  current_epoch=$(fabric_json_field "$status_temp" '.fabricEpoch')
  promotion_allowed=$(fabric_json_field "$status_temp" '.promotionAllowed')
  replica_lag=$(jq -er --arg host "$FABRIC_STANDBY_HOST_ID" '.candidates[$host].replicaLagBytes' "$status_temp")
  candidate_eligible=$(jq -er --arg host "$FABRIC_STANDBY_HOST_ID" '.candidates[$host].eligible' "$status_temp")
  candidate_in_recovery=$(jq -er --arg host "$FABRIC_STANDBY_HOST_ID" '.candidates[$host].inRecovery' "$status_temp")
  candidate_timeline=$(jq -er --arg host "$FABRIC_STANDBY_HOST_ID" '.candidates[$host].timelineId' "$status_temp")
  leader_timeline=$(fabric_json_field "$status_temp" '.timelineId')

  [ "$current_leader" = "$FABRIC_PRIMARY_HOST_ID" ] || {
    echo "expected $FABRIC_PRIMARY_HOST_ID leader, got $current_leader; refusing promotion" >&2
    exit 75
  }
  [ "$promotion_allowed" = true ] || {
    echo "leadership witness has not authorized promotion" >&2
    exit 75
  }
  [ "$candidate_eligible" = true ] && [ "$candidate_in_recovery" = true ] &&
    [ "$candidate_timeline" -eq "$leader_timeline" ] || {
    echo "$FABRIC_STANDBY_HOST_ID is not a measured standby on the leader timeline" >&2
    exit 75
  }
  [ "$replica_lag" -le "${FABRIC_MAX_REPLICA_LAG_BYTES:-67108864}" ] || {
    echo "replica lag exceeds configured RPO; refusing promotion" >&2
    exit 75
  }

  if [ -z "$request" ]; then
    candidate_sha=$(fabric_sha256 "$candidate_health")
    jq -n --arg incidentReceiptSha256 "$incident_sha" \
      --arg candidateHealthReceiptSha256 "$candidate_sha" \
      '{schemaVersion:"execution-fabric-promotion-evidence/v1",
        incidentReceiptSha256:$incidentReceiptSha256,
        candidateHealthReceiptSha256:$candidateHealthReceiptSha256}' >"$evidence_temp"
    fabric_atomic_write "$FABRIC_RUNTIME_STATE_DIR/promotion-evidence.json" "$evidence_temp"
    promotion_id=$(node -e 'console.log(require("node:crypto").randomUUID())')
    request=$(jq -cn \
      --arg promotionId "$promotion_id" \
      --arg candidate "$FABRIC_STANDBY_HOST_ID" \
      --arg expectedLeader "$current_leader" \
      --argjson expectedEpoch "$current_epoch" \
      --arg incidentDigest "$(fabric_sha256 "$evidence_temp")" \
      --arg authorityMode "degraded_primary" \
      --argjson degradedDurationSeconds "${FABRIC_DEGRADED_PRIMARY_MAX_SECONDS:-3600}" \
      '{promotionId:$promotionId,candidate:$candidate,expectedLeader:$expectedLeader,
        expectedEpoch:$expectedEpoch,incidentDigest:$incidentDigest,
        authorityMode:$authorityMode,degradedDurationSeconds:$degradedDurationSeconds}')
    jq -n --arg incidentReceiptSha256 "$incident_sha" --argjson request "$request" \
      --arg createdAt "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" \
      '{schemaVersion:"execution-fabric-promotion-operation/v1",phase:"intent",
        incidentReceiptSha256:$incidentReceiptSha256,request:$request,
        createdAt:$createdAt,updatedAt:$createdAt}' >"$journal_temp"
    fabric_atomic_write "$promotion_journal" "$journal_temp"
  fi
  fabric_api_post "$FABRIC_LEADERSHIP_API_BASE" \
    "/api/v1/admin/leadership/promote" \
    "$FABRIC_LEADERSHIP_ADMIN_TOKEN_FILE" "$request" >"$receipt_temp"
fi

[ "$(fabric_json_field "$receipt_temp" '.decision')" = promoted ] || {
  echo "leadership API did not return a promoted decision" >&2
  exit 75
}
new_epoch=$(fabric_json_field "$receipt_temp" '.fabricEpoch')
fence_token=$(fabric_json_field "$receipt_temp" '.fenceToken')
if [ "$receipt_replayed" = true ]; then
  current_epoch=$((new_epoch - 1))
fi
[ "$new_epoch" -gt "$current_epoch" ] || {
  echo "leadership receipt did not advance the fabric epoch" >&2
  exit 75
}
[ -n "$fence_token" ] || {
  echo "leadership receipt is missing the fence token" >&2
  exit 75
}

node "$script_dir/verify-leadership-receipt.mjs" \
  "$receipt_temp" \
  "$FABRIC_LEADERSHIP_PUBLIC_KEY_FILE" \
  "$FABRIC_CLUSTER_ID" \
  "$FABRIC_STANDBY_HOST_ID" \
  "$new_epoch" >"$FABRIC_RUNTIME_STATE_DIR/promotion-verification.json"
fabric_api_get_bearer \
  "$FABRIC_LEADERSHIP_API_BASE" \
  "/api/v1/admin/leadership/status" \
  "$FABRIC_LEADERSHIP_TOKEN_FILE" >"$status_temp"
[ "$(fabric_json_field "$status_temp" '.currentLeader')" = "$FABRIC_STANDBY_HOST_ID" ] &&
  [ "$(fabric_json_field "$status_temp" '.fabricEpoch')" -eq "$new_epoch" ] || {
    echo "witness readback does not match signed promotion receipt" >&2
    exit 75
  }
fabric_atomic_write "$FABRIC_LEADERSHIP_RECEIPT_FILE" "$receipt_temp"
promotion_journal_phase witness_committed

compose_file="$FABRIC_DEPLOYMENT_DIR/compose.bigmac.yml"
# Promotion occurs only after the independent witness returns a newer epoch.
postgres_recovery=$(fabric_compose "$compose_file" --profile standby exec -T postgres \
  psql -U postgres -d postgres -Atqc 'SELECT pg_is_in_recovery()')
case "$postgres_recovery" in
  t) fabric_compose "$compose_file" --profile standby exec -T postgres \
       pg_ctl promote -D /var/lib/postgresql/data ;;
  f) printf '%s\n' "PostgreSQL is already promoted; resuming after witness receipt" ;;
  *) echo "could not determine PostgreSQL recovery state" >&2; exit 70 ;;
esac
promotion_journal_phase postgres_promoted
fabric_compose "$compose_file" --profile promoted restart candidate-reporter

active_report=false
attempt=0
while [ "$attempt" -lt 12 ]; do
  if "$script_dir/candidate-reporter-health.sh" --require-active \
    --receipt "$FABRIC_RUNTIME_STATE_DIR/promotion-active-candidate-health.json" \
    >/dev/null 2>&1; then
    active_report=true
    break
  fi
  attempt=$((attempt + 1))
  sleep 5
done
[ "$active_report" = true ] || {
  echo "promoted host did not publish a fresh active candidate report" >&2
  exit 70
}

"$script_dir/enable-postgres-durable-primary.sh" \
  --apply --expected-leader "$FABRIC_STANDBY_HOST_ID" --degraded-primary \
  >"$FABRIC_RUNTIME_STATE_DIR/post-promotion-durability.json"
# Keep every promoted control-plane role supervised. The scheduler performs
# its own authority check and admits no occurrence when the canonical degraded
# policy disables it; starting the role here also means enabling that policy
# later cannot leave schedules silently dormant until a host-manager restart.
fabric_compose "$compose_file" \
  --profile promoted up -d control-plane observer healer scheduler

local_api="http://${FABRIC_TAILSCALE_IP}:3180"
ready=false
attempt=0
while [ "$attempt" -lt 12 ]; do
  if fabric_api_get "$local_api" "/readyz" >/dev/null 2>&1; then
    ready=true
    break
  fi
  attempt=$((attempt + 1))
  sleep 5
done
[ "$ready" = true ] || {
  echo "promoted control plane did not become ready" >&2
  exit 70
}

fabric_api_get_bearer \
  "$FABRIC_LEADERSHIP_API_BASE" \
  "/api/v1/admin/leadership/status" \
  "$FABRIC_LEADERSHIP_TOKEN_FILE" >"$status_temp"
promoted_policy_digest=$(jq -er '.configDigest' "$status_temp")
FABRIC_POLICY_CONVERGENCE_API_BASE=$local_api \
  "$script_dir/converge-policy-roles.sh" --verify "$promoted_policy_digest" \
  >"$FABRIC_RUNTIME_STATE_DIR/post-promotion-role-convergence.path"

fabric_api_post \
  "$local_api" \
  "/api/v1/admin/reconcile" \
  "$FABRIC_ADMIN_TOKEN_FILE" \
  '{}' >"$FABRIC_RUNTIME_STATE_DIR/post-promotion-reconcile.json"
fabric_atomic_write "$FABRIC_RUNTIME_STATE_DIR/promotion.receipt.json" "$receipt_temp"
degraded_temp=$(mktemp "${TMPDIR:-/tmp}/fabric-degraded-primary.XXXXXX")
promotion_incident_digest=$(printf '%s\n' "$request" | jq -er '.incidentDigest')
jq -n \
  --arg hostId "$FABRIC_STANDBY_HOST_ID" \
  --argjson fabricEpoch "$new_epoch" \
  --arg degradedUntil "$(fabric_json_field "$receipt_temp" '.degradedUntil')" \
  --arg incidentDigest "$promotion_incident_digest" \
  '{schemaVersion:"execution-fabric-degraded-primary/v1",
    status:"active",hostId:$hostId,fabricEpoch:$fabricEpoch,
    degradedUntil:$degradedUntil,incidentDigest:$incidentDigest,
    redundancyRestored:false}' >"$degraded_temp"
fabric_atomic_write \
  "$FABRIC_RUNTIME_STATE_DIR/degraded-primary.receipt.json" \
  "$degraded_temp"
rm -f "$degraded_temp"
promotion_journal_phase complete
fabric_notify critical \
  "Execution Fabric DEGRADED on $FABRIC_STANDBY_HOST_ID" \
  "Fenced takeover is accepting only policy-allowed work at epoch $new_epoch. Redundancy is absent; reseed $FABRIC_PRIMARY_HOST_ID before the signed deadline." \
  "execution-fabric-degraded-primary"
