#!/bin/sh
set -eu

usage() {
  echo "usage: converge-policy-roles.sh --recreate|--verify EXPECTED_FINGERPRINT" >&2
  exit 64
}

[ "$#" -eq 2 ] || usage
mode=$1
expected=$2
case "$mode" in
  --recreate|--verify) ;;
  *) usage ;;
esac
printf '%s\n' "$expected" | grep -Eq '^[a-f0-9]{64}$' || usage

script_dir=$(CDPATH="" cd -- "$(dirname -- "$0")" && pwd)
# shellcheck source=_lib.sh
. "$script_dir/_lib.sh"
fabric_load_runtime
fabric_require_command curl
fabric_require_command jq
api_base=${FABRIC_POLICY_CONVERGENCE_API_BASE:-${FABRIC_API_BASE:-}}
: "${api_base:?local control-plane API is required}"
: "${FABRIC_API_TOKEN_FILE:?control-plane read token file is required}"
: "${FABRIC_HOST_ID:?stable host identity is required}"
: "${FABRIC_DEPLOYMENT_DIR:?deployment directory is required}"

case "${FABRIC_DEPLOYMENT_ROLE:-}" in
  primary)
    compose_file="$FABRIC_DEPLOYMENT_DIR/compose.genomesbox.yml"
    compose_profile=primary
    ;;
  promoted)
    compose_file="$FABRIC_DEPLOYMENT_DIR/compose.bigmac.yml"
    compose_profile=promoted
    ;;
  standby)
    fabric_require_command docker
    compose_file="$FABRIC_DEPLOYMENT_DIR/compose.bigmac.yml"
    compose_profile=promoted
    cohort_state=$(fabric_policy_role_cohort_state "$compose_file" "$compose_profile")
    [ "$cohort_state" = active ] || {
      echo "standby policy role cohort is $cohort_state; convergence requires a complete active promoted cohort" >&2
      exit 75
    }
    ;;
  *)
    echo "policy role convergence requires the active primary or promoted role" >&2
    exit 75
    ;;
esac
[ -r "$compose_file" ] || {
  echo "policy role convergence compose file is unavailable: $compose_file" >&2
  exit 69
}

status_temp=$(mktemp "$FABRIC_RUNTIME_STATE_DIR/policy-role-status.XXXXXX")
before_temp=$(mktemp "$FABRIC_RUNTIME_STATE_DIR/policy-role-before.XXXXXX")
after_temp=$(mktemp "$FABRIC_RUNTIME_STATE_DIR/policy-role-after.XXXXXX")
receipt_temp=$(mktemp "$FABRIC_RUNTIME_STATE_DIR/policy-role-receipt.XXXXXX")
cleanup() {
  unlink "$status_temp" 2>/dev/null || true
  unlink "$before_temp" 2>/dev/null || true
  unlink "$after_temp" 2>/dev/null || true
  unlink "$receipt_temp" 2>/dev/null || true
}
trap cleanup EXIT HUP INT TERM

roles="control-plane observer healer scheduler"
if [ "$mode" = --recreate ]; then
  fabric_require_command docker
  : >"$before_temp"
  for role in $roles; do
    container_id=$(fabric_compose "$compose_file" --profile "$compose_profile" ps -q "$role")
    printf '%s=%s\n' "$role" "$container_id" >>"$before_temp"
  done
  fabric_compose "$compose_file" --profile "$compose_profile" up -d \
    --no-deps --force-recreate $roles
  : >"$after_temp"
  for role in $roles; do
    container_id=$(fabric_compose "$compose_file" --profile "$compose_profile" ps -q "$role")
    [ -n "$container_id" ] || {
      echo "policy role $role has no recreated container" >&2
      exit 75
    }
    printf '%s=%s\n' "$role" "$container_id" >>"$after_temp"
    before_id=$(sed -n "s/^${role}=//p" "$before_temp")
    [ -z "$before_id" ] || [ "$before_id" != "$container_id" ] || {
      echo "policy role $role retained its previous container" >&2
      exit 75
    }
  done
fi

verified=false
attempt=0
attempt_limit=${FABRIC_POLICY_CONVERGENCE_ATTEMPTS:-60}
case "$attempt_limit" in
  ''|*[!0-9]*) echo "FABRIC_POLICY_CONVERGENCE_ATTEMPTS must be a positive integer" >&2; exit 64 ;;
esac
[ "$attempt_limit" -ge 1 ] && [ "$attempt_limit" -le 300 ] || {
  echo "FABRIC_POLICY_CONVERGENCE_ATTEMPTS must be between 1 and 300" >&2
  exit 64
}
while [ "$attempt" -lt "$attempt_limit" ]; do
  attempt=$((attempt + 1))
  if fabric_api_get_bearer \
    "$api_base" "/api/v1/status?limit=1" \
    "$FABRIC_API_TOKEN_FILE" >"$status_temp" 2>/dev/null
  then
    jq -e '(.roleHealth | type)=="array"' "$status_temp" >/dev/null || {
      echo "control-plane status has no roleHealth array; upgrade the control-plane image before policy rotation" >&2
      exit 69
    }
    if [ "$mode" = --recreate ]; then
      predicate='(
        [.roleHealth[] | select(.hostId==$host and
          (.role=="api" or .role=="observer" or .role=="healer" or .role=="scheduler"))]
        | length == 4
      ) and all(.roleHealth[] | select(.hostId==$host and
        (.role=="api" or .role=="observer" or .role=="healer" or .role=="scheduler"));
        .approvedPolicyFingerprint==$digest and .appliedPolicyFingerprint==$digest)'
    else
      predicate='(
        [.roleHealth[] | select(.hostId==$host and
          (.role=="api" or .role=="observer" or .role=="healer" or .role=="scheduler"))]
        | length == 4
      ) and all(.roleHealth[] | select(.hostId==$host and
        (.role=="api" or .role=="observer" or .role=="healer" or .role=="scheduler"));
        .approvedPolicyFingerprint==$digest and .appliedPolicyFingerprint==$digest and
        .status=="healthy" and .lastSuccessfulTickAt!=null)'
    fi
    if jq -e --arg host "$FABRIC_HOST_ID" --arg digest "$expected" \
      "$predicate" "$status_temp" >/dev/null
    then
      verified=true
      break
    fi
  fi
  if [ "$attempt" -lt "$attempt_limit" ]; then
    sleep 2
  fi
done
[ "$verified" = true ] || {
  echo "policy roles did not converge to $expected during $mode" >&2
  exit 75
}

receipt_path="$FABRIC_RUNTIME_STATE_DIR/policy-role-convergence-${mode#--}-$expected.json"
jq -n \
  --arg mode "${mode#--}" \
  --arg fingerprint "$expected" \
  --arg verifiedAt "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  --rawfile containersBefore "$before_temp" \
  --rawfile containersAfter "$after_temp" \
  --slurpfile status "$status_temp" \
  'def container_ids($raw):
    $raw | split("\n") | map(select(length>0) |
      capture("^(?<role>[^=]+)=(?<id>.*)$") |
      {key:.role,value:.id}) | from_entries;
  {
    schemaVersion:"execution-fabric-policy-role-convergence/v1",
    mode:$mode,
    fingerprint:$fingerprint,
    verifiedAt:$verifiedAt,
    containersBefore:container_ids($containersBefore),
    containersAfter:container_ids($containersAfter),
    roleHealth:$status[0].roleHealth
  }' >"$receipt_temp"
fabric_atomic_write "$receipt_path" "$receipt_temp"
printf '%s\n' "$receipt_path"
