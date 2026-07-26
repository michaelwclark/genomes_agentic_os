#!/bin/sh
set -eu

script_dir=$(CDPATH="" cd -- "$(dirname -- "$0")" && pwd)
# shellcheck source=_lib.sh
. "$script_dir/_lib.sh"
fabric_load_runtime
fabric_require_command curl
fabric_require_command jq

: "${FABRIC_HOST_ID:?stable client host identity is required}"
: "${FABRIC_PRIMARY_HOST_ID:?stable primary host identity is required}"
: "${FABRIC_STANDBY_HOST_ID:?stable client host identity is required}"
[ "$FABRIC_HOST_ID" = "$FABRIC_STANDBY_HOST_ID" ] &&
  [ "$FABRIC_HOST_ID" != "$FABRIC_PRIMARY_HOST_ID" ] || {
  echo "personal client must run on the configured non-primary host" >&2
  exit 78
}
[ "${FABRIC_AUTO_FAILOVER:-false}" = false ] &&
  [ "${FABRIC_ENABLE_PROMOTION:-false}" = false ] || {
  echo "personal client mode does not permit automatic failover or shared-ledger promotion" >&2
  exit 78
}

: "${FABRIC_AGENTIC_OS_CLI:?installed Agentic OS CLI is required}"
[ -x "$FABRIC_AGENTIC_OS_CLI" ] || {
  echo "configured Agentic OS CLI is not executable" >&2
  exit 69
}
: "${FABRIC_GATEWAY_API_BASE:?signed-leader gateway API is required}"
: "${FABRIC_WORKER_ID:?durable worker identity is required}"
: "${FABRIC_WORKER_BOOTSTRAP_ID:?scoped worker bootstrap identity is required}"
: "${FABRIC_WORKER_POOL_ID:?worker pool identity is required}"
: "${FABRIC_WORKER_ACCEPTED_QUEUES:?worker queue set is required}"
: "${FABRIC_WORKER_CAPABILITIES:?worker capability set is required}"
: "${FABRIC_WORKER_MAX_CONCURRENCY:?worker concurrency is required}"
: "${AGENTIC_OS_EXECUTION_FABRIC_WORKER_TOKEN_FILE:?scoped worker token file is required}"
: "${FABRIC_ALARM_DISPATCHER_TOKEN_FILE:?scoped alarm dispatcher token file is required}"
: "${FABRIC_ALARM_DISPATCHER_CONSUMER_ID:?scoped alarm dispatcher identity is required}"
: "${FABRIC_ALARM_DISPATCHER_SOURCE:?scoped alarm dispatcher source is required}"

identifier_pattern='^[a-zA-Z0-9._:-]{1,128}$'
for identifier in \
  "$FABRIC_HOST_ID" \
  "$FABRIC_WORKER_ID" \
  "$FABRIC_WORKER_BOOTSTRAP_ID" \
  "$FABRIC_WORKER_POOL_ID" \
  "$FABRIC_ALARM_DISPATCHER_CONSUMER_ID" \
  "$FABRIC_ALARM_DISPATCHER_SOURCE"
do
  printf '%s\n' "$identifier" | grep -Eq "$identifier_pattern" || {
    echo "personal client identity is invalid" >&2
    exit 78
  }
done

case "$FABRIC_WORKER_MAX_CONCURRENCY" in
  ''|*[!0-9]*) echo "FABRIC_WORKER_MAX_CONCURRENCY must be an integer from 1 through 256" >&2; exit 78 ;;
esac
[ "$FABRIC_WORKER_MAX_CONCURRENCY" -ge 1 ] &&
  [ "$FABRIC_WORKER_MAX_CONCURRENCY" -le 256 ] || {
  echo "FABRIC_WORKER_MAX_CONCURRENCY must be an integer from 1 through 256" >&2
  exit 78
}

for csv_value in "$FABRIC_WORKER_ACCEPTED_QUEUES" "$FABRIC_WORKER_CAPABILITIES"; do
  jq -en --arg csv "$csv_value" '
    ($csv | split(",") | map(gsub("^\\s+|\\s+$"; ""))) as $items |
    ($items | length) > 0 and
    all($items[]; test("^[a-zA-Z0-9._:-]{1,128}$")) and
    ($items | unique | length) == ($items | length)
  ' >/dev/null || {
    echo "worker queue and capability sets must be non-empty, unique stable identifiers" >&2
    exit 78
  }
done

read_scoped_token() {
  token_path=$1
  token_label=$2
  [ -s "$token_path" ] || {
    echo "$token_label file is missing or empty" >&2
    exit 78
  }
  token_value=$(cat "$token_path")
  case "$token_value" in
    *[[:space:]]*) echo "$token_label must contain one non-whitespace token" >&2; exit 78 ;;
  esac
  [ "${#token_value}" -ge 32 ] || {
    echo "$token_label must contain at least 32 characters" >&2
    exit 78
  }
  printf '%s' "$token_value"
}

