#!/bin/sh
set -eu

usage() {
  echo "usage: rotate-policy.sh EXPECTED_CURRENT_DIGEST CANDIDATE_DIGEST [ROTATION_ID]" >&2
  echo "       standalone-primary requires FABRIC_POLICY_OVERRIDE_ACTOR, FABRIC_POLICY_OVERRIDE_REASON," >&2
  echo "       FABRIC_POLICY_OVERRIDE_APPROVAL_REFERENCE, FABRIC_POLICY_OVERRIDE_WINDOW_START," >&2
  echo "       and FABRIC_POLICY_OVERRIDE_WINDOW_END." >&2
  echo "       rotate-policy.sh --resume" >&2
  exit 64
}

mode=rotate
if [ "${1:-}" = --resume ]; then
  [ "$#" -eq 1 ] || usage
  mode=resume
  expected_current=
  candidate_digest=
  requested_rotation_id=
else
  [ "$#" -ge 2 ] && [ "$#" -le 3 ] || usage
  expected_current=$1
  candidate_digest=$2
  requested_rotation_id=${3:-}
  case "$expected_current:$candidate_digest" in
    *[!a-f0-9:]*|:*|*:) echo "policy digests must be lowercase sha256 values" >&2; exit 64 ;;
  esac
  [ "${#expected_current}" -eq 64 ] &&
    [ "${#candidate_digest}" -eq 64 ] || {
    echo "policy digests must be 64 characters" >&2
    exit 64
  }
  [ "$expected_current" != "$candidate_digest" ] || {
    echo "candidate digest must differ from current digest" >&2
    exit 64
  }
fi

script_dir=$(CDPATH="" cd -- "$(dirname -- "$0")" && pwd)
# shellcheck source=_lib.sh
. "$script_dir/_lib.sh"
fabric_load_runtime
fabric_require_command curl
fabric_require_command jq

: "${FABRIC_API_BASE:?local control-plane API is required}"
: "${FABRIC_API_TOKEN_FILE:?control-plane read token file is required}"
: "${FABRIC_ADMIN_TOKEN_FILE:?control-plane admin token file is required}"
: "${FABRIC_LEADERSHIP_API_BASE:?independent witness API is required}"
: "${FABRIC_LEADERSHIP_ADMIN_TOKEN_FILE:?witness admin token file is required}"
: "${FABRIC_HOST_ID:?stable host identity is required}"
: "${FABRIC_PRIMARY_HOST_ID:?stable primary host identity is required}"
standalone_primary=false
evidence_host=${FABRIC_STANDBY_HOST_ID:-}
evidence_label=standby
if [ "${FABRIC_WITNESS_MODE:-independent}" = standalone_primary ]; then
  standalone_primary=true
  evidence_host=$FABRIC_PRIMARY_HOST_ID
  evidence_label=local-primary
  [ "$FABRIC_HOST_ID" = "$FABRIC_PRIMARY_HOST_ID" ] || {
    echo "standalone-primary policy maintenance must run on its exact primary host" >&2
    exit 78
  }
else
  : "${FABRIC_STANDBY_HOST_ID:?stable standby host identity is required}"
fi

pending_path="$FABRIC_RUNTIME_STATE_DIR/policy-rotation.pending.json"
witness_status=$(mktemp "$FABRIC_RUNTIME_STATE_DIR/policy-witness-status.XXXXXX")
preparation=$(mktemp "$FABRIC_RUNTIME_STATE_DIR/policy-preparation.XXXXXX")
control_status=$(mktemp "$FABRIC_RUNTIME_STATE_DIR/policy-control-status.XXXXXX")
control_receipt=$(mktemp "$FABRIC_RUNTIME_STATE_DIR/policy-control-receipt.XXXXXX")
witness_receipt=$(mktemp "$FABRIC_RUNTIME_STATE_DIR/policy-witness-receipt.XXXXXX")
abort_receipt=$(mktemp "$FABRIC_RUNTIME_STATE_DIR/policy-abort-receipt.XXXXXX")
final_temp=$(mktemp "$FABRIC_RUNTIME_STATE_DIR/policy-rotation-receipt.XXXXXX")
role_recreate_receipt=
role_verify_receipt=
role_convergence_deferred=false
operator_override_json=null
if [ "$mode" = resume ] && [ "${FABRIC_DEPLOYMENT_ROLE:-}" = standby ]; then
  fabric_require_command docker
  : "${FABRIC_DEPLOYMENT_DIR:?deployment directory is required}"
  resume_compose="$FABRIC_DEPLOYMENT_DIR/compose.bigmac.yml"
  resume_cohort_state=$(fabric_policy_role_cohort_state "$resume_compose" promoted)
  case "$resume_cohort_state" in
    dormant) role_convergence_deferred=true ;;
    active) role_convergence_deferred=false ;;
    *)
      fabric_notify critical \
        "Execution Fabric policy recovery blocked by partial role cohort" \
        "The standby role cohort is partial; recovery remains fail-closed until it is fully dormant or fully promoted." \
        "execution-fabric-policy-rotation-recovery"
      echo "standby policy role cohort is partial; recovery remains fail-closed" >&2
      exit 75
      ;;
  esac
