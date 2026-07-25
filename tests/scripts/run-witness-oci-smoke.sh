#!/bin/sh
set -eu

repo_root=$(CDPATH="" cd -- "$(dirname -- "$0")/../.." && pwd)
service="$repo_root/services/execution-fabric-leadership-witness"
deployment="$repo_root/deploy/execution-fabric/witness"
for command in docker jq openssl curl node; do
  command -v "$command" >/dev/null 2>&1 || {
    echo "missing OCI smoke dependency: $command" >&2
    exit 69
  }
done

temporary=$(mktemp -d "${TMPDIR:-/tmp}/witness-oci-smoke.XXXXXX")
container="genomes-agentic-os-witness-smoke-$$"
cleanup() {
  docker rm -f "$container" >/dev/null 2>&1 || true
  chmod -R u+rwX "$temporary" >/dev/null 2>&1 || true
  rm -rf "$temporary"
}
trap cleanup EXIT HUP INT TERM

image_tag="genomes-agentic-os-witness-smoke:local"
docker build --quiet --tag "$image_tag" "$service" >/dev/null
image_id=$(docker image inspect --format '{{.Id}}' "$image_tag")
uid=$(id -u)
gid=$(id -g)
port=$(node -e '
  const n=require("node:net").createServer();
  n.listen(0,"127.0.0.1",()=>{console.log(n.address().port);n.close()})
')

mkdir -p "$temporary/source-secrets" "$temporary/state" "$temporary/monitor"
openssl rand -hex 32 >"$temporary/source-secrets/reader-token"
openssl rand -hex 32 >"$temporary/source-secrets/admin-token"
genomesbox_token=$(openssl rand -hex 32)
bigmac_token=$(openssl rand -hex 32)
jq -n --arg genomesbox "$genomesbox_token" --arg bigmac "$bigmac_token" \
  '{genomesbox:$genomesbox,bigmac:$bigmac}' \
  >"$temporary/source-secrets/candidate-tokens.json"
openssl genpkey -algorithm ED25519 \
  -out "$temporary/source-secrets/signing-private-key.pem" 2>/dev/null
chmod 0600 "$temporary/source-secrets"/*

environment="$temporary/witness.env"
printf '%s\n' \
  'WITNESS_MODE=independent' \
  'WITNESS_HOST_ID=witness-smoke' \
  'WITNESS_BIND_IP=127.0.0.1' \
  "WITNESS_PORT=$port" \
  'WITNESS_CLUSTER_ID=oci-smoke' \
  "WITNESS_STATE_DIR=$temporary/state" \
  'WITNESS_STATE_FILE=/var/lib/execution-fabric-witness/witness.sqlite3' \
  'WITNESS_BOOTSTRAP_ONCE=true' \
  'WITNESS_PROCESS_LEASE_SECONDS=10' \
  "WITNESS_UID=$uid" \
  "WITNESS_GID=$gid" \
  'WITNESS_INITIAL_LEADER=genomesbox' \
  'WITNESS_INITIAL_TIMELINE_ID=1' \
  'WITNESS_INITIAL_CONFIG_DIGEST=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa' \
  "WITNESS_READER_TOKEN_FILE=$temporary/source-secrets/reader-token" \
  "WITNESS_CANDIDATE_TOKENS_FILE=$temporary/source-secrets/candidate-tokens.json" \
  "WITNESS_ADMIN_TOKEN_FILE=$temporary/source-secrets/admin-token" \
  "WITNESS_SIGNING_PRIVATE_KEY_FILE=$temporary/source-secrets/signing-private-key.pem" \
  'WITNESS_LOG_LEVEL=warn' \
  'WITNESS_CONTAINER_RUNTIME=docker' \
  "WITNESS_CONTAINER_NAME=$container" \
  "WITNESS_RUNTIME_STATE_DIR=$temporary/monitor" \
  "FABRIC_WITNESS_IMAGE=$image_id" \
  'FABRIC_AUTO_FAILOVER=false' \
  'FABRIC_ENABLE_PROMOTION=false' >"$environment"
chmod 0600 "$environment"

WITNESS_ENV_FILE="$environment" "$deployment/bin/run.sh" >/dev/null
attempt=0
until curl --fail --silent "http://127.0.0.1:$port/readyz" >/dev/null 2>&1; do
  attempt=$((attempt + 1))
  [ "$attempt" -lt 30 ] || {
    docker logs "$container" >&2
    exit 1
  }
  sleep 1
done

test -s "$temporary/state/witness.sqlite3"
test -s "$temporary/state/witness.sqlite3.initialized"
test -s "$temporary/state/witness.sqlite3.backup"
reader=$(tr -d '\r\n' <"$temporary/source-secrets/reader-token")
curl --fail --silent --show-error \
  --header "Authorization: Bearer $reader" \
  "http://127.0.0.1:$port/api/v1/admin/leadership/status" |
  jq -e '.currentLeader=="genomesbox" and .fabricEpoch==1' >/dev/null

docker restart "$container" >/dev/null
attempt=0
until curl --fail --silent "http://127.0.0.1:$port/readyz" >/dev/null 2>&1; do
  attempt=$((attempt + 1))
  [ "$attempt" -lt 30 ] || {
    docker logs "$container" >&2
    exit 1
  }
  sleep 1
done
printf '%s\n' "OCI witness start, protected mounts, readiness, and restart passed"
