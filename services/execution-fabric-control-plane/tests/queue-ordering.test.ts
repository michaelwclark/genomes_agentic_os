import type pg from "pg";
import { describe, expect, it, vi } from "vitest";
import { PostgresLedger, type ClaimConstraints } from "../src/ledger.js";
import { DISPATCH_STARVATION_AGE_SECONDS, taskDispatchOrderSql } from "../src/queue-ordering.js";
import { createTestPolicy } from "./policy-fixture.js";

describe("actual PostgreSQL queue ordering consumers", () => {
  it("binds publication limit and age rather than interpolating policy values", async () => {
    const query = vi.fn().mockResolvedValue({ rows: [], rowCount: 0 });
    const ledger = new PostgresLedger({ query } as unknown as pg.Pool, 45);
    expect(await ledger.listPublishable(17)).toEqual([]);
    const [sql, values] = query.mock.calls[0]!;
    expect(sql).toContain("ORDER BY " + taskDispatchOrderSql("publish"));
    expect(values).toEqual([17, DISPATCH_STARVATION_AGE_SECONDS]);
    expect(sql).not.toContain("LIMIT 17");
  });

  it("uses the same oldest-aged-first rule in the actual fenced claim query", async () => {
    const query = vi.fn(async (sql: string, _values?: unknown[]) => {
      if (sql.includes("SELECT w.*, s.current_epoch")) {
        return { rows: [{ queues: ["code"], capabilities: ["test.run"], max_concurrency: 1, host_id: "fixture", current_epoch: 1 }], rowCount: 1 };
      }
      if (sql.includes("SELECT count(*)::text AS count FROM fabric_attempts")) {
        return { rows: [{ count: "0" }], rowCount: 1 };
      }
      return { rows: [], rowCount: 0 };
    });
    const client = { query, release: vi.fn() };
    const ledger = new PostgresLedger({ connect: vi.fn().mockResolvedValue(client) } as unknown as pg.Pool, 45);
    const policy = createTestPolicy().policy;
    const effective = policy.effective().execution_fabric;
    const constraints: ClaimConstraints = {
      configFingerprint: policy.snapshot().appliedFingerprint,
      pool: policy.pool("code_workers"), queue: policy.queue("code"),
      globalMaxRunning: 2, providerMaxRunning: 1,
      reservedInteractiveSlots: 0, maxInteractiveRunning: 1,
      namespaceLimits: {}, hostLimits: {}, namespaceWeights: {},
      priorityAgingIntervalSeconds: effective.scheduling.priority_aging.interval_seconds,
      priorityAgingBoost: effective.scheduling.priority_aging.boost_per_interval,
      priorityAgingMaxBoost: effective.scheduling.priority_aging.max_boost,
    };
    expect(await ledger.claim({
      workerId: "fixture", registrationToken: "fixture-token",
      queues: ["code"], capabilities: ["test.run"], waitMs: 0,
    }, constraints)).toBeNull();
    const selection = query.mock.calls.find(([sql]) => sql.includes("SELECT t.* FROM fabric_tasks t"));
    expect(selection).toBeDefined();
    expect(selection![0]).toContain("ORDER BY " + taskDispatchOrderSql("claim"));
    expect(selection![0]).toContain("FOR UPDATE SKIP LOCKED");
    expect(selection![1]).toEqual([
      ["code"], '["test.run"]', "{}", "{}",
      constraints.priorityAgingIntervalSeconds, constraints.priorityAgingBoost,
      constraints.priorityAgingMaxBoost, 3600,
    ]);
    expect(client.release).toHaveBeenCalledOnce();
  });

  it("rejects unknown SQL fragment consumers before construction", () => {
    expect(() => taskDispatchOrderSql("publish; DROP TABLE fabric_tasks" as "publish")).toThrow("unsupported queue ordering consumer");
  });
});