fi
cleanup() {
  unlink "$witness_status" 2>/dev/null || true
  unlink "$preparation" 2>/dev/null || true
  unlink "$control_status" 2>/dev/null || true
  unlink "$control_receipt" 2>/dev/null || true
  unlink "$witness_receipt" 2>/dev/null || true
  unlink "$abort_receipt" 2>/dev/null || true
  unlink "$final_temp" 2>/dev/null || true
}
trap cleanup EXIT HUP INT TERM

fabric_api_get_bearer \
  "$FABRIC_LEADERSHIP_API_BASE" \
  "/api/v1/admin/leadership/status" \
  "$FABRIC_LEADERSHIP_ADMIN_TOKEN_FILE" >"$witness_status"

if [ "$mode" = resume ]; then
  pending_count=$(jq -er '.pendingConfigDigestRotations | length' "$witness_status")
  if [ "$pending_count" -eq 0 ]; then
    printf '%s\n' "no prepared policy rotation requires recovery"
    exit 0
  fi
  [ "$pending_count" -eq 1 ] || {
    fabric_notify critical \
      "Execution Fabric has ambiguous policy recovery" \
      "$pending_count prepared policy rotations are active; operator review is required." \
      "execution-fabric-policy-rotation-ambiguous"
    exit 75
  }
  jq -e '.pendingConfigDigestRotations[0]' "$witness_status" >"$preparation"
  expected_current=$(jq -er '.expectedCurrentDigest' "$preparation")
  candidate_digest=$(jq -er '.candidateDigest' "$preparation")
  rotation_id=$(jq -er '.rotationId' "$preparation")
  expected_leader=$(jq -er '.expectedLeader' "$preparation")
  expected_epoch=$(jq -er '.expectedEpoch' "$preparation")
  preparation_token=$(jq -er '.preparationToken' "$preparation")
  preparation_expired=$(jq -er '.expired' "$preparation")
  if [ "$standalone_primary" = true ]; then
    operator_override_json=$(jq -ce '.operatorOverride' "$preparation") || {
      echo "standalone-primary recovery requires a prepared operator override receipt" >&2
      exit 75
    }
  fi
  jq -e \
    --arg evidenceHost "$evidence_host" \
    --arg leader "$expected_leader" \
    --arg current "$expected_current" \
    --argjson epoch "$expected_epoch" \
    '.currentLeader==$leader and .fabricEpoch==$epoch and
     .configDigest==$current and
     .candidates[$evidenceHost].healthy==true' \
    "$witness_status" >/dev/null || {
    fabric_notify critical \
      "Execution Fabric policy recovery blocked" \
      "Prepared rotation $rotation_id has no safe $evidence_label evidence; execution remains fail-closed." \
      "execution-fabric-policy-rotation-$rotation_id"
    exit 75
  }
  evidence_digest=$(jq -er \
    --arg evidenceHost "$evidence_host" \
    '.candidates[$evidenceHost].configDigest' \
    "$witness_status")
  if [ "$evidence_digest" = "$expected_current" ]; then
    if [ "$preparation_expired" != true ]; then
      fabric_notify critical \
        "Execution Fabric policy recovery waiting" \
        "Prepared rotation $rotation_id has not reached PostgreSQL and cannot be resolved before its preparation expires." \
        "execution-fabric-policy-rotation-$rotation_id"
      exit 75
    fi
    abort_body=$(jq -cn \
      --arg rotationId "$rotation_id" \
      --arg preparationToken "$preparation_token" \
      '{rotationId:$rotationId,preparationToken:$preparationToken}')
    if ! fabric_api_post \
      "$FABRIC_LEADERSHIP_API_BASE" \
      "/api/v1/admin/leadership/config-digest-rotations/abort" \
      "$FABRIC_LEADERSHIP_ADMIN_TOKEN_FILE" \
      "$abort_body" >"$abort_receipt"
    then
      fabric_notify critical \
        "Execution Fabric policy recovery fenced" \
        "Expired pre-database rotation $rotation_id could not be safely resolved; takeover remains fail-closed." \
        "execution-fabric-policy-rotation-$rotation_id"
      exit 75
    fi
    jq -e \
      --arg rotationId "$rotation_id" \
      --arg digest "$expected_current" \
      '.rotationId==$rotationId and .configDigest==$digest and
       .decision=="config_digest_rotation_aborted"' \
      "$abort_receipt" >/dev/null
    if [ -s "$pending_path" ] &&
      [ "$(jq -r '.rotationId // empty' "$pending_path")" = "$rotation_id" ]
    then
      unlink "$pending_path"
    fi
    fabric_notify warning \
      "Execution Fabric abandoned policy rotation resolved" \
      "Expired rotation $rotation_id never reached PostgreSQL and was safely aborted from fresh $evidence_label evidence." \
      "execution-fabric-policy-rotation-$rotation_id"
    printf '%s\n' "aborted expired pre-database policy rotation $rotation_id"
    exit 0
  fi
  [ "$evidence_digest" = "$candidate_digest" ] || {
    fabric_notify critical \
      "Execution Fabric policy recovery blocked" \
      "Prepared rotation $rotation_id has an unexpected $evidence_label digest; execution remains fail-closed." \
      "execution-fabric-policy-rotation-$rotation_id"
    exit 75
  }
