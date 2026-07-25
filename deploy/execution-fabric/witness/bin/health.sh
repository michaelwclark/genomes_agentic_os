#!/bin/sh
set -eu

script_dir=$(CDPATH="" cd -- "$(dirname -- "$0")" && pwd)
# shellcheck source=_lib.sh
. "$script_dir/_lib.sh"
witness_load_environment

[ "${WITNESS_MODE:-}" = independent ] || {
  echo "witness is intentionally unavailable in manual_fail_closed mode" >&2
  exit 78
}
witness_require_command curl
base=$(witness_api_base)
curl --fail --silent --show-error --connect-timeout 3 --max-time 8 \
  "$base/healthz" >/dev/null
curl --fail --silent --show-error --connect-timeout 3 --max-time 8 \
  "$base/readyz" >/dev/null
printf '%s\n' "witness healthy: $base"
