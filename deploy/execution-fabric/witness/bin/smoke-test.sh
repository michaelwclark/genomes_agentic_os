#!/bin/sh
set -eu

: "${FABRIC_LEADERSHIP_API_BASE:?witness HTTPS base is required}"
: "${FABRIC_LEADERSHIP_TOKEN_FILE:?witness token file is required}"
case "$FABRIC_LEADERSHIP_API_BASE" in
  https://*) ;;
  *) echo "witness base must use HTTPS" >&2; exit 78 ;;
esac
[ -s "$FABRIC_LEADERSHIP_TOKEN_FILE" ] || exit 78
token=$(tr -d '\r\n' <"$FABRIC_LEADERSHIP_TOKEN_FILE")

curl --fail --silent --show-error \
  --connect-timeout 5 --max-time 10 \
  "$FABRIC_LEADERSHIP_API_BASE/healthz" >/dev/null
curl --fail --silent --show-error \
  --connect-timeout 5 --max-time 10 \
  "$FABRIC_LEADERSHIP_API_BASE/readyz" >/dev/null
curl --fail --silent --show-error \
  --connect-timeout 5 --max-time 10 \
  -H "authorization: Bearer $token" \
  "$FABRIC_LEADERSHIP_API_BASE/api/v1/admin/leadership/status" |
  jq -e '
    .apiVersion == "execution-fabric-leadership/v1" and
    (.fabricEpoch | type == "number") and
    (.currentLeader | type == "string") and
    (.configDigest | test("^[a-f0-9]{64}$"))
  ' >/dev/null
