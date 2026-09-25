#!/bin/sh
set -eu

script_dir=$(CDPATH="" cd -- "$(dirname -- "$0")" && pwd)
# shellcheck source=_lib.sh
. "$script_dir/_lib.sh"
fabric_load_runtime

[ "${FABRIC_LOS_SECURITY_WORKER_ENABLED:-false}" = true ] || {
  echo "LOS security-remediation worker is disabled" >&2
  exit 78
}

: "${FABRIC_LOS_SECURITY_WORKER_ID:?LOS security worker identity is required}"
: "${FABRIC_LOS_SECURITY_WORKER_BOOTSTRAP_ID:?LOS security worker bootstrap identity is required}"
: "${FABRIC_LOS_SECURITY_WORKER_POOL_ID:?LOS security worker pool is required}"
: "${FABRIC_LOS_SECURITY_WORKER_ACCEPTED_QUEUES:?LOS security worker queue is required}"
: "${FABRIC_LOS_SECURITY_WORKER_CAPABILITIES:?LOS security worker capability is required}"
: "${FABRIC_LOS_SECURITY_WORKER_MAX_CONCURRENCY:?LOS security worker concurrency is required}"
: "${FABRIC_LOS_SECURITY_WORKER_TOKEN_FILE:?LOS security worker token file is required}"
: "${FABRIC_GATEWAY_API_BASE:?stable per-host gateway API base is required}"
: "${FABRIC_OS_ROOT:?installed Agentic OS root is required}"

[ -s "$FABRIC_LOS_SECURITY_WORKER_TOKEN_FILE" ] || {
  echo "LOS security worker token file is missing or empty" >&2
  exit 78
}

case "$FABRIC_LOS_SECURITY_WORKER_MAX_CONCURRENCY" in
  ''|*[!0-9]*)
    echo "LOS security worker concurrency must be a positive integer" >&2
    exit 78
    ;;
esac
[ "$FABRIC_LOS_SECURITY_WORKER_MAX_CONCURRENCY" -ge 1 ] || {
  echo "LOS security worker concurrency must be a positive integer" >&2
  exit 78
}

FABRIC_WORKER_ID=$FABRIC_LOS_SECURITY_WORKER_ID
FABRIC_WORKER_BOOTSTRAP_ID=$FABRIC_LOS_SECURITY_WORKER_BOOTSTRAP_ID
FABRIC_WORKER_POOL_ID=$FABRIC_LOS_SECURITY_WORKER_POOL_ID
FABRIC_WORKER_ACCEPTED_QUEUES=$FABRIC_LOS_SECURITY_WORKER_ACCEPTED_QUEUES
FABRIC_WORKER_CAPABILITIES=$FABRIC_LOS_SECURITY_WORKER_CAPABILITIES
FABRIC_WORKER_MAX_CONCURRENCY=$FABRIC_LOS_SECURITY_WORKER_MAX_CONCURRENCY
AGENTIC_OS_EXECUTION_FABRIC_WORKER_TOKEN_FILE=$FABRIC_LOS_SECURITY_WORKER_TOKEN_FILE
FABRIC_API_BASE=$FABRIC_GATEWAY_API_BASE
AGENTIC_OS_ROOT=$FABRIC_OS_ROOT
FABRIC_WORKER_ROOT_MODE=installed_host
export FABRIC_WORKER_ID FABRIC_WORKER_BOOTSTRAP_ID FABRIC_WORKER_POOL_ID
export FABRIC_WORKER_ACCEPTED_QUEUES FABRIC_WORKER_CAPABILITIES
export FABRIC_WORKER_MAX_CONCURRENCY AGENTIC_OS_EXECUTION_FABRIC_WORKER_TOKEN_FILE
export FABRIC_API_BASE AGENTIC_OS_ROOT FABRIC_WORKER_ROOT_MODE

worker="$script_dir/python-worker.sh"
[ -x "$worker" ] || {
  echo "packaged Python worker is unavailable: $worker" >&2
  exit 69
}

if [ "${1:-}" = --preflight ]; then
  [ "$#" -eq 1 ] || {
    echo "usage: los-security-worker.sh [--preflight]" >&2
    exit 64
  }
  exec "$worker" --preflight
fi
[ "$#" -eq 0 ] || {
  echo "usage: los-security-worker.sh [--preflight]" >&2
  exit 64
}
exec "$worker"
