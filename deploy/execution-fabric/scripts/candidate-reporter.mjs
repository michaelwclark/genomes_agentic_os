import { createHash } from "node:crypto";
import { readFile, rename, writeFile } from "node:fs/promises";
import { createRequire } from "node:module";
import process from "node:process";

const require = createRequire(`${process.cwd()}/package.json`);
const pg = require("pg");
const { parse: parseYaml } = require("yaml");
const { Client } = pg;
const heartbeatPath =
  process.env.FABRIC_CANDIDATE_HEARTBEAT_FILE ??
  "/tmp/execution-fabric-candidate-heartbeat.json";

function boundedInteger(name, fallback, minimum, maximum) {
  const value = Number(process.env[name] ?? fallback);
  if (!Number.isSafeInteger(value) || value < minimum || value > maximum) {
    throw new Error(`${name} must be an integer from ${minimum} through ${maximum}`);
  }
  return value;
}

function canonicalJson(value) {
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(",")}]`;
  if (value !== null && typeof value === "object") {
    return `{${Object.entries(value)
      .sort(([left], [right]) => left.localeCompare(right))
      .map(([key, child]) => `${JSON.stringify(key)}:${canonicalJson(child)}`)
      .join(",")}}`;
  }
  return JSON.stringify(value);
}

async function atomicWrite(value) {
  const temporary = `${heartbeatPath}.tmp.${process.pid}`;
  await writeFile(temporary, `${JSON.stringify(value)}\n`, { mode: 0o600 });
  await rename(temporary, heartbeatPath);
}

async function readHeartbeat() {
  try {
    return JSON.parse(await readFile(heartbeatPath, "utf8"));
  } catch {
    return null;
  }
}

async function policyFingerprint(path) {
  const policy = parseYaml(await readFile(path, "utf8"));
  return createHash("sha256").update(canonicalJson(policy)).digest("hex");
}

async function replicationSnapshot(databaseUrl) {
  const client = new Client({
    connectionString: databaseUrl,
    statement_timeout: 5000,
    connectionTimeoutMillis: 5000,
  });
  await client.connect();
  try {
    const result = await client.query(`
      WITH recovery AS (
        SELECT pg_is_in_recovery() AS in_recovery,
               (pg_control_checkpoint()).timeline_id AS timeline_id,
               pg_last_wal_receive_lsn() AS standby_receive_lsn,
               pg_last_wal_replay_lsn() AS standby_replay_lsn
      ), receiver AS (
        SELECT status,last_msg_receipt_time
        FROM pg_stat_wal_receiver
        LIMIT 1
      ), positions AS (
        SELECT in_recovery,timeline_id,
               CASE WHEN in_recovery
                    THEN COALESCE(standby_receive_lsn,standby_replay_lsn)
                    ELSE pg_current_wal_lsn() END AS receive_lsn,
               CASE WHEN in_recovery
                    THEN COALESCE(standby_replay_lsn,standby_receive_lsn)
                    ELSE pg_current_wal_lsn() END AS replay_lsn
        FROM recovery
      )
      SELECT in_recovery,timeline_id,receive_lsn::text,replay_lsn::text,
             pg_wal_lsn_diff(receive_lsn,'0/0')::bigint
               AS receive_wal_position,
             pg_wal_lsn_diff(replay_lsn,'0/0')::bigint
               AS replay_wal_position,
             GREATEST(pg_wal_lsn_diff(receive_lsn,replay_lsn),0)::bigint
               AS replica_lag_bytes,
             (pg_control_system()).system_identifier::text
               AS upstream_system_id,
             CASE WHEN NOT in_recovery THEN 'not_applicable'
                  ELSE COALESCE((SELECT status FROM receiver),'disconnected')
             END AS receiver_state,
             CASE WHEN NOT in_recovery THEN clock_timestamp()
                  ELSE COALESCE(
                    (SELECT last_msg_receipt_time FROM receiver),
                    TIMESTAMPTZ '1970-01-01T00:00:00Z')
             END AS last_message_at,
             clock_timestamp() AS measured_at
      FROM positions
    `);
    const row = result.rows[0];
    if (!row) throw new Error("PostgreSQL replication probe returned no row");
    const replicaLagBytes = Number(row.replica_lag_bytes);
    const receiveWalPosition = Number(row.receive_wal_position);
    const replayWalPosition = Number(row.replay_wal_position);
    if (
      !Number.isSafeInteger(replicaLagBytes) ||
      replicaLagBytes < 0 ||
      !Number.isSafeInteger(receiveWalPosition) ||
      receiveWalPosition < 0 ||
      !Number.isSafeInteger(replayWalPosition) ||
      replayWalPosition < 0
    ) {
      throw new Error("PostgreSQL WAL position is outside the safe integer range");
    }
    return {
      inRecovery: row.in_recovery === true,
      timelineId: Number(row.timeline_id),
      receiveLsn: String(row.receive_lsn),
      replayLsn: String(row.replay_lsn),
      receiveWalPosition,
      replayWalPosition,
      replicaLagBytes,
      upstreamSystemId: String(row.upstream_system_id),
      receiverState: String(row.receiver_state),
      lastMessageAt: new Date(row.last_message_at).toISOString(),
      lagMeasuredAt: new Date(row.measured_at).toISOString(),
    };
  } finally {
    await client.end();
  }
}

async function reportOnce() {
  const hostId = process.env.FABRIC_HOST_ID;
  const databaseUrl = process.env.FABRIC_DATABASE_URL;
  const witnessBase = process.env.FABRIC_LEADERSHIP_API_BASE;
  const tokenFile = process.env.FABRIC_LEADERSHIP_CANDIDATE_TOKEN_FILE;
  const policyFile = process.env.FABRIC_POLICY_CONFIG_FILE;
  if (!hostId || !databaseUrl || !witnessBase || !tokenFile || !policyFile) {
    throw new Error("candidate reporter configuration is incomplete");
  }
  if (!/^https:\/\//.test(witnessBase)) {
    throw new Error("candidate reporter requires an HTTPS witness URL");
  }
  const token = (await readFile(tokenFile, "utf8")).trim();
  if (!/^\S{32,}$/.test(token)) {
    throw new Error("candidate credential is missing or too short");
  }
  const previous = await readHeartbeat();
  const attemptedAt = new Date().toISOString();
  try {
    const replication = await replicationSnapshot(databaseUrl);
    const configDigest = await policyFingerprint(policyFile);
    const payload = {
      healthy: true,
      ...replication,
      configDigest,
      observedAt: attemptedAt,
    };
    const response = await fetch(
      `${witnessBase.replace(/\/$/, "")}/api/v1/admin/leadership/candidates/${encodeURIComponent(hostId)}`,
      {
        method: "PUT",
        headers: {
          authorization: `Bearer ${token}`,
          "content-type": "application/json",
        },
        body: JSON.stringify(payload),
        signal: AbortSignal.timeout(10000),
      },
    );
    if (!response.ok) {
      throw new Error(`witness rejected candidate report with HTTP ${response.status}`);
    }
    const heartbeat = {
      schemaVersion: "execution-fabric-candidate-heartbeat/v1",
      hostId,
      status: "healthy",
      mode: replication.inRecovery ? "standby" : "active",
      ...replication,
      configDigest,
      lastAttemptAt: attemptedAt,
      lastSuccessfulAt: new Date().toISOString(),
      lastError: null,
    };
    await atomicWrite(heartbeat);
    return heartbeat;
  } catch (error) {
    await atomicWrite({
      schemaVersion: "execution-fabric-candidate-heartbeat/v1",
      hostId,
      status: "failed",
      mode: previous?.mode ?? "unknown",
      inRecovery: previous?.inRecovery ?? null,
      timelineId: previous?.timelineId ?? null,
      receiveLsn: previous?.receiveLsn ?? null,
      replayLsn: previous?.replayLsn ?? null,
      receiveWalPosition: previous?.receiveWalPosition ?? null,
      replayWalPosition: previous?.replayWalPosition ?? null,
      replicaLagBytes: previous?.replicaLagBytes ?? null,
      lagMeasuredAt: previous?.lagMeasuredAt ?? null,
      upstreamSystemId: previous?.upstreamSystemId ?? null,
      receiverState: previous?.receiverState ?? null,
      lastMessageAt: previous?.lastMessageAt ?? null,
      configDigest: previous?.configDigest ?? null,
      lastAttemptAt: attemptedAt,
      lastSuccessfulAt: previous?.lastSuccessfulAt ?? null,
      lastError: error instanceof Error ? error.message.slice(0, 512) : "unknown error",
    });
    throw error;
  }
}

async function healthcheck() {
  const heartbeat = await readHeartbeat();
  const maxAgeSeconds = boundedInteger(
    "FABRIC_CANDIDATE_HEARTBEAT_MAX_AGE_SECONDS",
    75,
    15,
    600,
  );
  const successfulAt = Date.parse(heartbeat?.lastSuccessfulAt ?? "");
  const ageSeconds = (Date.now() - successfulAt) / 1000;
  if (
    !heartbeat ||
    heartbeat.hostId !== process.env.FABRIC_HOST_ID ||
    !Number.isFinite(ageSeconds) ||
    ageSeconds < -30 ||
    ageSeconds > maxAgeSeconds
  ) {
    throw new Error("candidate reporter heartbeat is stale or invalid");
  }
}

async function main() {
  if (process.argv.includes("--print-heartbeat")) {
    const heartbeat = await readHeartbeat();
    if (!heartbeat) process.exitCode = 1;
    else process.stdout.write(`${JSON.stringify(heartbeat)}\n`);
    return;
  }
  if (process.argv.includes("--healthcheck")) {
    await healthcheck();
    return;
  }
  if (process.argv.includes("--once")) {
    await reportOnce();
    return;
  }
  const intervalSeconds = boundedInteger(
    "FABRIC_CANDIDATE_REPORT_INTERVAL_SECONDS",
    30,
    10,
    300,
  );
  while (true) {
    await reportOnce().catch((error) => {
      process.stderr.write(
        `${JSON.stringify({
          role: "candidate-reporter",
          sampledAt: new Date().toISOString(),
          error: error instanceof Error ? error.message : "unknown error",
        })}\n`,
      );
    });
    await new Promise((resolve) => setTimeout(resolve, intervalSeconds * 1000));
  }
}

await main().catch((error) => {
  process.stderr.write(
    `${error instanceof Error ? error.message : "candidate reporter failed"}\n`,
  );
  process.exitCode = 1;
});
