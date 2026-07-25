#!/bin/sh
set -eu

usage() {
  echo "usage: reseed-postgres-standby.sh --apply --target-role failback-target|standby" >&2
  exit 64
}

apply=false
target_role=
while [ "$#" -gt 0 ]; do
  case "$1" in
    --apply) apply=true ;;
    --target-role) shift; [ "$#" -gt 0 ] || usage; target_role=$1 ;;
    *) usage ;;
  esac
  shift
done
[ "$apply" = true ] || usage

script_dir=$(CDPATH="" cd -- "$(dirname -- "$0")" && pwd)
. "$script_dir/_lib.sh"
fabric_load_runtime
fabric_require_command curl
fabric_require_command docker
fabric_require_command jq

: "${FABRIC_HOST_ID:?local host id is required}"
: "${FABRIC_LEADERSHIP_API_BASE:?witness API is required}"
: "${FABRIC_LEADERSHIP_TOKEN_FILE:?witness reader token is required}"
: "${FABRIC_DEPLOYMENT_DIR:?deployment directory is required}"
: "${FABRIC_POSTGRES_IMAGE:?immutable PostgreSQL image is required}"
: "${FABRIC_SECRETS_DIR:?runtime secret directory is required}"

case "$FABRIC_POSTGRES_IMAGE" in
  *@sha256:[a-f0-9]*) ;;
  *) echo "FABRIC_POSTGRES_IMAGE must be digest-pinned" >&2; exit 78 ;;
esac

case "$target_role" in
  failback-target)
    [ "$FABRIC_HOST_ID" = genomesbox ] || {
      echo "failback-target reseed may run only on genomesbox" >&2
      exit 78
    }
    compose_file="$FABRIC_DEPLOYMENT_DIR/compose.genomesbox.yml"
    compose_profile=primary
    compose_project=genomes-agentic-os-execution-fabric
    volume_key=postgres-primary-data
    source_host=${FABRIC_STANDBY_TAILSCALE_IP:?bigmac source address is required}
    expected_leader=bigmac
    slot=genomesbox_fabric
    pgpass="$FABRIC_SECRETS_DIR/postgres-failback-pgpass"
    ;;
  standby)
    [ "$FABRIC_HOST_ID" = bigmac ] || {
      echo "standby reseed may run only on bigmac" >&2
      exit 78
    }
    compose_file="$FABRIC_DEPLOYMENT_DIR/compose.bigmac.yml"
    compose_profile=standby
    compose_project=genomes-agentic-os-execution-fabric-standby
    volume_key=postgres-standby-data
    source_host=${FABRIC_PRIMARY_TAILSCALE_IP:?genomesbox source address is required}
    expected_leader=genomesbox
    slot=bigmac_fabric
    pgpass="$FABRIC_SECRETS_DIR/postgres-replication-pgpass"
    ;;
  *) usage ;;
esac

[ -s "$pgpass" ] || {
  echo "replication pgpass is missing: $pgpass" >&2
  exit 78
}

status_temp=$(mktemp "${TMPDIR:-/tmp}/fabric-reseed-status.XXXXXX")
trap 'rm -f "$status_temp"' EXIT HUP INT TERM
fabric_api_get_bearer \
  "$FABRIC_LEADERSHIP_API_BASE" \
  "/api/v1/admin/leadership/status" \
  "$FABRIC_LEADERSHIP_TOKEN_FILE" >"$status_temp"
[ "$(fabric_json_field "$status_temp" '.currentLeader')" = "$expected_leader" ] || {
  echo "witness leader changed; refusing destructive standby reseed" >&2
  exit 75
}
[ "$FABRIC_HOST_ID" != "$expected_leader" ] || {
  echo "refusing to reseed the witnessed leader" >&2
  exit 75
}

compose="docker compose --env-file $FABRIC_RUNTIME_ENV_FILE -f $compose_file"
$compose --profile "$compose_profile" stop control-plane observer healer scheduler gateway candidate-reporter postgres 2>/dev/null || true

volume=$(docker volume ls \
  --filter "label=com.docker.compose.project=$compose_project" \
  --filter "label=com.docker.compose.volume=$volume_key" \
  --format '{{.Name}}')
[ -n "$volume" ] && [ "$(printf '%s\n' "$volume" | wc -l | tr -d ' ')" -eq 1 ] || {
  echo "could not resolve exactly one PostgreSQL volume for $compose_project/$volume_key" >&2
  exit 78
}

# The exact compose-labelled PostgreSQL volume is the only destructive target.
docker run --rm \
  --volume "$volume:/target" \
  --entrypoint sh \
  "$FABRIC_POSTGRES_IMAGE" \
  -ec 'test -d /target; find /target -mindepth 1 -maxdepth 1 -exec rm -rf -- {} +; chown postgres:postgres /target'

docker run --rm \
  --user postgres \
  --network host \
  --volume "$volume:/var/lib/postgresql/data" \
  --volume "$pgpass:/run/secrets/pgpass:ro" \
  --env PGPASSFILE=/run/secrets/pgpass \
  "$FABRIC_POSTGRES_IMAGE" \
  pg_basebackup \
  --host="$source_host" \
  --port="${FABRIC_POSTGRES_REPLICATION_PORT:-35432}" \
  --username=fabric_replica \
  --pgdata=/var/lib/postgresql/data \
  --write-recovery-conf \
  --slot="$slot" \
  --wal-method=stream \
  --checkpoint=fast

$compose --profile "$compose_profile" up -d postgres candidate-reporter
attempt=0
while [ "$attempt" -lt 24 ]; do
  if [ "$($compose --profile "$compose_profile" exec -T postgres \
    psql -X -qAt -U "${FABRIC_POSTGRES_USER:-fabric}" \
      -d "${FABRIC_POSTGRES_DB:-execution_fabric}" \
      -c 'SELECT pg_is_in_recovery()' 2>/dev/null)" = t ]; then
    if "$script_dir/candidate-reporter-health.sh" --require-standby \
      --receipt "$FABRIC_RUNTIME_STATE_DIR/reseed-candidate-health.json" \
      >/dev/null 2>&1; then
      printf '%s\n' "standby reseed complete for $FABRIC_HOST_ID"
      exit 0
    fi
  fi
  attempt=$((attempt + 1))
  sleep 5
done
echo "reseeded PostgreSQL did not enter recovery" >&2
exit 70
