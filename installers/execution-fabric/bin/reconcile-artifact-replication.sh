#!/bin/sh
set -eu

script_dir=$(CDPATH="" cd -- "$(dirname -- "$0")" && pwd)
# shellcheck source=_lib.sh
. "$script_dir/_lib.sh"
fabric_load_runtime
fabric_require_command docker
fabric_require_command jq

: "${FABRIC_MINIO_CLIENT_IMAGE:?digest-pinned MinIO client image is required}"
: "${FABRIC_MINIO_PRIMARY_URL:?primary MinIO Tailscale URL is required}"
: "${FABRIC_MINIO_STANDBY_URL:?standby MinIO Tailscale URL is required}"
bucket=${FABRIC_ARTIFACT_BUCKET:-execution-fabric-artifacts}
user_file=${FABRIC_MINIO_ROOT_USER_FILE:-"$FABRIC_SECRETS_DIR/minio-root-user"}
password_file=${FABRIC_MINIO_ROOT_PASSWORD_FILE:-"$FABRIC_SECRETS_DIR/minio-root-password"}
[ -s "$user_file" ] && [ -s "$password_file" ] || {
  echo "MinIO replication credential files are missing" >&2
  exit 78
}

status_dir=$(mktemp -d "${TMPDIR:-/tmp}/fabric-artifact-replication.XXXXXX")
trap 'rm -rf "$status_dir"' EXIT HUP INT TERM

docker run --rm \
  --entrypoint /bin/sh \
  -e FABRIC_MINIO_PRIMARY_URL="$FABRIC_MINIO_PRIMARY_URL" \
  -e FABRIC_MINIO_STANDBY_URL="$FABRIC_MINIO_STANDBY_URL" \
  -e FABRIC_ARTIFACT_BUCKET="$bucket" \
  -v "$user_file:/run/secrets/minio-user:ro" \
  -v "$password_file:/run/secrets/minio-password:ro" \
  -v "$status_dir:/receipts" \
  "$FABRIC_MINIO_CLIENT_IMAGE" \
  -ec '
    user=$(cat /run/secrets/minio-user)
    password=$(cat /run/secrets/minio-password)
    mc alias set primary "$FABRIC_MINIO_PRIMARY_URL" "$user" "$password"
    mc alias set standby "$FABRIC_MINIO_STANDBY_URL" "$user" "$password"
    mc mb --ignore-existing "primary/$FABRIC_ARTIFACT_BUCKET"
    mc mb --ignore-existing "standby/$FABRIC_ARTIFACT_BUCKET"
    mc version enable "primary/$FABRIC_ARTIFACT_BUCKET"
    mc version enable "standby/$FABRIC_ARTIFACT_BUCKET"
    if ! mc replicate ls --json "primary/$FABRIC_ARTIFACT_BUCKET" |
      grep -q "aos-primary-to-standby"; then
      mc replicate add \
        --id aos-primary-to-standby \
        --remote-bucket "standby/$FABRIC_ARTIFACT_BUCKET" \
        --replicate "delete,delete-marker,existing-objects,metadata-sync" \
        "primary/$FABRIC_ARTIFACT_BUCKET"
    fi
    if ! mc replicate ls --json "standby/$FABRIC_ARTIFACT_BUCKET" |
      grep -q "aos-standby-to-primary"; then
      mc replicate add \
        --id aos-standby-to-primary \
        --remote-bucket "primary/$FABRIC_ARTIFACT_BUCKET" \
        --replicate "delete,delete-marker,existing-objects,metadata-sync" \
        "standby/$FABRIC_ARTIFACT_BUCKET"
    fi
    mc replicate ls --json "primary/$FABRIC_ARTIFACT_BUCKET" > /receipts/primary.jsonl
    mc replicate ls --json "standby/$FABRIC_ARTIFACT_BUCKET" > /receipts/standby.jsonl
  '

receipt_temp="$status_dir/reconcile.receipt.json"
jq -n \
  --arg completedAt "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  --arg bucket "$bucket" \
  --slurpfile primary "$status_dir/primary.jsonl" \
  --slurpfile standby "$status_dir/standby.jsonl" \
  '{
    schemaVersion:"execution-fabric-artifact-replication-reconcile/v1",
    status:"configured",
    completedAt:$completedAt,
    bucket:$bucket,
    mode:"active-active-single-writer",
    directions:{
      primaryToStandby:$primary,
      standbyToPrimary:$standby
    }
  }' >"$receipt_temp"
fabric_atomic_write \
  "$FABRIC_RUNTIME_STATE_DIR/artifact-replication-reconcile.json" \
  "$receipt_temp"
"$script_dir/artifact-replication-health.sh"
