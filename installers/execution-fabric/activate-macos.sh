#!/bin/sh
set -eu

usage() {
  echo "usage: activate-macos.sh --apply" >&2
  exit 64
}

apply=false
while [ "$#" -gt 0 ]; do
  case "$1" in
    --apply) apply=true ;;
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

# launchctl bootstrap starts RunAtLoad jobs, so the complete standby preflight
# must succeed before the first service-manager mutation.
"$preflight" standby

domain="gui/$(id -u)"
launch_agents="$HOME/Library/LaunchAgents"
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
