import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import type { AuditRecord, LeadershipState } from "../src/contracts.js";
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
    const first = new SqliteWitnessStore(database, "test-fabric");
    await expect(first.initialize(state, initialized)).resolves.toEqual(state);
    await first.appendAudit({
      ...initialized,
      auditId: "rejected-1",
      eventType: "failback_rejected",
    });
    await expect(first.ready()).resolves.toBeUndefined();

    const restarted = new SqliteWitnessStore(database, "test-fabric");
    await expect(restarted.getState()).resolves.toEqual(state);
    await expect(restarted.listAudit(10)).resolves.toMatchObject([
      { auditId: "rejected-1" },
      { auditId: "initialized-1" },
    ]);
    await expect(restarted.initialize({ ...state, fabricEpoch: 99 }, initialized))
      .resolves.toEqual(state);
  });

  it("isolates clusters sharing one portable database", async () => {
    const directory = mkdtempSync(join(tmpdir(), "witness-sqlite-"));
    const database = join(directory, "witness.sqlite3");
    const first = new SqliteWitnessStore(database, "fabric-a");
    const second = new SqliteWitnessStore(database, "fabric-b");
    await first.initialize(state, initialized);
    await second.initialize(
      { ...state, currentLeader: "other", fabricEpoch: 7 },
      { ...initialized, auditId: "initialized-2" },
    );

    await expect(
      new SqliteWitnessStore(database, "fabric-a").getState(),
    ).resolves.toMatchObject({ currentLeader: "genomesbox", fabricEpoch: 1 });
    await expect(
      new SqliteWitnessStore(database, "fabric-b").getState(),
    ).resolves.toMatchObject({ currentLeader: "other", fabricEpoch: 7 });
  });

  it("poisons readiness and authority reads after a durable write failure", async () => {
    const directory = mkdtempSync(join(tmpdir(), "witness-sqlite-"));
    const store = new SqliteWitnessStore(
      join(directory, "witness.sqlite3"),
      "test-fabric",
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

    const restarted = new SqliteWitnessStore(
      join(directory, "witness.sqlite3"),
      "test-fabric",
    );
    await expect(restarted.getState()).resolves.toEqual(state);
    await expect(restarted.listAudit(10)).resolves.not.toContainEqual(
      expect.objectContaining({ auditId: "must-not-commit" }),
    );
  });
});
