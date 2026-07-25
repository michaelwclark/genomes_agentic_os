#!/bin/sh
set -eu

usage() {
  echo "usage: failback.sh --prepare | --reseed --preparation-file PATH | --plan --preparation-file PATH | --approve --operator ID | --apply --approval-file PATH" >&2
  exit 64
}

action=
operator=
approval_file=
preparation_file=
while [ "$#" -gt 0 ]; do
  case "$1" in
    --prepare|--reseed|--plan|--approve|--apply)
      [ -z "$action" ] || usage
      action=${1#--}
      ;;
    --operator) shift; [ "$#" -gt 0 ] || usage; operator=$1 ;;
    --approval-file) shift; [ "$#" -gt 0 ] || usage; approval_file=$1 ;;
    --preparation-file) shift; [ "$#" -gt 0 ] || usage; preparation_file=$1 ;;
    *) usage ;;
  esac
  shift
done
[ -n "$action" ] || usage

script_dir=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
. "$script_dir/_lib.sh"
fabric_load_runtime
fabric_require_command curl
fabric_require_command jq
fabric_require_command docker
fabric_require_command node

: "${FABRIC_LEADERSHIP_API_BASE:?independent leadership API is required}"
: "${FABRIC_LEADERSHIP_TOKEN_FILE:?witness reader token file is required}"
: "${FABRIC_LEADERSHIP_ADMIN_TOKEN_FILE:?witness admin token file is required}"
: "${FABRIC_DEPLOYMENT_DIR:?installed deployment directory is required}"
: "${FABRIC_CLUSTER_ID:?fabric cluster id is required}"
: "${FABRIC_LEADERSHIP_PUBLIC_KEY_FILE:?witness public key is required}"
: "${FABRIC_PRIMARY_HOST_ID:?primary host id is required}"
: "${FABRIC_STANDBY_HOST_ID:?standby host id is required}"
: "${FABRIC_PRIMARY_SSH_TARGET:?primary SSH target is required}"
: "${FABRIC_REMOTE_INSTALLER_DIR:?remote installer directory is required}"

plan_path="$FABRIC_RUNTIME_STATE_DIR/failback.plan.json"
preparation_path="$FABRIC_RUNTIME_STATE_DIR/failback.reseed-authorization.json"
eligibility_path="$FABRIC_RUNTIME_STATE_DIR/failback.target-eligibility.json"
temporary=$(mktemp "${TMPDIR:-/tmp}/fabric-failback.XXXXXX")
status_temp=$(mktemp "${TMPDIR:-/tmp}/fabric-failback-status.XXXXXX")
trap 'rm -f "$temporary" "$status_temp"' EXIT HUP INT TERM

if [ "$action" = prepare ]; then
  [ -z "$operator$approval_file$preparation_file" ] || usage
  "$script_dir/validate-artifact-replication-receipt.sh"
  prepare_request=$(jq -cn \
    --arg from "$FABRIC_STANDBY_HOST_ID" \
    --arg to "$FABRIC_PRIMARY_HOST_ID" \
    '{from:$from,to:$to,mode:"standby_reseed"}')
  fabric_api_post \
    "$FABRIC_LEADERSHIP_API_BASE" \
    "/api/v1/admin/leadership/failback-prepare" \
    "$FABRIC_LEADERSHIP_ADMIN_TOKEN_FILE" \
    "$prepare_request" >"$temporary"
  [ "$(fabric_json_field "$temporary" '.authorized')" = true ] || {
    echo "leadership API did not authorize target reseed" >&2
    exit 75
  }
  fabric_atomic_write "$preparation_path" "$temporary"
  cat "$temporary"
  exit 0
fi

