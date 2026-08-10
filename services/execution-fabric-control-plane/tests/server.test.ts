import { randomUUID } from "node:crypto";
import { describe, expect, it, vi } from "vitest";
import type { Config } from "../src/config.js";
import type { TaskRecord } from "../src/contracts.js";
import type { DeliveryPort } from "../src/delivery.js";
import { ExecutionFabric } from "../src/fabric.js";
import { ConflictError, FencedError, type LedgerPort } from "../src/ledger.js";
import type { LeadershipGuard } from "../src/leadership.js";
import { buildServer } from "../src/server.js";
import { createTestPolicy } from "./policy-fixture.js";
import type { ArtifactStore } from "../src/artifacts.js";
import type { PostgresScheduler } from "../src/scheduler.js";
import type { PostgresReliabilityStore } from "../src/reliability.js";

const config: Config = {
  host: "127.0.0.1",
  port: 3180,
  hostId: "test-host",
  databaseUrl: "postgresql://localhost/test",
  valkeyUrl: "redis://localhost:6379",
  queuePrefix: "test",
  leaseSeconds: 120,
  workerTtlSeconds: 45,
  longPollMs: 0,
  reconcileIntervalMs: 10000,
  metricsPrefix: "test_fabric_",
  policyConfigPath: "/tmp/test-execution-fabric.yml",
  policySchemaPath: "/tmp/test-execution-fabric.schema.json",
  submitToken: "submit-token-0000000000000000000000",
  workerBootstrapCredentials: {
    "test-host.code.worker-a": {
      token: "worker-token-0000000000000000000000",
      workerId: "worker-a",
      hostId: "test-host",
      poolId: "code_workers",
      queues: ["code"],
      capabilities: ["test.run"],
      maxConcurrency: 1,
    },
  },
  apiToken: "api-token-000000000000000000000000",
  adminToken: "admin-token-0000000000000000000000",
  reliabilitySourceTokens: {
    "team-pr-runner": "team-pr-source-token-000000000000000",
    "losmon-mongo-outbox": "losmon-source-token-000000000000000",
  },
  effectConsumerCredentials: {
    "jira-projector": {
      token: "effect-consumer-token-000000000000000",
      source: "jira-projector",
      effectTypes: ["example.effect"],
    },
  },
  alarmDispatcherCredentials: {
    "bigmac-agentic-os-notifier": {
      token: "alarm-dispatcher-token-00000000000000",
      source: "agentic-os-notify",
    },
  },
  artifactStore: {
    endpoint: "http://minio:9000",
    region: "us-east-1",
    bucket: "test-artifacts",
    accessKeyId: "artifact-access-000000000000000000",
    secretAccessKey: "artifact-secret-000000000000000000",
    forcePathStyle: true,
    uploadTtlSeconds: 300,
    downloadTtlSeconds: 300,
    maxBytes: 10485760,
  },
  clusterId: "test-fabric",
  leadershipApiBase: "https://witness.example.test",
  leadershipToken: "leadership-token-00000000000000000000",
  leadershipCandidateToken:
    "leadership-candidate-token-0000000000000000",
  leadershipPublicKey:
    "-----BEGIN PUBLIC KEY-----\nMCowBQYDK2VwAyEA000000000000000000000000000000000000000=\n-----END PUBLIC KEY-----\n",
  leadershipRefreshMs: 10000,
  leadershipRecoveryHoldSeconds: 30,
  logLevel: "silent",
};

