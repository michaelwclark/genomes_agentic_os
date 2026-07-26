import type pg from "pg";

export type PostgresReplicationSnapshot = {
  inRecovery: boolean;
  timelineId: number;
  receiveLsn: string;
  replayLsn: string;
  receiveWalPosition: number;
  replayWalPosition: number;
  replicaLagBytes: number;
  lagMeasuredAt: string;
  upstreamSystemId: string;
  receiverState:
    | "not_applicable"
    | "startup"
    | "catchup"
    | "streaming"
    | "backup"
    | "stopping"
    | "disconnected";
  lastMessageAt: string;
};

export type PostgresMutationDurabilitySnapshot = {
  inRecovery: boolean;
  synchronousCommit: string;
  synchronousStandbyNames: string;
  synchronousStandbyCount: number;
  fsync?: boolean;
  fullPageWrites?: boolean;
  archiveMode?: string;
  mutationDurabilityReady: boolean;
  degradedPrimaryDurabilityReady?: boolean;
  standalonePrimaryDurabilityReady?: boolean;
  measuredAt: string;
};

type ReplicationRow = {
  in_recovery: boolean;
  timeline_id: number | string;
  receive_lsn: string;
  replay_lsn: string;
  receive_wal_position: number | string;
  replay_wal_position: number | string;
  lag_bytes: number | string;
  measured_at: Date | string;
  upstream_system_id: string;
  receiver_state: PostgresReplicationSnapshot["receiverState"];
  last_message_at: Date | string;
};

/**
 * Read PostgreSQL's own recovery and WAL positions. Promotion eligibility must
 * never be inferred from application health or network reachability.
 */
export async function measurePostgresReplication(
  pool: pg.Pool,
): Promise<PostgresReplicationSnapshot> {
  const result = await pool.query<ReplicationRow>(`
    WITH recovery AS (
      SELECT
        pg_is_in_recovery() AS in_recovery,
        (pg_control_checkpoint()).timeline_id AS timeline_id,
        pg_last_wal_receive_lsn() AS standby_receive_lsn,
        pg_last_wal_replay_lsn() AS standby_replay_lsn
    ),
    receiver AS (
      SELECT status, last_msg_receipt_time
      FROM pg_stat_wal_receiver
      LIMIT 1
    ),
    positions AS (
      SELECT
        in_recovery,
        timeline_id,
        CASE
          WHEN in_recovery
            THEN COALESCE(standby_receive_lsn, standby_replay_lsn)
          ELSE pg_current_wal_lsn()
        END AS receive_lsn,
        CASE
          WHEN in_recovery
            THEN COALESCE(standby_replay_lsn, standby_receive_lsn)
          ELSE pg_current_wal_lsn()
        END AS replay_lsn
      FROM recovery
    )
    SELECT
      in_recovery,
      timeline_id,
      receive_lsn::text AS receive_lsn,
      replay_lsn::text AS replay_lsn,
      pg_wal_lsn_diff(receive_lsn, '0/0')::bigint AS receive_wal_position,
      pg_wal_lsn_diff(replay_lsn, '0/0')::bigint AS replay_wal_position,
      GREATEST(pg_wal_lsn_diff(receive_lsn, replay_lsn), 0)::bigint AS lag_bytes,
      clock_timestamp() AS measured_at,
      (pg_control_system()).system_identifier::text AS upstream_system_id,
      CASE
        WHEN NOT in_recovery THEN 'not_applicable'
        ELSE COALESCE((SELECT status FROM receiver), 'disconnected')
      END AS receiver_state,
      CASE
        WHEN NOT in_recovery THEN clock_timestamp()
        ELSE COALESCE(
          (SELECT last_msg_receipt_time FROM receiver),
          TIMESTAMPTZ '1970-01-01T00:00:00Z'
        )
      END AS last_message_at
    FROM positions
  `);
  const row = result.rows[0];
  if (!row) throw new Error("PostgreSQL replication probe returned no row");
  const replicaLagBytes = Number(row.lag_bytes);
  const receiveWalPosition = Number(row.receive_wal_position);
  const replayWalPosition = Number(row.replay_wal_position);
  const timelineId = Number(row.timeline_id);
  if (
    !Number.isSafeInteger(replicaLagBytes) ||
    replicaLagBytes < 0 ||
    !Number.isSafeInteger(receiveWalPosition) ||
    receiveWalPosition < 0 ||
    !Number.isSafeInteger(replayWalPosition) ||
    replayWalPosition < 0 ||
    !Number.isSafeInteger(timelineId) ||
    timelineId < 1
  ) {
    throw new Error("PostgreSQL replication probe returned invalid values");
  }
  return {
    inRecovery: row.in_recovery,
    timelineId,
    receiveLsn: row.receive_lsn,
    replayLsn: row.replay_lsn,
    receiveWalPosition,
    replayWalPosition,
    replicaLagBytes,
    upstreamSystemId: row.upstream_system_id,
    receiverState: row.receiver_state,
    lastMessageAt:
      row.last_message_at instanceof Date
        ? row.last_message_at.toISOString()
        : new Date(row.last_message_at).toISOString(),
    lagMeasuredAt:
      row.measured_at instanceof Date
        ? row.measured_at.toISOString()
        : new Date(row.measured_at).toISOString(),
  };
}

