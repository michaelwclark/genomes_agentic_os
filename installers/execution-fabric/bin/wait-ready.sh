#!/bin/sh
set -eu

script_dir=$(CDPATH="" cd -- "$(dirname -- "$0")" && pwd)
# shellcheck source=_lib.sh
. "$script_dir/_lib.sh"
fabric_load_runtime
fabric_require_command curl
: "${FABRIC_API_BASE:?FABRIC_API_BASE is required}"

attempt=0
while [ "$attempt" -lt 24 ]; do
  if fabric_api_get "$FABRIC_API_BASE" "/readyz" >/dev/null 2>&1; then
    exit 0
  fi
  attempt=$((attempt + 1))
  sleep 5
done
echo "execution-fabric API did not become ready" >&2
exit 70
