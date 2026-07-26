#!/bin/sh
set -eu

usage() {
  echo "usage: activate-linux.sh --apply" >&2
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
[ "$(id -u)" -eq 0 ] || {
  echo "Linux activation requires root" >&2
  exit 77
}

script_dir=$(CDPATH="" cd -- "$(dirname -- "$0")" && pwd)
# shellcheck source=bin/_lib.sh
. "$script_dir/bin/_lib.sh"
fabric_load_runtime
preflight="$script_dir/bin/preflight.sh"
[ -x "$preflight" ] || {
  echo "installed Execution Fabric preflight is unavailable: $preflight" >&2
  exit 69
}

# Activation is deliberately a second operation after installation. Nothing is
# enabled or started until the complete role preflight succeeds.
"$preflight" primary

units="
genomes-agentic-os-execution-fabric-primary.service
genomes-agentic-os-execution-fabric-scheduler.service
genomes-agentic-os-execution-fabric-observer.timer
genomes-agentic-os-execution-fabric-backup.timer
genomes-agentic-os-execution-fabric-candidate-reporter-health.timer
"
if [ "${FABRIC_WITNESS_MODE:-independent}" != standalone_primary ]; then
  units="$units
genomes-agentic-os-execution-fabric-artifact-replication.timer
"
else
  systemctl disable --now \
    genomes-agentic-os-execution-fabric-artifact-replication.timer \
    2>/dev/null || true
fi

systemctl daemon-reload
for unit in $units; do
  systemctl enable "$unit"
done
for unit in $units; do
  systemctl start "$unit"
done

echo "Execution Fabric Linux services are active"