else
  if [ -s "$pending_path" ]; then
    jq -e \
      --arg current "$expected_current" \
      --arg candidate "$candidate_digest" \
      'select(.expectedCurrentDigest==$current and .candidateDigest==$candidate)' \
      "$pending_path" >"$preparation" || {
      echo "a different policy rotation is already pending: $pending_path" >&2
      exit 75
    }
    rotation_id=$(jq -er '.rotationId' "$preparation")
    if [ -n "$requested_rotation_id" ] &&
      [ "$requested_rotation_id" != "$rotation_id" ]
    then
      echo "requested rotation id does not match the durable pending rotation" >&2
      exit 75
    fi
  else
    if [ -n "$requested_rotation_id" ]; then
      rotation_id=$requested_rotation_id
    elif [ -r /proc/sys/kernel/random/uuid ]; then
      rotation_id=$(tr '[:upper:]' '[:lower:]' </proc/sys/kernel/random/uuid)
    elif command -v uuidgen >/dev/null 2>&1; then
      rotation_id=$(uuidgen | tr '[:upper:]' '[:lower:]')
    else
      echo "uuidgen is required when /proc/sys/kernel/random/uuid is unavailable" >&2
      exit 69
    fi
    printf '%s\n' "$rotation_id" | grep -Eq \
      '^[a-f0-9]{8}-[a-f0-9]{4}-[1-5][a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$' || {
      echo "rotation id must be a UUID" >&2
      exit 64
    }
    leader=$(jq -er '.currentLeader' "$witness_status")
    epoch=$(jq -er '.fabricEpoch' "$witness_status")
    if [ "$standalone_primary" = true ]; then
      : "${FABRIC_POLICY_OVERRIDE_ACTOR:?standalone policy override actor is required}"
      : "${FABRIC_POLICY_OVERRIDE_REASON:?standalone policy override reason is required}"
      : "${FABRIC_POLICY_OVERRIDE_APPROVAL_REFERENCE:?standalone policy override approval reference is required}"
      : "${FABRIC_POLICY_OVERRIDE_WINDOW_START:?standalone policy override maintenance window start is required}"
      : "${FABRIC_POLICY_OVERRIDE_WINDOW_END:?standalone policy override maintenance window end is required}"
      operator_override_json=$(jq -cn \
        --arg actor "$FABRIC_POLICY_OVERRIDE_ACTOR" \
        --arg reason "$FABRIC_POLICY_OVERRIDE_REASON" \
        --arg approvalReference "$FABRIC_POLICY_OVERRIDE_APPROVAL_REFERENCE" \
        --arg startsAt "$FABRIC_POLICY_OVERRIDE_WINDOW_START" \
        --arg endsAt "$FABRIC_POLICY_OVERRIDE_WINDOW_END" \
        '{actor:$actor,reason:$reason,approvalReference:$approvalReference,maintenanceWindow:{startsAt:$startsAt,endsAt:$endsAt}}')
    fi
    witness_digest=$(jq -er '.configDigest' "$witness_status")
    [ "$leader" = "$FABRIC_HOST_ID" ] &&
      [ "$witness_digest" = "$expected_current" ] || {
      echo "new policy rotation must run on the witnessed current leader" >&2
      exit 75
    }
    if [ "$standalone_primary" = true ]; then
      jq -e \
        --arg primary "$FABRIC_PRIMARY_HOST_ID" \
        --arg current "$expected_current" \
        --arg candidate "$candidate_digest" \
        '.authorityMode=="standalone_primary" and
         .currentLeader==$primary and
         .candidates[$primary].healthy == true and
         .candidates[$primary].inRecovery == false and
         .candidates[$primary].configDigest == $current and
         .candidates[$primary].policyCandidateDigest == $candidate' \
        "$witness_status" >/dev/null || {
        echo "standalone-primary must report exact current and staged policy digests" >&2
        exit 75
      }
    else
      jq -e \
        --arg primary "$FABRIC_PRIMARY_HOST_ID" \
        --arg standby "$FABRIC_STANDBY_HOST_ID" \
        --arg current "$expected_current" \
        --arg candidate "$candidate_digest" \
        '.candidates[$primary].healthy == true and
         .candidates[$primary].configDigest == $current and
         .candidates[$primary].policyCandidateDigest == $candidate and
         .candidates[$standby].healthy == true and
         .candidates[$standby].configDigest == $current and
         .candidates[$standby].policyCandidateDigest == $candidate' \
        "$witness_status" >/dev/null || {
        echo "both configured hosts must report current and staged policy digests" >&2
        exit 75
      }
    fi
    prepare_body=$(jq -cn \
      --arg rotationId "$rotation_id" \
      --arg expectedLeader "$leader" \
      --argjson expectedEpoch "$epoch" \
      --arg expectedCurrentDigest "$expected_current" \
      --arg candidateDigest "$candidate_digest" \
      --argjson operatorOverride "$operator_override_json" \
      '{
        rotationId:$rotationId,
        expectedLeader:$expectedLeader,
        expectedEpoch:$expectedEpoch,
        expectedCurrentDigest:$expectedCurrentDigest,
        candidateDigest:$candidateDigest
      } + (if $operatorOverride == null then {} else {operatorOverride:$operatorOverride} end)')
    fabric_api_post \
      "$FABRIC_LEADERSHIP_API_BASE" \
      "/api/v1/admin/leadership/config-digest-rotations/prepare" \
      "$FABRIC_LEADERSHIP_ADMIN_TOKEN_FILE" \
      "$prepare_body" >"$preparation"
    jq -e \
      --arg rotationId "$rotation_id" \
      --arg current "$expected_current" \
      --arg candidate "$candidate_digest" \
      '.decision=="config_digest_rotation_prepared" and
       .rotationId==$rotationId and
       .expectedCurrentDigest==$current and .candidateDigest==$candidate' \
      "$preparation" >/dev/null
    pending_temp=$(mktemp "$FABRIC_RUNTIME_STATE_DIR/policy-rotation.XXXXXX")
    jq '. + {phase:"witness_prepared"}' "$preparation" >"$pending_temp"
    fabric_atomic_write "$pending_path" "$pending_temp"
    unlink "$pending_temp"
  fi
  expected_leader=$(jq -er '.expectedLeader' "$preparation")
  expected_epoch=$(jq -er '.expectedEpoch' "$preparation")
  preparation_token=$(jq -er '.preparationToken' "$preparation")
  if [ "$standalone_primary" = true ]; then
    operator_override_json=$(jq -ce '.operatorOverride' "$preparation") || {
      echo "standalone-primary preparation is missing its signed operator override" >&2
      exit 75
    }
  fi

  fabric_api_get_bearer \
    "$FABRIC_API_BASE" \
    "/api/v1/status?limit=1" \
    "$FABRIC_API_TOKEN_FILE" >"$control_status"
  applied_digest=$(jq -er '.config.appliedFingerprint' "$control_status")
  database_digest=$(jq -er '.controlPlane.databasePolicyFingerprint' "$control_status")
  if [ "$applied_digest" = "$expected_current" ] &&
    [ "$database_digest" = "$expected_current" ]
  then
    reload_body=$(jq -cn \
      --arg rotationId "$rotation_id" \
      --arg preparationToken "$preparation_token" \
      --arg current "$expected_current" \
      --arg candidate "$candidate_digest" \
      --argjson operatorOverride "$operator_override_json" \
      '{
        rotationId:$rotationId,
        preparationToken:$preparationToken,
        expectedCurrentFingerprint:$current,
        expectedCandidateFingerprint:$candidate
      } + (if $operatorOverride == null then {} else {operatorOverride:$operatorOverride} end)')
    if ! fabric_api_post \
      "$FABRIC_API_BASE" \
      "/api/v1/admin/config/reload" \
      "$FABRIC_ADMIN_TOKEN_FILE" \
      "$reload_body" >"$control_receipt"
    then
      fabric_notify critical \
        "Execution Fabric policy rotation failed" \
        "Witness preparation exists, but PostgreSQL did not commit rotation $rotation_id." \
        "execution-fabric-policy-rotation-$rotation_id"
      exit 75
    fi
    jq -e \
      --arg rotationId "$rotation_id" \
      --arg digest "$candidate_digest" \
      '.appliedFingerprint==$digest and
       .receipt.rotationId==$rotationId and
       .receipt.appliedFingerprint==$digest' \
      "$control_receipt" >/dev/null
  elif [ "$applied_digest" = "$candidate_digest" ] &&
    [ "$database_digest" = "$candidate_digest" ]
  then
    jq -n \
      --arg rotationId "$rotation_id" \
      --arg appliedFingerprint "$candidate_digest" \
      '{recovered:true,rotationId:$rotationId,
        appliedFingerprint:$appliedFingerprint}' >"$control_receipt"
  else
    echo "control-plane disk and database policy are at no recoverable phase" >&2
    exit 75
  fi
