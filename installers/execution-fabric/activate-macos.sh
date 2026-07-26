#!/bin/sh
set -eu

usage() {
  echo "usage: activate-macos.sh --apply [--personal-fallback]" >&2
  exit 64
}

apply=false
personal_fallback=false
while [ "$#" -gt 0 ]; do
  case "$1" in
    --apply) apply=true ;;
    --personal-fallback) personal_fallback=true ;;
    *) usage ;;
  esac
  shift
done

[ "$apply" = true ] || usage
[ "$(uname -s)" = Darwin ] || {
  echo "macOS activation must run on Darwin" >&2
  exit 77
}

script_dir=$(CDPATH="" cd -- "$(dirname -- "$0")" && pwd)
preflight="$script_dir/bin/preflight.sh"
[ -x "$preflight" ] || {
  echo "installed Execution Fabric preflight is unavailable: $preflight" >&2
  exit 69
}

domain="gui/$(id -u)"
launch_agents="$HOME/Library/LaunchAgents"
if [ "$personal_fallback" = true ]; then
  script="$script_dir/bin/personal-fallback-watchdog.sh"
  [ -x "$script" ] || {
    echo "personal fallback watchdog is unavailable: $script" >&2
    exit 69
  }
  FABRIC_RUNTIME_ENV_FILE=${FABRIC_RUNTIME_ENV_FILE:-"$HOME/Library/Application Support/GenomesAgenticOS/execution-fabric/runtime.env"}
  export FABRIC_RUNTIME_ENV_FILE
  set -a
  # shellcheck disable=SC1090
  . "$FABRIC_RUNTIME_ENV_FILE"
  set +a
  : "${FABRIC_OS_ROOT:?FABRIC_OS_ROOT is required}"
  : "${FABRIC_AGENTIC_OS_CLI:?FABRIC_AGENTIC_OS_CLI is required}"
  [ -x "$FABRIC_AGENTIC_OS_CLI" ] || {
    echo "configured Agentic OS CLI is not executable: $FABRIC_AGENTIC_OS_CLI" >&2
    exit 69
  }
  "$FABRIC_AGENTIC_OS_CLI" runtime fallback status \
    --root "$FABRIC_OS_ROOT" --json >/dev/null
  label="com.genomes.agentic-os.execution-fabric.personal-fallback"
  plist="$launch_agents/$label.plist"
  [ -r "$plist" ] || {
    echo "installed launchd definition is unavailable: $plist" >&2
    exit 69
  }
  if ! launchctl print "$domain/$label" >/dev/null 2>&1; then
    launchctl bootstrap "$domain" "$plist"
  fi
  echo "Execution Fabric personal fallback watchdog is active"
  exit 0
fi

# launchctl bootstrap starts RunAtLoad jobs, so the complete standby preflight
# must succeed before the first service-manager mutation.
"$preflight" standby

labels="
standby
worker
observer
watchdog
alarm-dispatcher
artifact-replication
candidate-reporter-health
scheduler-role
"

for suffix in $labels; do
  label="com.genomes.agentic-os.execution-fabric.$suffix"
  plist="$launch_agents/$label.plist"
  [ -r "$plist" ] || {
    echo "installed launchd definition is unavailable: $plist" >&2
    exit 69
  }
  if launchctl print "$domain/$label" >/dev/null 2>&1; then
    continue
  fi
  launchctl bootstrap "$domain" "$plist"
done

echo "Execution Fabric macOS services are active"
