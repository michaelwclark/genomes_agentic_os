#!/bin/sh
set -eu

apply=false
install_root=/opt/genomes-agentic-os/execution-fabric-witness
environment_file=/etc/genomes-agentic-os/execution-fabric-witness/witness.env
while [ "$#" -gt 0 ]; do
  case "$1" in
    --apply) apply=true ;;
    --install-root) shift; install_root=${1:?missing install root} ;;
    --environment-file) shift; environment_file=${1:?missing environment file} ;;
    *)
      echo "usage: activate-witness.sh [--apply] [--install-root PATH] [--environment-file PATH]" >&2
      exit 64
      ;;
  esac
  shift
done

runner="$install_root/current/bin/run.sh"
[ -x "$runner" ] || {
  echo "current portable witness release is not installed" >&2
  exit 66
}
if [ "$apply" != true ]; then
  printf '%s\n' "dry-run: would preflight and activate $runner"
  exit 0
fi
WITNESS_ENV_FILE="$environment_file" exec "$runner"
