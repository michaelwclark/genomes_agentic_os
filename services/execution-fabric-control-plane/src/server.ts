import { timingSafeEqual } from "node:crypto";
import Fastify, { type FastifyInstance } from "fastify";
import { z } from "zod";
import type { Config } from "./config.js";
import {
  artifactFinalizeSchema,
  artifactRecoveryFinalizeSchema,
  artifactRecoveryUploadSchema,
  artifactUploadSchema,
  attemptCompletionSchema,
  attemptFailureSchema,
  claimSchema,
  configReloadSchema,
  deliveryReconciliationSchema,
  effectClaimSchema,
  effectDeliverySchema,
  effectFailureSchema,
  reliabilityObservationSchema,
  scheduleUpsertSchema,
  taskAdmissionSchema,
  type PolicyReloadOperatorOverride,
  type ReliabilityObservation,
  workerHeartbeatSchema,
  workerRegistrationSchema,
} from "./contracts.js";
import type { ArtifactStore } from "./artifacts.js";
import { ExecutionFabric } from "./fabric.js";
import {
  ConflictError,
  FencedError,
  NotFoundError,
} from "./ledger.js";
import { createMetrics } from "./metrics.js";
import { openApiDocument } from "./openapi.js";
import { PolicyError } from "./policy.js";
import { LeadershipFencedError } from "./leadership.js";
import type { PostgresReliabilityStore } from "./reliability.js";
import type { PostgresScheduler } from "./scheduler.js";

const uuidParam = z.object({ taskId: z.string().uuid() });
const workerParam = z.object({ workerId: z.string().min(1).max(128) });
const attemptParam = z.object({ attemptId: z.string().uuid() });
const effectParam = z.object({ effectId: z.string().uuid() });
const findingParam = z.object({ findingId: z.string().uuid() });
const alarmParam = z.object({ alarmId: z.string().uuid() });
const artifactParam = z.object({ artifactId: z.string().uuid() });
const scheduleParam = z.object({
  scheduleId: z.string().min(1).max(128).regex(/^[a-zA-Z0-9._:-]+$/),
});
const scheduleToggleSchema = z.object({ enabled: z.boolean() });
const queueParam = z.object({
  queue: z.string().min(1).max(128).regex(/^[a-zA-Z0-9._:-]+$/),
});
const operatorActionSchema = z.object({
  actor: z.string().min(1).max(128),
  idempotencyKey: z.string().min(1).max(512),
});
const alarmClaimSchema = z.object({
  consumerId: z.string().min(1).max(128),
  source: z.string().min(1).max(128),
  limit: z.number().int().min(1).max(100).default(10),
});
const alarmDeliverySchema = z.object({
  consumerId: z.string().min(1).max(128),
  claimToken: z.string().uuid(),
  fabricEpoch: z.number().int().nonnegative(),
  deliveryReceipt: z.record(z.unknown()).default({}),
});
const alarmFailureSchema = z.object({
  consumerId: z.string().min(1).max(128),
  claimToken: z.string().uuid(),
  fabricEpoch: z.number().int().nonnegative(),
  errorSummary: z.string().min(1).max(2048),
});

function authorized(actual: string | undefined, expected: string | undefined): boolean {
  if (!expected || !actual) return false;
  const actualBuffer = Buffer.from(actual);
  const expectedBuffer = Buffer.from(expected);
  return (
    actualBuffer.length === expectedBuffer.length &&
    timingSafeEqual(actualBuffer, expectedBuffer)
  );
}

