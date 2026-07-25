#!/bin/sh
set -eu

expected_mode=
receipt_path=
while [ "$#" -gt 0 ]; do
  case "$1" in
    --require-standby) [ -z "$expected_mode" ] || exit 64; expected_mode=standby ;;
    --require-active) [ -z "$expected_mode" ] || exit 64; expected_mode=active ;;
    --receipt) shift; [ "$#" -gt 0 ] || exit 64; receipt_path=$1 ;;
    *) echo "usage: candidate-reporter-health.sh [--require-standby|--require-active] [--receipt PATH]" >&2; exit 64 ;;
  esac
  shift
done

script_dir=$(CDPATH="" cd -- "$(dirname -- "$0")" && pwd)
. "$script_dir/_lib.sh"
fabric_load_runtime
fabric_require_command docker
fabric_require_command jq

: "${FABRIC_HOST_ID:?host identity is required}"
: "${FABRIC_DEPLOYMENT_DIR:?deployment directory is required}"
max_age=${FABRIC_CANDIDATE_HEARTBEAT_MAX_AGE_SECONDS:-75}
case "$max_age" in ''|*[!0-9]*) echo "candidate heartbeat max age must be an integer" >&2; exit 78 ;; esac
[ "$max_age" -ge 15 ] && [ "$max_age" -le 600 ] || {
  echo "candidate heartbeat max age must be from 15 through 600 seconds" >&2
  exit 78
}

case "$FABRIC_HOST_ID" in
  genomesbox)
    compose_file="$FABRIC_DEPLOYMENT_DIR/compose.genomesbox.yml"
    profile=primary
    ;;
  bigmac)
    compose_file="$FABRIC_DEPLOYMENT_DIR/compose.bigmac.yml"
    profile=standby
    ;;
  *) echo "candidate reporter is not configured for $FABRIC_HOST_ID" >&2; exit 78 ;;
esac

receipt_path=${receipt_path:-"$FABRIC_RUNTIME_STATE_DIR/candidate-reporter-health.json"}
heartbeat_temp=$(mktemp "${TMPDIR:-/tmp}/fabric-candidate-heartbeat.XXXXXX")
receipt_temp=$(mktemp "${TMPDIR:-/tmp}/fabric-candidate-health.XXXXXX")
trap 'rm -f "$heartbeat_temp" "$receipt_temp"' EXIT HUP INT TERM
previous_status=
[ -r "$receipt_path" ] &&
  previous_status=$(jq -r '.status // empty' "$receipt_path" 2>/dev/null || true)

fail_health() {
  reason=$1
  jq -n \
    --arg hostId "$FABRIC_HOST_ID" \
    --arg checkedAt "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    --arg reason "$reason" \
    '{schemaVersion:"execution-fabric-candidate-health/v1",hostId:$hostId,status:"failed",checkedAt:$checkedAt,reason:$reason}' \
    >"$receipt_temp"
  fabric_atomic_write "$receipt_path" "$receipt_temp"
  fabric_notify critical \
    "Execution Fabric candidate reporting unhealthy" \
    "$FABRIC_HOST_ID candidate reporting failed: $reason" \
    "execution-fabric-candidate-reporter-$FABRIC_HOST_ID"
  echo "$reason" >&2
  exit 75
}

container=$(fabric_compose "$compose_file" \
  --profile "$profile" ps --status running -q candidate-reporter)
[ -n "$container" ] &&
  [ "$(printf '%s\n' "$container" | wc -l | tr -d ' ')" -eq 1 ] ||
  fail_health "candidate-reporter container is not uniquely running"

fabric_compose "$compose_file" --profile "$profile" exec -T candidate-reporter \
  node /app/dist/candidate-reporter.mjs --print-heartbeat >"$heartbeat_temp" ||
  fail_health "candidate heartbeat is unavailable"

jq -e \
  --arg hostId "$FABRIC_HOST_ID" \
  '.schemaVersion=="execution-fabric-candidate-heartbeat/v1"
   and .hostId==$hostId
   and (.lastSuccessfulAt | type=="string")
   and (.configDigest | type=="string" and test("^[a-f0-9]{64}$"))
   and (.policyCandidateDigest | type=="string" and test("^[a-f0-9]{64}$"))
   and (.policyCandidateObservedAt | type=="string")
   and (.timelineId | type=="number" and .>=1)
   and (.receiveWalPosition | type=="number" and .>=0)
   and (.replayWalPosition | type=="number")
   and (.replayWalPosition>=0 and .replayWalPosition<=.receiveWalPosition)
   and (.replicaLagBytes | type=="number" and .>=0)
   and (.lagMeasuredAt | type=="string")
   and (.upstreamSystemId | type=="string" and test("^[0-9]{1,32}$"))
   and (.receiverState | type=="string")
   and (.lastMessageAt | type=="string")
   and (.mode=="standby" or .mode=="active")' \
  "$heartbeat_temp" >/dev/null ||
  fail_health "candidate heartbeat contract is invalid"

now_epoch=$(date -u +%s)
success_epoch=$(jq -r \
  '.lastSuccessfulAt | sub("\\.[0-9]+Z$";"Z") | fromdateiso8601' \
  "$heartbeat_temp") || fail_health "candidate heartbeat timestamp is invalid"
age=$((now_epoch - success_epoch))
[ "$age" -ge -30 ] && [ "$age" -le "$max_age" ] ||
  fail_health "candidate heartbeat is stale by ${age}s"

mode=$(jq -r '.mode' "$heartbeat_temp")
if [ -n "$expected_mode" ] && [ "$mode" != "$expected_mode" ]; then
  fail_health "candidate mode is $mode, expected $expected_mode"
fi
if [ "$mode" = standby ]; then
  [ "$(jq -r '.inRecovery' "$heartbeat_temp")" = true ] ||
    fail_health "standby candidate is not in PostgreSQL recovery"
else
  [ "$(jq -r '.inRecovery' "$heartbeat_temp")" = false ] ||
    fail_health "active candidate incorrectly reports PostgreSQL recovery"
fi

jq \
  --arg checkedAt "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  --argjson ageSeconds "$age" \
  --arg expectedMode "${expected_mode:-any}" \
  '{schemaVersion:"execution-fabric-candidate-health/v1",hostId,status:"healthy",
    checkedAt:$checkedAt,ageSeconds:$ageSeconds,expectedMode:$expectedMode,
    heartbeat:.}' "$heartbeat_temp" >"$receipt_temp"
fabric_atomic_write "$receipt_path" "$receipt_temp"
if [ "$previous_status" = failed ]; then
  fabric_notify info \
    "Execution Fabric candidate reporting recovered" \
    "$FABRIC_HOST_ID candidate heartbeat is fresh in $mode mode." \
    "execution-fabric-candidate-reporter-$FABRIC_HOST_ID"
fi
cat "$receipt_path"
