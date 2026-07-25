#!/bin/sh
set -eu

[ "$#" -eq 1 ] || {
  echo "usage: preflight.sh primary|standby" >&2
  exit 64
}
expected_role=$1
case "$expected_role" in primary|standby) ;; *) exit 64 ;; esac

script_dir=$(CDPATH="" cd -- "$(dirname -- "$0")" && pwd)
# shellcheck source=_lib.sh
. "$script_dir/_lib.sh"
fabric_load_runtime
fabric_require_command docker
fabric_require_command curl
fabric_require_command jq

[ "${FABRIC_DEPLOYMENT_ROLE:-}" = "$expected_role" ] || {
  echo "expected role $expected_role, got ${FABRIC_DEPLOYMENT_ROLE:-unset}" >&2
  exit 78
}
: "${FABRIC_HOST_ID:?stable host identity is required}"
: "${FABRIC_PRIMARY_HOST_ID:?stable primary host identity is required}"
: "${FABRIC_STANDBY_HOST_ID:?stable standby host identity is required}"
[ "$FABRIC_PRIMARY_HOST_ID" != "$FABRIC_STANDBY_HOST_ID" ] || {
  echo "primary and standby host identities must differ" >&2
  exit 78
}
case "$expected_role:$FABRIC_HOST_ID" in
  "primary:$FABRIC_PRIMARY_HOST_ID"|"standby:$FABRIC_STANDBY_HOST_ID") ;;
  *) echo "deployment role $expected_role does not match host $FABRIC_HOST_ID" >&2; exit 78 ;;
esac
: "${FABRIC_DEPLOYMENT_DIR:?installed deployment directory is required}"
: "${FABRIC_SECRETS_DIR:?runtime secret directory is required}"
: "${FABRIC_TAILSCALE_IP:?Tailscale bind address is required}"
: "${FABRIC_CLUSTER_ID:?fabric cluster id is required}"
: "${FABRIC_LEADERSHIP_API_BASE:?independent witness API is required}"
: "${FABRIC_LEADERSHIP_TOKEN_FILE:?witness token file is required}"
: "${FABRIC_LEADERSHIP_CANDIDATE_TOKEN_FILE:?host-scoped witness candidate token file is required}"
: "${FABRIC_LEADERSHIP_ADMIN_TOKEN_FILE:?witness operator admin token file is required}"
: "${FABRIC_LEADERSHIP_PUBLIC_KEY_FILE:?witness public key file is required}"
: "${FABRIC_LEADERSHIP_RECEIPT_FILE:?leadership receipt path is required}"
: "${FABRIC_GATEWAY_API_BASE:?stable worker gateway API is required}"
: "${FABRIC_WORKER_BOOTSTRAP_CREDENTIALS_FILE:?worker bootstrap credential map is required}"
: "${FABRIC_RELIABILITY_SOURCE_TOKENS_FILE:?reliability source token map is required}"
: "${FABRIC_EFFECT_CONSUMER_CREDENTIALS_FILE:?effect consumer credential map is required}"
: "${FABRIC_ALARM_DISPATCHER_CREDENTIALS_FILE:?alarm dispatcher credential map is required}"
[ -s "$FABRIC_LEADERSHIP_TOKEN_FILE" ] || {
  echo "witness token file is missing or empty" >&2
  exit 78
}
[ -s "$FABRIC_LEADERSHIP_CANDIDATE_TOKEN_FILE" ] || {
  echo "witness candidate token file is missing or empty" >&2
  exit 78
}
[ -s "$FABRIC_LEADERSHIP_ADMIN_TOKEN_FILE" ] || {
  echo "witness operator admin token file is missing or empty" >&2
  exit 78
}
[ -s "$FABRIC_LEADERSHIP_PUBLIC_KEY_FILE" ] || {
  echo "witness public key file is missing or empty" >&2
  exit 78
}
[ -s "$FABRIC_RELIABILITY_SOURCE_TOKENS_FILE" ] || {
  echo "reliability source token map is missing or empty" >&2
  exit 78
}
if [ ! -s "$FABRIC_WORKER_BOOTSTRAP_CREDENTIALS_FILE" ] ||
  ! jq -e '
    type=="object" and length>0 and
    all(to_entries[];
      (.key | test("^[a-zA-Z0-9._:-]{1,128}$")) and
      (.value | type=="object") and
      (.value.token | type=="string" and test("^\\S{32,}$")) and
      (.value.workerId | type=="string" and length>0) and
      (.value.hostId | type=="string" and length>0) and
      (.value.poolId | type=="string" and length>0) and
      (.value.queues | type=="array" and length>0) and
      (.value.capabilities | type=="array" and length>0) and
      (.value.maxConcurrency | type=="number" and .>=1)
    )
  ' "$FABRIC_WORKER_BOOTSTRAP_CREDENTIALS_FILE" >/dev/null
then
  echo "worker bootstrap credential map is missing, empty, or invalid" >&2
  exit 78
fi
for credential_map in \
  "$FABRIC_EFFECT_CONSUMER_CREDENTIALS_FILE" \
  "$FABRIC_ALARM_DISPATCHER_CREDENTIALS_FILE"
