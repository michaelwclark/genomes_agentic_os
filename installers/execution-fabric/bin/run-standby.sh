#!/bin/sh
set -eu

script_dir=$(CDPATH="" cd -- "$(dirname -- "$0")" && pwd)
# shellcheck source=_lib.sh
. "$script_dir/_lib.sh"
fabric_load_runtime
"$script_dir/preflight.sh" standby

docker compose \
  --env-file "$FABRIC_RUNTIME_ENV_FILE" \
  -f "$FABRIC_DEPLOYMENT_DIR/compose.bigmac.yml" \
  --profile standby up -d --remove-orphans
