#!/bin/sh
set -eu

usage() {
  echo "usage: report-candidate.sh CANDIDATE CONFIG_DIGEST" >&2
  exit 64
}

[ "$#" -eq 2 ] || usage
candidate=$1
digest=$2

: "${FABRIC_LEADERSHIP_API_BASE:?witness HTTPS base is required}"
: "${FABRIC_LEADERSHIP_CANDIDATE_TOKEN_FILE:?host-scoped witness candidate token file is required}"
: "${FABRIC_DATABASE_URL:?PostgreSQL connection URL is required}"
[ -s "$FABRIC_LEADERSHIP_CANDIDATE_TOKEN_FILE" ] || {
  echo "candidate token file is missing or empty" >&2
  exit 78
}
case "$candidate" in
  *[!a-zA-Z0-9._-]*|"") usage ;;
esac
case "$digest" in
  *[!a-f0-9]*|"") usage ;;
esac
[ "${#digest}" -eq 64 ] || usage
case "$FABRIC_LEADERSHIP_API_BASE" in
  https://*) ;;
  *) echo "witness base must use HTTPS" >&2; exit 78 ;;
esac

token=$(tr -d '\r\n' <"$FABRIC_LEADERSHIP_CANDIDATE_TOKEN_FILE")
sample=$(psql "$FABRIC_DATABASE_URL" -X -qAt -c "
WITH recovery AS (
  SELECT pg_is_in_recovery() AS in_recovery,
         (pg_control_checkpoint()).timeline_id AS timeline_id,
         pg_last_wal_receive_lsn() AS standby_receive_lsn,
         pg_last_wal_replay_lsn() AS standby_replay_lsn
), receiver AS (
  SELECT status, last_msg_receipt_time
  FROM pg_stat_wal_receiver
  LIMIT 1
), positions AS (
  SELECT in_recovery, timeline_id,
         CASE WHEN in_recovery THEN COALESCE(standby_receive_lsn, standby_replay_lsn)
              ELSE pg_current_wal_lsn() END AS receive_lsn,
         CASE WHEN in_recovery THEN COALESCE(standby_replay_lsn, standby_receive_lsn)
              ELSE pg_current_wal_lsn() END AS replay_lsn
  FROM recovery
)
SELECT json_build_object(
  'healthy', true,
  'inRecovery', in_recovery,
  'timelineId', timeline_id,
  'receiveLsn', receive_lsn::text,
  'replayLsn', replay_lsn::text,
  'receiveWalPosition', pg_wal_lsn_diff(receive_lsn, '0/0')::bigint,
  'replayWalPosition', pg_wal_lsn_diff(replay_lsn, '0/0')::bigint,
  'replicaLagBytes', GREATEST(pg_wal_lsn_diff(receive_lsn, replay_lsn), 0)::bigint,
  'lagMeasuredAt', clock_timestamp(),
  'upstreamSystemId', (pg_control_system()).system_identifier::text,
  'receiverState', CASE
    WHEN NOT in_recovery THEN 'not_applicable'
    ELSE COALESCE((SELECT status FROM receiver), 'disconnected')
  END,
  'lastMessageAt', CASE
    WHEN NOT in_recovery THEN clock_timestamp()
    ELSE COALESCE(
      (SELECT last_msg_receipt_time FROM receiver),
      TIMESTAMPTZ '1970-01-01T00:00:00Z')
  END
)::text FROM positions")
[ -n "$sample" ] || {
  echo "PostgreSQL replication probe returned no sample" >&2
  exit 69
}
body=$(jq -c \
  --arg configDigest "$digest" \
  '. + {configDigest:$configDigest}' <<EOF
$sample
EOF
)
curl --fail-with-body --silent --show-error \
  --connect-timeout 5 \
  --max-time 15 \
  -X PUT \
  -H "authorization: Bearer $token" \
  -H "content-type: application/json" \
  --data "$body" \
  "$FABRIC_LEADERSHIP_API_BASE/api/v1/admin/leadership/candidates/$candidate"
