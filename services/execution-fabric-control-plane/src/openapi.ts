export const openApiDocument = {
  openapi: "3.1.0",
  info: {
    title: "Agentic OS Execution Fabric Control Plane",
    version: "1.0.0",
    description:
      "Versioned cross-host task, worker, lease, run, and observability contract.",
  },
  components: {
    securitySchemes: {
      bearerAuth: {
        type: "http",
        scheme: "bearer",
        bearerFormat: "opaque",
        description:
          "Observer token. Submit, worker bootstrap, and sessions use narrower credentials.",
      },
      adminBearerAuth: {
        type: "http",
        scheme: "bearer",
        bearerFormat: "opaque",
        description:
          "Separate operator token loaded by the service from FABRIC_ADMIN_TOKEN_FILE.",
      },
      reliabilitySourceBearerAuth: {
        type: "http",
        scheme: "bearer",
        bearerFormat: "opaque",
        description:
          "Source-scoped token from FABRIC_RELIABILITY_SOURCE_TOKENS_FILE; body.source must match.",
      },
    },
  },
  security: [{ bearerAuth: [] }],
  servers: [{ url: "/api/v1" }],
  paths: {
    "/tasks": {
      post: {
        operationId: "admitTask",
        summary: "Idempotently admit a task",
        responses: { "201": { description: "Admitted" }, "200": { description: "Existing" } },
      },
    },
    "/tasks/{taskId}": {
      get: {
        operationId: "getTask",
        summary: "Read canonical task state",
        responses: { "200": { description: "Task" }, "404": { description: "Not found" } },
      },
    },
    "/artifacts/uploads": {
      post: {
        operationId: "initiateArtifactUpload",
        summary:
          "Create a bounded task-attempt artifact and a short-lived scoped upload",
        responses: {
          "201": { description: "Upload prepared" },
          "200": { description: "Artifact already available" },
        },
      },
    },
    "/artifacts/{artifactId}/finalize": {
      post: {
        operationId: "finalizeArtifactUpload",
        summary: "Verify object size and SHA-256 metadata before publication",
        responses: {
          "200": { description: "Verified artifact metadata" },
          "409": { description: "Object verification failed" },
        },
      },
    },
    "/artifacts/recovery-uploads": {
      post: {
        operationId: "initiateArtifactRecoveryUpload",
        summary:
          "Issue a fresh upload bound to the current worker session and the assignment recovery token",
        responses: {
          "201": { description: "Recovery upload prepared" },
          "200": { description: "Artifact already available" },
          "409": { description: "Worker or attempt recovery token fenced" },
        },
      },
    },
    "/artifacts/{artifactId}/recovery-finalize": {
      post: {
        operationId: "finalizeArtifactRecoveryUpload",
        summary:
          "Verify a recovered object's size and SHA-256 under the same recovery fence",
        responses: {
          "200": { description: "Recovered artifact verified" },
          "409": { description: "Recovery fence or object verification failed" },
        },
      },
    },
    "/artifacts/{artifactId}/download": {
      get: {
        operationId: "downloadArtifact",
        summary: "Issue a short-lived download for an available run artifact",
        responses: {
          "200": { description: "Artifact metadata and scoped URL" },
          "404": { description: "Artifact unavailable" },
        },
      },
    },
    "/workers/register": {
      post: {
        operationId: "registerWorker",
        summary: "Register or replace a worker lease",
        responses: { "200": { description: "Registration receipt" } },
      },
    },
    "/workers/{workerId}/heartbeat": {
      post: {
        operationId: "heartbeatWorker",
        summary: "Renew a worker and its declared active attempt leases",
        responses: { "200": { description: "Heartbeat receipt" }, "409": { description: "Fenced" } },
      },
    },
    "/assignments/claim": {
      post: {
        operationId: "claimAssignment",
        summary: "Long-poll for one fenced assignment",
        responses: { "200": { description: "Assignment" }, "204": { description: "No work" } },
      },
    },
    "/attempts/{attemptId}/complete": {
      post: {
        operationId: "completeAttempt",
        summary: "Complete the current fenced attempt and stage idempotent effects",
        responses: { "200": { description: "Task" }, "409": { description: "Fenced" } },
      },
    },
    "/attempts/{attemptId}/fail": {
      post: {
        operationId: "failAttempt",
        summary: "Fail the current fenced attempt",
        responses: { "200": { description: "Task" }, "409": { description: "Fenced" } },
      },
    },
    "/effects/claim": {
      post: {
        operationId: "claimEffects",
        summary: "Claim fenced external-effect intents by explicit owned effect types",
        responses: { "200": { description: "Effect assignments" } },
      },
    },
    "/effects/{effectId}/deliver": {
      post: {
        operationId: "deliverEffect",
        summary: "Store provider readback and mark a fenced effect delivered",
        responses: { "204": { description: "Delivered" }, "409": { description: "Fenced" } },
      },
    },
    "/effects/{effectId}/fail": {
      post: {
        operationId: "failEffect",
        summary: "Return a fenced effect to its retry schedule",
        responses: { "204": { description: "Retry scheduled" }, "409": { description: "Fenced" } },
      },
    },
    "/alarms/claim": {
      post: {
        operationId: "claimAlarms",
        summary: "Lease durable alarm intents for the separate Agentic OS dispatcher",
        responses: { "200": { description: "Alarm assignments" }, "409": { description: "Fenced" } },
      },
    },
    "/alarms/{alarmId}/deliver": {
      post: {
        operationId: "deliverAlarm",
        summary: "Receipt one current-epoch Agentic OS alarm delivery",
        responses: { "204": { description: "Delivered" }, "409": { description: "Fenced" } },
      },
    },
    "/alarms/{alarmId}/fail": {
      post: {
        operationId: "failAlarm",
        summary: "Record one bounded alarm-dispatch failure",
        responses: { "204": { description: "Retry scheduled" }, "409": { description: "Fenced" } },
      },
    },
    "/snapshots/queues": {
      get: { operationId: "queueSnapshot", responses: { "200": { description: "Queue snapshot" } } },
    },
    "/snapshots/workers": {
      get: { operationId: "workerSnapshot", responses: { "200": { description: "Worker snapshot" } } },
    },
    "/snapshots/runs": {
      get: { operationId: "runSnapshot", responses: { "200": { description: "Run snapshot" } } },
    },
    "/snapshots/artifacts": {
      get: {
        operationId: "artifactSnapshot",
        responses: {
          "200": {
            description: "Artifact counts, recent metadata, and object-store health",
          },
        },
      },
    },
    "/snapshots/schedules": {
      get: {
        operationId: "scheduleSnapshot",
        responses: { "200": { description: "Schedule and occurrence snapshot" } },
      },
    },
    "/snapshots/reliability": {
      get: {
        operationId: "reliabilitySnapshot",
        responses: { "200": { description: "Durable finding, alarm, and repair counts" } },
      },
    },
    "/reliability/observations": {
      post: {
        operationId: "ingestReliabilityObservation",
        summary:
          "Idempotently persist one source-scoped active or recovery observation; the platform derives and resolves sticky alarms",
        security: [{ reliabilitySourceBearerAuth: [] }],
        responses: {
          "201": { description: "New observation revision admitted" },
          "200": { description: "Exact idempotent replay" },
          "401": { description: "Source credential mismatch" },
          "409": { description: "Revision conflict or stale revision" },
        },
      },
    },
    "/status": {
      get: {
        operationId: "fabricStatus",
        summary: "Read config, host, queue, worker, run, effect, alarm, and healer state",
        responses: { "200": { description: "Unified system status" }, "503": { description: "Config invalid or drifted" } },
      },
    },
    "/admin/reconcile": {
      post: {
        operationId: "reconcileFabric",
        summary: "Deterministically expire stale leases and reconstruct delivery",
        security: [{ adminBearerAuth: [] }],
        responses: { "200": { description: "Reconcile receipt" }, "401": { description: "Unauthorized" } },
      },
    },
    "/admin/config/reload": {
      post: {
        operationId: "reloadFabricConfig",
        summary: "Compare-and-swap validate and activate the canonical queue policy with a durable receipt",
        description:
          "Normal witness-backed reloads omit operatorOverride. The disabled-by-default standalone-primary drift exception requires an exact signed operator reason, approval reference, and current maintenance window; invocation and outcome produce durable critical alarms.",
        security: [{ adminBearerAuth: [] }],
        requestBody: {
          required: true,
          content: {
            "application/json": {
              schema: {
                type: "object",
                additionalProperties: false,
                required: [
                  "rotationId",
                  "preparationToken",
                  "expectedCurrentFingerprint",
                  "expectedCandidateFingerprint",
                ],
                properties: {
                  rotationId: { type: "string", format: "uuid" },
                  preparationToken: { type: "string", pattern: "^cpr1\\.[A-Za-z0-9_-]+\\.[A-Za-z0-9_-]+$" },
                  expectedCurrentFingerprint: { type: "string", pattern: "^[a-f0-9]{64}$" },
                  expectedCandidateFingerprint: { type: "string", pattern: "^[a-f0-9]{64}$" },
                  operatorOverride: {
                    type: "object",
                    additionalProperties: false,
                    required: ["actor", "reason", "approvalReference", "maintenanceWindow"],
                    properties: {
                      actor: { type: "string", pattern: "^[a-zA-Z0-9._:-]{1,128}$" },
                      reason: { type: "string", minLength: 1, maxLength: 2048 },
                      approvalReference: { type: "string", minLength: 1, maxLength: 512 },
                      maintenanceWindow: {
                        type: "object",
                        additionalProperties: false,
                        required: ["startsAt", "endsAt"],
                        properties: {
                          startsAt: { type: "string", format: "date-time" },
                          endsAt: { type: "string", format: "date-time" },
                        },
                      },
                    },
                  },
                },
              },
            },
          },
        },
        responses: {
          "200": { description: "Applied config receipt and durable alert receipts" },
          "409": { description: "Fenced, expired, or outside the maintenance window" },
          "503": { description: "Invalid config or durable alert plane unavailable" },
        },
      },
    },
    "/admin/schedules/{scheduleId}": {
      put: {
        operationId: "upsertSchedule",
        responses: {
          "200": { description: "Schedule created or updated" },
          "409": { description: "Leadership fenced" },
        },
      },
      patch: {
        operationId: "setScheduleEnabled",
        responses: {
          "204": { description: "Schedule enabled state updated" },
          "409": { description: "Leadership fenced" },
        },
      },
    },
    "/admin/findings/{findingId}/acknowledge": {
      post: {
        operationId: "acknowledgeFinding",
        summary: "Acknowledge one durable finding and its outstanding alarms",
        security: [{ adminBearerAuth: [] }],
        responses: { "200": { description: "Acknowledged finding" }, "404": { description: "Not found" } },
      },
    },
    "/admin/effects/{effectId}/replay": {
      post: {
        operationId: "replayEffect",
        summary: "Replay one explicit failed effect with a current-epoch receipt",
        security: [{ adminBearerAuth: [] }],
        responses: { "200": { description: "Operator receipt" }, "409": { description: "Fenced" } },
      },
    },
    "/admin/tasks/{taskId}/cancel": {
      post: {
        operationId: "cancelTask",
        summary: "Cancel one queued or running task with a durable receipt",
        security: [{ adminBearerAuth: [] }],
        responses: { "200": { description: "Operator receipt" }, "409": { description: "Fenced" } },
      },
    },
    "/admin/tasks/{taskId}/requeue": {
      post: {
        operationId: "requeueTask",
        summary: "Requeue one terminal task with a durable receipt",
        security: [{ adminBearerAuth: [] }],
        responses: { "200": { description: "Operator receipt" }, "409": { description: "Fenced" } },
      },
    },
    "/admin/queues/{queue}/drain": {
      post: {
        operationId: "drainQueue",
        summary: "Cancel only queued work in one queue with a durable receipt",
        security: [{ adminBearerAuth: [] }],
        responses: { "200": { description: "Operator receipt" }, "409": { description: "Fenced" } },
      },
    },
  },
} as const;
