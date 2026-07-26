#!/bin/sh
set -eu

script_dir=$(CDPATH="" cd -- "$(dirname -- "$0")" && pwd)
# shellcheck source=_lib.sh
. "$script_dir/_lib.sh"
fabric_load_runtime

FABRIC_WORKER_EXECUTABLE=${FABRIC_WORKER_EXECUTABLE:-"$script_dir/python-worker.sh"}

if [ ! -x "$FABRIC_WORKER_EXECUTABLE" ]; then
  echo "configured worker executable is unavailable: $FABRIC_WORKER_EXECUTABLE" >&2
  exit 69
fi

# Workers always use the stable local gateway. The gateway follows only a
# signed witness leadership proof and fences itself when that proof expires.
: "${FABRIC_GATEWAY_API_BASE:?stable per-host gateway API base is required}"
FABRIC_API_BASE=$FABRIC_GATEWAY_API_BASE
# The packaged macOS/Linux worker runs against the canonical installed OS root.
# Portable OCI workers invoke the Python module directly and retain its
# disposable-root bootstrap behavior.
AGENTIC_OS_ROOT=${AGENTIC_OS_ROOT:-$FABRIC_OS_ROOT}
FABRIC_WORKER_ROOT_MODE=installed_host
export FABRIC_API_BASE AGENTIC_OS_ROOT FABRIC_WORKER_ROOT_MODE
exec "$FABRIC_WORKER_EXECUTABLE"