worker_token=$(read_scoped_token \
  "$AGENTIC_OS_EXECUTION_FABRIC_WORKER_TOKEN_FILE" "worker credential")
alarm_token=$(read_scoped_token \
  "$FABRIC_ALARM_DISPATCHER_TOKEN_FILE" "alarm dispatcher credential")
[ "$worker_token" != "$alarm_token" ] || {
  echo "worker and alarm dispatcher credentials must be distinct" >&2
  exit 78
}
unset worker_token alarm_token token_value

worker_python=${FABRIC_WORKER_PYTHON:-python3}
fabric_require_command "$worker_python"
"$worker_python" - "$FABRIC_GATEWAY_API_BASE" <<'PY'
import ipaddress
import sys
from urllib.parse import urlsplit

value = sys.argv[1].rstrip("/")
parsed = urlsplit(value)
if parsed.scheme not in {"http", "https"} or not parsed.hostname:
    raise SystemExit("gateway must be an absolute HTTP(S) URL")
if parsed.username or parsed.password or parsed.query or parsed.fragment:
    raise SystemExit("gateway URL must not contain credentials, query, or fragment")
try:
    address = ipaddress.ip_address(parsed.hostname)
except ValueError:
    address = None
tailscale = isinstance(address, ipaddress.IPv4Address) and address in ipaddress.ip_network("100.64.0.0/10")
if parsed.scheme != "https" and not tailscale:
    raise SystemExit("gateway requires HTTPS or a literal Tailscale address")
PY

policy_temp=$(mktemp "${TMPDIR:-/tmp}/fabric-personal-client-policy.XXXXXX")
gateway_temp=$(mktemp "${TMPDIR:-/tmp}/fabric-personal-client-gateway.XXXXXX")
trap 'rm -f "$policy_temp" "$gateway_temp"' EXIT HUP INT TERM
"$FABRIC_AGENTIC_OS_CLI" runtime config show \
  --root "$FABRIC_OS_ROOT" --json >"$policy_temp"
jq -e \
  --arg host "$FABRIC_HOST_ID" \
  --arg pool "$FABRIC_WORKER_POOL_ID" \
  --arg queues "$FABRIC_WORKER_ACCEPTED_QUEUES" \
  --argjson concurrency "$FABRIC_WORKER_MAX_CONCURRENCY" '
    .effective.execution_fabric as $fabric |
    ($queues | split(",") | map(gsub("^\\s+|\\s+$"; "")) | sort) as $queue_set |
    ($fabric.worker_pools | map(select(.id==$pool))) as $pools |
    ($fabric.queues | map(select(.id as $id | $queue_set | index($id)))) as $queues_found |
    $fabric.transport.mode=="remote_with_local_fallback" and
    ($fabric.transport.control_plane_url | type=="string" and length>0) and
    ($pools | length)==1 and
    ($pools[0].queues | sort)==$queue_set and
    $pools[0].enabled==true and
    $pools[0].capacity.max_tasks_per_worker >= $concurrency and
    ($queues_found | length)==($queue_set | length) and
    all($queues_found[]; .enabled==true and .worker_pool==$pool) and
    $fabric.admission.host_limits[$host] >= $concurrency
  ' "$policy_temp" >/dev/null || {
  echo "personal worker identity, queues, pool, concurrency, or fallback transport conflicts with canonical policy" >&2
  exit 78
}

"$FABRIC_AGENTIC_OS_CLI" runtime fallback status \
  --root "$FABRIC_OS_ROOT" --json >/dev/null

worker_executable=${FABRIC_WORKER_EXECUTABLE:-"$script_dir/python-worker.sh"}
[ -x "$worker_executable" ] || {
  echo "configured worker executable is unavailable: $worker_executable" >&2
  exit 69
}
if [ "$worker_executable" = "$script_dir/python-worker.sh" ]; then
  "$worker_executable" --preflight
  AGENTIC_OS_ROOT="$FABRIC_OS_ROOT" \
    FABRIC_WORKER_ROOT_MODE=installed_host \
    FABRIC_API_BASE="$FABRIC_GATEWAY_API_BASE" \
    "$worker_executable" --validate-routes >/dev/null
fi

[ -x "$FABRIC_OS_ROOT/harness/bin/agentic-os-notify" ] || {
  echo "canonical Agentic OS notifier is unavailable" >&2
  exit 69
}
curl --fail --silent --show-error --connect-timeout 5 --max-time 15 \
  "${FABRIC_GATEWAY_API_BASE%/}/gateway/status" >"$gateway_temp"
jq -e '.state=="routable" and (.leader | type=="string" and length>0)' \
  "$gateway_temp" >/dev/null || {
  echo "signed-leader gateway is not currently routable" >&2
  exit 75
}

printf '%s\n' "Execution Fabric personal client preflight passed"