fi

if [ "$role_convergence_deferred" = false ]; then
  if ! role_recreate_receipt=$(
    "$script_dir/converge-policy-roles.sh" --recreate "$candidate_digest"
  ); then
    fabric_notify critical \
      "Execution Fabric policy role recreation failed" \
      "Rotation $rotation_id did not recreate and fingerprint-verify the complete role cohort. Rerun rotate-policy.sh --resume; mutations remain fenced." \
      "execution-fabric-policy-rotation-$rotation_id"
    exit 75
  fi
fi

if [ "$mode" = rotate ]; then
  evidence_applied=false
  attempt=0
  while [ "$attempt" -lt 18 ]; do
    attempt=$((attempt + 1))
    if fabric_api_get_bearer \
      "$FABRIC_LEADERSHIP_API_BASE" \
      "/api/v1/admin/leadership/status" \
      "$FABRIC_LEADERSHIP_ADMIN_TOKEN_FILE" >"$witness_status" 2>/dev/null &&
      jq -e \
        --arg evidenceHost "$evidence_host" \
        --arg digest "$candidate_digest" \
        '.candidates[$evidenceHost].healthy==true and
         .candidates[$evidenceHost].configDigest==$digest' \
        "$witness_status" >/dev/null
    then
      evidence_applied=true
      break
    fi
    sleep 5
  done
  [ "$evidence_applied" = true ] || {
    fabric_notify critical \
      "Execution Fabric policy rotation awaiting replication" \
      "PostgreSQL committed rotation $rotation_id, but the $evidence_label has not reported the applied digest. Rerun --resume; mutations remain fenced." \
      "execution-fabric-policy-rotation-$rotation_id"
    exit 75
  }
