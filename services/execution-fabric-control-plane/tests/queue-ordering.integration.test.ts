import { randomUUID } from "node:crypto";
import type pg from "pg";
import { afterAll, beforeAll, beforeEach, describe, expect, it } from "vitest";
import { createPool, migrate } from "../src/db.js";
import { BullMqDelivery } from "../src/delivery.js";
import { ExecutionFabric } from "../src/fabric.js";
import { PostgresLedger } from "../src/ledger.js";
import { taskDispatchOrderSql } from "../src/queue-ordering.js";
import { createTestPolicy } from "./policy-fixture.js";

const enabled = process.env.FABRIC_INTEGRATION_TESTS === "1";
describe.skipIf(!enabled)("owned PostgreSQL queue ordering conformance", () => {
  let pool: pg.Pool;
  let delivery: BullMqDelivery;
  let fabric: ExecutionFabric;
  let ledger: PostgresLedger;
  let registrationToken: string;
  const workerId = "ordering-fixture";
  beforeAll(async () => {
    const databaseUrl = process.env.FABRIC_TEST_DATABASE_URL;
    const valkeyUrl = process.env.FABRIC_TEST_VALKEY_URL;
    if (!databaseUrl || !valkeyUrl) throw new Error("explicit disposable provider URLs required");
    pool = createPool(databaseUrl);
    await migrate(pool);
    delivery = new BullMqDelivery(valkeyUrl, "age206_ordering_" + randomUUID());
    ledger = new PostgresLedger(pool, 45);
    fabric = new ExecutionFabric(ledger, delivery, 120, 0, createTestPolicy((value) => {
      value.execution_fabric.queues[0].concurrency.max_queued = 100;
    }).policy);
    await fabric.ready();
  });
  afterAll(async () => { await delivery?.close(); await pool?.end(); });
  beforeEach(async () => {
    await pool.query(`TRUNCATE fabric_effect_outbox,fabric_events,fabric_attempts,
      fabric_runs,fabric_workers,fabric_tasks,fabric_config_reload_receipts RESTART IDENTITY CASCADE`);
    await pool.query(`UPDATE fabric_state SET current_epoch=1,leader_host_id=NULL,
      leader_lease_expires_at=NULL,leadership_cluster_id=NULL,leadership_receipt_id=NULL,
      leadership_fence_digest=NULL,leader_recovery_hold_until=NULL,policy_fingerprint=NULL,updated_at=now()
      WHERE singleton=true`);
    await fabric.ready();
    const registration = await fabric.registerWorker({
      bootstrapId: "integration-host.code." + workerId, workerId, hostId: "integration-host",
      queues: ["code"], capabilities: ["test.run"], maxConcurrency: 1, metadata: {},
    });
    registrationToken = registration.registrationToken;
  });
  async function admit(name: string, priority: number) {
    return (await fabric.admit({
      namespace: "integration-ordering", queue: "code", taskType: "example.run",
      idempotencyKey: name, payload: {}, requiredCapabilities: ["test.run"],
      priority, maxAttempts: 1,
    })).task;
  }
  async function claim() {
    return fabric.claim({ workerId, registrationToken, queues: ["code"], capabilities: ["test.run"], waitMs: 0 });
  }
  async function complete(assignment: NonNullable<Awaited<ReturnType<typeof claim>>>) {
    return ledger.complete(assignment.attemptId, {
      workerId, leaseToken: assignment.leaseToken, fabricEpoch: assignment.fabricEpoch, result: {}, effects: [],
    });
  }
  it("claims the oldest aged low-priority work under sustained fresh high-priority arrivals", async () => {
    const oldest = await admit("oldest-low", 0);
    const newer = await admit("newer-aged-high", 1000);
    await pool.query("UPDATE fabric_tasks SET available_at=now()-interval '2 hours',created_at=now()-interval '2 hours' WHERE id=$1", [oldest.id]);
    await pool.query("UPDATE fabric_tasks SET available_at=now()-interval '90 minutes',created_at=now()-interval '90 minutes' WHERE id=$1", [newer.id]);
    for (let i = 0; i < 20; i++) await admit("fresh-" + i, 1000);
    const first = await claim();
    expect(first?.task.id).toBe(oldest.id);
    await complete(first!);
    for (let i = 20; i < 25; i++) await admit("fresh-" + i, 1000);
    const second = await claim();
    expect(second?.task.id).toBe(newer.id);
  });
  it("publishes aged work before all fresh priorities and keeps oldest aged order", async () => {
    const oldest = await admit("oldest-low", 0);
    const newer = await admit("newer-aged-high", 1000);
    await admit("fresh-high", 1000);
    await pool.query("UPDATE fabric_tasks SET delivery_published_at=NULL");
    await pool.query("UPDATE fabric_tasks SET available_at=now()-interval '2 hours' WHERE id=$1", [oldest.id]);
    await pool.query("UPDATE fabric_tasks SET available_at=now()-interval '90 minutes' WHERE id=$1", [newer.id]);
    expect((await ledger.listPublishable(2)).map((task) => task.id)).toEqual([oldest.id, newer.id]);
  });
  it.each([-1, 0, 1])("uses exact PostgreSQL cutoff microseconds (%i) in the actual claim transaction", async (offsetUs) => {
    const boundary = await admit("boundary-low", 0);
    const fresh = await admit("fresh-high", 1000);
    // Inject fixture timestamps inside the real claim transaction. Production
    // SQL remains unmodified and sees the same transaction-stable now().
    const wrappedPool = {
      connect: async () => {
        const client = await pool.connect();
        return {
          release: () => client.release(),
          query: async (sql: string, values?: unknown[]) => {
            if (sql.includes("SELECT t.* FROM fabric_tasks t") && sql.includes("FOR UPDATE SKIP LOCKED")) {
              await client.query("UPDATE fabric_tasks SET available_at=now()-interval '1 hour'+($2::integer*interval '1 microsecond') WHERE id=$1", [boundary.id, offsetUs]);
              await client.query("UPDATE fabric_tasks SET available_at=now(),created_at=now() WHERE id=$1", [fresh.id]);
            }
            return client.query(sql, values);
          },
        };
      },
    } as unknown as pg.Pool;
    const actual = new ExecutionFabric(new PostgresLedger(wrappedPool, 45), delivery, 120, 0, fabric.policy);
    const selected = await actual.claim({ workerId, registrationToken, queues: ["code"], capabilities: ["test.run"], waitMs: 0 });
    expect(selected?.task.id).toBe(offsetUs <= 0 ? boundary.id : fresh.id);
  });
  it("shares exact equality and offset normalization in publication SQL", async () => {
    const boundary = await admit("boundary-low", 0);
    const fresh = await admit("fresh-high", 1000);
    const client = await pool.connect();
    try {
      await client.query("BEGIN");
      await client.query("UPDATE fabric_tasks SET delivery_published_at=NULL");
      await client.query("UPDATE fabric_tasks SET available_at=now()-interval '1 hour' WHERE id=$1", [boundary.id]);
      await client.query("UPDATE fabric_tasks SET available_at=now() WHERE id=$1", [fresh.id]);
      const selected = await client.query(`SELECT t.id FROM fabric_tasks t WHERE status='queued'
        ORDER BY ${taskDispatchOrderSql("publish")} LIMIT $1`, [2, 3600]);
      expect(selected.rows.map((row) => row.id)).toEqual([boundary.id, fresh.id]);
      const normalized = await client.query("SELECT '2026-07-01 02:00:00.500001+02:00'::timestamptz = '2026-07-01T00:00:00.500001Z'::timestamptz AS equal");
      expect(normalized.rows[0].equal).toBe(true);
    } finally { await client.query("ROLLBACK"); client.release(); }
  });
});
