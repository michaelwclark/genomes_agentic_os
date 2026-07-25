#!/bin/sh
set -eu

script_dir=$(CDPATH="" cd -- "$(dirname -- "$0")" && pwd)
# shellcheck source=_lib.sh
. "$script_dir/_lib.sh"
fabric_load_runtime

: "${FABRIC_WORKER_EXECUTABLE:?FABRIC_WORKER_EXECUTABLE is required}"

if [ ! -x "$FABRIC_WORKER_EXECUTABLE" ]; then
  echo "configured worker executable is unavailable: $FABRIC_WORKER_EXECUTABLE" >&2
  exit 69
fi

# Workers always use the stable local gateway. The gateway follows only a
# signed witness leadership proof and fences itself when that proof expires.
: "${FABRIC_GATEWAY_API_BASE:?stable per-host gateway API base is required}"
FABRIC_API_BASE=$FABRIC_GATEWAY_API_BASE
export FABRIC_API_BASE
exec "$FABRIC_WORKER_EXECUTABLE"