fi

commit_body=$(jq -cn \
  --arg rotationId "$rotation_id" \
  --arg preparationToken "$preparation_token" \
  '{rotationId:$rotationId,preparationToken:$preparationToken}')
if ! fabric_api_post \
  "$FABRIC_LEADERSHIP_API_BASE" \
  "/api/v1/admin/leadership/config-digest-rotations/commit" \
  "$FABRIC_LEADERSHIP_ADMIN_TOKEN_FILE" \
  "$commit_body" >"$witness_receipt"
then
  fabric_notify critical \
    "Execution Fabric policy rotation fenced" \
    "Prepared rotation $rotation_id did not commit at the witness. Rerun rotate-policy.sh --resume; mutations remain fail-closed." \
    "execution-fabric-policy-rotation-$rotation_id"
  exit 75
fi
jq -e \
  --arg rotationId "$rotation_id" \
  --arg digest "$candidate_digest" \
  '.rotationId==$rotationId and .configDigest==$digest and
   .decision=="config_digest_rotated"' \
  "$witness_receipt" >/dev/null

receipt_path="$FABRIC_RUNTIME_STATE_DIR/policy-rotation-$rotation_id.receipt.json"
if [ "$mode" = rotate ]; then
  attempt=0
  while [ "$attempt" -lt 12 ]; do
    attempt=$((attempt + 1))
    if fabric_api_get_bearer \
      "$FABRIC_API_BASE" \
      "/api/v1/status?limit=1" \
      "$FABRIC_API_TOKEN_FILE" >"$control_status" 2>/dev/null &&
      jq -e \
        --arg digest "$candidate_digest" \
        '.config.appliedFingerprint==$digest and
         .controlPlane.databasePolicyFingerprint==$digest and
         .controlPlane.leadership.state=="active"' \
        "$control_status" >/dev/null
    then
      break
    fi
    sleep 2
  done
  jq -e \
    --arg digest "$candidate_digest" \
    '.config.appliedFingerprint==$digest and
     .controlPlane.databasePolicyFingerprint==$digest and
     .controlPlane.leadership.state=="active"' \
    "$control_status" >/dev/null || {
    fabric_notify critical \
      "Execution Fabric policy rotation needs attention" \
      "Witness commit succeeded, but the leader did not regain authority for $rotation_id." \
      "execution-fabric-policy-rotation-$rotation_id"
    exit 75
  }
