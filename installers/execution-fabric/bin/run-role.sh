#!/bin/sh
set -eu

script_dir=$(CDPATH="" cd -- "$(dirname -- "$0")" && pwd)
# shellcheck source=_lib.sh
. "$script_dir/_lib.sh"
fabric_load_runtime

role=${1:-}
case "$role" in
  api) service=control-plane ;;
  observer) service=observer ;;
  healer) service=healer ;;
  scheduler) service=scheduler ;;
  *)
    echo "usage: run-role.sh api|observer|healer|scheduler" >&2
    exit 64
    ;;
esac

host_id=${FABRIC_HOST_ID:-}
if [ "$host_id" = bigmac ]; then
  promotion_receipt="$FABRIC_RUNTIME_STATE_DIR/promotion.receipt.json"
  [ -s "$promotion_receipt" ] || exit 0
  [ "$(fabric_json_field "$promotion_receipt" '.leaderHostId')" = bigmac ] || exit 0
  compose_file="$FABRIC_DEPLOYMENT_DIR/compose.bigmac.yml"
  profile=promoted
else
  compose_file="$FABRIC_DEPLOYMENT_DIR/compose.genomesbox.yml"
  profile=primary
fi

docker compose \
  --env-file "$FABRIC_RUNTIME_ENV_FILE" \
  -f "$compose_file" \
  --profile "$profile" up -d --no-deps "$service"
