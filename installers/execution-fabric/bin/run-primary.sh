#!/bin/sh
set -eu

[ "$#" -eq 1 ] || {
  echo "usage: run-primary.sh start|stop" >&2
  exit 64
}
action=$1
case "$action" in start|stop) ;; *) exit 64 ;; esac

script_dir=$(CDPATH="" cd -- "$(dirname -- "$0")" && pwd)
# shellcheck source=_lib.sh
. "$script_dir/_lib.sh"
fabric_load_runtime
: "${FABRIC_DEPLOYMENT_DIR:?installed deployment directory is required}"
compose_file="$FABRIC_DEPLOYMENT_DIR/compose.genomesbox.yml"

if [ "$action" = start ]; then
  if [ "${FABRIC_WITNESS_MODE:-independent}" = standalone_primary ]; then
    fabric_require_command curl
    witness_state_dir="$FABRIC_RUNTIME_STATE_DIR/standalone-witness"
    witness_database="$witness_state_dir/witness.sqlite3"
    witness_sentinel="$witness_database.initialized"
    witness_host_marker="$FABRIC_RUNTIME_STATE_DIR/standalone-witness.bootstrap-complete"
    wait_for_standalone_witness() {
      witness_ready=false
      attempt=0
      while [ "$attempt" -lt 30 ]; do
        attempt=$((attempt + 1))
        if curl --fail --silent --show-error --connect-timeout 2 --max-time 5 \
          "${FABRIC_LEADERSHIP_API_BASE%/}/readyz" >/dev/null 2>&1
        then
          witness_ready=true
          break
        fi
        sleep 2
      done
      [ "$witness_ready" = true ] || {
        echo "standalone witness did not become ready before primary activation" >&2
        return 75
      }
    }
    install -d -m 0700 -o 3195 -g 3195 "$witness_state_dir"

    if [ -e "$witness_host_marker" ] &&
      { [ ! -s "$witness_database" ] || [ ! -s "$witness_sentinel" ]; }
    then
      echo "initialized standalone witness state is missing; restore it before starting" >&2
      exit 75
    fi
    if [ ! -e "$witness_host_marker" ] &&
      [ ! -e "$witness_database" ] && [ ! -e "$witness_sentinel" ]
    then
      # The bootstrap capability exists only for this first, bounded command.
      # Normal runtime.env remains false, so loss of initialized state cannot
      # silently mint a replacement authority database on a later restart.
      (
        FABRIC_STANDALONE_WITNESS_BOOTSTRAP_ONCE=true
        export FABRIC_STANDALONE_WITNESS_BOOTSTRAP_ONCE
        fabric_compose "$compose_file" --profile standalone-primary \
          up -d leadership-witness
      )
    else
      fabric_compose "$compose_file" --profile standalone-primary \
        up -d leadership-witness
    fi

    wait_for_standalone_witness

    if [ ! -e "$witness_host_marker" ]; then
      [ -s "$witness_database" ] && [ -s "$witness_sentinel" ] || {
        echo "standalone witness reported ready without complete durable bootstrap state" >&2
        exit 75
      }
      marker_temp="$FABRIC_RUNTIME_STATE_DIR/standalone-witness.bootstrap-complete.tmp"
      umask 077
      printf '%s\n' "cluster=$FABRIC_CLUSTER_ID initialized=$(date -u +%Y-%m-%dT%H:%M:%SZ)" >"$marker_temp"
      mv "$marker_temp" "$witness_host_marker"
      # Recreate immediately without the one-shot bootstrap capability.
      fabric_compose "$compose_file" --profile standalone-primary \
        up -d --force-recreate leadership-witness
      wait_for_standalone_witness
    fi
    fabric_compose "$compose_file" --profile primary \
      --profile standalone-primary up -d --remove-orphans
  else
    fabric_compose "$compose_file" --profile primary up -d --remove-orphans
  fi
else
  # Stop by service set, independent of which optional profile created it.
  fabric_compose "$compose_file" \
    --profile primary --profile standalone-primary stop
fi