/**
 * Prove the local primary cannot acknowledge a fabric mutation before one
 * streaming synchronous standby has applied it. This is deliberately separate
 * from candidate lag: a healthy server or a zero local replay gap is not a
 * durability receipt.
 */
export async function measurePostgresMutationDurability(
  pool: pg.Pool,
): Promise<PostgresMutationDurabilitySnapshot> {
  const result = await pool.query<{
    in_recovery: boolean;
    synchronous_commit: string;
    synchronous_standby_names: string;
    synchronous_standby_count: number | string;
    fsync: string;
    full_page_writes: string;
    archive_mode: string;
    measured_at: Date | string;
  }>(`
    SELECT
      pg_is_in_recovery() AS in_recovery,
      current_setting('synchronous_commit') AS synchronous_commit,
      current_setting('synchronous_standby_names') AS synchronous_standby_names,
      current_setting('fsync') AS fsync,
      current_setting('full_page_writes') AS full_page_writes,
      current_setting('archive_mode') AS archive_mode,
      (
        SELECT count(*)
        FROM pg_stat_replication
        WHERE state = 'streaming' AND sync_state = 'sync'
      )::integer AS synchronous_standby_count,
      clock_timestamp() AS measured_at
  `);
  const row = result.rows[0];
  if (!row) throw new Error("PostgreSQL durability probe returned no row");
  const synchronousStandbyCount = Number(row.synchronous_standby_count);
  if (!Number.isSafeInteger(synchronousStandbyCount) || synchronousStandbyCount < 0) {
    throw new Error("PostgreSQL durability probe returned invalid values");
  }
  const synchronousCommit = String(row.synchronous_commit);
  const synchronousStandbyNames = String(row.synchronous_standby_names);
  const fsync = row.fsync === "on";
  const fullPageWrites = row.full_page_writes === "on";
  const archiveMode = String(row.archive_mode);
  return {
    inRecovery: row.in_recovery,
    synchronousCommit,
    synchronousStandbyNames,
    synchronousStandbyCount,
    fsync,
    fullPageWrites,
    archiveMode,
    mutationDurabilityReady:
      !row.in_recovery &&
      synchronousCommit === "remote_apply" &&
      synchronousStandbyNames.trim().length > 0 &&
      synchronousStandbyCount >= 1,
    degradedPrimaryDurabilityReady:
      !row.in_recovery &&
      synchronousCommit === "on" &&
      fsync &&
      fullPageWrites &&
      archiveMode === "on",
    standalonePrimaryDurabilityReady:
      !row.in_recovery &&
      (synchronousCommit === "on" || synchronousCommit === "local") &&
      synchronousStandbyNames.trim().length === 0 &&
      synchronousStandbyCount === 0 &&
      fsync &&
      fullPageWrites &&
      archiveMode === "on",
    measuredAt:
      row.measured_at instanceof Date
        ? row.measured_at.toISOString()
        : new Date(row.measured_at).toISOString(),
  };
}