function policyOverrideObservation(input: {
  rotationId: string;
  override: PolicyReloadOperatorOverride;
  phase: "invoked" | "succeeded" | "failed";
  fabricEpoch: number;
  expectedCurrentFingerprint: string;
  expectedCandidateFingerprint: string;
  errorSummary?: string;
}): ReliabilityObservation {
  const phaseSummary =
    input.phase === "invoked"
      ? "Standalone policy override invoked; signed maintenance authorization is being checked."
      : input.phase === "succeeded"
        ? "Standalone policy override committed; witness commit and control-plane readback are required."
        : "Standalone policy override failed closed before a complete outcome could be confirmed.";
  return {
    source: "control-plane-policy-override",
    incidentKey: `policy-rotation:${input.rotationId}:${input.phase}`,
    revision: 1,
    active: true,
    severity: "critical",
    code: `standalone_policy_override_${input.phase}`,
    summary: phaseSummary,
    evidence: {
      rotationId: input.rotationId,
      actor: input.override.actor,
      reason: input.override.reason,
      approvalReference: input.override.approvalReference,
      maintenanceWindow: input.override.maintenanceWindow,
      expectedCurrentFingerprint: input.expectedCurrentFingerprint,
      expectedCandidateFingerprint: input.expectedCandidateFingerprint,
      fabricEpoch: input.fabricEpoch,
      ...(input.errorSummary ? { errorSummary: input.errorSummary } : {}),
    },
    affected: { kind: "policy_rotation", id: input.rotationId },
    runbook: { ref: "installers/execution-fabric/bin/rotate-policy.sh" },
    // A resumed rotation reuses its signed override envelope.  Keep the
    // pre-commit observation canonical so the reliability ledger can return
    // its idempotent receipt before the policy-reload ledger is replayed.
    observedAt:
      input.phase === "invoked"
        ? input.override.maintenanceWindow.startsAt
        : new Date().toISOString(),
  };
}

function bearerToken(authorization: string | undefined): string | undefined {
  const match = authorization?.match(/^Bearer ([^\s]+)$/i);
  return match?.[1];
}

function requireSessionBearer(
  authorization: string | undefined,
  expected: string,
): void {
  if (!authorized(bearerToken(authorization), expected)) {
    throw new FencedError("request bearer is not bound to this worker or claim");
  }
}

function requireEffectConsumer(
  config: Config,
  authorization: string | undefined,
  input: z.infer<typeof effectClaimSchema>,
): void {
  const credential = config.effectConsumerCredentials[input.consumerId];
  const requested = new Set(input.effectTypes);
  if (
    !credential ||
    !authorized(bearerToken(authorization), credential.token) ||
    credential.source !== input.source ||
    [...requested].some((effectType) => !credential.effectTypes.includes(effectType))
  ) {
    throw new FencedError(
      "effect consumer bearer is not bound to this consumer, source, and effect type set",
    );
  }
}

function requireWorkerBootstrap(
  config: Config,
  authorization: string | undefined,
  input: z.infer<typeof workerRegistrationSchema>,
): Config["workerBootstrapCredentials"][string] {
  const credential = config.workerBootstrapCredentials[input.bootstrapId];
  if (
    !credential ||
    !authorized(bearerToken(authorization), credential.token) ||
    credential.workerId !== input.workerId ||
    credential.hostId !== input.hostId ||
    credential.queues.length !== input.queues.length ||
    credential.queues.some((queue) => !input.queues.includes(queue)) ||
    credential.capabilities.length !== input.capabilities.length ||
    credential.capabilities.some(
      (capability) => !input.capabilities.includes(capability),
    ) ||
    credential.maxConcurrency !== input.maxConcurrency
  ) {
    throw new FencedError(
      "worker bootstrap bearer is not bound to this durable worker, host, queue set, capability set, and concurrency",
    );
  }
  return credential;
}

function requireAlarmDispatcher(
  config: Config,
  authorization: string | undefined,
  input: z.infer<typeof alarmClaimSchema>,
): void {
  const credential = config.alarmDispatcherCredentials[input.consumerId];
  if (
    !credential ||
    !authorized(bearerToken(authorization), credential.token) ||
    credential.source !== input.source
  ) {
    throw new FencedError(
      "alarm dispatcher bearer is not bound to this consumer and source",
    );
  }
}

