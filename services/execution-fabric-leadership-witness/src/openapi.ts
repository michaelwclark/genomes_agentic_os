export const openApiDocument = {
  openapi: "3.1.0",
  info: {
    title: "Agentic OS Execution Fabric Leadership Witness",
    version: "1.0.0",
    description:
      "Authenticated, monotonic leadership arbitration, including an explicit non-HA standalone-primary mode that disables promotion and failback.",
  },
  components: {
    securitySchemes: {
      adminBearerAuth: {
        type: "http",
        scheme: "bearer",
        bearerFormat: "opaque",
      },
    },
    schemas: {
      CandidateUpdate: {
        type: "object",
        additionalProperties: false,
        required: [
          "healthy",
          "inRecovery",
          "timelineId",
          "receiveLsn",
          "replayLsn",
          "receiveWalPosition",
          "replayWalPosition",
          "replicaLagBytes",
          "lagMeasuredAt",
          "upstreamSystemId",
          "receiverState",
          "lastMessageAt",
          "configDigest",
        ],
        properties: {
          healthy: { type: "boolean" },
          inRecovery: { type: "boolean" },
          timelineId: { type: "integer", minimum: 1 },
          receiveLsn: { type: "string", pattern: "^[0-9A-F]+/[0-9A-F]+$" },
          replayLsn: { type: "string", pattern: "^[0-9A-F]+/[0-9A-F]+$" },
          receiveWalPosition: { type: "integer", minimum: 0 },
          replayWalPosition: { type: "integer", minimum: 0 },
          replicaLagBytes: { type: "integer", minimum: 0 },
          lagMeasuredAt: { type: "string", format: "date-time" },
          upstreamSystemId: { type: "string", pattern: "^[0-9]{1,32}$" },
          receiverState: {
            type: "string",
            enum: [
              "not_applicable",
              "startup",
              "catchup",
              "streaming",
              "backup",
              "stopping",
              "disconnected",
            ],
          },
          lastMessageAt: { type: "string", format: "date-time" },
          configDigest: {
            type: "string",
            pattern: "^[a-f0-9]{64}$",
            description: "Currently applied durable authority digest.",
          },
          policyCandidateDigest: {
            type: "string",
            pattern: "^[a-f0-9]{64}$",
            description: "Staged on-disk policy digest proposed for rotation.",
          },
          policyCandidateObservedAt: {
            type: "string",
            format: "date-time",
            description:
              "Freshness time for policyCandidateDigest; defaults to report observation time.",
          },
          observedAt: { type: "string", format: "date-time" },
        },
      },
      PromotionRequest: {
        type: "object",
        additionalProperties: false,
        required: [
          "promotionId",
          "candidate",
          "expectedLeader",
          "expectedEpoch",
          "incidentDigest",
        ],
        properties: {
          promotionId: { type: "string", format: "uuid" },
          candidate: { type: "string", pattern: "^[a-zA-Z0-9._-]{1,128}$" },
          expectedLeader: { type: "string", pattern: "^[a-zA-Z0-9._-]{1,128}$" },
          expectedEpoch: { type: "integer", minimum: 1 },
          incidentDigest: { type: "string", pattern: "^[a-f0-9]{64}$" },
          authorityMode: {
            type: "string",
            enum: ["synchronous", "degraded_primary"],
          },
          degradedDurationSeconds: { type: "integer", minimum: 60, maximum: 86400 },
        },
      },
      PromotionReceipt: {
        type: "object",
        additionalProperties: false,
        required: [
          "apiVersion", "decision", "promotionId", "requestDigest",
          "receiptId", "previousLeader", "currentLeader", "fabricEpoch",
          "clusterId", "fenceToken", "authorityMode", "degradedUntil",
          "committedAt",
        ],
        properties: {
          apiVersion: { type: "string", const: "execution-fabric-leadership/v1" },
          decision: { type: "string", const: "promoted" },
          promotionId: { type: "string", format: "uuid" },
          requestDigest: { type: "string", pattern: "^[a-f0-9]{64}$" },
          receiptId: { type: "string" },
          previousLeader: { type: "string" },
          currentLeader: { type: "string" },
          fabricEpoch: { type: "integer", minimum: 2 },
          clusterId: { type: "string" },
          fenceToken: { type: "string" },
          authorityMode: { type: "string", enum: ["synchronous", "degraded_primary", "standalone_primary"] },
          degradedUntil: { type: ["string", "null"], format: "date-time" },
          committedAt: { type: "string", format: "date-time" },
        },
      },
      ConfigDigestRotationRequest: {
        type: "object",
        additionalProperties: false,
        required: [
          "rotationId",
          "expectedLeader",
          "expectedEpoch",
          "expectedCurrentDigest",
          "candidateDigest",
        ],
        properties: {
          rotationId: { type: "string", format: "uuid" },
          expectedLeader: {
            type: "string",
            pattern: "^[a-zA-Z0-9._-]{1,128}$",
          },
          expectedEpoch: { type: "integer", minimum: 1 },
          expectedCurrentDigest: {
            type: "string",
            pattern: "^[a-f0-9]{64}$",
          },
          candidateDigest: {
            type: "string",
            pattern: "^[a-f0-9]{64}$",
            description: "Must differ from expectedCurrentDigest.",
          },
          operatorOverride: {
            allOf: [{ $ref: "#/components/schemas/ConfigDigestRotationOperatorOverride" }],
            description:
              "Required only for the explicit standalone-primary manual override; signed into the expiring preparation.",
          },
        },
      },
      ConfigDigestRotationOperatorOverride: {
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
      ConfigDigestRotationReceipt: {
        type: "object",
        additionalProperties: false,
        required: [
          "apiVersion",
          "decision",
          "rotationId",
          "requestDigest",
          "currentLeader",
          "fabricEpoch",
          "previousConfigDigest",
          "configDigest",
          "candidateHosts",
          "preparationTokenHash",
          "committedAt",
        ],
        properties: {
          apiVersion: {
            type: "string",
            const: "execution-fabric-leadership/v1",
          },
          decision: { type: "string", const: "config_digest_rotated" },
          rotationId: { type: "string", format: "uuid" },
          requestDigest: {
            type: "string",
            pattern: "^[a-f0-9]{64}$",
          },
          currentLeader: { type: "string" },
          fabricEpoch: { type: "integer", minimum: 1 },
          previousConfigDigest: {
            type: "string",
            pattern: "^[a-f0-9]{64}$",
          },
          configDigest: {
            type: "string",
            pattern: "^[a-f0-9]{64}$",
          },
          operatorOverride: {
            $ref: "#/components/schemas/ConfigDigestRotationOperatorOverride",
          },
          candidateHosts: {
            type: "array",
            minItems: 1,
            description:
              "One exact current leader only in standalone-primary maintenance mode; at least two failover hosts otherwise.",
            uniqueItems: true,
            items: { type: "string" },
          },
          preparationTokenHash: {
            type: "string",
            pattern: "^[a-f0-9]{64}$",
          },
          committedAt: { type: "string", format: "date-time" },
        },
      },
      ConfigDigestRotationPreparation: {
        type: "object",
        additionalProperties: false,
        required: [
          "apiVersion",
          "decision",
          "rotationId",
          "requestDigest",
          "expectedLeader",
          "expectedEpoch",
          "expectedCurrentDigest",
          "candidateDigest",
          "candidateHosts",
          "expectedTimelineId",
          "expectedLeaderWalPosition",
          "expectedUpstreamSystemId",
          "minimumStandbyReplayWalPosition",
          "maxReplicaLagBytes",
          "preparationToken",
          "preparationTokenHash",
          "issuedAt",
          "expiresAt",
          "expiresAtEpoch",
        ],
        properties: {
          apiVersion: {
            type: "string",
            const: "execution-fabric-leadership/v1",
          },
          decision: {
            type: "string",
            const: "config_digest_rotation_prepared",
          },
          rotationId: { type: "string", format: "uuid" },
          requestDigest: { type: "string", pattern: "^[a-f0-9]{64}$" },
          expectedLeader: { type: "string" },
          expectedEpoch: { type: "integer", minimum: 1 },
          expectedCurrentDigest: {
            type: "string",
            pattern: "^[a-f0-9]{64}$",
          },
          candidateDigest: {
            type: "string",
            pattern: "^[a-f0-9]{64}$",
          },
          operatorOverride: {
            $ref: "#/components/schemas/ConfigDigestRotationOperatorOverride",
          },
          candidateHosts: {
            type: "array",
            minItems: 1,
            description:
              "One exact current leader only in standalone-primary maintenance mode; at least two failover hosts otherwise.",
            uniqueItems: true,
            items: { type: "string" },
          },
          expectedTimelineId: { type: "integer", minimum: 1 },
          expectedLeaderWalPosition: { type: "integer", minimum: 0 },
          expectedUpstreamSystemId: {
            type: "string",
            pattern: "^[0-9]{1,32}$",
          },
          minimumStandbyReplayWalPosition: {
            type: "integer",
            minimum: 0,
          },
          maxReplicaLagBytes: { type: "integer", minimum: 0 },
          preparationToken: {
            type: "string",
            pattern: "^cpr1\\.[A-Za-z0-9_-]+\\.[A-Za-z0-9_-]+$",
          },
          preparationTokenHash: {
            type: "string",
            pattern: "^[a-f0-9]{64}$",
          },
          issuedAt: { type: "string", format: "date-time" },
          expiresAt: { type: "string", format: "date-time" },
          expiresAtEpoch: { type: "integer", minimum: 1 },
        },
      },
      ConfigDigestRotationCommitRequest: {
        type: "object",
        additionalProperties: false,
        required: ["rotationId", "preparationToken"],
        properties: {
          rotationId: { type: "string", format: "uuid" },
          preparationToken: {
            type: "string",
            pattern: "^cpr1\\.[A-Za-z0-9_-]+\\.[A-Za-z0-9_-]+$",
          },
        },
      },
      ConfigDigestRotationAbortRequest: {
        type: "object",
        additionalProperties: false,
        required: ["rotationId", "preparationToken"],
        properties: {
          rotationId: { type: "string", format: "uuid" },
          preparationToken: {
            type: "string",
            pattern: "^cpr1\\.[A-Za-z0-9_-]+\\.[A-Za-z0-9_-]+$",
          },
        },
      },
      ConfigDigestRotationAbortReceipt: {
        type: "object",
        additionalProperties: false,
        required: [
          "apiVersion",
          "decision",
          "rotationId",
          "requestDigest",
          "currentLeader",
          "fabricEpoch",
          "configDigest",
          "candidateDigest",
          "evidenceHost",
          "preparationTokenHash",
          "expiredAt",
          "abortedAt",
        ],
        properties: {
          apiVersion: {
            type: "string",
            const: "execution-fabric-leadership/v1",
          },
          decision: {
            type: "string",
            const: "config_digest_rotation_aborted",
          },
          rotationId: { type: "string", format: "uuid" },
          requestDigest: { type: "string", pattern: "^[a-f0-9]{64}$" },
          currentLeader: { type: "string" },
          fabricEpoch: { type: "integer", minimum: 1 },
          configDigest: { type: "string", pattern: "^[a-f0-9]{64}$" },
          candidateDigest: {
            type: "string",
            pattern: "^[a-f0-9]{64}$",
          },
          evidenceHost: { type: "string" },
          preparationTokenHash: {
            type: "string",
            pattern: "^[a-f0-9]{64}$",
          },
          expiredAt: { type: "string", format: "date-time" },
          abortedAt: { type: "string", format: "date-time" },
        },
      },
    },
  },
  security: [{ adminBearerAuth: [] }],
  paths: {
    "/api/v1/admin/leadership/status": {
      get: {
        operationId: "leadershipStatus",
        description:
          "Leadership, candidate health, and the singleton unconsumed config-digest preparation with a dynamic expired flag.",
        responses: { "200": { description: "Leadership and candidate status" } },
      },
    },
    "/api/v1/admin/leadership/candidates/{candidate}": {
      put: {
        operationId: "updateLeadershipCandidate",
        description:
          "Publish applied configDigest health and, when staging a rotation, optional policyCandidateDigest and policyCandidateObservedAt.",
        requestBody: {
          required: true,
          content: {
            "application/json": {
              schema: { $ref: "#/components/schemas/CandidateUpdate" },
            },
          },
        },
        responses: { "200": { description: "Candidate observation receipt" } },
      },
    },
    "/api/v1/admin/leadership/promote": {
      post: {
        operationId: "promoteLeadershipCandidate",
        description:
          "Atomically CAS leadership and persist an idempotent receipt. Exact promotionId replays return the original receipt.",
        requestBody: {
          required: true,
          content: {
            "application/json": {
              schema: { $ref: "#/components/schemas/PromotionRequest" },
            },
          },
        },
        responses: {
          "200": {
            description: "Monotonic durable promotion and fence receipt",
            content: {
              "application/json": {
                schema: { $ref: "#/components/schemas/PromotionReceipt" },
              },
            },
          },
          "409": { description: "Stale or unsafe request" },
        },
      },
    },
    "/api/v1/admin/leadership/promotions/{promotionId}": {
      get: {
        operationId: "getLeadershipPromotion",
        description: "Read the durable receipt used to resume after response loss.",
        responses: {
          "200": {
            description: "Durable promotion receipt",
            content: {
              "application/json": {
                schema: { $ref: "#/components/schemas/PromotionReceipt" },
              },
            },
          },
          "404": { description: "Promotion receipt not found" },
        },
      },
    },
    "/api/v1/admin/leadership/config-digest-rotations/prepare": {
      post: {
        operationId: "prepareLeadershipConfigDigestRotation",
        description:
          "Validate fresh WAL-safe staged policy reports from every configured host and durably issue the cluster's singleton signed preparation without changing the witnessed digest. Exact replays return the existing preparation.",
        requestBody: {
          required: true,
          content: {
            "application/json": {
              schema: {
                $ref: "#/components/schemas/ConfigDigestRotationRequest",
              },
            },
          },
        },
        responses: {
          "200": {
            description:
              "Durable idempotent signed configuration-digest preparation",
            content: {
              "application/json": {
                schema: {
                  $ref: "#/components/schemas/ConfigDigestRotationPreparation",
                },
              },
            },
          },
          "400": { description: "Malformed or invalid request" },
          "401": { description: "Missing or invalid admin bearer token" },
          "409": {
            description:
              "Stale, replayed with conflicting content, or unsafe request",
          },
        },
      },
    },
    "/api/v1/admin/leadership/config-digest-rotations/commit": {
      post: {
        operationId: "commitLeadershipConfigDigestRotation",
        description:
          "Consume one exact signed preparation only after a fresh healthy non-leader proves the database applied the candidate digest. Expired preparations remain recoverable with that causal evidence.",
        requestBody: {
          required: true,
          content: {
            "application/json": {
              schema: {
                $ref: "#/components/schemas/ConfigDigestRotationCommitRequest",
              },
            },
          },
        },
        responses: {
          "200": {
            description:
              "Durable idempotent configuration-digest rotation receipt",
            content: {
              "application/json": {
                schema: {
                  $ref: "#/components/schemas/ConfigDigestRotationReceipt",
                },
              },
            },
          },
          "400": { description: "Malformed or invalid request" },
          "401": { description: "Missing or invalid admin bearer token" },
          "404": { description: "Preparation not found or already consumed" },
          "409": {
            description:
              "Stale, mismatched, conflicting, or missing applied standby evidence",
          },
        },
      },
    },
    "/api/v1/admin/leadership/config-digest-rotations/abort": {
      post: {
        operationId: "abortLeadershipConfigDigestRotation",
        description:
          "After expiry, consume an abandoned preparation only when a healthy non-leader observation, lag measurement, and receiver timestamp are all strictly post-expiry and prove the database remains on the old digest, while no configured non-leader reports the candidate digest.",
        requestBody: {
          required: true,
          content: {
            "application/json": {
              schema: {
                $ref: "#/components/schemas/ConfigDigestRotationAbortRequest",
              },
            },
          },
        },
        responses: {
          "200": {
            description: "Durable idempotent abort receipt",
            content: {
              "application/json": {
                schema: {
                  $ref: "#/components/schemas/ConfigDigestRotationAbortReceipt",
                },
              },
            },
          },
          "400": { description: "Malformed or invalid request" },
          "401": { description: "Missing or invalid admin bearer token" },
          "404": { description: "Preparation not found or already resolved" },
          "409": {
            description:
              "Preparation not expired, stale, mismatched, candidate applied, or missing old-digest standby evidence",
          },
        },
      },
    },
    "/api/v1/admin/leadership/config-digest-rotations/{rotationId}": {
      get: {
        operationId: "readLeadershipConfigDigestRotation",
        description:
          "Read back one durable configuration-digest rotation receipt.",
        parameters: [
          {
            name: "rotationId",
            in: "path",
            required: true,
            schema: { type: "string", format: "uuid" },
          },
        ],
        responses: {
          "200": {
            description: "Configuration-digest rotation receipt",
            content: {
              "application/json": {
                schema: {
                  $ref: "#/components/schemas/ConfigDigestRotationReceipt",
                },
              },
            },
          },
          "400": { description: "Malformed rotation identifier" },
          "401": { description: "Missing or invalid admin bearer token" },
          "404": { description: "Rotation receipt not found" },
        },
      },
    },
    "/api/v1/admin/leadership/config-digest-rotations/{rotationId}/preparation":
      {
        get: {
          operationId: "readLeadershipConfigDigestRotationPreparation",
          description:
            "Read back a durable pending or expired rotation preparation.",
          parameters: [
            {
              name: "rotationId",
              in: "path",
              required: true,
              schema: { type: "string", format: "uuid" },
            },
          ],
          responses: {
            "200": {
              description: "Configuration-digest rotation preparation",
              content: {
                "application/json": {
                  schema: {
                    $ref: "#/components/schemas/ConfigDigestRotationPreparation",
                  },
                },
              },
            },
            "400": { description: "Malformed rotation identifier" },
            "401": { description: "Missing or invalid admin bearer token" },
            "404": { description: "Rotation preparation not found" },
          },
        },
      },
    "/api/v1/admin/leadership/config-digest-rotations/{rotationId}/abort": {
      get: {
        operationId: "readLeadershipConfigDigestRotationAbort",
        parameters: [
          {
            name: "rotationId",
            in: "path",
            required: true,
            schema: { type: "string", format: "uuid" },
          },
        ],
        responses: {
          "200": {
            description: "Durable configuration-digest abort receipt",
            content: {
              "application/json": {
                schema: {
                  $ref: "#/components/schemas/ConfigDigestRotationAbortReceipt",
                },
              },
            },
          },
          "400": { description: "Malformed rotation identifier" },
          "401": { description: "Missing or invalid admin bearer token" },
          "404": { description: "Abort receipt not found" },
        },
      },
    },
    "/api/v1/admin/leadership/failback-plan": {
      post: {
        operationId: "planLeadershipFailback",
        responses: { "200": { description: "Approval-bound failback plan" } },
      },
    },
    "/api/v1/admin/leadership/failback-prepare": {
      post: {
        operationId: "authorizeLeadershipFailbackReseed",
        responses: {
          "200": { description: "Epoch-bound standby reseed authorization" },
          "409": { description: "Stale or unsafe source leadership" },
        },
      },
    },
    "/api/v1/admin/leadership/failback-commit": {
      post: {
        operationId: "commitLeadershipFailback",
        responses: {
          "200": { description: "Consumed plan and monotonic failback receipt" },
          "409": { description: "Stale, unsafe, or mismatched approval" },
        },
      },
    },
    "/api/v1/admin/leadership/audit": {
      get: {
        operationId: "leadershipAudit",
        responses: { "200": { description: "Durable audit records" } },
      },
    },
  },
} as const;
