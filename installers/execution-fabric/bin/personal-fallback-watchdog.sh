#!/bin/sh
set -eu

script_dir=$(CDPATH="" cd -- "$(dirname -- "$0")" && pwd)
# shellcheck source=_lib.sh
. "$script_dir/_lib.sh"
fabric_load_runtime
fabric_require_command jq

: "${FABRIC_AGENTIC_OS_CLI:?FABRIC_AGENTIC_OS_CLI is required}"
[ -x "$FABRIC_AGENTIC_OS_CLI" ] || {
  echo "configured Agentic OS CLI is not executable: $FABRIC_AGENTIC_OS_CLI" >&2
  exit 69
}

before=$(
  "$FABRIC_AGENTIC_OS_CLI" runtime fallback status \
    --root "$FABRIC_OS_ROOT" --json 2>/dev/null || printf '%s\n' '{"status":"unknown"}'
)
result_file=$(mktemp "${TMPDIR:-/tmp}/fabric-personal-fallback.XXXXXX")
trap 'rm -f "$result_file"' EXIT HUP INT TERM

set +e
"$FABRIC_AGENTIC_OS_CLI" runtime fallback probe \
  --root "$FABRIC_OS_ROOT" --apply --json >"$result_file"
probe_status=$?
set -e

after_status=$(jq -er '.status' "$result_file")
before_status=$(printf '%s\n' "$before" | jq -r '.status // "unknown"')
primary_ready=$(jq -er '.primary_ready' "$result_file")

if [ "$after_status" = active ] && [ "$before_status" != active ]; then
  fabric_notify critical \
    "Execution Fabric local fallback ACTIVE" \
    "genomesbox failed the sustained readiness threshold. bigmac is now using its local durable queue. Failback is manual." \
    "execution-fabric-personal-fallback-active"
elif [ "$after_status" = active ] && [ "$primary_ready" = true ]; then
  fabric_notify warning \
    "Execution Fabric primary recovered" \
    "genomesbox is reachable again, but bigmac remains latched to local fallback until you run the explicit failback command." \
    "execution-fabric-personal-fallback-recovered"
fi

cat "$result_file"
exit "$probe_status"
