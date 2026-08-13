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
  personal_preflight="$script_dir/bin/preflight-personal-client.sh"
  [ -x "$personal_preflight" ] || {
    echo "personal client preflight is unavailable: $personal_preflight" >&2
    exit 69
  }
  "$personal_preflight"
  personal_labels="worker alarm-dispatcher personal-fallback"
  # Resolve the complete mutation set before launchctl starts the first job.
  for suffix in $personal_labels; do
    label="com.genomes.agentic-os.execution-fabric.$suffix"
    plist="$launch_agents/$label.plist"
    [ -r "$plist" ] || {
      echo "installed launchd definition is unavailable: $plist" >&2
      exit 69
    }
  done
  for suffix in $personal_labels; do
    label="com.genomes.agentic-os.execution-fabric.$suffix"
    plist="$launch_agents/$label.plist"
    # A release activation changes the current runtime symlink.  Keeping an
    # already loaded job would leave it executing the previous package, so
    # replace it only after the complete preflight above has passed.
    if launchctl print "$domain/$label" >/dev/null 2>&1; then
      launchctl bootout "$domain/$label"
    fi
    launchctl bootstrap "$domain" "$plist"
  done
  echo "Execution Fabric personal worker, alarm dispatcher, and fallback watchdog are active"
  exit 0
fi

# launchctl bootstrap starts RunAtLoad jobs, so the complete standby preflight
# must succeed before the first service-manager mutation.  Restart a loaded
# label after that preflight: otherwise an activated release only changes the
# current symlink while its worker keeps the previous runtime in memory.
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
    launchctl bootout "$domain/$label"
  fi
  launchctl bootstrap "$domain" "$plist"
done

echo "Execution Fabric macOS services are active"
