import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { stringify } from "yaml";
import { PolicyManager } from "../src/policy.js";

export function testPolicyValue(): Record<string, unknown> {
  return {
    schema_version: 1,
    execution_fabric: {
      standalone_primary: {
        enabled: false,
        host_id: "genomesbox",
      },
      degraded_primary: {
        allow_degraded_primary: false,
        max_duration_seconds: 3600,
        allowed_task_types: [],
        allowed_effect_types: [],
        allow_scheduler: false,
      },
      transport: {
        mode: "remote",
        control_plane_url: "http://127.0.0.1:3180",
        request_timeout_seconds: 20,
        long_poll_seconds: 0,
        submit_token_env: "TEST_SUBMIT_TOKEN",
        worker_token_env: "TEST_WORKER_TOKEN",
        observer_token_env: "TEST_OBSERVER_TOKEN",
        admin_token_env: "TEST_ADMIN_TOKEN",
      },
      admission: {
        global_max_running: 2,
        reserved_interactive_slots: 0,
        max_interactive_running: 1,
        provider_limits: { test: 1 },
      },
      task_routes: [
        {
          task_type: "example.run",
          queue: "code",
          scheduling_class: "background",
          execution: {
            remote_allowed: true,
            target: "domain_worker",
            required_capability: "test.run",
            command_template: null,
            domain_worker: "example_runner",
          },
          mutation_class: "internal_write",
          approval_class: "policy_gated",
          payload: {
            additional_properties: false,
            required: [],
            properties: {},
          },
          allowed_effect_types: ["example.effect"],
        },
      ],
      queues: [
        {
          id: "code",
          enabled: true,
          worker_pool: "code_workers",
          accepted_task_types: ["example.run"],
          priority: 50,
          concurrency: { max_running: 1, max_queued: 2 },
        },
      ],
      worker_pools: [
        {
          id: "code_workers",
          enabled: true,
          provider: "test",
          queues: ["code"],
          capabilities: ["test.run"],
          capacity: {
            min_workers: 0,
            max_workers: 10,
            max_tasks_per_worker: 1,
          },
          lease: { timeout_seconds: 120, heartbeat_seconds: 20 },
          retry: { max_attempts: 4, backoff_seconds: 15 },
        },
      ],
    },
  };
}

export function createTestPolicy(
  mutate?: (value: Record<string, any>) => void,
): { policy: PolicyManager; source: string; value: Record<string, any> } {
  const directory = mkdtempSync(join(tmpdir(), "fabric-policy-"));
  const source = join(directory, "execution-fabric.yml");
  const value = testPolicyValue() as Record<string, any>;
  mutate?.(value);
  writeFileSync(source, stringify(value));
  return {
    policy: new PolicyManager(source, "/schemas/execution-fabric.schema.json"),
    source,
    value,
  };
}