function fixture() {
  const task: TaskRecord = {
    id: randomUUID(),
    namespace: "test",
    queue: "code",
    taskType: "example.run",
    schedulingClass: "background",
    payload: {},
    requiredCapabilities: [],
    priority: 0,
    status: "queued",
    maxAttempts: 3,
    attemptCount: 0,
    availableAt: new Date().toISOString(),
    createdAt: new Date().toISOString(),
  };
  const ledger = {
    admitTask: vi.fn().mockResolvedValue({ task, admitted: true }),
    getTask: vi.fn().mockResolvedValue(task),
    taskIdForAttempt: vi.fn().mockResolvedValue(task.id),
    registerWorker: vi.fn(),
    heartbeat: vi.fn(),
    claim: vi.fn().mockResolvedValue(null),
    complete: vi.fn(),
    fail: vi.fn(),
    reconcileExpired: vi
      .fn()
      .mockResolvedValue({
        expiredRequeued: 0,
        expiredDeadLettered: 0,
        effectsRequeued: 0,
        effectsDeadLettered: 0,
      }),
    claimEffects: vi.fn().mockResolvedValue([]),
    deliverEffect: vi.fn().mockResolvedValue(undefined),
    failEffect: vi.fn().mockResolvedValue(undefined),
    listPublishable: vi.fn().mockResolvedValue([]),
    markPublished: vi.fn(),
    queueSnapshot: vi.fn().mockResolvedValue([]),
    workerSnapshot: vi.fn().mockResolvedValue([]),
    runSnapshot: vi.fn().mockResolvedValue([]),
    systemSnapshot: vi.fn().mockResolvedValue({
      fabricEpoch: 1,
      leaderHostId: "test-host",
      leaderLeaseExpiresAt: null,
      leadershipClusterId: "test-fabric",
      leadershipReceiptId: "status:test",
      leadershipFenceDigest: "a".repeat(64),
      leaderRecoveryHoldUntil: null,
      databasePolicyFingerprint: null,
      effects: {},
      eventSequence: 0,
    }),
    activatePolicy: vi.fn().mockResolvedValue(undefined),
    activatePolicyReload: vi.fn().mockImplementation(async (input) => ({
      schemaVersion: "execution-fabric-config-reload-receipt/v1",
      receiptId: randomUUID(),
      rotationId: input.rotationId,
      preparationTokenHash: input.preparationTokenHash,
      expectedCurrentFingerprint: input.expectedCurrentFingerprint,
      expectedCandidateFingerprint: input.expectedCandidateFingerprint,
      appliedFingerprint: input.expectedCandidateFingerprint,
      fabricEpoch: 1,
      hostId: "test-host",
      appliedAt: new Date().toISOString(),
    })),
    activateLeadership: vi.fn().mockResolvedValue(undefined),
    ping: vi.fn().mockResolvedValue(undefined),
  } satisfies LedgerPort;
  const delivery = {
    publish: vi.fn(),
    acknowledge: vi.fn(),
    waitForWork: vi.fn(),
    ping: vi.fn().mockResolvedValue(undefined),
    close: vi.fn(),
  } satisfies DeliveryPort;
  const { policy } = createTestPolicy();
  const leadership = {
    assertMutation: vi.fn(),
    assertTaskMutation: vi.fn(),
    assertEffectMutation: vi.fn(),
    assertSchedulerMutation: vi.fn(),
    authorizePolicyRotation: vi.fn().mockReturnValue({
      issuedAt: new Date().toISOString(),
      expiresAt: new Date(Date.now() + 60_000).toISOString(),
      expectedEpoch: 1,
    }),
    snapshot: vi.fn().mockReturnValue({ state: "active" }),
  } as unknown as LeadershipGuard;
  const fabric = new ExecutionFabric(
    ledger,
    delivery,
    120,
    0,
    policy,
    leadership,
  );
  const artifactId = randomUUID();
  const artifact = {
    artifactId,
    taskId: task.id,
    attemptId: randomUUID(),
    name: "run-report.json",
    contentType: "application/json",
    sha256: "a".repeat(64),
    sizeBytes: 123,
    status: "available" as const,
    uri: "s3://test-artifacts/run-report.json",
    createdAt: new Date().toISOString(),
    availableAt: new Date().toISOString(),
  };
  const artifacts = {
    initiate: vi.fn().mockResolvedValue({
      artifact: { ...artifact, status: "pending", uri: null, availableAt: null },
      alreadyAvailable: false,
      upload: {
        method: "PUT",
        url: "https://objects.example.test/upload",
        expiresAt: new Date().toISOString(),
        headers: {
          "content-type": "application/json",
          "content-length": "123",
          "x-amz-meta-sha256": "a".repeat(64),
        },
      },
    }),
    initiateRecovery: vi.fn().mockResolvedValue({
      artifact: { ...artifact, status: "pending", uri: null, availableAt: null },
      alreadyAvailable: false,
      upload: {
        method: "PUT",
        url: "https://objects.example.test/recovery-upload",
        expiresAt: new Date().toISOString(),
        headers: {
          "content-type": "application/json",
          "content-length": "123",
          "x-amz-meta-sha256": "a".repeat(64),
        },
      },
    }),
    finalize: vi.fn().mockResolvedValue(artifact),
    finalizeRecovery: vi.fn().mockResolvedValue(artifact),
    download: vi.fn().mockResolvedValue({
      artifact,
      downloadUrl: "https://objects.example.test/download",
      expiresAt: new Date().toISOString(),
    }),
    forTask: vi.fn().mockResolvedValue([artifact]),
    snapshot: vi.fn().mockResolvedValue({
      counts: { available: 1 },
      recent: [artifact],
      objectStore: {
        status: "healthy",
        bucket: "test-artifacts",
        checkedAt: new Date().toISOString(),
      },
    }),
    health: vi.fn().mockResolvedValue({
      status: "healthy",
      bucket: "test-artifacts",
      checkedAt: new Date().toISOString(),
    }),
  } as unknown as ArtifactStore;
  const scheduler = {
    snapshot: vi.fn().mockResolvedValue([]),
    upsert: vi.fn().mockImplementation(async (value) => value),
    setEnabled: vi.fn().mockResolvedValue(undefined),
  } as unknown as PostgresScheduler;
  const reliability = {
    snapshot: vi.fn().mockResolvedValue({
      schemaVersion: "execution-fabric-reliability-status/v1",
      findings: {},
      alarms: {},
      repairs: {},
      lastObservationAt: null,
      lastRepairAt: null,
    }),
    ingestExternalObservation: vi.fn().mockImplementation(
      async (observation: {
        source: string;
        incidentKey: string;
        revision: number;
        active: boolean;
        severity: string;
      }) => ({
        schemaVersion:
          "execution-fabric-reliability-observation-receipt/v1",
        admitted: true,
        idempotent: false,
        source: observation.source,
        incidentKey: observation.incidentKey,
        revision: observation.revision,
        alarmDerived: observation.active && observation.severity !== "info",
        recoveryRecorded: !observation.active,
        alarmStatus:
          observation.active ? null : "resolved_awaiting_ack",
        finding: { id: randomUUID() },
      }),
    ),
    claimAlarms: vi.fn().mockResolvedValue([]),
    deliverAlarm: vi.fn().mockResolvedValue(undefined),
    failAlarm: vi.fn().mockResolvedValue(undefined),
  } as unknown as PostgresReliabilityStore;
  return {
    server: buildServer(config, fabric, {
      artifacts,
      scheduler,
      reliability,
    }),
    ledger,
    delivery,
    artifacts,
    scheduler,
    reliability,
    task,
    fabric,
    leadership,
  };
}