if [ "$action" = reseed ]; then
  [ -z "$operator$approval_file" ] && [ -s "$preparation_file" ] || usage
  preparation_token=$(fabric_json_field "$preparation_file" '.preparationToken')
  expected_epoch=$(fabric_json_field "$preparation_file" '.expectedEpoch')
  [ -n "$preparation_token" ] || {
    echo "standby reseed authorization is missing its opaque token" >&2
    exit 75
  }
  fabric_api_get_bearer \
    "$FABRIC_LEADERSHIP_API_BASE" \
    "/api/v1/admin/leadership/status" \
    "$FABRIC_LEADERSHIP_TOKEN_FILE" >"$status_temp"
  [ "$(fabric_json_field "$status_temp" '.currentLeader')" = "$FABRIC_STANDBY_HOST_ID" ] &&
    [ "$(fabric_json_field "$status_temp" '.fabricEpoch')" -eq "$expected_epoch" ] || {
    echo "witness leadership changed after standby reseed authorization" >&2
    exit 75
  }
  compose="docker compose --env-file $FABRIC_RUNTIME_ENV_FILE -f $FABRIC_DEPLOYMENT_DIR/compose.bigmac.yml"
  $compose --profile promoted exec -T postgres \
    psql -X -v ON_ERROR_STOP=1 -U "${FABRIC_POSTGRES_USER:-fabric}" \
      -d "${FABRIC_POSTGRES_DB:-execution_fabric}" \
      -c "SELECT pg_create_physical_replication_slot('fabric_failback_target') WHERE NOT EXISTS (SELECT 1 FROM pg_replication_slots WHERE slot_name='fabric_failback_target')"
  ssh "$FABRIC_PRIMARY_SSH_TARGET" \
    "$FABRIC_REMOTE_INSTALLER_DIR/bin/reseed-postgres-standby.sh --apply --target-role failback-target"
  fabric_api_get_bearer \
    "$FABRIC_LEADERSHIP_API_BASE" \
    "/api/v1/admin/leadership/status" \
    "$FABRIC_LEADERSHIP_TOKEN_FILE" >"$status_temp"
  [ "$(fabric_json_field "$status_temp" '.currentLeader')" = "$FABRIC_STANDBY_HOST_ID" ] &&
    [ "$(fabric_json_field "$status_temp" '.fabricEpoch')" -eq "$expected_epoch" ] &&
    [ "$(jq -er --arg host "$FABRIC_PRIMARY_HOST_ID" '.candidates[$host].eligible' "$status_temp")" = true ] &&
    [ "$(jq -er --arg host "$FABRIC_PRIMARY_HOST_ID" '.candidates[$host].inRecovery' "$status_temp")" = true ] &&
    [ "$(jq -er --arg host "$FABRIC_PRIMARY_HOST_ID" '.candidates[$host].timelineId' "$status_temp")" -eq \
      "$(fabric_json_field "$status_temp" '.timelineId')" ] || {
    echo "$FABRIC_PRIMARY_HOST_ID reseed completed but measured transfer eligibility failed" >&2
    exit 75
  }
  printf '%s' "$preparation_token" >"$temporary"
  preparation_token_hash=$(fabric_sha256 "$temporary")
  jq -n \
    --arg preparationTokenHash "$preparation_token_hash" \
    --arg host "$FABRIC_PRIMARY_HOST_ID" \
    --argjson expectedEpoch "$expected_epoch" \
    --arg measuredAt "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    --slurpfile witness "$status_temp" \
    '{schemaVersion:"execution-fabric-failback-target-eligibility/v1",
      preparationTokenHash:$preparationTokenHash,
      expectedEpoch:$expectedEpoch,measuredAt:$measuredAt,
      candidate:$witness[0].candidates[$host]}' >"$temporary"
  fabric_atomic_write "$eligibility_path" "$temporary"
  cat "$temporary"
  exit 0
fi

if [ "$action" = plan ]; then
  [ -z "$operator$approval_file" ] && [ -s "$preparation_file" ] || usage
  [ -s "$eligibility_path" ] || {
    echo "measured target eligibility is required before transfer planning" >&2
    exit 78
  }
  preparation_token=$(fabric_json_field "$preparation_file" '.preparationToken')
  plan_request=$(jq -cn \
    --arg from "$FABRIC_STANDBY_HOST_ID" \
    --arg to "$FABRIC_PRIMARY_HOST_ID" \
    --arg preparationToken "$preparation_token" \
    '{from:$from,to:$to,mode:"manual_failback",preparationToken:$preparationToken}')
  fabric_api_post \
    "$FABRIC_LEADERSHIP_API_BASE" \
    "/api/v1/admin/leadership/failback-plan" \
    "$FABRIC_LEADERSHIP_ADMIN_TOKEN_FILE" \
    "$plan_request" >"$temporary"
  [ "$(fabric_json_field "$temporary" '.safe')" = true ] || {
    cat "$temporary"
    echo "leadership API reports transfer plan unsafe" >&2
    exit 75
  }
  fabric_atomic_write "$plan_path" "$temporary"
  cat "$temporary"
  exit 0
fi

[ -s "$plan_path" ] || {
  echo "a current failback transfer plan is required: $plan_path" >&2
  exit 78
}
plan_token=$(fabric_json_field "$plan_path" '.planToken')
printf '%s' "$plan_token" >"$temporary"
plan_token_hash=$(fabric_sha256 "$temporary")

