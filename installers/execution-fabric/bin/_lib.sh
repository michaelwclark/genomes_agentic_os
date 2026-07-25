#!/bin/sh
set -eu

fabric_runtime_env_default() {
  if [ "$(uname -s)" = Darwin ]; then
    printf '%s\n' "${HOME}/Library/Application Support/GenomesAgenticOS/execution-fabric/runtime.env"
  else
    printf '%s\n' "/etc/genomes-agentic-os/execution-fabric/runtime.env"
  fi
}

fabric_load_runtime() {
  FABRIC_RUNTIME_ENV_FILE=${FABRIC_RUNTIME_ENV_FILE:-$(fabric_runtime_env_default)}
  if [ ! -r "$FABRIC_RUNTIME_ENV_FILE" ]; then
    echo "execution-fabric runtime environment is missing: $FABRIC_RUNTIME_ENV_FILE" >&2
    exit 78
  fi
  set -a
  # The file is operator-owned and must contain shell-safe KEY=VALUE entries.
  # shellcheck disable=SC1090
  . "$FABRIC_RUNTIME_ENV_FILE"
  set +a

  : "${FABRIC_OS_ROOT:?FABRIC_OS_ROOT is required}"
  : "${FABRIC_RUNTIME_STATE_DIR:?FABRIC_RUNTIME_STATE_DIR is required}"
  mkdir -p "$FABRIC_RUNTIME_STATE_DIR"
}

fabric_require_command() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "required command is unavailable: $1" >&2
    exit 69
  }
}

fabric_compose() {
  [ "$#" -ge 1 ] || {
    echo "fabric_compose requires a compose file" >&2
    return 64
  }
  _fabric_compose_file=$1
  shift
  docker compose \
    --env-file "$FABRIC_RUNTIME_ENV_FILE" \
    -f "$_fabric_compose_file" \
    "$@"
}

fabric_replication_slot() {
  [ "$#" -eq 1 ] || {
    echo "fabric_replication_slot requires primary or standby" >&2
    return 64
  }
  case "$1" in
    primary) printf '%s\n' genomesbox_fabric ;;
    standby) printf '%s\n' bigmac_fabric ;;
    *)
      echo "unknown replication slot target: $1" >&2
      return 64
      ;;
  esac
}

fabric_api_get() {
  base=$1
  path=$2
  curl --fail --silent --show-error \
    --connect-timeout 5 \
    --max-time 20 \
    "${base%/}${path}"
}

fabric_bearer_token() {
  token_file=$1
  if [ ! -s "$token_file" ]; then
    echo "missing API token file: $token_file" >&2
    exit 78
  fi
  cat "$token_file"
}

fabric_api_post() {
  base=$1
  path=$2
  token_file=$3
  body=$4
  token=$(fabric_bearer_token "$token_file")
  curl --fail --silent --show-error \
    --connect-timeout 5 \
    --max-time 30 \
    --header "Authorization: Bearer $token" \
    --header "Content-Type: application/json" \
    --data "$body" \
    "${base%/}${path}"
}

fabric_api_post_bearer_value() {
  base=$1
  path=$2
  token=$3
  body=$4
  curl --fail --silent --show-error \
    --connect-timeout 5 \
    --max-time 30 \
    --header "Authorization: Bearer $token" \
    --header "Content-Type: application/json" \
    --data "$body" \
    "${base%/}${path}"
}

fabric_api_get_bearer() {
  base=$1
  path=$2
  token_file=$3
  token=$(fabric_bearer_token "$token_file")
  curl --fail --silent --show-error \
    --connect-timeout 5 \
    --max-time 20 \
    --header "Authorization: Bearer $token" \
    "${base%/}${path}"
}

fabric_atomic_write() {
  destination=$1
  source=$2
  temporary="${destination}.tmp.$$"
  install -m 0600 "$source" "$temporary"
  mv "$temporary" "$destination"
}

fabric_notify() {
  level=$1
  title=$2
  message=$3
  dedupe=$4
  notifier="$FABRIC_OS_ROOT/harness/bin/agentic-os-notify"
  if [ -x "$notifier" ]; then
    "$notifier" \
      --source runtime.execution_fabric.health \
      --level "$level" \
      --title "$title" \
      --message "$message" \
      --dedupe-key "$dedupe" || true
  else
    logger -t genomes-agentic-os-execution-fabric "$level: $title - $message" || true
  fi
}

fabric_json_field() {
  document=$1
  expression=$2
  jq -er "$expression" "$document"
}

fabric_sha256() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | awk '{print $1}'
  elif command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$1" | awk '{print $1}'
  else
    echo "sha256sum or shasum is required" >&2
    exit 69
  fi
}
