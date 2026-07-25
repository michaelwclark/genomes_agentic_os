#!/bin/sh
set -eu

witness_env_default() {
  printf '%s\n' /etc/genomes-agentic-os/execution-fabric-witness/witness.env
}

witness_load_environment() {
  WITNESS_ENV_FILE=${WITNESS_ENV_FILE:-$(witness_env_default)}
  [ -r "$WITNESS_ENV_FILE" ] || {
    echo "witness environment is missing: $WITNESS_ENV_FILE" >&2
    exit 78
  }
  set -a
  # Operator-owned and restricted to shell-safe KEY=VALUE entries.
  # shellcheck disable=SC1090
  . "$WITNESS_ENV_FILE"
  set +a
}

witness_require_command() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "required command is unavailable: $1" >&2
    exit 69
  }
}

witness_api_base() {
  case "$WITNESS_TAILSCALE_IP" in
    *:*) printf 'http://[%s]:%s\n' "$WITNESS_TAILSCALE_IP" "$WITNESS_PORT" ;;
    *) printf 'http://%s:%s\n' "$WITNESS_TAILSCALE_IP" "$WITNESS_PORT" ;;
  esac
}

witness_atomic_write() {
  destination=$1
  source=$2
  temporary="${destination}.tmp.$$"
  install -m 0600 "$source" "$temporary"
  mv "$temporary" "$destination"
}

witness_notify() {
  level=$1
  title=$2
  message=$3
  dedupe=$4
  notifier=${WITNESS_ALERT_COMMAND:-${WITNESS_OS_ROOT:-}/harness/bin/agentic-os-notify}
  if [ -n "$notifier" ] && [ -x "$notifier" ]; then
    "$notifier" \
      --source runtime.execution_fabric.health \
      --level "$level" \
      --title "$title" \
      --message "$message" \
      --dedupe-key "$dedupe" || true
  elif command -v logger >/dev/null 2>&1; then
    logger -t genomes-agentic-os-execution-fabric-witness \
      "$level: $title - $message" || true
  fi
}