if [ "$action" = approve ]; then
  [ -n "$operator" ] && [ -z "$approval_file" ] || usage
  case "$operator" in *[!a-zA-Z0-9._@:-]*|"") usage ;; esac
  jq -cn \
    --arg planTokenHash "$plan_token_hash" \
    --arg approvalId "$(python3 -c 'import uuid; print(uuid.uuid4())')" \
    --arg approvedBy "$operator" \
    --arg approvedAt "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    '{planTokenHash:$planTokenHash,approvalId:$approvalId,approvedBy:$approvedBy,approvedAt:$approvedAt}' \
    >"$temporary"
  approval_path="$FABRIC_RUNTIME_STATE_DIR/failback.approval.json"
  fabric_atomic_write "$approval_path" "$temporary"
  printf '%s\n' "$approval_path"
  exit 0
fi

[ "$action" = apply ] && [ -z "$operator$preparation_file" ] && [ -s "$approval_file" ] || usage
[ "$(fabric_json_field "$approval_file" '.planTokenHash')" = "$plan_token_hash" ] || {
  echo "operator approval is not bound to the current failback plan" >&2
  exit 75
}
"$script_dir/validate-artifact-replication-receipt.sh"
"$script_dir/validate-backup-health-receipt.sh"

# Fence the old mutation plane before the independent witness advances epoch.
compose="docker compose --env-file $FABRIC_RUNTIME_ENV_FILE -f $FABRIC_DEPLOYMENT_DIR/compose.bigmac.yml"
$compose --profile promoted stop control-plane observer healer scheduler
commit_request=$(jq -cn \
  --arg planToken "$plan_token" \
  --slurpfile approval "$approval_file" \
  '{planToken:$planToken,approval:$approval[0]}')
fabric_api_post \
  "$FABRIC_LEADERSHIP_API_BASE" \
  "/api/v1/admin/leadership/failback-commit" \
  "$FABRIC_LEADERSHIP_ADMIN_TOKEN_FILE" \
  "$commit_request" >"$temporary"

[ "$(fabric_json_field "$temporary" '.decision')" = committed ] || {
  echo "leadership API did not commit failback" >&2
  exit 75
}
new_epoch=$(fabric_json_field "$temporary" '.fabricEpoch')
node "$script_dir/verify-leadership-receipt.mjs" \
  "$temporary" "$FABRIC_LEADERSHIP_PUBLIC_KEY_FILE" \
  "$FABRIC_CLUSTER_ID" "$FABRIC_PRIMARY_HOST_ID" "$new_epoch" \
  >"$FABRIC_RUNTIME_STATE_DIR/failback-verification.json"

# The target verifies witness readback, promotes PostgreSQL, then starts its
# mutation roles. Witness commit never occurs before target reseed/catch-up.
# shellcheck disable=SC2029 # Remote installer path is an operator-owned setting.
ssh "$FABRIC_PRIMARY_SSH_TARGET" \
  "$FABRIC_REMOTE_INSTALLER_DIR/bin/activate-receipt.sh --stdin --expected-leader $FABRIC_PRIMARY_HOST_ID" \
  <"$temporary"
fabric_atomic_write "$FABRIC_RUNTIME_STATE_DIR/failback.receipt.json" "$temporary"

# Only after the configured primary is active do we destroy and rebuild the former
# primary data as a standby. Failure here is critical but cannot split brain.
"$script_dir/reseed-postgres-standby.sh" --apply --target-role standby
# The promoted target was intentionally fenced while no synchronous standby
# existed. Enable acknowledged mutations only after the standby is rebuilt and
# PostgreSQL proves remote_apply with a streaming sync replica.
ssh "$FABRIC_PRIMARY_SSH_TARGET" \
  "$FABRIC_REMOTE_INSTALLER_DIR/bin/enable-postgres-durable-primary.sh --apply --expected-leader $FABRIC_PRIMARY_HOST_ID"
if [ -s "$FABRIC_RUNTIME_STATE_DIR/degraded-primary.receipt.json" ]; then
  jq \
    --arg restoredAt "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    '.status="restored" | .redundancyRestored=true | .restoredAt=$restoredAt' \
    "$FABRIC_RUNTIME_STATE_DIR/degraded-primary.receipt.json" >"$status_temp"
  fabric_atomic_write \
    "$FABRIC_RUNTIME_STATE_DIR/degraded-primary.receipt.json" \
    "$status_temp"
fi
fabric_notify warning \
  "Execution Fabric failback completed" \
  "$FABRIC_PRIMARY_HOST_ID is active at epoch $new_epoch and $FABRIC_STANDBY_HOST_ID has been rebuilt as its standby." \
  "execution-fabric-failback-complete"