describe("HTTP contract", () => {
  it("serves liveness and OpenAPI", async () => {
    const { server } = fixture();
    const health = await server.inject({ method: "GET", url: "/healthz" });
    expect(health.statusCode).toBe(200);
    const openapi = await server.inject({ method: "GET", url: "/openapi.json" });
    expect(openapi.json().openapi).toBe("3.1.0");
    expect(
      openapi.json().paths["/admin/config/reload"].post.requestBody.content[
        "application/json"
      ].schema.properties,
    ).toHaveProperty("operatorOverride");
    await server.close();
  });

  it("validates and admits a task", async () => {
    const { server, ledger, delivery } = fixture();
    const response = await server.inject({
      method: "POST",
      url: "/api/v1/tasks",
      headers: { authorization: `Bearer ${config.submitToken}` },
      payload: {
        namespace: "test",
        queue: "code",
        taskType: "example.run",
        idempotencyKey: "task-1",
      },
    });
    expect(response.statusCode).toBe(201);
    expect(ledger.admitTask).toHaveBeenCalledOnce();
    expect(delivery.publish).toHaveBeenCalledOnce();
    await server.close();
  });

  it("binds worker bootstrap credentials to one durable identity", async () => {
    const { server, ledger } = fixture();
    const registration = {
      bootstrapId: "test-host.code.worker-a",
      workerId: "worker-a",
      hostId: "test-host",
      queues: ["code"],
      capabilities: ["test.run"],
      maxConcurrency: 1,
      metadata: {},
    };
    const admitted = await server.inject({
      method: "POST",
      url: "/api/v1/workers/register",
      headers: {
        authorization:
          "Bearer worker-token-0000000000000000000000",
      },
      payload: registration,
    });
    expect(admitted.statusCode).toBe(200);
    expect(ledger.registerWorker).toHaveBeenCalledWith(
      registration,
      expect.objectContaining({
        pool: expect.objectContaining({ id: "code_workers" }),
      }),
    );

    const impersonation = await server.inject({
      method: "POST",
      url: "/api/v1/workers/register",
      headers: {
        authorization:
          "Bearer worker-token-0000000000000000000000",
      },
      payload: {
        ...registration,
        workerId: "worker-b",
      },
    });
    expect(impersonation.statusCode).toBe(409);
    expect(impersonation.json()).toMatchObject({
      error: "fenced",
      message: expect.stringMatching(/not bound to this durable worker/),
    });
    expect(ledger.registerWorker).toHaveBeenCalledOnce();
    await server.close();
  });

  it("prepares, verifies, and exposes portable run artifacts", async () => {
    const { server, artifacts, task } = fixture();
    const attemptId = randomUUID();
    const workerId = "worker-a";
    const leaseToken = randomUUID();
    const initiated = await server.inject({
      method: "POST",
      url: "/api/v1/artifacts/uploads",
      headers: { authorization: `Bearer ${leaseToken}` },
      payload: {
        taskId: task.id,
        attemptId,
        workerId,
        leaseToken,
        fabricEpoch: 1,
        name: "run-report.json",
        contentType: "application/json",
        sha256: "a".repeat(64),
        sizeBytes: 123,
      },
    });
    expect(initiated.statusCode).toBe(201);
    expect(artifacts.initiate).toHaveBeenCalledOnce();
    const artifactId = initiated.json().artifact.artifactId;
    const finalized = await server.inject({
      method: "POST",
      url: `/api/v1/artifacts/${artifactId}/finalize`,
      headers: { authorization: `Bearer ${leaseToken}` },
      payload: {
        taskId: task.id,
        attemptId,
        workerId,
        leaseToken,
        fabricEpoch: 1,
      },
    });
    expect(finalized.statusCode).toBe(200);
    const detail = await server.inject({
      method: "GET",
      url: `/api/v1/tasks/${task.id}`,
      headers: { authorization: `Bearer ${config.apiToken}` },
    });
    expect(detail.json().artifacts[0].uri).toMatch(/^s3:/);

    const registrationToken = randomUUID();
    const attemptRecoveryToken = randomUUID();
    const recovered = await server.inject({
      method: "POST",
      url: "/api/v1/artifacts/recovery-uploads",
      headers: { authorization: `Bearer ${registrationToken}` },
      payload: {
        taskId: task.id,
        attemptId,
        workerId,
        registrationToken,
        attemptRecoveryToken,
        fabricEpoch: 1,
        name: "run-report.json",
        contentType: "application/json",
        sha256: "a".repeat(64),
        sizeBytes: 123,
      },
    });
    expect(recovered.statusCode).toBe(201);
    const recoveryFinalized = await server.inject({
      method: "POST",
      url: `/api/v1/artifacts/${artifactId}/recovery-finalize`,
      headers: { authorization: `Bearer ${registrationToken}` },
      payload: {
        taskId: task.id,
        attemptId,
        workerId,
        registrationToken,
        attemptRecoveryToken,
        fabricEpoch: 1,
      },
    });
    expect(recoveryFinalized.statusCode).toBe(200);
    await server.close();
  });

  it("rejects unauthenticated repair", async () => {
    const { server } = fixture();
    const response = await server.inject({
      method: "POST",
      url: "/api/v1/admin/reconcile",
    });
    expect(response.statusCode).toBe(401);
    await server.close();
  });

  it("keeps delivery reconciliation read-only unless apply is explicit", async () => {
    const { server, delivery, ledger, task } = fixture();
    vi.mocked(ledger.listPublishable).mockResolvedValue([task]);

    const response = await server.inject({
      method: "POST",
      url: "/api/v1/admin/delivery-reconciliation",
      headers: { authorization: `Bearer ${config.adminToken}` },
    });

    expect(response.statusCode).toBe(200);
    expect(response.json()).toMatchObject({
      dryRun: true,
      eligible: 1,
      deliveriesPublished: 0,
      taskIds: [task.id],
    });
    expect(delivery.publish).not.toHaveBeenCalled();
    expect(ledger.markPublished).not.toHaveBeenCalled();
    await server.close();
  });

  it("rejects every API and metrics route without its exact scoped token", async () => {
    const { server } = fixture();
    const taskId = randomUUID();
    const attemptId = randomUUID();
    const effectId = randomUUID();
    for (const request of [
      { method: "POST" as const, url: "/api/v1/tasks", scope: "submit" },
      {
        method: "GET" as const,
        url: `/api/v1/tasks/${taskId}`,
        scope: "observer",
      },
      {
        method: "POST" as const,
        url: "/api/v1/workers/register",
        scope: "worker-bootstrap",
      },
      {
        method: "POST" as const,
        url: "/api/v1/workers/worker-a/heartbeat",
        scope: "session",
      },
      {
        method: "POST" as const,
        url: "/api/v1/assignments/claim",
        scope: "session",
      },
      {
        method: "POST" as const,
        url: `/api/v1/attempts/${attemptId}/complete`,
        scope: "session",
      },
      {
        method: "POST" as const,
        url: `/api/v1/attempts/${attemptId}/fail`,
        scope: "session",
      },
      {
        method: "POST" as const,
        url: "/api/v1/effects/claim",
        scope: "consumer",
      },
      {
        method: "POST" as const,
        url: `/api/v1/effects/${effectId}/deliver`,
        scope: "session",
      },
      {
        method: "POST" as const,
        url: `/api/v1/effects/${effectId}/fail`,
        scope: "session",
      },
      {
        method: "GET" as const,
        url: "/api/v1/snapshots/queues",
        scope: "observer",
      },
      {
        method: "GET" as const,
        url: "/api/v1/snapshots/workers",
        scope: "observer",
      },
      {
        method: "GET" as const,
        url: "/api/v1/snapshots/runs",
        scope: "observer",
      },
      {
        method: "GET" as const,
        url: "/api/v1/snapshots/reliability",
        scope: "observer",
      },
      {
        method: "POST" as const,
        url: "/api/v1/alarms/claim",
        scope: "consumer",
      },
      {
        method: "POST" as const,
        url: "/api/v1/reliability/observations",
        scope: "reliability-source",
      },
      {
        method: "POST" as const,
        url: `/api/v1/alarms/${effectId}/deliver`,
        scope: "session",
      },
      {
        method: "POST" as const,
        url: `/api/v1/alarms/${effectId}/fail`,
        scope: "session",
      },
      { method: "GET" as const, url: "/api/v1/status", scope: "observer" },
      { method: "GET" as const, url: "/metrics", scope: "observer" },
      {
        method: "POST" as const,
        url: "/api/v1/admin/reconcile",
        scope: "admin",
      },
      {
        method: "POST" as const,
        url: "/api/v1/admin/delivery-reconciliation",
        scope: "admin",
      },
      {
        method: "POST" as const,
        url: "/api/v1/admin/config/reload",
        scope: "admin",
      },
      {
        method: "POST" as const,
        url: `/api/v1/admin/findings/${effectId}/acknowledge`,
        scope: "admin",
      },
      {
        method: "POST" as const,
        url: `/api/v1/admin/effects/${effectId}/replay`,
        scope: "admin",
      },
      {
        method: "POST" as const,
        url: `/api/v1/admin/tasks/${taskId}/cancel`,
        scope: "admin",
      },
      {
        method: "POST" as const,
        url: `/api/v1/admin/tasks/${taskId}/requeue`,
        scope: "admin",
      },
      {
        method: "POST" as const,
        url: "/api/v1/admin/queues/code/drain",
        scope: "admin",
      },
    ]) {
      const response = await server.inject({
        method: request.method,
        url: request.url,
      });
      expect(response.statusCode).toBe(401);
      if (request.scope !== "session") {
        expect(response.headers["www-authenticate"]).toContain(
          `scope="${request.scope}"`,
        );
      }
    }

    for (const authorization of [
      `Bearer ${config.apiToken} extra`,
      `Basic ${config.apiToken}`,
      "Bearer wrong-token",
    ]) {
      const response = await server.inject({
        method: "GET",
        url: "/api/v1/status",
        headers: { authorization },
      });
      expect(response.statusCode).toBe(401);
    }
    await server.close();
  });

  it("keeps API and admin credentials separate", async () => {
    const { server } = fixture();
    const apiAsAdmin = await server.inject({
      method: "POST",
      url: "/api/v1/admin/reconcile",
      headers: {
        authorization:
          "Bearer effect-consumer-token-000000000000000",
      },
    });
    expect(apiAsAdmin.statusCode).toBe(401);

    const adminAsApi = await server.inject({
      method: "GET",
      url: "/api/v1/snapshots/queues",
      headers: { authorization: `Bearer ${config.adminToken}` },
    });
    expect(adminAsApi.statusCode).toBe(401);

    const admin = await server.inject({
      method: "POST",
      url: "/api/v1/admin/reconcile",
      headers: { authorization: `Bearer ${config.adminToken}` },
    });
    expect(admin.statusCode).toBe(200);
    await server.close();
  });

  it("admits only source-scoped external reliability observations", async () => {
    const { server, reliability } = fixture();
    const payload = {
      source: "team-pr-runner",
      incidentKey: "malformed-row:notion-page-1",
      revision: 1,
      active: true,
      severity: "warning",
      code: "malformed_request_row",
      summary: "Team PR request row is malformed",
      evidence: { field: "pull_request_url" },
      affected: { kind: "notion_page", id: "notion-page-1" },
      runbook: { ref: "execution-fabric/team-pr-malformed-row" },
      observedAt: "2026-07-24T20:00:00.000Z",
    };
    const wrongSource = await server.inject({
      method: "POST",
      url: "/api/v1/reliability/observations",
      headers: {
        authorization: `Bearer ${config.reliabilitySourceTokens["losmon-mongo-outbox"]}`,
      },
      payload,
    });
    expect(wrongSource.statusCode).toBe(401);
    expect(reliability.ingestExternalObservation).not.toHaveBeenCalled();

    const admitted = await server.inject({
      method: "POST",
      url: "/api/v1/reliability/observations",
      headers: {
        authorization: `Bearer ${config.reliabilitySourceTokens["team-pr-runner"]}`,
      },
      payload,
    });
    expect(admitted.statusCode).toBe(201);
    expect(reliability.ingestExternalObservation).toHaveBeenCalledWith(
      payload,
      1,
    );
    await server.close();
  });

  it("returns 204 when no assignment is available", async () => {
    const { server } = fixture();
    const registrationToken = randomUUID();
    const response = await server.inject({
      method: "POST",
      url: "/api/v1/assignments/claim",
      headers: { authorization: `Bearer ${registrationToken}` },
      payload: {
        workerId: "worker-a",
        registrationToken,
        queues: ["code"],
        capabilities: ["test.run"],
      },
    });
    expect(response.statusCode).toBe(204);
    await server.close();
  });

  it("requires effect consumers to declare owned effect types", async () => {
    const { server, ledger } = fixture();
    const unfiltered = await server.inject({
      method: "POST",
      url: "/api/v1/effects/claim",
      headers: { authorization: `Bearer ${config.apiToken}` },
      payload: { consumerId: "unsafe-global-consumer", limit: 10 },
    });
    expect(unfiltered.statusCode).toBe(400);
    expect(ledger.claimEffects).not.toHaveBeenCalled();

    const filtered = await server.inject({
      method: "POST",
      url: "/api/v1/effects/claim",
      headers: {
        authorization:
          "Bearer effect-consumer-token-000000000000000",
      },
      payload: {
        consumerId: "jira-projector",
        source: "jira-projector",
        effectTypes: ["example.effect"],
        limit: 10,
      },
    });
    expect(filtered.statusCode).toBe(200);
    expect(ledger.claimEffects).toHaveBeenCalledWith(
      {
        consumerId: "jira-projector",
        source: "jira-projector",
        effectTypes: ["example.effect"],
        limit: 10,
      },
      config.leaseSeconds,
    );
    await server.close();
  });

  it("keeps observers read-only and binds claims to consumer identity and source", async () => {
    const { server, ledger, reliability } = fixture();
    for (const payload of [
      {
        consumerId: "jira-projector",
        source: "jira-projector",
        effectTypes: ["example.effect"],
      },
      {
        consumerId: "jira-projector",
        source: "forged-source",
        effectTypes: ["example.effect"],
      },
      {
        consumerId: "jira-projector",
        source: "jira-projector",
        effectTypes: ["admin.effect"],
      },
    ]) {
      const response = await server.inject({
        method: "POST",
        url: "/api/v1/effects/claim",
        headers: {
          authorization: `Bearer ${
            payload.source === "jira-projector" &&
            payload.effectTypes[0] === "example.effect"
              ? config.apiToken
              : config.effectConsumerCredentials["jira-projector"]!.token
          }`,
        },
        payload,
      });
      expect(response.statusCode).toBe(409);
    }
    expect(ledger.claimEffects).not.toHaveBeenCalled();

    const alarm = await server.inject({
      method: "POST",
      url: "/api/v1/alarms/claim",
      headers: { authorization: `Bearer ${config.apiToken}` },
      payload: {
        consumerId: "bigmac-agentic-os-notifier",
        source: "agentic-os-notify",
        limit: 10,
      },
    });
    expect(alarm.statusCode).toBe(409);
    expect(reliability.claimAlarms).not.toHaveBeenCalled();
    await server.close();
  });

  it("returns one authenticated versioned operator status", async () => {
    const { server } = fixture();
    const response = await server.inject({
      method: "GET",
      url: "/api/v1/status?limit=25",
      headers: { authorization: `Bearer ${config.apiToken}` },
    });
    expect(response.statusCode).toBe(200);
    expect(response.json()).toMatchObject({
      schemaVersion: "agentic-os-execution-fabric-status/v1",
      config: {
        state: "applied",
        appliedFingerprint: expect.stringMatching(/^[0-9a-f]{64}$/),
      },
      controlPlane: { activeHost: "test-host", fabricEpoch: 1 },
      effects: {},
      healing: { status: "healthy" },
      alarms: [],
      queues: [
        {
          queue: "code",
          workerPool: "code_workers",
          maxRunning: 1,
          maxQueued: 2,
        },
      ],
    });
    await server.close();
  });

  it("keeps config reload on the admin credential", async () => {
    const { server, ledger, fabric, leadership } = fixture();
    const fingerprint = fabric.policy.snapshot().appliedFingerprint;
    const rotationId = randomUUID();
    const preparationToken = "cpr1.payload.signature";
    const denied = await server.inject({
      method: "POST",
      url: "/api/v1/admin/config/reload",
      headers: { authorization: `Bearer ${config.apiToken}` },
    });
    expect(denied.statusCode).toBe(401);
    const unprepared = await server.inject({
      method: "POST",
      url: "/api/v1/admin/config/reload",
      headers: { authorization: `Bearer ${config.adminToken}` },
      payload: {
        expectedCurrentFingerprint: fingerprint,
        expectedCandidateFingerprint: fingerprint,
      },
    });
    expect(unprepared.statusCode).toBe(400);
    expect(ledger.activatePolicyReload).not.toHaveBeenCalled();
    const applied = await server.inject({
      method: "POST",
      url: "/api/v1/admin/config/reload",
      headers: { authorization: `Bearer ${config.adminToken}` },
      payload: {
        rotationId,
        preparationToken,
        expectedCurrentFingerprint: fingerprint,
        expectedCandidateFingerprint: fingerprint,
      },
    });
    expect(applied.statusCode).toBe(200);
    expect(applied.json().lastReloadStatus).toBe("succeeded");
    expect(applied.json().appliedFingerprint).toBe(fingerprint);
    expect(applied.json().receipt).toMatchObject({
      schemaVersion: "execution-fabric-config-reload-receipt/v1",
      expectedCurrentFingerprint: fingerprint,
      expectedCandidateFingerprint: fingerprint,
      appliedFingerprint: fingerprint,
      rotationId,
    });
    expect(ledger.activatePolicyReload).toHaveBeenCalledOnce();
    expect(ledger.activatePolicyReload).toHaveBeenCalledWith({
      rotationId,
      preparationTokenHash:
        "0d1b4f4f14b47a69d41311d57c0ec31583804d173d4a930ed16adf63a1ead8b1",
      authorizationIssuedAt: expect.any(String),
      authorizationExpiresAt: expect.any(String),
      expectedEpoch: 1,
      expectedCurrentFingerprint: fingerprint,
      expectedCandidateFingerprint: fingerprint,
    });
    expect(leadership.authorizePolicyRotation).toHaveBeenCalledWith({
      rotationId,
      preparationToken,
      expectedCurrentDigest: fingerprint,
      candidateDigest: fingerprint,
    });

    const stale = await server.inject({
      method: "POST",
      url: "/api/v1/admin/config/reload",
      headers: { authorization: `Bearer ${config.adminToken}` },
      payload: {
        rotationId: randomUUID(),
        preparationToken,
        expectedCurrentFingerprint: "0".repeat(64),
        expectedCandidateFingerprint: fingerprint,
      },
    });
    expect(stale.statusCode).toBe(409);
    expect(ledger.activatePolicyReload).toHaveBeenCalledOnce();
    await server.close();
  });

  it("emits durable critical invocation and outcome alerts for a signed standalone override", async () => {
    const { server, ledger, reliability, fabric, leadership } = fixture();
    const fingerprint = fabric.policy.snapshot().appliedFingerprint;
    const operatorOverride = {
      actor: "operator-1",
      reason: "restore fenced standalone policy reload",
      approvalReference: "AGE-161",
      maintenanceWindow: {
        startsAt: new Date(Date.now() - 30_000).toISOString(),
        endsAt: new Date(Date.now() + 60_000).toISOString(),
      },
    };
    (leadership.authorizePolicyRotation as ReturnType<typeof vi.fn>).mockReturnValue({
      issuedAt: new Date().toISOString(),
      expiresAt: operatorOverride.maintenanceWindow.endsAt,
      expectedEpoch: 1,
      operatorOverride,
    });
    const response = await server.inject({
      method: "POST",
      url: "/api/v1/admin/config/reload",
      headers: { authorization: `Bearer ${config.adminToken}` },
      payload: {
        rotationId: randomUUID(),
        preparationToken: "cpr1.payload.signature",
        expectedCurrentFingerprint: fingerprint,
        expectedCandidateFingerprint: fingerprint,
        operatorOverride,
      },
    });
    expect(response.statusCode).toBe(200);
    expect(response.json().alerts).toMatchObject({
      invocation: { alarmDerived: true },
      outcome: { alarmDerived: true },
    });
    expect(reliability.ingestExternalObservation).toHaveBeenCalledTimes(2);
    expect(reliability.ingestExternalObservation).toHaveBeenNthCalledWith(
      1,
      expect.objectContaining({
        source: "control-plane-policy-override",
        code: "standalone_policy_override_invoked",
        severity: "critical",
      }),
      1,
    );
    expect(reliability.ingestExternalObservation).toHaveBeenNthCalledWith(
      2,
      expect.objectContaining({
        code: "standalone_policy_override_succeeded",
        severity: "critical",
      }),
      1,
    );
    expect(ledger.activatePolicyReload).toHaveBeenCalledWith(
      expect.objectContaining({ operatorOverride }),
    );
    await server.close();
  });

  it("replays a same-rotation override after a pre-commit failure but fences a changed envelope", async () => {
    const { server, ledger, reliability, fabric, leadership } = fixture();
    const fingerprint = fabric.policy.snapshot().appliedFingerprint;
    const rotationId = randomUUID();
    const operatorOverride = {
      actor: "operator:primary",
      reason: "retry a fenced standalone policy reload",
      approvalReference: "AGE-161",
      maintenanceWindow: {
        startsAt: new Date(Date.now() - 30_000).toISOString(),
        endsAt: new Date(Date.now() + 60_000).toISOString(),
      },
    };
    (leadership.authorizePolicyRotation as ReturnType<typeof vi.fn>).mockReturnValue({
      issuedAt: new Date().toISOString(),
      expiresAt: operatorOverride.maintenanceWindow.endsAt,
      expectedEpoch: 1,
      operatorOverride,
    });
    const seenObservations = new Map<string, string>();
    (reliability.ingestExternalObservation as ReturnType<typeof vi.fn>).mockImplementation(
      async (observation: {
        source: string;
        incidentKey: string;
        revision: number;
        active: boolean;
        severity: string;
      }) => {
        const key = `${observation.source}:${observation.incidentKey}:${observation.revision}`;
        const canonical = JSON.stringify(observation);
        const previous = seenObservations.get(key);
        if (previous && previous !== canonical) {
          throw new ConflictError(
            "reliability observation revision was already used with different content",
          );
        }
        seenObservations.set(key, canonical);
        return {
          schemaVersion: "execution-fabric-reliability-observation-receipt/v1",
          admitted: !previous,
          idempotent: Boolean(previous),
          source: observation.source,
          incidentKey: observation.incidentKey,
          revision: observation.revision,
          alarmDerived: observation.active && observation.severity !== "info",
          recoveryRecorded: !observation.active,
          alarmStatus: observation.active ? null : "resolved_awaiting_ack",
          finding: { id: randomUUID() },
        };
      },
    );
    (ledger.activatePolicyReload as ReturnType<typeof vi.fn>).mockRejectedValueOnce(
      new FencedError("injected pre-commit failure"),
    );
    const payload = {
      rotationId,
      preparationToken: "cpr1.payload.signature",
      expectedCurrentFingerprint: fingerprint,
      expectedCandidateFingerprint: fingerprint,
      operatorOverride,
    };

    const first = await server.inject({
      method: "POST",
      url: "/api/v1/admin/config/reload",
      headers: { authorization: `Bearer ${config.adminToken}` },
      payload,
    });
    expect(first.statusCode).toBe(409);

    const retry = await server.inject({
      method: "POST",
      url: "/api/v1/admin/config/reload",
      headers: { authorization: `Bearer ${config.adminToken}` },
      payload,
    });
    expect(retry.statusCode).toBe(200);
    expect(retry.json().alerts.invocation).toMatchObject({ idempotent: true });
    expect(ledger.activatePolicyReload).toHaveBeenCalledTimes(2);

    const changedEnvelope = await server.inject({
      method: "POST",
      url: "/api/v1/admin/config/reload",
      headers: { authorization: `Bearer ${config.adminToken}` },
      payload: {
        ...payload,
        operatorOverride: { ...operatorOverride, reason: "different signed reason" },
      },
    });
    expect(changedEnvelope.statusCode).toBe(409);
    expect(ledger.activatePolicyReload).toHaveBeenCalledTimes(2);
    await server.close();
  });

  it("does not report a committed override as failed when its outcome alert errors", async () => {
    const { server, ledger, reliability, fabric, leadership } = fixture();
    const fingerprint = fabric.policy.snapshot().appliedFingerprint;
    const operatorOverride = {
      actor: "operator-1",
      reason: "confirm applied outcome handling",
      approvalReference: "AGE-161",
      maintenanceWindow: {
        startsAt: new Date(Date.now() - 30_000).toISOString(),
        endsAt: new Date(Date.now() + 60_000).toISOString(),
      },
    };
    (leadership.authorizePolicyRotation as ReturnType<typeof vi.fn>).mockReturnValue({
      issuedAt: new Date().toISOString(),
      expiresAt: operatorOverride.maintenanceWindow.endsAt,
      expectedEpoch: 1,
      operatorOverride,
    });
    (reliability.ingestExternalObservation as ReturnType<typeof vi.fn>)
      .mockResolvedValueOnce({
        admitted: true,
        idempotent: false,
        alarmDerived: true,
      })
      .mockRejectedValueOnce(new Error("outcome alert unavailable"));

    const response = await server.inject({
      method: "POST",
      url: "/api/v1/admin/config/reload",
      headers: { authorization: `Bearer ${config.adminToken}` },
      payload: {
        rotationId: randomUUID(),
        preparationToken: "cpr1.payload.signature",
        expectedCurrentFingerprint: fingerprint,
        expectedCandidateFingerprint: fingerprint,
        operatorOverride,
      },
    });
    expect(response.statusCode).toBe(500);
    expect(ledger.activatePolicyReload).toHaveBeenCalledOnce();
    expect(reliability.ingestExternalObservation).toHaveBeenCalledTimes(2);
    expect(reliability.ingestExternalObservation).toHaveBeenLastCalledWith(
      expect.objectContaining({ code: "standalone_policy_override_succeeded" }),
      1,
    );
    await server.close();
  });

  it("exposes scheduler visibility and keeps schedule mutations admin-scoped", async () => {
    const { server, scheduler } = fixture();
    const snapshot = await server.inject({
      method: "GET",
      url: "/api/v1/snapshots/schedules",
      headers: { authorization: `Bearer ${config.apiToken}` },
    });
    expect(snapshot.statusCode).toBe(200);
    expect(scheduler.snapshot).toHaveBeenCalledWith(200);

    const upsert = await server.inject({
      method: "PUT",
      url: "/api/v1/admin/schedules/nightly-health",
      headers: { authorization: `Bearer ${config.adminToken}` },
      payload: {
        namespace: "test",
        queue: "code",
        taskType: "example.run",
        payload: {},
        requiredCapabilities: [],
        priority: 0,
        maxAttempts: 4,
        intervalSeconds: 300,
        nextOccurrenceAt: "2026-07-24T12:00:00Z",
        enabled: true,
      },
    });
    expect(upsert.statusCode).toBe(200);
    expect(scheduler.upsert).toHaveBeenCalledWith(
      expect.objectContaining({ id: "nightly-health", intervalSeconds: 300 }),
    );

    const toggle = await server.inject({
      method: "PATCH",
      url: "/api/v1/admin/schedules/nightly-health",
      headers: { authorization: `Bearer ${config.adminToken}` },
      payload: { enabled: false },
    });
    expect(toggle.statusCode).toBe(204);
    expect(scheduler.setEnabled).toHaveBeenCalledWith("nightly-health", false);
    await server.close();
  });
});
