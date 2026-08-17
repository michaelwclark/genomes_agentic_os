#!/bin/sh
set -eu

script_dir=$(CDPATH="" cd -- "$(dirname -- "$0")" && pwd)
# shellcheck source=_lib.sh
. "$script_dir/_lib.sh"
fabric_load_runtime
fabric_require_command curl
fabric_require_command jq

api_base=${FABRIC_GATEWAY_API_BASE:-${FABRIC_API_BASE:-}}
: "${api_base:?FABRIC_GATEWAY_API_BASE or FABRIC_API_BASE is required}"
: "${FABRIC_ALARM_DISPATCHER_TOKEN_FILE:?FABRIC_ALARM_DISPATCHER_TOKEN_FILE is required}"
limit=${FABRIC_ALARM_DISPATCH_LIMIT:-20}
consumer_id=${FABRIC_ALARM_DISPATCHER_CONSUMER_ID:-bigmac-agentic-os-notifier}
source=${FABRIC_ALARM_DISPATCHER_SOURCE:-agentic-os-notify}
notifier="$FABRIC_OS_ROOT/harness/bin/agentic-os-notify"

claim_body=$(jq -cn \
  --arg consumerId "$consumer_id" \
  --arg source "$source" \
  --argjson limit "$limit" \
  '{consumerId:$consumerId,source:$source,limit:$limit}')
response=$(mktemp "${TMPDIR:-/tmp}/fabric-alarms.XXXXXX")
trap 'rm -f "$response"' EXIT HUP INT TERM
fabric_api_post \
  "$api_base" \
  "/api/v1/alarms/claim" \
  "$FABRIC_ALARM_DISPATCHER_TOKEN_FILE" \
  "$claim_body" >"$response"

jq -c '.alarms[]?' "$response" | while IFS= read -r alarm; do
  alarm_id=$(printf '%s' "$alarm" | jq -er '.alarmId')
  claim_token=$(printf '%s' "$alarm" | jq -er '.claimToken')
  fabric_epoch=$(printf '%s' "$alarm" | jq -er '.fabricEpoch')
  incident_key=$(printf '%s' "$alarm" | jq -er '.incidentKey')
  severity=$(printf '%s' "$alarm" | jq -er '.severity')
  summary=$(printf '%s' "$alarm" | jq -er '.payload.summary')
  case "$severity" in
    critical|warning|error|info) ;;
    *) severity=warning ;;
  esac

  # The notification helper is Python and its env shebang would otherwise
  # resolve launchd's system interpreter.  Run it through the immutable
  # Fabric runtime so its declared dependencies (including PyYAML) are always
  # available on the headless BigMac client plane.
  if [ -x "$notifier" ] && "$FABRIC_WORKER_PYTHON" "$notifier" \
    --source runtime.execution_fabric.health \
    --level "$severity" \
    --title "Execution Fabric needs attention" \
    --message "$summary" \
    --dedupe-key "$incident_key"; then
    delivery_body=$(jq -cn \
      --arg consumerId "$consumer_id" \
      --arg claimToken "$claim_token" \
      --argjson fabricEpoch "$fabric_epoch" \
      '{
        consumerId:$consumerId,
        claimToken:$claimToken,
        fabricEpoch:$fabricEpoch,
        deliveryReceipt:{
          dispatcher:"agentic-os-notify",
          accepted:true
        }
      }')
    fabric_api_post_bearer_value \
      "$api_base" \
      "/api/v1/alarms/${alarm_id}/deliver" \
      "$claim_token" \
      "$delivery_body" >/dev/null
  else
    failure_body=$(jq -cn \
      --arg consumerId "$consumer_id" \
      --arg claimToken "$claim_token" \
      --argjson fabricEpoch "$fabric_epoch" \
      '{
        consumerId:$consumerId,
        claimToken:$claimToken,
        fabricEpoch:$fabricEpoch,
        errorSummary:"Agentic OS notifier unavailable or rejected alarm"
      }')
    fabric_api_post_bearer_value \
      "$api_base" \
      "/api/v1/alarms/${alarm_id}/fail" \
      "$claim_token" \
      "$failure_body" >/dev/null
  fi
done
