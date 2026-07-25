#!/bin/sh
set -eu

script_dir=$(CDPATH="" cd -- "$(dirname -- "$0")" && pwd)
# shellcheck source=_lib.sh
. "$script_dir/_lib.sh"
witness_load_environment

case "${WITNESS_MODE:-}" in
  manual_fail_closed)
    [ "${FABRIC_AUTO_FAILOVER:-false}" != true ] &&
      [ "${FABRIC_ENABLE_PROMOTION:-false}" != true ] || {
      echo "manual_fail_closed requires automatic failover and promotion disabled" >&2
      exit 78
    }
    printf '%s\n' "manual_fail_closed: no witness container will start"
    exit 0
    ;;
  independent) ;;
  *)
    echo "WITNESS_MODE must be independent or manual_fail_closed" >&2
    exit 78
    ;;
esac

: "${WITNESS_HOST_ID:?independent witness host identity is required}"
: "${WITNESS_TAILSCALE_IP:?witness Tailscale bind IP is required}"
: "${WITNESS_PORT:?witness port is required}"
: "${WITNESS_CLUSTER_ID:?witness cluster identity is required}"
: "${WITNESS_INITIAL_LEADER:?initial leader is required}"
: "${WITNESS_INITIAL_CONFIG_DIGEST:?initial config digest is required}"
: "${WITNESS_STATE_DIR:?host state directory is required}"
: "${WITNESS_STATE_FILE:?container state file is required}"
: "${WITNESS_READER_TOKEN_FILE:?reader token file is required}"
: "${WITNESS_CANDIDATE_TOKENS_FILE:?candidate token map is required}"
: "${WITNESS_ADMIN_TOKEN_FILE:?admin token file is required}"
: "${WITNESS_SIGNING_PRIVATE_KEY_FILE:?signing key file is required}"
: "${FABRIC_WITNESS_IMAGE:?digest-pinned witness image is required}"

witness_require_command jq
witness_require_command tailscale
container_runtime=${WITNESS_CONTAINER_RUNTIME:-docker}
witness_require_command "$container_runtime"

printf '%s\n' "$FABRIC_WITNESS_IMAGE" |
  grep -Eq '^.+@sha256:[a-f0-9]{64}$' || {
  echo "FABRIC_WITNESS_IMAGE must be an immutable sha256 image reference" >&2
  exit 78
}
printf '%s\n' "$WITNESS_INITIAL_CONFIG_DIGEST" |
  grep -Eq '^[a-f0-9]{64}$' || {
  echo "WITNESS_INITIAL_CONFIG_DIGEST must be a sha256 digest" >&2
  exit 78
}
case "$WITNESS_PORT" in
  ''|*[!0-9]*) echo "WITNESS_PORT must be an integer" >&2; exit 78 ;;
esac
[ "$WITNESS_PORT" -ge 1 ] && [ "$WITNESS_PORT" -le 65535 ] || {
  echo "WITNESS_PORT must be between 1 and 65535" >&2
  exit 78
}

{
  tailscale ip -4 2>/dev/null || true
  tailscale ip -6 2>/dev/null || true
} | grep -Fx "$WITNESS_TAILSCALE_IP" >/dev/null || {
  echo "WITNESS_TAILSCALE_IP is not assigned to this witness host" >&2
  exit 78
}

for secret in \
  "$WITNESS_READER_TOKEN_FILE" \
  "$WITNESS_CANDIDATE_TOKENS_FILE" \
  "$WITNESS_ADMIN_TOKEN_FILE" \
  "$WITNESS_SIGNING_PRIVATE_KEY_FILE"
do
  [ -s "$secret" ] || {
    echo "required witness secret is missing or empty: $secret" >&2
    exit 78
  }
done

jq -e \
  --arg witness "$WITNESS_HOST_ID" \
  --arg leader "$WITNESS_INITIAL_LEADER" '
    type=="object" and length>=2 and
    has($leader) and (has($witness) | not) and
    ([to_entries[].value] | unique | length)==length and
    all(to_entries[];
      (.key | test("^[a-zA-Z0-9._-]{1,128}$")) and
      (.value | type=="string" and test("^\\S{32,}$"))
    )
  ' "$WITNESS_CANDIDATE_TOKENS_FILE" >/dev/null || {
  echo "candidate tokens must name at least two unique candidates and exclude the witness host" >&2
  exit 78
}

case "${WITNESS_STORE:-sqlite}" in
  sqlite)
    case "$WITNESS_STATE_FILE" in
      /var/lib/execution-fabric-witness/*) ;;
      *)
        echo "portable WITNESS_STATE_FILE must live in the mounted container state directory" >&2
        exit 78
        ;;
    esac
    ;;
  dynamodb)
    : "${WITNESS_TABLE_NAME:?DynamoDB table is required}"
    : "${AWS_REGION:?AWS region is required}"
    ;;
  *)
    echo "WITNESS_STORE must be sqlite or dynamodb" >&2
    exit 78
    ;;
esac

"$container_runtime" image inspect "$FABRIC_WITNESS_IMAGE" >/dev/null 2>&1 || {
  echo "digest-pinned witness image is not installed locally" >&2
  exit 78
}

mkdir -p "$WITNESS_STATE_DIR" "${WITNESS_RUNTIME_STATE_DIR:-$WITNESS_STATE_DIR/monitor}"
chmod 0700 "$WITNESS_STATE_DIR"
printf '%s\n' "independent witness preflight passed"
