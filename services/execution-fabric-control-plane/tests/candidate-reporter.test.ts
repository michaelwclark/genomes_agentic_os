import { mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { spawnSync } from "node:child_process";
import { describe, expect, it } from "vitest";

const script = resolve(
  process.cwd(),
  "../../deploy/execution-fabric/scripts/candidate-reporter.mjs",
);

function runHealth(heartbeat: Record<string, unknown>) {
  const directory = mkdtempSync(join(tmpdir(), "fabric-candidate-test-"));
  const heartbeatPath = join(directory, "heartbeat.json");
  writeFileSync(heartbeatPath, JSON.stringify(heartbeat));
  return spawnSync(process.execPath, [script, "--healthcheck"], {
    cwd: process.cwd(),
    env: {
      ...process.env,
      FABRIC_HOST_ID: "bigmac",
      FABRIC_CANDIDATE_HEARTBEAT_FILE: heartbeatPath,
      FABRIC_CANDIDATE_HEARTBEAT_MAX_AGE_SECONDS: "75",
    },
    encoding: "utf8",
  });
}

describe("portable candidate reporter heartbeat", () => {
  it("accepts a fresh measured heartbeat and rejects stale evidence", () => {
    const heartbeat = {
      schemaVersion: "execution-fabric-candidate-heartbeat/v1",
      hostId: "bigmac",
      status: "healthy",
      mode: "standby",
      inRecovery: true,
      timelineId: 4,
      receiveLsn: "0/1600000",
      replayLsn: "0/15FFFF0",
      receiveWalPosition: 23068672,
      replayWalPosition: 23068656,
      replicaLagBytes: 16,
      lagMeasuredAt: new Date().toISOString(),
      upstreamSystemId: "7600000000000000000",
      receiverState: "streaming",
      lastMessageAt: new Date().toISOString(),
      configDigest: "a".repeat(64),
      policyCandidateDigest: "b".repeat(64),
      policyCandidateObservedAt: new Date().toISOString(),
      lastAttemptAt: new Date().toISOString(),
      lastSuccessfulAt: new Date().toISOString(),
      lastError: null,
    };
    expect(runHealth(heartbeat).status).toBe(0);
    expect(
      runHealth({
        ...heartbeat,
        lastSuccessfulAt: new Date(Date.now() - 120_000).toISOString(),
      }).status,
    ).not.toBe(0);
  });

  it("contains only measured PostgreSQL inputs for witness reporting", () => {
    const source = readFileSync(script, "utf8");
    expect(source).toContain("pg_is_in_recovery()");
    expect(source).toContain("pg_last_wal_receive_lsn()");
    expect(source).toContain("pg_last_wal_replay_lsn()");
    expect(source).toContain("replicaLagBytes");
    expect(source).toContain("receiveWalPosition");
    expect(source).toContain("upstreamSystemId");
    expect(source).toContain("receiverState");
    expect(source).toContain("lastMessageAt");
    expect(source).toContain("clock_timestamp()");
    expect(source).toContain("applied_config_digest");
    expect(source).toContain("policyCandidateDigest");
    expect(source).toContain("FABRIC_LEADERSHIP_CANDIDATE_TOKEN_FILE");
    expect(source).not.toContain("FABRIC_LEADERSHIP_ADMIN_TOKEN_FILE");
  });
});
