import { randomUUID } from "node:crypto";
import type pg from "pg";
import { afterAll, beforeAll, beforeEach, describe, expect, it } from "vitest";
import { createPool, migrate } from "../src/db.js";
import { BullMqDelivery } from "../src/delivery.js";
import { ExecutionFabric } from "../src/fabric.js";
import {
  ConflictError,
  FencedError,
  PostgresLedger,
} from "../src/ledger.js";
import { PostgresReliabilityStore } from "../src/reliability.js";
import { createTestPolicy } from "./policy-fixture.js";

const enabled = process.env.FABRIC_INTEGRATION_TESTS === "1";
const databaseUrl = process.env.FABRIC_TEST_DATABASE_URL;
const valkeyUrl = process.env.FABRIC_TEST_VALKEY_URL;

describe.skipIf(!enabled)("PostgreSQL + Valkey integration", () => {
  let pool: pg.Pool;
  let delivery: BullMqDelivery;
  let fabric: ExecutionFabric;

  beforeAll(async () => {
    if (!databaseUrl || !valkeyUrl) {
      throw new Error(
        "FABRIC_TEST_DATABASE_URL and FABRIC_TEST_VALKEY_URL are required",
      );
    }
    pool = createPool(databaseUrl);
    await migrate(pool);
    delivery = new BullMqDelivery(valkeyUrl, `integration_${randomUUID()}`);
    fabric = new ExecutionFabric(
      new PostgresLedger(pool, 45),
      delivery,
      120,
      0,
      createTestPolicy().policy,
    );
    await fabric.ready();
  });

  afterAll(async () => {
    await delivery?.close();
    await pool?.end();
  });

  beforeEach(async () => {
    await pool.query(
      `TRUNCATE fabric_effect_outbox,fabric_events,fabric_attempts,
         fabric_runs,fabric_workers,fabric_tasks RESTART IDENTITY CASCADE`,
    );
    await pool.query(
      `UPDATE fabric_state SET current_epoch=1,leader_host_id=NULL,
         leader_lease_expires_at=NULL,leadership_cluster_id=NULL,
         leadership_receipt_id=NULL,leadership_fence_digest=NULL,
         leader_recovery_hold_until=NULL,
         policy_fingerprint=NULL,updated_at=now()
       WHERE singleton=true`,
    );
    await fabric.ready();
  });

  it("admits idempotently, claims, fences, completes, and stages one effect", async () => {
    const namespace = `integration-${randomUUID()}`;
    const queue = "code";
    const workerId = `worker-${randomUUID()}`;
    const admission = {
      namespace,
      queue,
      taskType: "example.run",
      idempotencyKey: "one",
      payload: {},
      requiredCapabilities: ["test.run"],
      priority: 10,
      maxAttempts: 2,
    };
    const first = await fabric.admit(admission);
    const duplicate = await fabric.admit(admission);
    expect(first.admitted).toBe(true);
    expect(duplicate.admitted).toBe(false);
    expect(duplicate.task.id).toBe(first.task.id);
    await expect(
      fabric.admit({ ...admission, priority: admission.priority + 1 }),
    ).rejects.toBeInstanceOf(ConflictError);

    const registration = await fabric.registerWorker({
      bootstrapId: `integration-host.code.${workerId}`,
      workerId,
      hostId: "integration-host",
      queues: [queue],
      capabilities: ["test.run"],
      maxConcurrency: 1,
      metadata: {},
    });
    const assignment = await fabric.claim({
      workerId,
      registrationToken: registration.registrationToken,
      queues: [queue],
      capabilities: ["test.run"],
      waitMs: 0,
    });
    expect(assignment?.task.id).toBe(first.task.id);
    const effectKey = `integration-effect-${randomUUID()}`;
    const completed = await fabric.ledger.complete(assignment!.attemptId, {
      workerId,
      leaseToken: assignment!.leaseToken,
      fabricEpoch: assignment!.fabricEpoch,
      result: { echoed: true },
      effects: [
        {
          effectKey,
          effectType: "integration.receipt",
          payload: { ok: true },
          maxAttempts: 3,
          baseBackoffSeconds: 1,
        },
        {
          effectKey: `${effectKey}-unrelated`,
          effectType: "integration.unrelated",
          payload: { mustRemainUnclaimed: true },
          maxAttempts: 3,
          baseBackoffSeconds: 1,
        },
        {
          effectKey: `${effectKey}-expired`,
          effectType: "integration.expired",
          payload: { expiryMustConsumeAttempt: true },
          maxAttempts: 1,
          baseBackoffSeconds: 1,
        },
      ],
    });
    expect(completed.status).toBe("succeeded");
    const outbox = await pool.query<{ count: string }>(
      "SELECT count(*)::text AS count FROM fabric_effect_outbox WHERE effect_key=$1",
      [effectKey],
    );
    expect(Number(outbox.rows[0]?.count)).toBe(1);
    const effects = await fabric.ledger.claimEffects(
      {
        consumerId: "integration-effects",
        source: "integration",
        effectTypes: ["integration.receipt"],
        limit: 10,
      },
      120,
    );
    expect(effects).toHaveLength(1);
    expect(effects[0]?.effectKey).toBe(effectKey);
    const unrelated = await pool.query<{ status: string }>(
      "SELECT status FROM fabric_effect_outbox WHERE effect_key=$1",
      [`${effectKey}-unrelated`],
    );
    expect(unrelated.rows[0]?.status).toBe("pending");
    for (let attempt = 1; attempt <= 3; attempt += 1) {
      const [projection] = await fabric.ledger.claimEffects(
        {
          consumerId: "integration-unrelated",
          source: "integration",
          effectTypes: ["integration.unrelated"],
          limit: 1,
        },
        120,
      );
      expect(projection).toBeDefined();
      await fabric.ledger.failEffect(projection!.effectId, {
        consumerId: "integration-unrelated",
        claimToken: projection!.claimToken,
        fabricEpoch: projection!.fabricEpoch,
        errorSummary: "identical projection failure",
        retryAfterSeconds: 1,
      });
      if (attempt < 3) {
        await pool.query(
          "UPDATE fabric_effect_outbox SET available_at=now() WHERE id=$1",
          [projection!.effectId],
        );
      }
    }
    const deadLettered = await pool.query<{
      status: string;
      attempt_count: number;
    }>(
      "SELECT status,attempt_count FROM fabric_effect_outbox WHERE effect_key=$1",
      [`${effectKey}-unrelated`],
    );
    expect(deadLettered.rows[0]).toMatchObject({
      status: "dead_lettered",
      attempt_count: 3,
    });
    const [expiredClaim] = await fabric.ledger.claimEffects(
      {
        consumerId: "integration-expiry",
        source: "integration",
        effectTypes: ["integration.expired"],
        limit: 1,
      },
      120,
    );
    expect(expiredClaim).toBeDefined();
    await pool.query(
      "UPDATE fabric_effect_outbox SET claim_expires_at=now()-interval '1 second' WHERE id=$1",
      [expiredClaim!.effectId],
    );
    const reconciled = await fabric.ledger.reconcileExpired();
    expect(reconciled).toMatchObject({
      effectsRequeued: 0,
      effectsDeadLettered: 1,
    });
    const expiredDeadLettered = await pool.query<{
      status: string;
      attempt_count: number;
    }>(
      "SELECT status,attempt_count FROM fabric_effect_outbox WHERE effect_key=$1",
      [`${effectKey}-expired`],
    );
    expect(expiredDeadLettered.rows[0]).toMatchObject({
      status: "dead_lettered",
      attempt_count: 1,
    });
    await pool.query(
      `UPDATE fabric_state SET leader_host_id='integration-host',
         leader_lease_expires_at=now()+interval '1 minute' WHERE singleton=true`,
    );
    await new PostgresReliabilityStore(pool, "integration-host").replayEffect(
      String(
        (
          await pool.query<{ id: string }>(
            "SELECT id FROM fabric_effect_outbox WHERE effect_key=$1",
            [`${effectKey}-unrelated`],
          )
        ).rows[0]!.id,
      ),
      "integration-operator",
      `replay:${effectKey}`,
    );
    const replayed = await pool.query<{
      status: string;
      attempt_count: number;
    }>(
      "SELECT status,attempt_count FROM fabric_effect_outbox WHERE effect_key=$1",
      [`${effectKey}-unrelated`],
    );
    expect(replayed.rows[0]).toMatchObject({
      status: "pending",
      attempt_count: 0,
    });
    await fabric.ledger.deliverEffect(effects[0]!.effectId, {
      consumerId: "integration-effects",
      claimToken: effects[0]!.claimToken,
      fabricEpoch: effects[0]!.fabricEpoch,
      providerReceipt: { providerId: "integration-receipt" },
    });
    const delivered = await pool.query<{ status: string }>(
      "SELECT status FROM fabric_effect_outbox WHERE effect_key=$1",
      [effectKey],
    );
    expect(delivered.rows[0]?.status).toBe("delivered");
    const status = await fabric.status("integration-host", 20);
    expect(status).toMatchObject({
      schemaVersion: "agentic-os-execution-fabric-status/v1",
      config: { state: "applied" },
      controlPlane: {
        activeHost: "integration-host",
        databasePolicyFingerprint:
          fabric.policy.snapshot().appliedFingerprint,
      },
      effects: { delivered: 1 },
    });
    expect(status.workers).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          workerId,
          poolId: "code_workers",
          provider: "test",
          configFingerprint: fabric.policy.snapshot().appliedFingerprint,
        }),
      ]),
    );
  });

  it("idempotently ingests source-scoped observations and derives sticky alarms", async () => {
    const store = new PostgresReliabilityStore(pool, "integration-host");
    const incidentKey = `malformed:${randomUUID()}`;
    const observation = {
      source: "team-pr-runner",
      incidentKey,
      revision: 1,
      active: true,
      severity: "warning" as const,
      code: "malformed_request_row",
      summary: "Team PR request row is malformed",
      evidence: { field: "pull_request_url" },
      affected: { kind: "notion_page", id: randomUUID() },
      runbook: { ref: "execution-fabric/team-pr-malformed-row" },
      observedAt: new Date().toISOString(),
    };
    const first = await store.ingestExternalObservation(observation, 1);
    const duplicate = await store.ingestExternalObservation(observation, 1);
    expect(first).toMatchObject({ admitted: true, alarmDerived: true });
    expect(duplicate).toMatchObject({
      admitted: false,
      idempotent: true,
      finding: { id: first.finding.id },
    });
    await expect(
      store.ingestExternalObservation(
        { ...observation, summary: "different content" },
        1,
      ),
    ).rejects.toBeInstanceOf(ConflictError);
    const next = await store.ingestExternalObservation(
      {
        ...observation,
        revision: 2,
        summary: "Team PR request row remains malformed",
      },
      1,
    );
    expect(next.finding).toMatchObject({
      id: first.finding.id,
      revision: 2,
      status: "open",
    });
    const alarms = await pool.query<{ count: string }>(
      "SELECT count(*)::text AS count FROM fabric_alarm_outbox WHERE incident_key=$1",
      [`external:team-pr-runner:${incidentKey}`],
    );
    expect(Number(alarms.rows[0]?.count)).toBe(2);

    const recovered = await store.ingestExternalObservation(
      {
        ...observation,
        revision: 3,
        active: false,
        summary: "Team PR request row recovered",
        evidence: { field: "pull_request_url", recovered: true },
      },
      1,
    );
    expect(recovered).toMatchObject({
      admitted: true,
      alarmDerived: false,
      recoveryRecorded: true,
      alarmStatus: "resolved_awaiting_ack",
      finding: {
        id: first.finding.id,
        revision: 3,
        status: "resolved",
      },
    });
    const recovery = await pool.query<{ count: string }>(
      `SELECT count(*)::text AS count
       FROM fabric_external_recoveries
       WHERE source=$1 AND incident_key=$2 AND revision=3`,
      [observation.source, incidentKey],
    );
    expect(Number(recovery.rows[0]?.count)).toBe(1);
    const resolvedAlarms = await pool.query<{ status: string }>(
      `SELECT DISTINCT status
       FROM fabric_alarm_outbox
       WHERE incident_key=$1`,
      [`external:team-pr-runner:${incidentKey}`],
    );
    expect(resolvedAlarms.rows).toEqual([
      { status: "resolved_awaiting_ack" },
    ]);
    await store.acknowledgeFinding(first.finding.id, "integration-operator");
    const acknowledgedAlarms = await pool.query<{ status: string }>(
      `SELECT DISTINCT status
       FROM fabric_alarm_outbox
       WHERE incident_key=$1`,
      [`external:team-pr-runner:${incidentKey}`],
    );
    expect(acknowledgedAlarms.rows).toEqual([{ status: "acknowledged" }]);
  });

  it("enforces queue depth and provider concurrency transactionally", async () => {
    const namespace = `policy-${randomUUID()}`;
    const task = (idempotencyKey: string) => ({
      namespace,
      queue: "code",
      taskType: "example.run",
      idempotencyKey,
      payload: {},
      requiredCapabilities: ["test.run"],
      priority: 0,
    });
    await Promise.all([fabric.admit(task("one")), fabric.admit(task("two"))]);
    await expect(fabric.admit(task("three"))).rejects.toThrow(/max_queued 2/);

    const worker = async (name: string) =>
      fabric.registerWorker({
        bootstrapId: `integration-host.code.${name}-${randomUUID()}`,
        workerId: `${name}-${randomUUID()}`,
        hostId: "integration-host",
        queues: ["code"],
        capabilities: ["test.run"],
        maxConcurrency: 1,
        metadata: {},
      });
    const [left, right] = await Promise.all([worker("left"), worker("right")]);
    const [first, second] = await Promise.all([
      fabric.claim({
        workerId: left.workerId,
        registrationToken: left.registrationToken,
        queues: ["code"],
        capabilities: ["test.run"],
        waitMs: 0,
      }),
      fabric.claim({
        workerId: right.workerId,
        registrationToken: right.registrationToken,
        queues: ["code"],
        capabilities: ["test.run"],
        waitMs: 0,
      }),
    ]);
    expect([first, second].filter(Boolean)).toHaveLength(1);
  });

  it("records immutable worker sessions and exposes rich queue and run history", async () => {
    const workerId = `session-worker-${randomUUID()}`;
    const first = await fabric.registerWorker({
      bootstrapId: `integration-host.code.${workerId}`,
      workerId,
      hostId: "integration-host",
      queues: ["code"],
      capabilities: ["test.run"],
      maxConcurrency: 1,
      metadata: { revision: 1 },
    });
    const second = await fabric.registerWorker({
      bootstrapId: `integration-host.code.${workerId}`,
      workerId,
      hostId: "integration-host",
      queues: ["code"],
      capabilities: ["test.run"],
      maxConcurrency: 1,
      metadata: { revision: 2 },
    });
    expect(second.registrationToken).not.toBe(first.registrationToken);

    const admitted = await fabric.admit({
      namespace: "session_history",
      queue: "code",
      taskType: "example.run",
      idempotencyKey: `session-history-${randomUUID()}`,
      payload: {},
      requiredCapabilities: ["test.run"],
    });
    const assignment = await fabric.claim({
      workerId,
      registrationToken: second.registrationToken,
      queues: ["code"],
      capabilities: ["test.run"],
      waitMs: 0,
    });
    expect(assignment?.task.id).toBe(admitted.task.id);
    await fabric.ledger.complete(assignment!.attemptId, {
      workerId,
      leaseToken: assignment!.leaseToken,
      fabricEpoch: assignment!.fabricEpoch,
      result: { ok: true },
      effects: [],
    });

    const [worker] = await fabric.ledger.workerSnapshot();
    expect(worker?.currentSessionId).toBeTruthy();
    expect(worker?.sessionHistory).toHaveLength(2);
    expect(worker?.sessionHistory.map((session) => session.status)).toEqual([
      "active",
      "fenced",
    ]);
    expect(worker?.sessionHistory[1]?.endReason).toBe("re_registered");
    const [run] = await fabric.ledger.runSnapshot(10);
    expect(run).toMatchObject({
      taskId: admitted.task.id,
      status: "succeeded",
      lastErrorCode: null,
    });
    expect(run?.attempts[0]).toMatchObject({
      attemptId: assignment!.attemptId,
      workerId,
      status: "succeeded",
    });
    expect(run?.attempts[0]?.workerSessionId).toBe(worker?.currentSessionId);
    const [queue] = await fabric.ledger.queueSnapshot();
    expect(queue).toMatchObject({
      queue: "code",
      queued: 0,
      running: 0,
      completedLastHour: 1,
      throughputPerHour: 1,
    });
  });

  it("serializes host and namespace caps and lets bounded aging rescue old work", async () => {
    const { policy } = createTestPolicy((value) => {
      value.execution_fabric.admission.global_max_running = 2;
      value.execution_fabric.admission.provider_limits.test = 2;
      value.execution_fabric.admission.host_limits = { capped_host: 1 };
      value.execution_fabric.admission.namespace_limits = { capped_tenant: 1 };
      value.execution_fabric.scheduling = {
        priority_aging: {
          interval_seconds: 1,
          boost_per_interval: 1,
          max_boost: 100,
        },
        namespace_weights: { capped_tenant: 1, fresh_tenant: 1 },
      };
      value.execution_fabric.queues[0].concurrency.max_running = 2;
    });
    const bounded = new ExecutionFabric(
      new PostgresLedger(pool, 45),
      delivery,
      120,
      0,
      policy,
    );
    await bounded.ready();
    const old = await bounded.admit({
      namespace: "capped_tenant",
      queue: "code",
      taskType: "example.run",
      idempotencyKey: `old-${randomUUID()}`,
      payload: {},
      requiredCapabilities: ["test.run"],
      priority: 0,
    });
    await bounded.admit({
      namespace: "fresh_tenant",
      queue: "code",
      taskType: "example.run",
      idempotencyKey: `fresh-${randomUUID()}`,
      payload: {},
      requiredCapabilities: ["test.run"],
      priority: 10,
    });
    await pool.query(
      "UPDATE fabric_tasks SET created_at=now()-interval '20 seconds' WHERE id=$1",
      [old.task.id],
    );
    const register = (suffix: string) =>
      bounded.registerWorker({
        bootstrapId: `capped-host.code.${suffix}-${randomUUID()}`,
        workerId: `bounded-${suffix}-${randomUUID()}`,
        hostId: "capped_host",
        queues: ["code"],
        capabilities: ["test.run"],
        maxConcurrency: 1,
        metadata: {},
      });
    const [left, right] = await Promise.all([register("left"), register("right")]);
    const [leftClaim, rightClaim] = await Promise.all([
      bounded.claim({
        workerId: left.workerId,
        registrationToken: left.registrationToken,
        queues: ["code"],
        capabilities: ["test.run"],
        waitMs: 0,
      }),
      bounded.claim({
        workerId: right.workerId,
        registrationToken: right.registrationToken,
        queues: ["code"],
        capabilities: ["test.run"],
        waitMs: 0,
      }),
    ]);
    const claims = [leftClaim, rightClaim].filter(
      (claim): claim is NonNullable<typeof claim> => claim !== null,
    );
    expect(claims).toHaveLength(1);
    expect(claims[0]!.task.id).toBe(old.task.id);
  });

  it("advances leadership transactionally and fences the old host, workers, attempts, and effects", async () => {
    const oldLedger = new PostgresLedger(pool, 45, "genomesbox");
    const newLedger = new PostgresLedger(pool, 45, "bigmac");
    const lease = new Date(Date.now() + 60_000).toISOString();
    await oldLedger.activateLeadership({
      clusterId: "test-fabric",
      leaderHostId: "genomesbox",
      fabricEpoch: 1,
      receiptId: "status:epoch-1",
      fenceDigest: "1".repeat(64),
      leaseExpiresAt: lease,
      recoveryHoldUntil: null,
    });
    const namespace = `ha-${randomUUID()}`;
    const admitted = await oldLedger.admitTask(
      {
        namespace,
        queue: "code",
        taskType: "example.run",
        idempotencyKey: "epoch-one-task",
        payload: {},
        requiredCapabilities: ["test.run"],
        priority: 0,
        maxAttempts: 3,
        schedulingClass: "background",
        availableAt: new Date().toISOString(),
      },
      {
        configFingerprint: createTestPolicy().policy.snapshot().appliedFingerprint,
        queue: createTestPolicy().policy.queue("code"),
        pool: createTestPolicy().policy.pool("code_workers"),
      },
    );
      const registration = await oldLedger.registerWorker(
        {
          bootstrapId: `old-host.code.${randomUUID()}`,
          workerId: `old-${randomUUID()}`,
        hostId: "genomesbox",
        queues: ["code"],
        capabilities: ["test.run"],
        maxConcurrency: 1,
        metadata: {},
      },
      {
        configFingerprint: createTestPolicy().policy.snapshot().appliedFingerprint,
        pool: createTestPolicy().policy.pool("code_workers"),
      },
    );
    const assignment = await oldLedger.claim(
      {
        workerId: registration.workerId,
        registrationToken: registration.registrationToken,
        queues: ["code"],
        capabilities: ["test.run"],
        waitMs: 0,
      },
      {
        configFingerprint: createTestPolicy().policy.snapshot().appliedFingerprint,
        pool: createTestPolicy().policy.pool("code_workers"),
        queue: createTestPolicy().policy.queue("code"),
        globalMaxRunning: 10,
        providerMaxRunning: 10,
        reservedInteractiveSlots: 1,
        maxInteractiveRunning: 2,
        namespaceLimits: {},
        hostLimits: {},
        namespaceWeights: {},
        priorityAgingIntervalSeconds: 300,
        priorityAgingBoost: 1,
        priorityAgingMaxBoost: 100,
      },
    );
    expect(assignment?.task.id).toBe(admitted.task.id);

    await newLedger.activateLeadership({
      clusterId: "test-fabric",
      leaderHostId: "bigmac",
      fabricEpoch: 2,
      receiptId: "promotion-receipt-2",
      fenceDigest: "2".repeat(64),
      leaseExpiresAt: lease,
      recoveryHoldUntil: new Date(Date.now() + 30_000).toISOString(),
    });
    await expect(
      oldLedger.heartbeat(registration.workerId, {
        registrationToken: registration.registrationToken,
        activeAttemptIds: [assignment!.attemptId],
      }),
    ).rejects.toBeInstanceOf(FencedError);
    await expect(
      oldLedger.complete(assignment!.attemptId, {
        workerId: registration.workerId,
        leaseToken: assignment!.leaseToken,
        fabricEpoch: 1,
        result: {},
        effects: [],
      }),
    ).rejects.toBeInstanceOf(FencedError);
    const state = await newLedger.systemSnapshot();
    expect(state.fabricEpoch).toBe(2);
    expect(state.leaderHostId).toBe("bigmac");
    const task = await newLedger.getTask(admitted.task.id);
    expect(task?.status).toBe("queued");

    await expect(
      oldLedger.activateLeadership({
        clusterId: "test-fabric",
        leaderHostId: "genomesbox",
        fabricEpoch: 2,
        receiptId: "conflicting-receipt",
        fenceDigest: "3".repeat(64),
        leaseExpiresAt: lease,
        recoveryHoldUntil: null,
      }),
    ).rejects.toBeInstanceOf(FencedError);
  });
});