else
  jq -n \
    --arg appliedFingerprint "$candidate_digest" \
    '{recoveredOnStandby:true,appliedFingerprint:$appliedFingerprint}' \
    >"$control_status"
fi

if [ "$role_convergence_deferred" = false ]; then
  if ! role_verify_receipt=$(
    FABRIC_POLICY_CONVERGENCE_RECREATE_RECEIPT="$role_recreate_receipt" \
      "$script_dir/converge-policy-roles.sh" --verify "$candidate_digest"
  ); then
    fabric_notify critical \
      "Execution Fabric policy role verification failed" \
      "Witness commit succeeded for rotation $rotation_id, but the complete role cohort did not report fresh healthy ticks. Rerun rotate-policy.sh --resume; mutations remain fenced." \
      "execution-fabric-policy-rotation-$rotation_id"
    exit 75
  fi
fi

jq -n \
  --arg rotationId "$rotation_id" \
  --arg expectedCurrentDigest "$expected_current" \
  --arg candidateDigest "$candidate_digest" \
  --arg mode "$mode" \
  --argjson operatorOverride "$operator_override_json" \
  --arg roleRecreateReceipt "$role_recreate_receipt" \
  --arg roleVerifyReceipt "$role_verify_receipt" \
  --argjson roleConvergenceDeferred "$role_convergence_deferred" \
  --arg completedAt "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  --slurpfile witness "$witness_receipt" \
  --slurpfile status "$control_status" \
  '{
    schemaVersion:"execution-fabric-policy-rotation-receipt/v1",
    rotationId:$rotationId,
    expectedCurrentDigest:$expectedCurrentDigest,
    candidateDigest:$candidateDigest,
    operatorOverride:$operatorOverride,
    recoveryMode:$mode,
    roleRecreateReceipt:($roleRecreateReceipt | if length>0 then . else null end),
    roleVerifyReceipt:($roleVerifyReceipt | if length>0 then . else null end),
    roleConvergenceDeferred:$roleConvergenceDeferred,
    completedAt:$completedAt,
    witness:$witness[0],
    readback:$status[0]
  }' >"$final_temp"
fabric_atomic_write "$receipt_path" "$final_temp"
if [ -s "$pending_path" ] &&
  [ "$(jq -r '.rotationId // empty' "$pending_path")" = "$rotation_id" ]
then
  unlink "$pending_path"
fi
fabric_notify info \
  "Execution Fabric policy rotation complete" \
  "Policy $candidate_digest is witness-approved; receipt: $receipt_path." \
  "execution-fabric-policy-rotation-$rotation_id"
printf '%s\n' "$receipt_path"
