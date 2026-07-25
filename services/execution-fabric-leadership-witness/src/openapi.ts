export const openApiDocument = {
  openapi: "3.1.0",
  info: {
    title: "Agentic OS Execution Fabric Leadership Witness",
    version: "1.0.0",
    description:
      "Independent, authenticated, monotonic leadership and failback arbitration.",
  },
  components: {
    securitySchemes: {
      adminBearerAuth: {
        type: "http",
        scheme: "bearer",
        bearerFormat: "opaque",
      },
    },
  },
  security: [{ adminBearerAuth: [] }],
  paths: {
    "/api/v1/admin/leadership/status": {
      get: {
        operationId: "leadershipStatus",
        responses: { "200": { description: "Leadership and candidate status" } },
      },
    },
    "/api/v1/admin/leadership/candidates/{candidate}": {
      put: {
        operationId: "updateLeadershipCandidate",
        responses: { "200": { description: "Candidate observation receipt" } },
      },
    },
    "/api/v1/admin/leadership/promote": {
      post: {
        operationId: "promoteLeadershipCandidate",
        responses: {
          "200": { description: "Monotonic promotion and fence receipt" },
          "409": { description: "Stale or unsafe request" },
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
