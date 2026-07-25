#!/bin/sh
set -eu

script_dir=$(CDPATH="" cd -- "$(dirname -- "$0")" && pwd)
# shellcheck source=_lib.sh
. "$script_dir/_lib.sh"
witness_load_environment
"$script_dir/preflight.sh"

if [ "$WITNESS_MODE" = manual_fail_closed ]; then
  exit 0
fi

runtime=${WITNESS_CONTAINER_RUNTIME:-docker}
name=${WITNESS_CONTAINER_NAME:-genomes-agentic-os-execution-fabric-witness}
witness_wait_ready() {
  timeout=${WITNESS_START_TIMEOUT_SECONDS:-30}
  attempt=0
  while [ "$attempt" -lt "$timeout" ]; do
    if "$script_dir/health.sh" >/dev/null 2>&1; then
      printf '%s\n' "witness ready: $name"
      return 0
    fi
    attempt=$((attempt + 1))
    sleep 1
  done
  "$runtime" logs --tail 100 "$name" >&2 || true
  echo "witness container did not become durably ready" >&2
  return 70
}
if "$runtime" container inspect "$name" >/dev/null 2>&1; then
  running=$("$runtime" inspect --format '{{.State.Running}}' "$name")
  installed_image=$("$runtime" inspect --format '{{.Config.Image}}' "$name")
  [ "$installed_image" = "$FABRIC_WITNESS_IMAGE" ] || {
    echo "existing witness container uses a different immutable image; replace it explicitly" >&2
    exit 73
  }
  if [ "$running" = true ]; then
    "$script_dir/health.sh"
    exit 0
  fi
  "$runtime" start "$name" >/dev/null
  witness_wait_ready
  exit $?
fi

"$runtime" run --detach \
  --name "$name" \
  --restart unless-stopped \
  --network host \
  --read-only \
  --cap-drop ALL \
  --security-opt no-new-privileges \
  --user "${WITNESS_UID:-3195}:${WITNESS_GID:-3195}" \
  --tmpfs /tmp:rw,noexec,nosuid,size=16m \
  --volume "$WITNESS_STATE_DIR:/var/lib/execution-fabric-witness:rw" \
  --volume "${WITNESS_PREPARED_SECRETS_DIR:-$WITNESS_STATE_DIR/container-secrets}:/run/secrets/execution-fabric-witness:ro" \
  --env-file "$WITNESS_ENV_FILE" \
  --env WITNESS_READER_TOKEN_FILE=/run/secrets/execution-fabric-witness/reader-token \
  --env WITNESS_CANDIDATE_TOKENS_FILE=/run/secrets/execution-fabric-witness/candidate-tokens.json \
  --env WITNESS_ADMIN_TOKEN_FILE=/run/secrets/execution-fabric-witness/admin-token \
  --env WITNESS_SIGNING_PRIVATE_KEY_FILE=/run/secrets/execution-fabric-witness/signing-private-key.pem \
  "$FABRIC_WITNESS_IMAGE" >/dev/null
witness_wait_ready