do
  if [ ! -s "$credential_map" ] ||
    ! jq -e 'type=="object" and length>0' "$credential_map" >/dev/null
  then
    echo "scoped consumer credential map is missing, empty, or invalid" >&2
    exit 78
  fi
done
if [ "$expected_role" = standby ]; then
  : "${FABRIC_ALARM_DISPATCHER_TOKEN_FILE:?alarm dispatcher token file is required}"
  dispatcher_id=${FABRIC_ALARM_DISPATCHER_CONSUMER_ID:-standby-agentic-os-notifier}
  dispatcher_source=${FABRIC_ALARM_DISPATCHER_SOURCE:-agentic-os-notify}
  expected_dispatcher_token=$(jq -er \
    --arg id "$dispatcher_id" \
    --arg source "$dispatcher_source" \
    '.[$id] | select(.source==$source) | .token' \
    "$FABRIC_ALARM_DISPATCHER_CREDENTIALS_FILE") || {
    echo "alarm dispatcher identity/source is absent from its credential map" >&2
    exit 78
  }
  [ -s "$FABRIC_ALARM_DISPATCHER_TOKEN_FILE" ] &&
    [ "$(cat "$FABRIC_ALARM_DISPATCHER_TOKEN_FILE")" = "$expected_dispatcher_token" ] || {
    echo "alarm dispatcher token file does not match its scoped credential" >&2
    exit 78
  }
fi
replication_port=${FABRIC_POSTGRES_REPLICATION_PORT:-35432}
case "$replication_port" in
  ''|*[!0-9]*) echo "FABRIC_POSTGRES_REPLICATION_PORT must be an integer" >&2; exit 78 ;;
esac
[ "$replication_port" -ge 1 ] && [ "$replication_port" -le 65535 ] || {
  echo "FABRIC_POSTGRES_REPLICATION_PORT must be between 1 and 65535" >&2
  exit 78
}
candidate_interval=${FABRIC_CANDIDATE_REPORT_INTERVAL_SECONDS:-30}
candidate_max_age=${FABRIC_CANDIDATE_HEARTBEAT_MAX_AGE_SECONDS:-75}
case "$candidate_interval:$candidate_max_age" in
  *[!0-9:]*|:*|*:) echo "candidate reporter intervals must be integers" >&2; exit 78 ;;
esac
[ "$candidate_interval" -ge 10 ] && [ "$candidate_interval" -le 300 ] &&
  [ "$candidate_max_age" -ge $((candidate_interval * 2)) ] &&
  [ "$candidate_max_age" -le 600 ] || {
  echo "candidate heartbeat max age must be at least two report intervals and no more than 600 seconds" >&2
  exit 78
}

value=''
for variable in \
  FABRIC_CONTROL_PLANE_IMAGE \
  FABRIC_POSTGRES_IMAGE \
  FABRIC_VALKEY_IMAGE \
  FABRIC_MINIO_IMAGE
do
  eval "value=\${$variable:-}"
  printf '%s\n' "$value" | grep -Eq '^.+@sha256:[a-f0-9]{64}$' || {
    echo "$variable must contain an immutable sha256 image digest" >&2
    exit 78
  }
done

for relative in \
  harness/config/execution-fabric.yml \
  harness/registries/hosts-routing.yml \
  harness/registries/alerts.yml
do
  [ -r "$FABRIC_OS_ROOT/$relative" ] || {
    echo "canonical Agentic OS config is unreadable: $relative" >&2
    exit 78
  }
done

if [ ! -r "$FABRIC_OS_ROOT/config/hosts.yml" ] && [ ! -r "$FABRIC_OS_ROOT/harness/config/hosts.yml" ]; then
  echo "canonical hosts config is unavailable" >&2
  exit 78
fi
grep -Eq '^  runtime\.execution_fabric\.health:' \
  "$FABRIC_OS_ROOT/harness/registries/alerts.yml" || {
  echo "canonical Execution Fabric alert source is not registered" >&2
  exit 78
}

case "$expected_role" in
  primary)
    compose_file="$FABRIC_DEPLOYMENT_DIR/compose.genomesbox.yml"
    required_secrets="postgres-password postgres-replication-password postgres-pgpass postgres-failback-pgpass valkey-acl valkey-health-password minio-root-user minio-root-password artifact-observer-access-key artifact-observer-secret-key fabric-api-token fabric-submit-token fabric-admin-token"
    ;;
  standby)
    compose_file="$FABRIC_DEPLOYMENT_DIR/compose.bigmac.yml"
    required_secrets="postgres-replication-pgpass valkey-acl valkey-health-password minio-root-user minio-root-password artifact-observer-access-key artifact-observer-secret-key fabric-api-token fabric-submit-token fabric-admin-token"
    ;;
esac

for secret in $required_secrets; do
  [ -s "$FABRIC_SECRETS_DIR/$secret" ] || {
    echo "required runtime secret is missing: $secret" >&2
    exit 78
  }
done

docker compose \
  --env-file "$FABRIC_RUNTIME_ENV_FILE" \
  -f "$compose_file" \
  config --quiet
docker compose \
  --env-file "$FABRIC_RUNTIME_ENV_FILE" \
  -f "$compose_file" \
  --profile "$expected_role" \
  config --services | grep -qx candidate-reporter || {
  echo "candidate-reporter service is missing from the $expected_role profile" >&2
  exit 78
}