export function buildServer(
  config: Config,
  fabric: ExecutionFabric,
  options: {
    reliability?: PostgresReliabilityStore;
    artifacts?: ArtifactStore;
    scheduler?: PostgresScheduler;
  } = {},
): FastifyInstance {
  const server = Fastify({
    logger: { level: config.logLevel },
    bodyLimit: 1024 * 1024,
    requestTimeout: Math.max(35000, config.longPollMs + 5000),
  });
  const metrics = createMetrics(config.metricsPrefix);

  server.addHook("onRequest", async (request) => {
    (request as typeof request & { startedAt?: bigint }).startedAt =
      process.hrtime.bigint();
  });
  server.addHook("onRequest", async (request, reply) => {
    const path = request.url.split("?", 1)[0] ?? "";
    const isAdmin = path === "/api/v1/admin" || path.startsWith("/api/v1/admin/");
    const isApi = path === "/api/v1" || path.startsWith("/api/v1/");
    const isMetrics = path === "/metrics";
    if (!isApi && !isMetrics) return;
    const sessionBound =
      /^\/api\/v1\/workers\/[^/]+\/heartbeat$/.test(path) ||
      path === "/api/v1/assignments/claim" ||
      /^\/api\/v1\/attempts\/[^/]+\/(complete|fail)$/.test(path) ||
      path === "/api/v1/artifacts/uploads" ||
      path === "/api/v1/artifacts/recovery-uploads" ||
      /^\/api\/v1\/artifacts\/[^/]+\/finalize$/.test(path) ||
      /^\/api\/v1\/artifacts\/[^/]+\/recovery-finalize$/.test(path) ||
      /^\/api\/v1\/effects\/[^/]+\/(deliver|fail)$/.test(path) ||
      /^\/api\/v1\/alarms\/[^/]+\/(deliver|fail)$/.test(path);
    const sourceBound =
      path === "/api/v1/reliability/observations" &&
      request.method === "POST";
    const consumerBound =
      (path === "/api/v1/effects/claim" ||
        path === "/api/v1/alarms/claim") &&
      request.method === "POST";
    const workerBootstrapBound =
      path === "/api/v1/workers/register" && request.method === "POST";
    if (consumerBound) {
      if (!bearerToken(request.headers.authorization)) {
        reply.header(
          "www-authenticate",
          'Bearer realm="execution-fabric", scope="consumer"',
        );
        return reply.status(401).send({ error: "unauthorized" });
      }
      return;
    }
    if (sourceBound) {
      if (!bearerToken(request.headers.authorization)) {
        reply.header(
          "www-authenticate",
          'Bearer realm="execution-fabric", scope="reliability-source"',
        );
        return reply.status(401).send({ error: "unauthorized" });
      }
      return;
    }
    if (workerBootstrapBound) {
      if (!bearerToken(request.headers.authorization)) {
        reply.header(
          "www-authenticate",
          'Bearer realm="execution-fabric", scope="worker-bootstrap"',
        );
        return reply.status(401).send({ error: "unauthorized" });
      }
      return;
    }
    if (sessionBound) {
      if (!bearerToken(request.headers.authorization)) {
        reply.header(
          "www-authenticate",
          'Bearer realm="execution-fabric", scope="session"',
        );
        return reply.status(401).send({ error: "unauthorized" });
      }
      return;
    }
    const expected = isAdmin
      ? config.adminToken
      : path === "/api/v1/tasks" && request.method === "POST"
        ? config.submitToken
        : request.method === "GET"
            ? config.apiToken
            : undefined;
    if (!authorized(bearerToken(request.headers.authorization), expected)) {
      reply.header(
        "www-authenticate",
        `Bearer realm="execution-fabric", scope="${
          isAdmin
            ? "admin"
            : path === "/api/v1/tasks" && request.method === "POST"
              ? "submit"
              : request.method === "GET"
                  ? "observer"
                  : "restricted"
        }"`,
      );
      return reply.status(401).send({ error: "unauthorized" });
    }
  });
  server.addHook("onResponse", async (request, reply) => {
    const startedAt = (request as typeof request & { startedAt?: bigint }).startedAt;
    if (!startedAt) return;
    metrics.requestDuration.observe(
      {
        method: request.method,
        route: request.routeOptions.url ?? "unmatched",
        status: String(reply.statusCode),
      },
      Number(process.hrtime.bigint() - startedAt) / 1e9,
    );
  });

  server.setErrorHandler((error, _request, reply) => {
    if (error instanceof z.ZodError) {
      void reply.status(400).send({
        error: "invalid_request",
        issues: error.issues.map((issue) => ({
          path: issue.path.join("."),
          message: issue.message,
        })),
      });
      return;
    }
    if (error instanceof ConflictError || error instanceof FencedError) {
      void reply.status(409).send({
        error: error instanceof FencedError ? "fenced" : "conflict",
        message: error.message,
      });
      return;
    }
    if (error instanceof LeadershipFencedError) {
      void reply.status(503).send({
        error: "leadership_fenced",
        message: error.message,
      });
      return;
    }
    if (error instanceof NotFoundError) {
      void reply.status(404).send({ error: "not_found", message: error.message });
      return;
    }
    if (error instanceof PolicyError) {
      const unavailable =
        error.code === "config_invalid" || error.code === "config_drift";
      void reply.status(unavailable ? 503 : 422).send({
        error: error.code,
        message: error.message,
      });
      return;
    }
    server.log.error({ err: error }, "request failed");
    void reply.status(500).send({ error: "internal_error" });
  });

  server.get("/healthz", async () => ({
    status: "ok",
    service: "execution-fabric-control-plane",
    apiVersion: "v1",
  }));
  server.get("/readyz", async (_request, reply) => {
    try {
      await fabric.ready();
      return { status: "ready" };
    } catch (error) {
      server.log.warn({ err: error }, "readiness dependency failed");
      return reply.status(503).send({ status: "not_ready" });
    }
  });
  server.get("/openapi.json", async () => openApiDocument);
  server.get("/metrics", async (_request, reply) => {
    await metrics.refresh(fabric.ledger, options.reliability);
    reply.header("content-type", metrics.registry.contentType);
    return metrics.registry.metrics();
  });

  server.post("/api/v1/tasks", async (request, reply) => {
    const input = taskAdmissionSchema.parse(request.body);
    const result = await fabric.admit(input);
    if (result.admitted) metrics.admitted.inc();
    return reply.status(result.admitted ? 201 : 200).send(result);
  });
  server.get("/api/v1/tasks/:taskId", async (request, reply) => {
    const { taskId } = uuidParam.parse(request.params);
    const task = await fabric.ledger.getTask(taskId);
    if (!task) return reply.status(404).send({ error: "not_found" });
    return {
      ...task,
      artifacts: options.artifacts
        ? await options.artifacts.forTask(taskId)
        : [],
    };
  });
  server.post("/api/v1/artifacts/uploads", async (request, reply) => {
    if (!options.artifacts) {
      return reply.status(503).send({ error: "artifact_store_unavailable" });
    }
    const input = artifactUploadSchema.parse(request.body);
    requireSessionBearer(request.headers.authorization, input.leaseToken);
    const result = await options.artifacts.initiate(input);
    return reply.status(result.alreadyAvailable ? 200 : 201).send(result);
  });
  server.post("/api/v1/artifacts/recovery-uploads", async (request, reply) => {
    if (!options.artifacts) {
      return reply.status(503).send({ error: "artifact_store_unavailable" });
    }
    const input = artifactRecoveryUploadSchema.parse(request.body);
    requireSessionBearer(
      request.headers.authorization,
      input.registrationToken,
    );
    const result = await options.artifacts.initiateRecovery(input);
    return reply.status(result.alreadyAvailable ? 200 : 201).send(result);
  });
  server.post(
    "/api/v1/artifacts/:artifactId/finalize",
    async (request, reply) => {
      if (!options.artifacts) {
        return reply.status(503).send({ error: "artifact_store_unavailable" });
      }
      const { artifactId } = artifactParam.parse(request.params);
      const input = artifactFinalizeSchema.parse(request.body);
      requireSessionBearer(request.headers.authorization, input.leaseToken);
      return options.artifacts.finalize(artifactId, input);
    },
  );
  server.post(
    "/api/v1/artifacts/:artifactId/recovery-finalize",
    async (request, reply) => {
      if (!options.artifacts) {
        return reply.status(503).send({ error: "artifact_store_unavailable" });
      }
      const { artifactId } = artifactParam.parse(request.params);
      const input = artifactRecoveryFinalizeSchema.parse(request.body);
      requireSessionBearer(
        request.headers.authorization,
        input.registrationToken,
      );
      return options.artifacts.finalizeRecovery(artifactId, input);
    },
  );
  server.get(
    "/api/v1/artifacts/:artifactId/download",
    async (request, reply) => {
      if (!options.artifacts) {
        return reply.status(503).send({ error: "artifact_store_unavailable" });
      }
      const { artifactId } = artifactParam.parse(request.params);
      return options.artifacts.download(artifactId);
    },
  );
  server.post("/api/v1/workers/register", async (request) => {
    const input = workerRegistrationSchema.parse(request.body);
    const credential = requireWorkerBootstrap(
      config,
      request.headers.authorization,
      input,
    );
    const pool = fabric.policy.pool(credential.poolId);
    if (
      input.queues.length !== pool.queues.length ||
      !input.queues.every((queue) => pool.queues.includes(queue))
    ) {
      throw new FencedError(
        "worker bootstrap pool is not compatible with the registered queues",
      );
    }
    return fabric.registerWorker(input);
  });
  server.post("/api/v1/workers/:workerId/heartbeat", async (request) => {
    fabric.assertMutation();
    const { workerId } = workerParam.parse(request.params);
    const input = workerHeartbeatSchema.parse(request.body);
    requireSessionBearer(request.headers.authorization, input.registrationToken);
    return fabric.ledger.heartbeat(workerId, input);
  });
  server.post("/api/v1/assignments/claim", async (request, reply) => {
    const input = claimSchema.parse(request.body);
    requireSessionBearer(request.headers.authorization, input.registrationToken);
    const assignment = await fabric.claim(input);
    if (!assignment) return reply.status(204).send();
    metrics.assignments.inc();
    return assignment;
  });
  server.post("/api/v1/attempts/:attemptId/complete", async (request) => {
    fabric.assertMutation();
    const { attemptId } = attemptParam.parse(request.params);
    const input = attemptCompletionSchema.parse(request.body);
    requireSessionBearer(request.headers.authorization, input.leaseToken);
    return fabric.complete(attemptId, input);
  });
  server.post("/api/v1/attempts/:attemptId/fail", async (request) => {
    fabric.assertMutation();
    const { attemptId } = attemptParam.parse(request.params);
    const input = attemptFailureSchema.parse(request.body);
    requireSessionBearer(request.headers.authorization, input.leaseToken);
    return fabric.ledger.fail(attemptId, input);
  });
  server.post("/api/v1/effects/claim", async (request) => {
    fabric.assertMutation();
    const input = effectClaimSchema.parse(request.body);
    requireEffectConsumer(config, request.headers.authorization, input);
    return { effects: await fabric.claimEffects(input) };
  });
  server.post("/api/v1/effects/:effectId/deliver", async (request, reply) => {
    fabric.assertMutation();
    const { effectId } = effectParam.parse(request.params);
    const input = effectDeliverySchema.parse(request.body);
    requireSessionBearer(request.headers.authorization, input.claimToken);
    await fabric.ledger.deliverEffect(effectId, input);
    return reply.status(204).send();
  });
  server.post("/api/v1/effects/:effectId/fail", async (request, reply) => {
    fabric.assertMutation();
    const { effectId } = effectParam.parse(request.params);
    const input = effectFailureSchema.parse(request.body);
    requireSessionBearer(request.headers.authorization, input.claimToken);
    await fabric.ledger.failEffect(effectId, input);
    return reply.status(204).send();
  });
  server.get("/api/v1/snapshots/queues", async () => ({
    sampledAt: new Date().toISOString(),
    queues: await fabric.ledger.queueSnapshot(),
  }));
  server.get("/api/v1/snapshots/workers", async () => ({
    sampledAt: new Date().toISOString(),
    workers: await fabric.ledger.workerSnapshot(),
  }));
  server.get("/api/v1/snapshots/runs", async (request) => {
    const query = z
      .object({ limit: z.coerce.number().int().min(1).max(1000).default(200) })
      .parse(request.query);
    return {
      sampledAt: new Date().toISOString(),
      sampleLimit: query.limit,
      runs: await fabric.ledger.runSnapshot(query.limit),
    };
  });
  server.get("/api/v1/snapshots/artifacts", async (request, reply) => {
    if (!options.artifacts) {
      return reply.status(503).send({ error: "artifact_store_unavailable" });
    }
    const query = z
      .object({ limit: z.coerce.number().int().min(1).max(1000).default(200) })
      .parse(request.query);
    return {
      sampledAt: new Date().toISOString(),
      ...(await options.artifacts.snapshot(query.limit)),
    };
  });
  server.get("/api/v1/snapshots/schedules", async (request, reply) => {
    if (!options.scheduler) {
      return reply.status(503).send({ error: "scheduler_unavailable" });
    }
    const query = z
      .object({ limit: z.coerce.number().int().min(1).max(1000).default(200) })
      .parse(request.query);
    return {
      sampledAt: new Date().toISOString(),
      sampleLimit: query.limit,
      schedules: await options.scheduler.snapshot(query.limit),
    };
  });
  server.get("/api/v1/status", async (request) => {
    const query = z
      .object({ limit: z.coerce.number().int().min(1).max(1000).default(200) })
      .parse(request.query);
    const status = await fabric.status(config.hostId, query.limit);
    const objectStore = options.artifacts
      ? await options.artifacts.health()
      : { status: "unavailable", checkedAt: new Date().toISOString() };
    if (!options.reliability) return { ...status, objectStore };
    const reliability = await options.reliability.snapshot();
    const existingHealing =
      (status.healing as Record<string, unknown> | undefined) ?? {};
    const existingAlarms =
      (status.alarms as Array<Record<string, unknown>> | undefined) ?? [];
    const openFindings = reliability.findings.open ?? 0;
    const failedRepairs = reliability.repairs.failed ?? 0;
    const pendingAlarms =
      (reliability.alarms.pending ?? 0) +
      (reliability.alarms.failed ?? 0) +
      (reliability.alarms.dead_lettered ?? 0);
    return {
      ...status,
      objectStore,
      healing: {
        ...existingHealing,
        status:
          failedRepairs > 0 ? "failed" : openFindings > 0 ? "degraded" : "healthy",
        lastObservedAt: reliability.lastObservationAt,
        lastRepairAt: reliability.lastRepairAt,
        findings: reliability.findings,
        repairs: reliability.repairs,
        findingDetails: reliability.activeFindings ?? [],
        repairReceipts: reliability.recentRepairReceipts ?? [],
      },
      alarms:
        pendingAlarms > 0
          ? [
              ...existingAlarms,
              ...(reliability.unresolvedAlarms ?? []),
              {
                code: "durable_alarm_backlog",
                severity:
                  (reliability.alarms.dead_lettered ?? 0) > 0
                    ? "critical"
                    : "warning",
                count: pendingAlarms,
                statuses: reliability.alarms,
              },
            ]
          : [...existingAlarms, ...(reliability.unresolvedAlarms ?? [])],
    };
  });
  server.get("/api/v1/snapshots/reliability", async (_request, reply) => {
    if (!options.reliability) {
      return reply.status(503).send({ error: "reliability_plane_unavailable" });
    }
    return options.reliability.snapshot();
  });
  server.post("/api/v1/reliability/observations", async (request, reply) => {
    if (!options.reliability) {
      return reply.status(503).send({ error: "reliability_plane_unavailable" });
    }
    const input = reliabilityObservationSchema.parse(request.body);
    const expected = config.reliabilitySourceTokens[input.source];
    if (!expected || !authorized(bearerToken(request.headers.authorization), expected)) {
      reply.header(
        "www-authenticate",
        `Bearer realm="execution-fabric", scope="reliability-source:${input.source}"`,
      );
      return reply.status(401).send({ error: "unauthorized" });
    }
    fabric.assertMutation();
    const state = await fabric.ledger.systemSnapshot();
    const receipt = await options.reliability.ingestExternalObservation(
      input,
      state.fabricEpoch,
    );
    return reply.status(receipt.admitted ? 201 : 200).send(receipt);
  });
  server.post("/api/v1/alarms/claim", async (request, reply) => {
    if (!options.reliability) {
      return reply.status(503).send({ error: "reliability_plane_unavailable" });
    }
    fabric.assertMutation();
    const input = alarmClaimSchema.parse(request.body);
    requireAlarmDispatcher(config, request.headers.authorization, input);
    return {
      alarms: await options.reliability.claimAlarms(
        input.consumerId,
        input.limit,
        config.leaseSeconds,
      ),
    };
  });
  server.post("/api/v1/alarms/:alarmId/deliver", async (request, reply) => {
    if (!options.reliability) {
      return reply.status(503).send({ error: "reliability_plane_unavailable" });
    }
    fabric.assertMutation();
    const { alarmId } = alarmParam.parse(request.params);
    const input = alarmDeliverySchema.parse(request.body);
    requireSessionBearer(request.headers.authorization, input.claimToken);
    await options.reliability.deliverAlarm(
      alarmId,
      input.consumerId,
      input.claimToken,
      input.fabricEpoch,
      input.deliveryReceipt,
    );
    return reply.status(204).send();
  });
  server.post("/api/v1/alarms/:alarmId/fail", async (request, reply) => {
    if (!options.reliability) {
      return reply.status(503).send({ error: "reliability_plane_unavailable" });
    }
    fabric.assertMutation();
    const { alarmId } = alarmParam.parse(request.params);
    const input = alarmFailureSchema.parse(request.body);
    requireSessionBearer(request.headers.authorization, input.claimToken);
    await options.reliability.failAlarm(
      alarmId,
      input.consumerId,
      input.claimToken,
      input.fabricEpoch,
      input.errorSummary,
    );
    return reply.status(204).send();
  });
  server.post("/api/v1/admin/reconcile", async (request, reply) => {
    return fabric.reconcile();
  });
  server.post("/api/v1/admin/delivery-reconciliation", async (request) => {
    return fabric.reconcileDeliveryProjection(
      deliveryReconciliationSchema.parse(request.body),
    );
  });
  server.post("/api/v1/admin/config/reload", async (request) => {
    const input = configReloadSchema.parse(request.body);
    if (!input.operatorOverride) {
      return fabric.reloadPolicy({
        rotationId: input.rotationId,
        preparationToken: input.preparationToken,
        expectedCurrentFingerprint: input.expectedCurrentFingerprint,
        expectedCandidateFingerprint: input.expectedCandidateFingerprint,
      });
    }
    if (!options.reliability) {
      throw new FencedError(
        "standalone policy override requires the durable reliability alert plane",
      );
    }
    const before = await fabric.ledger.systemSnapshot();
    const invocation = await options.reliability.ingestExternalObservation(
      policyOverrideObservation({
        rotationId: input.rotationId,
        override: input.operatorOverride,
        phase: "invoked",
        fabricEpoch: before.fabricEpoch,
        expectedCurrentFingerprint: input.expectedCurrentFingerprint,
        expectedCandidateFingerprint: input.expectedCandidateFingerprint,
      }),
      before.fabricEpoch,
    );
    let reloadApplied = false;
    try {
      const result = await fabric.reloadPolicy({
        rotationId: input.rotationId,
        preparationToken: input.preparationToken,
        expectedCurrentFingerprint: input.expectedCurrentFingerprint,
        expectedCandidateFingerprint: input.expectedCandidateFingerprint,
        operatorOverride: input.operatorOverride,
      });
      reloadApplied = true;
      const after = await fabric.ledger.systemSnapshot();
      const outcome = await options.reliability.ingestExternalObservation(
        policyOverrideObservation({
          rotationId: input.rotationId,
          override: input.operatorOverride,
          phase: "succeeded",
          fabricEpoch: after.fabricEpoch,
          expectedCurrentFingerprint: input.expectedCurrentFingerprint,
          expectedCandidateFingerprint: input.expectedCandidateFingerprint,
        }),
        after.fabricEpoch,
      );
      return { ...result, alerts: { invocation, outcome } };
    } catch (error) {
      if (!reloadApplied) {
        const errorSummary =
          error instanceof Error ? error.message : "unknown policy override failure";
        try {
          await options.reliability.ingestExternalObservation(
            policyOverrideObservation({
              rotationId: input.rotationId,
              override: input.operatorOverride,
              phase: "failed",
              fabricEpoch: before.fabricEpoch,
              expectedCurrentFingerprint: input.expectedCurrentFingerprint,
              expectedCandidateFingerprint: input.expectedCandidateFingerprint,
              errorSummary,
            }),
            before.fabricEpoch,
          );
        } catch {
          // The critical invocation alert is already durable.  Preserve the
          // reload failure rather than masking it with a secondary alert error.
        }
      }
      throw error;
    }
  });
  server.put(
    "/api/v1/admin/schedules/:scheduleId",
    async (request, reply) => {
      if (!options.scheduler) {
        return reply.status(503).send({ error: "scheduler_unavailable" });
      }
      const { scheduleId } = scheduleParam.parse(request.params);
      const input = scheduleUpsertSchema.parse({
        ...(request.body as Record<string, unknown>),
        id: scheduleId,
      });
      return options.scheduler.upsert(input);
    },
  );
  server.patch(
    "/api/v1/admin/schedules/:scheduleId",
    async (request, reply) => {
      if (!options.scheduler) {
        return reply.status(503).send({ error: "scheduler_unavailable" });
      }
      const { scheduleId } = scheduleParam.parse(request.params);
      const { enabled } = scheduleToggleSchema.parse(request.body);
      await options.scheduler.setEnabled(scheduleId, enabled);
      return reply.status(204).send();
    },
  );
  server.post(
    "/api/v1/admin/findings/:findingId/acknowledge",
    async (request, reply) => {
      if (!options.reliability) {
        return reply.status(503).send({ error: "reliability_plane_unavailable" });
      }
      const { findingId } = findingParam.parse(request.params);
      const input = operatorActionSchema.parse(request.body);
      return options.reliability.acknowledgeFinding(findingId, input.actor);
    },
  );
  server.post("/api/v1/admin/effects/:effectId/replay", async (request, reply) => {
    if (!options.reliability) {
      return reply.status(503).send({ error: "reliability_plane_unavailable" });
    }
    fabric.assertMutation();
    const { effectId } = effectParam.parse(request.params);
    const input = operatorActionSchema.parse(request.body);
    return options.reliability.replayEffect(
      effectId,
      input.actor,
      input.idempotencyKey,
    );
  });
  server.post("/api/v1/admin/tasks/:taskId/cancel", async (request, reply) => {
    if (!options.reliability) {
      return reply.status(503).send({ error: "reliability_plane_unavailable" });
    }
    fabric.assertMutation();
    const { taskId } = uuidParam.parse(request.params);
    const input = operatorActionSchema.parse(request.body);
    return options.reliability.cancelTask(
      taskId,
      input.actor,
      input.idempotencyKey,
    );
  });
  server.post("/api/v1/admin/tasks/:taskId/requeue", async (request, reply) => {
    if (!options.reliability) {
      return reply.status(503).send({ error: "reliability_plane_unavailable" });
    }
    fabric.assertMutation();
    const { taskId } = uuidParam.parse(request.params);
    const input = operatorActionSchema.parse(request.body);
    return options.reliability.requeueTask(
      taskId,
      input.actor,
      input.idempotencyKey,
    );
  });
  server.post("/api/v1/admin/queues/:queue/drain", async (request, reply) => {
    if (!options.reliability) {
      return reply.status(503).send({ error: "reliability_plane_unavailable" });
    }
    fabric.assertMutation();
    const { queue } = queueParam.parse(request.params);
    const input = operatorActionSchema.parse(request.body);
    return options.reliability.drainQueue(
      queue,
      input.actor,
      input.idempotencyKey,
    );
  });

  return server;
}
