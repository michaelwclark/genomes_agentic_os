import {
  mkdtempSync,
  readFileSync,
  unlinkSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import type {
  AuditRecord,
  CandidateRecord,
  LeadershipState,
  PromotionMutation,
} from "../src/contracts.js";
import { SqliteWitnessStore } from "../src/sqlite-store.js";

const state: LeadershipState = {
  currentLeader: "genomesbox",
  fabricEpoch: 1,
  timelineId: 1,
  configDigest: "a".repeat(64),
  leaderWalPosition: null,
  leaderBaselineAt: null,
  upstreamSystemId: null,
  updatedAt: "2026-07-25T00:00:00.000Z",
  fenceDigest: "b".repeat(64),
  authorityMode: "synchronous",
  degradedUntil: null,
  degradedIncidentDigest: null,
};

const initialized: AuditRecord = {
  auditId: "initialized-1",
  eventType: "initialized",
  actor: "witness",
  occurredAt: state.updatedAt,
  detail: {},
};

describe("portable SQLite witness store", () => {
  it("commits state and audit before returning and restores them after restart", async () => {
    const directory = mkdtempSync(join(tmpdir(), "witness-sqlite-"));
    const database = join(directory, "witness.sqlite3");
    const first = new SqliteWitnessStore(database, "test-fabric", {
      allowInitialBootstrap: true,
    });
    await expect(first.initialize(state, initialized)).resolves.toEqual(state);
    await first.appendAudit({
      ...initialized,
      auditId: "rejected-1",
      eventType: "failback_rejected",
    });
    await expect(first.ready()).resolves.toBeUndefined();
    await first.close();

    const restarted = new SqliteWitnessStore(database, "test-fabric");
    await expect(restarted.getState()).resolves.toEqual(state);
    await expect(restarted.listAudit(10)).resolves.toMatchObject([
      { auditId: "rejected-1" },
      { auditId: "initialized-1" },
    ]);
    await expect(restarted.initialize({ ...state, fabricEpoch: 99 }, initialized))
      .resolves.toEqual(state);
    await restarted.close();
  });

  it("requires explicit first bootstrap and fences a concurrent process", async () => {
    const directory = mkdtempSync(join(tmpdir(), "witness-sqlite-"));
    const database = join(directory, "witness.sqlite3");
    expect(() => new SqliteWitnessStore(database, "fabric-a")).toThrow(
      /WITNESS_BOOTSTRAP_ONCE/,
    );
    const first = new SqliteWitnessStore(database, "fabric-a", {
      allowInitialBootstrap: true,
    });
    await first.initialize(state, initialized);
    expect(() => new SqliteWitnessStore(database, "fabric-a")).toThrow(
      /singleton storage lease/,
    );
    await first.close();
    const restarted = new SqliteWitnessStore(database, "fabric-a");
    await expect(restarted.getState()).resolves.toEqual(state);
    await restarted.close();
  });

  it("poisons readiness and authority reads after a durable write failure", async () => {
    const directory = mkdtempSync(join(tmpdir(), "witness-sqlite-"));
    const store = new SqliteWitnessStore(
      join(directory, "witness.sqlite3"),
      "test-fabric",
      { allowInitialBootstrap: true },
    );
    await store.initialize(state, initialized);
    (
      store as unknown as {
        database: { exec(statement: string): void };
      }
    ).database.exec(`
      CREATE TRIGGER reject_snapshot_update
      BEFORE UPDATE ON witness_snapshot
      BEGIN
        SELECT RAISE(ABORT, 'simulated durable write failure');
      END;
    `);

    await expect(
      store.appendAudit({
        ...initialized,
        auditId: "must-not-commit",
        eventType: "failback_rejected",
      }),
    ).rejects.toThrow(/simulated durable write failure/);
    await expect(store.ready()).rejects.toThrow(/simulated durable write failure/);
    await expect(store.getState()).rejects.toThrow(
      /simulated durable write failure/,
    );
    await store.close();

    const restarted = new SqliteWitnessStore(
      join(directory, "witness.sqlite3"),
      "test-fabric",
    );
    await expect(restarted.getState()).resolves.toEqual(state);
    await expect(restarted.listAudit(10)).resolves.not.toContainEqual(
      expect.objectContaining({ auditId: "must-not-commit" }),
    );
    await restarted.close();
  });

  it("fails closed when initialized state is missing or corrupt", async () => {
    const directory = mkdtempSync(join(tmpdir(), "witness-sqlite-"));
    const database = join(directory, "witness.sqlite3");
    const store = new SqliteWitnessStore(database, "test-fabric", {
      allowInitialBootstrap: true,
    });
    await store.initialize(state, initialized);
    await store.close();
    unlinkSync(database);
    expect(() => new SqliteWitnessStore(database, "test-fabric")).toThrow(
      /database is missing/,
    );

    copyRecovery(database);
    writeFileSync(database, "not a sqlite database", { mode: 0o600 });
    expect(() => new SqliteWitnessStore(database, "test-fabric")).toThrow();
  });

  it("fences a paused process after another process claims its expired lease", async () => {
    const directory = mkdtempSync(join(tmpdir(), "witness-sqlite-"));
    const database = join(directory, "witness.sqlite3");
    let now = Date.parse("2026-07-25T00:00:00.000Z");
    const first = new SqliteWitnessStore(database, "test-fabric", {
      allowInitialBootstrap: true,
      leaseDurationMs: 3_000,
      now: () => now,
    });
    await first.initialize(state, initialized);
    now += 4_000;
    const replacement = new SqliteWitnessStore(database, "test-fabric", {
      leaseDurationMs: 3_000,
      now: () => now,
    });
    await expect(
      first.appendAudit({
        ...initialized,
        auditId: "partitioned-old-process",
        eventType: "failback_rejected",
      }),
    ).rejects.toThrow(/lease was lost/);
    await replacement.close();
    await first.close();
  });

  it("rejects a stale local snapshot version instead of overwriting it", async () => {
    const directory = mkdtempSync(join(tmpdir(), "witness-sqlite-"));
    const store = new SqliteWitnessStore(
      join(directory, "witness.sqlite3"),
      "test-fabric",
      { allowInitialBootstrap: true },
    );
    await store.initialize(state, initialized);
    (
      store as unknown as {
        database: { exec(statement: string): void };
      }
    ).database.exec(
      "UPDATE witness_snapshot SET version=version+1 WHERE cluster_id='test-fabric'",
    );
    await expect(
      store.appendAudit({
        ...initialized,
        auditId: "stale-writer",
        eventType: "failback_rejected",
      }),
    ).rejects.toThrow(/local state version is stale/);
    await store.close();
  });

  it("replays the exact durable promotion receipt after a response-loss restart", async () => {
    const directory = mkdtempSync(join(tmpdir(), "witness-sqlite-"));
    const database = join(directory, "witness.sqlite3");
    const store = new SqliteWitnessStore(database, "test-fabric", {
      allowInitialBootstrap: true,
    });
    await store.initialize(state, initialized);
    const candidate = (
      host: string,
      inRecovery: boolean,
      observedAtEpoch: number,
    ): CandidateRecord => ({
      candidate: host,
      healthy: true,
      inRecovery,
      timelineId: 1,
      receiveLsn: "0/100",
      replayLsn: "0/100",
      receiveWalPosition: 1_000,
      replayWalPosition: 1_000,
      replicaLagBytes: 0,
      lagMeasuredAt: "2026-07-25T00:00:00.000Z",
      upstreamSystemId: "7600000000000000000",
      receiverState: inRecovery ? "streaming" : "not_applicable",
      lastMessageAt: "2026-07-25T00:00:00.000Z",
      configDigest: state.configDigest,
      observedAt: "2026-07-25T00:00:00.000Z",
      observedAtEpoch,
    });
    await store.putCandidate(candidate("genomesbox", false, 1), initialized, {
      expectedLeader: "genomesbox",
      expectedTimelineId: 1,
      expectedConfigDigest: state.configDigest,
    });
    await store.putCandidate(
      candidate("bigmac", true, 20),
      { ...initialized, auditId: "candidate-bigmac" },
    );
    const nextState: LeadershipState = {
      ...state,
      currentLeader: "bigmac",
      fabricEpoch: 2,
      timelineId: 2,
      leaderWalPosition: 1_000,
      leaderBaselineAt: "2026-07-25T00:00:00.000Z",
      upstreamSystemId: "7600000000000000000",
    };
    const mutation: PromotionMutation = {
      promotionId: "00000000-0000-4000-8000-000000000301",
      requestDigest: "d".repeat(64),
      expectedLeader: "genomesbox",
      expectedEpoch: 1,
      candidate: "bigmac",
      configDigest: state.configDigest,
      freshAfterEpoch: 10,
      maxReplicaLagBytes: 100,
      expectedTimelineId: 1,
      expectedLeaderWalPosition: 1_000,
      minimumReplayWalPosition: 900,
      expectedUpstreamSystemId: "7600000000000000000",
      leaderBaselineFreshAfterEpoch: 10,
      receiverFreshAfterEpoch: 10,
      nextState,
      receipt: {
        apiVersion: "execution-fabric-leadership/v1",
        decision: "promoted",
        promotionId: "00000000-0000-4000-8000-000000000301",
        requestDigest: "d".repeat(64),
        receiptId: "promotion-receipt",
        previousLeader: "genomesbox",
        currentLeader: "bigmac",
        fabricEpoch: 2,
        clusterId: "test-fabric",
        fenceToken: "signed-fence-token",
        authorityMode: "synchronous",
        degradedUntil: null,
        committedAt: "2026-07-25T00:00:00.000Z",
      },
      audit: {
        ...initialized,
        auditId: "promotion-receipt",
        eventType: "promotion_committed",
      },
    };
    await expect(store.promote(mutation)).resolves.toEqual(mutation.receipt);
    await store.close();
    const restarted = new SqliteWitnessStore(database, "test-fabric");
    await expect(restarted.promote(mutation)).resolves.toEqual(mutation.receipt);
    await expect(restarted.getState()).resolves.toEqual(nextState);
    await restarted.close();
  });
});

function copyRecovery(database: string): void {
  const source = `${database}.backup`;
  const content = readFileSync(source);
  writeFileSync(database, content, { mode: 0o600 });
}
