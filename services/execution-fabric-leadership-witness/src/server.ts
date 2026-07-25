import { timingSafeEqual } from "node:crypto";
import Fastify, { type FastifyInstance } from "fastify";
import { z } from "zod";
import type { WitnessConfig } from "./config.js";
import {
  candidateUpdateSchema,
  configDigestRotationAbortSchema,
  configDigestRotationCommitSchema,
  configDigestRotationSchema,
  failbackCommitSchema,
  failbackPrepareSchema,
  failbackPlanSchema,
  hostIdSchema,
  promotionSchema,
} from "./contracts.js";
import { openApiDocument } from "./openapi.js";
import {
  LeadershipWitness,
  WitnessConflictError,
  WitnessNotFoundError,
} from "./witness.js";

function authorized(actual: string | undefined, expected: string): boolean {
  const match = actual?.match(/^Bearer ([^\s]+)$/i);
  if (!match?.[1]) return false;
  const actualBuffer = Buffer.from(match[1]);
  const expectedBuffer = Buffer.from(expected);
  return (
    actualBuffer.length === expectedBuffer.length &&
    timingSafeEqual(actualBuffer, expectedBuffer)
  );
}

export function buildServer(
  config: WitnessConfig,
  witness: LeadershipWitness,
): FastifyInstance {
  const server = Fastify({
    logger: { level: config.logLevel },
    bodyLimit: 64 * 1024,
    requestTimeout: 10000,
  });

  server.addHook("onRequest", async (request, reply) => {
    const path = request.url.split("?", 1)[0] ?? "";
    if (path === "/api/v1/admin/leadership/status") {
      if (authorized(request.headers.authorization, config.readerToken)) return;
      reply.header(
        "www-authenticate",
        'Bearer realm="execution-fabric-witness", scope="reader"',
      );
      return reply.status(401).send({ error: "unauthorized" });
    }
    const candidateMatch = path.match(
      /^\/api\/v1\/admin\/leadership\/candidates\/([a-zA-Z0-9._-]{1,128})$/,
    );
    if (candidateMatch && request.method === "PUT") {
      const candidate = candidateMatch[1]!;
      const expected = config.candidateTokens[candidate];
      if (expected && authorized(request.headers.authorization, expected)) return;
      reply.header(
        "www-authenticate",
        `Bearer realm="execution-fabric-witness", scope="candidate:${candidate}"`,
      );
      return reply.status(401).send({ error: "unauthorized" });
    }
    if (
      (path === "/api/v1/admin" || path.startsWith("/api/v1/admin/")) &&
      !authorized(request.headers.authorization, config.adminToken)
    ) {
      reply.header(
        "www-authenticate",
        'Bearer realm="execution-fabric-witness", scope="admin"',
      );
      return reply.status(401).send({ error: "unauthorized" });
    }
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
    if (error instanceof WitnessConflictError) {
      void reply
        .status(409)
        .send({ error: "leadership_conflict", message: error.message });
      return;
    }
    if (error instanceof WitnessNotFoundError) {
      void reply.status(404).send({ error: "not_found", message: error.message });
      return;
    }
    server.log.error({ err: error }, "witness request failed");
    void reply.status(500).send({ error: "internal_error" });
  });

  server.get("/healthz", async () => ({
    status: "ok",
    service: "execution-fabric-leadership-witness",
    apiVersion: "v1",
  }));
  server.get("/readyz", async (_request, reply) => {
    try {
      await witness.ready();
      return { status: "ready" };
    } catch (error) {
      server.log.warn({ err: error }, "witness readiness dependency failed");
      return reply.status(503).send({ status: "not_ready" });
    }
  });
  server.get("/openapi.json", async () => openApiDocument);

  server.get("/api/v1/admin/leadership/status", async () => witness.status());
  server.put(
    "/api/v1/admin/leadership/candidates/:candidate",
    async (request) => {
      const { candidate } = z
        .object({ candidate: hostIdSchema })
        .parse(request.params);
      return witness.updateCandidate(
        candidate,
        candidateUpdateSchema.parse(request.body),
      );
    },
  );
  server.post("/api/v1/admin/leadership/promote", async (request) =>
    witness.promote(promotionSchema.parse(request.body)),
  );
  server.get(
    "/api/v1/admin/leadership/promotions/:promotionId",
    async (request) => {
      const { promotionId } = z
        .object({ promotionId: z.string().uuid() })
        .parse(request.params);
      return witness.promotion(promotionId);
    },
  );
  server.post(
    "/api/v1/admin/leadership/config-digest-rotations/prepare",
    async (request) =>
      witness.prepareConfigDigestRotation(
        configDigestRotationSchema.parse(request.body),
      ),
  );
  server.post(
    "/api/v1/admin/leadership/config-digest-rotations/commit",
    async (request) =>
      witness.commitConfigDigestRotation(
        configDigestRotationCommitSchema.parse(request.body),
      ),
  );
  server.post(
    "/api/v1/admin/leadership/config-digest-rotations/abort",
    async (request) =>
      witness.abortConfigDigestRotation(
        configDigestRotationAbortSchema.parse(request.body),
      ),
  );
  server.get(
    "/api/v1/admin/leadership/config-digest-rotations/:rotationId",
    async (request) => {
      const { rotationId } = z
        .object({ rotationId: z.string().uuid() })
        .parse(request.params);
      return witness.configDigestRotation(rotationId);
    },
  );
  server.get(
    "/api/v1/admin/leadership/config-digest-rotations/:rotationId/preparation",
    async (request) => {
      const { rotationId } = z
        .object({ rotationId: z.string().uuid() })
        .parse(request.params);
      return witness.configDigestRotationPreparation(rotationId);
    },
  );
  server.get(
    "/api/v1/admin/leadership/config-digest-rotations/:rotationId/abort",
    async (request) => {
      const { rotationId } = z
        .object({ rotationId: z.string().uuid() })
        .parse(request.params);
      return witness.configDigestRotationAbort(rotationId);
    },
  );
  server.post("/api/v1/admin/leadership/failback-plan", async (request) =>
    witness.planFailback(failbackPlanSchema.parse(request.body)),
  );
  server.post("/api/v1/admin/leadership/failback-prepare", async (request) =>
    witness.prepareFailback(failbackPrepareSchema.parse(request.body)),
  );
  server.post("/api/v1/admin/leadership/failback-commit", async (request) =>
    witness.commitFailback(failbackCommitSchema.parse(request.body)),
  );
  server.get("/api/v1/admin/leadership/audit", async (request) => {
    const { limit } = z
      .object({
        limit: z.coerce.number().int().min(1).max(500).default(100),
      })
      .parse(request.query);
    return {
      sampledAt: new Date().toISOString(),
      records: await witness.audit(limit),
    };
  });

  return server;
}
