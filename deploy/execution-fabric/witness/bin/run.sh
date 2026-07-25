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
  exit 0
fi

exec "$runtime" run --detach \
  --name "$name" \
  --restart unless-stopped \
  --network host \
  --read-only \
  --cap-drop ALL \
  --security-opt no-new-privileges \
  --tmpfs /tmp:rw,noexec,nosuid,size=16m \
  --volume "$WITNESS_STATE_DIR:/var/lib/execution-fabric-witness:rw" \
  --volume "$WITNESS_READER_TOKEN_FILE:$WITNESS_READER_TOKEN_FILE:ro" \
  --volume "$WITNESS_CANDIDATE_TOKENS_FILE:$WITNESS_CANDIDATE_TOKENS_FILE:ro" \
  --volume "$WITNESS_ADMIN_TOKEN_FILE:$WITNESS_ADMIN_TOKEN_FILE:ro" \
  --volume "$WITNESS_SIGNING_PRIVATE_KEY_FILE:$WITNESS_SIGNING_PRIVATE_KEY_FILE:ro" \
  --env-file "$WITNESS_ENV_FILE" \
  "$FABRIC_WITNESS_IMAGE"
