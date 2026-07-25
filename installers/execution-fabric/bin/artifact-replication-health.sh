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
max_lag=${FABRIC_ARTIFACT_REPLICATION_MAX_LAG_SECONDS:-60}
user_file=${FABRIC_MINIO_ROOT_USER_FILE:-"$FABRIC_SECRETS_DIR/minio-root-user"}
password_file=${FABRIC_MINIO_ROOT_PASSWORD_FILE:-"$FABRIC_SECRETS_DIR/minio-root-password"}
[ -s "$user_file" ] && [ -s "$password_file" ] || {
  echo "MinIO replication credential files are missing" >&2
  exit 78
}

receipt_dir=$(mktemp -d "${TMPDIR:-/tmp}/fabric-artifact-health.XXXXXX")
trap 'rm -rf "$receipt_dir"' EXIT HUP INT TERM
started_epoch=$(date +%s)
canary="health/$(hostname)-$(date -u +%Y%m%dT%H%M%SZ)-$$"

if docker run --rm \
  --entrypoint /bin/sh \
  -e FABRIC_MINIO_PRIMARY_URL="$FABRIC_MINIO_PRIMARY_URL" \
  -e FABRIC_MINIO_STANDBY_URL="$FABRIC_MINIO_STANDBY_URL" \
  -e FABRIC_ARTIFACT_BUCKET="$bucket" \
  -e FABRIC_ARTIFACT_CANARY="$canary" \
  -e FABRIC_ARTIFACT_MAX_LAG="$max_lag" \
  -v "$user_file:/run/secrets/minio-user:ro" \
  -v "$password_file:/run/secrets/minio-password:ro" \
  -v "$receipt_dir:/receipts" \
  "$FABRIC_MINIO_CLIENT_IMAGE" \
  -ec '
    user=$(cat /run/secrets/minio-user)
    password=$(cat /run/secrets/minio-password)
    mc alias set primary "$FABRIC_MINIO_PRIMARY_URL" "$user" "$password"
    mc alias set standby "$FABRIC_MINIO_STANDBY_URL" "$user" "$password"
    mc replicate status --json "primary/$FABRIC_ARTIFACT_BUCKET" > /receipts/primary-status.jsonl
    mc replicate status --json "standby/$FABRIC_ARTIFACT_BUCKET" > /receipts/standby-status.jsonl
    printf "primary-to-standby\n" |
      mc pipe "primary/$FABRIC_ARTIFACT_BUCKET/$FABRIC_ARTIFACT_CANARY-primary"
    elapsed=0
    until mc stat "standby/$FABRIC_ARTIFACT_BUCKET/$FABRIC_ARTIFACT_CANARY-primary" >/dev/null 2>&1; do
      [ "$elapsed" -lt "$FABRIC_ARTIFACT_MAX_LAG" ] || exit 75
      elapsed=$((elapsed + 1))
      sleep 1
    done
    printf "%s\n" "$elapsed" > /receipts/primary-lag
    printf "standby-to-primary\n" |
      mc pipe "standby/$FABRIC_ARTIFACT_BUCKET/$FABRIC_ARTIFACT_CANARY-standby"
    elapsed=0
    until mc stat "primary/$FABRIC_ARTIFACT_BUCKET/$FABRIC_ARTIFACT_CANARY-standby" >/dev/null 2>&1; do
      [ "$elapsed" -lt "$FABRIC_ARTIFACT_MAX_LAG" ] || exit 75
      elapsed=$((elapsed + 1))
      sleep 1
    done
    printf "%s\n" "$elapsed" > /receipts/standby-lag
    mc rm "primary/$FABRIC_ARTIFACT_BUCKET/$FABRIC_ARTIFACT_CANARY-primary"
    mc rm "standby/$FABRIC_ARTIFACT_BUCKET/$FABRIC_ARTIFACT_CANARY-standby"
  '; then
  status=passed
else
  status=failed
fi

finished_epoch=$(date +%s)
primary_lag=$(cat "$receipt_dir/primary-lag" 2>/dev/null || printf 'null')
standby_lag=$(cat "$receipt_dir/standby-lag" 2>/dev/null || printf 'null')
printf '%s\n' '{}' >"$receipt_dir/empty.jsonl"
[ -s "$receipt_dir/primary-status.jsonl" ] ||
  cp "$receipt_dir/empty.jsonl" "$receipt_dir/primary-status.jsonl"
[ -s "$receipt_dir/standby-status.jsonl" ] ||
  cp "$receipt_dir/empty.jsonl" "$receipt_dir/standby-status.jsonl"
jq -n \
  --arg status "$status" \
  --arg sampledAt "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  --arg bucket "$bucket" \
  --argjson durationSeconds "$((finished_epoch - started_epoch))" \
  --argjson maxLagSeconds "$max_lag" \
  --argjson primaryLagSeconds "$primary_lag" \
  --argjson standbyLagSeconds "$standby_lag" \
  --slurpfile primary "$receipt_dir/primary-status.jsonl" \
  --slurpfile standby "$receipt_dir/standby-status.jsonl" \
  '{
    schemaVersion:"execution-fabric-artifact-replication-health/v1",
    status:$status,
    sampledAt:$sampledAt,
    bucket:$bucket,
    mode:"active-active-single-writer",
    durationSeconds:$durationSeconds,
    maxLagSeconds:$maxLagSeconds,
    directions:{
      primaryToStandby:{
        canaryLagSeconds:$primaryLagSeconds,
        status:$primary
      },
      standbyToPrimary:{
        canaryLagSeconds:$standbyLagSeconds,
        status:$standby
      }
    }
  }' >"$receipt_dir/health.json"
fabric_atomic_write \
  "$FABRIC_RUNTIME_STATE_DIR/artifact-replication-health.json" \
  "$receipt_dir/health.json"

if [ "$status" != passed ]; then
  fabric_notify critical \
    "Execution Fabric artifact replication unhealthy" \
    "Run artifacts are not proven portable between genomesbox and bigmac. Promotion remains fenced." \
    "execution-fabric-artifact-replication"
  exit 1
fi
