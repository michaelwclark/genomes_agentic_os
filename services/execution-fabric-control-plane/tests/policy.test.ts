import { writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { stringify } from "yaml";
import { PolicyError, PolicyManager } from "../src/policy.js";
import { createTestPolicy, testPolicyValue } from "./policy-fixture.js";

describe("canonical policy", () => {
  it("loads the shipped policy and admits every remote route", () => {
    const here = dirname(fileURLToPath(import.meta.url));
    const repository = resolve(here, "../../..");
    const policy = new PolicyManager(
      resolve(repository, "harness/config/execution-fabric.yml"),
      resolve(repository, "schemas/execution-fabric.schema.json"),
    );
    const payloads: Record<string, Record<string, unknown>> = {
      "llm.codex": {
        work_item_id: "cc-357",
        instruction_ref: "work-items/cc-357/instruction.md",
      },
      "llm.claude": {
        work_item_id: "cc-357",
        instruction_ref: "work-items/cc-357/instruction.md",
      },
      "los.team_pr.ai_review.v1": {
        repository: "example/repository",
        pull_request: 42,
        pull_request_url: "https://github.com/example/repository/pull/42",
        expected_head_sha: "a".repeat(40),
        author_identity: "github:michaelwclark",
        base_branch: "develop",
        source_key: "FLYWL-42",
        title: "Review the change",
        notion_page_id: "00000000000000000000000000000001",
      },
      "los.environment.deployment.observed": {
        environment: "beta",
        sha: "a".repeat(40),
        previous_sha: "b".repeat(40),
        observed_at: "2026-07-24T00:00:00Z",
        health_url: "https://beta.example.invalid/health_check",
      },
      "los.jira.action.execute": {
        action_id: "action-42",
        action_key: "FLYWL-42:env_beta",
      },
    };

    for (const route of policy.effective().execution_fabric.task_routes) {
      if (!route.execution.remote_allowed) continue;
      const admitted = policy.normalizeAdmission({
        namespace: "test",
        queue: route.queue,
        taskType: route.task_type,
        idempotencyKey: `route:${route.task_type}`,
        payload: payloads[route.task_type]!,
        requiredCapabilities: [],
      });
      expect(admitted.taskType).toBe(route.task_type);
      if (route.execution.required_capability) {
        expect(admitted.requiredCapabilities).toContain(
          route.execution.required_capability,
        );
      }
    }

    const missingAuthor = { ...payloads["los.team_pr.ai_review.v1"] };
    delete missingAuthor.author_identity;
    expect(() =>
      policy.normalizeAdmission({
        namespace: "test",
        queue: "pr_reviews",
        taskType: "los.team_pr.ai_review.v1",
        idempotencyKey: "team-pr:missing-author",
        payload: missingAuthor,
        requiredCapabilities: [],
      }),
    ).toThrow(/requires payload field author_identity/);
  });

  it("publishes stable provenance and policy-derived defaults", () => {
    const { policy, source } = createTestPolicy();
    const snapshot = policy.snapshot();
    expect(snapshot.source).toBe(source);
    expect(snapshot.appliedFingerprint).toMatch(/^[0-9a-f]{64}$/);
    expect(snapshot.state).toBe("applied");

    const admitted = policy.normalizeAdmission({
      namespace: "test",
      queue: "code",
      taskType: "example.run",
      idempotencyKey: "one",
      payload: {},
      requiredCapabilities: [],
    });
    expect(admitted.maxAttempts).toBe(4);
    expect(admitted.priority).toBe(50);
  });

  it("accepts personal fallback policy and validates its strict bounds", () => {
    const { policy } = createTestPolicy((value) => {
      value.execution_fabric.transport.mode = "remote_with_local_fallback";
      value.execution_fabric.transport.fallback = {
        failure_threshold: 3,
        state_path: "runtime/execution-fabric-fallback.json",
      };
    });
    expect(policy.effective().execution_fabric.transport?.mode).toBe(
      "remote_with_local_fallback",
    );

    for (const fallback of [
      { failure_threshold: 1, state_path: "runtime/fallback.json" },
      {
        failure_threshold: 3,
        state_path: "runtime/fallback.json",
        surprise: true,
      },
    ]) {
      const { source, value } = createTestPolicy();
      value.execution_fabric.transport.fallback = fallback;
      writeFileSync(source, stringify(value));
      expect(
        () => new PolicyManager(source, "/schemas/execution-fabric.schema.json"),
      ).toThrow(/Unrecognized key|invalid policy|greater than or equal to 2/);
    }
  });

  it("requires an exact standalone-primary opt-in and host identity", () => {
    const { policy } = createTestPolicy((value) => {
      value.execution_fabric.standalone_primary = {
        enabled: true,
        host_id: "genomesbox",
      };
    });
    expect(policy.effective().execution_fabric.standalone_primary).toEqual({
      enabled: true,
      host_id: "genomesbox",
    });

    for (const standalone of [
      { enabled: true, host_id: "" },
      { enabled: true, host_id: "genomesbox", surprise: true },
    ]) {
      const { source, value } = createTestPolicy();
      value.execution_fabric.standalone_primary = standalone;
      writeFileSync(source, stringify(value));
      expect(
        () => new PolicyManager(source, "/schemas/execution-fabric.schema.json"),
      ).toThrow(/Unrecognized key|invalid policy|at least 1 character/);
    }
  });

  it("rejects unknown fields, queues, task types, and excessive retries", () => {
    const value = testPolicyValue() as Record<string, any>;
    value.execution_fabric.surprise = true;
    const { source } = createTestPolicy();
    writeFileSync(source, stringify(value));
    expect(
      () => new PolicyManager(source, "/schemas/execution-fabric.schema.json"),
    ).toThrow(/Unrecognized key|invalid policy/);

    const { policy } = createTestPolicy();
    expect(() =>
      policy.normalizeAdmission({
        namespace: "test",
        queue: "missing",
        taskType: "example.run",
        idempotencyKey: "unknown",
        payload: {},
        requiredCapabilities: [],
        priority: 0,
      }),
    ).toThrow(PolicyError);
    expect(() =>
      policy.normalizeAdmission({
        namespace: "test",
        queue: "code",
        taskType: "wrong",
        idempotencyKey: "wrong",
        payload: {},
        requiredCapabilities: [],
        priority: 0,
      }),
    ).toThrow(/not accepted/);
    expect(() =>
      policy.normalizeAdmission({
        namespace: "test",
        queue: "code",
        taskType: "example.run",
        idempotencyKey: "retries",
        payload: {},
        requiredCapabilities: [],
        priority: 0,
        maxAttempts: 5,
      }),
    ).toThrow(/exceeds queue policy/);
  });

  it("fails closed on disk drift until an explicit reload succeeds", () => {
    const { policy, source, value } = createTestPolicy();
    value.execution_fabric.queues[0].concurrency.max_queued = 5;
    writeFileSync(source, stringify(value));
    expect(policy.check().state).toBe("drifted");
    expect(() =>
      policy.normalizeAdmission({
        namespace: "test",
        queue: "code",
        taskType: "example.run",
        idempotencyKey: "blocked",
        payload: {},
        requiredCapabilities: [],
        priority: 0,
      }),
    ).toThrow(/explicit reload/);
    expect(policy.reload().lastReloadStatus).toBe("succeeded");
    expect(policy.snapshot().state).toBe("applied");
  });

  it("lets long-running roles adopt only the database-approved disk fingerprint", () => {
    const { policy, source, value } = createTestPolicy();
    const original = policy.snapshot().appliedFingerprint;
    value.execution_fabric.degraded_primary.allow_scheduler = true;
    writeFileSync(source, stringify(value));
    const candidate = policy.prepareReload().candidateFingerprint;

    expect(() =>
      policy.synchronizeApprovedFingerprint(original),
    ).toThrow(/differs from the applied policy/);
    expect(
      policy.effective().execution_fabric.degraded_primary.allow_scheduler,
    ).toBe(false);
    const synchronized =
      policy.synchronizeApprovedFingerprint(candidate);
    expect(synchronized.appliedFingerprint).toBe(candidate);
    expect(synchronized.state).toBe("applied");
    expect(
      policy.effective().execution_fabric.degraded_primary.allow_scheduler,
    ).toBe(true);
    expect(() =>
      policy.synchronizeApprovedFingerprint("f".repeat(64)),
    ).toThrow(/database-approved fingerprint/);
  });

  it("enforces queue to pool capability and worker capacity mapping", () => {
    const { policy } = createTestPolicy();
    expect(() =>
      policy.validateWorker({
        bootstrapId: "host-a.code.worker-a",
        workerId: "worker-a",
        hostId: "host-a",
        queues: ["code"],
        capabilities: [],
        maxConcurrency: 1,
        metadata: {},
      }),
    ).toThrow(/missing required capabilities/);
    expect(() =>
      policy.validateWorker({
        bootstrapId: "host-a.code.worker-a",
        workerId: "worker-a",
        hostId: "host-a",
        queues: ["code"],
        capabilities: ["test.run"],
        maxConcurrency: 2,
        metadata: {},
      }),
    ).toThrow(/max_tasks_per_worker/);
    expect(
      policy.validateWorker({
        bootstrapId: "host-a.code.worker-a",
        workerId: "worker-a",
        hostId: "host-a",
        queues: ["code"],
        capabilities: ["test.run"],
        maxConcurrency: 1,
        metadata: {},
      }).id,
    ).toBe("code_workers");
  });

  it("applies canonical host overrides by stable id and rejects unsafe aliases", () => {
    const previousHost = process.env.FABRIC_HOST_ID;
    process.env.FABRIC_HOST_ID = "bigmac";
    try {
      const { policy } = createTestPolicy((value) => {
        value.execution_fabric.host_overrides = {
          bigmac: {
            admission: { global_max_running: 1 },
            queues: [
              {
                id: "code",
                concurrency: { max_running: 1, max_queued: 1 },
              },
            ],
          },
        };
      });
      expect(
        policy.effective().execution_fabric.admission.global_max_running,
      ).toBe(1);
      expect(
        policy.queue("code").concurrency.max_queued,
      ).toBe(1);
      expect(policy.snapshot().appliedFingerprint).toMatch(/^[0-9a-f]{64}$/);

      expect(() =>
        createTestPolicy((value) => {
          value.execution_fabric.host_overrides = {
            unused_but_invalid: {
              admission: { global_max_running: 3 },
            },
          };
        }),
      ).toThrow(/may tighten but not increase capacity/);
    } finally {
      if (previousHost === undefined) delete process.env.FABRIC_HOST_ID;
      else process.env.FABRIC_HOST_ID = previousHost;
    }
  });
});
