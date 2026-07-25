---
name: execution-fabric
description: Inspect, design, and validate the optional Agentic OS named-queue and bounded worker-pool program while preserving the filesystem queue default.
---

# Execution Fabric

Use this skill for Agentic OS queue-mode, named-queue, worker-pool, admission,
concurrency, lease, retry, or dead-letter design and readiness work.

## Procedure

1. Read the routed Agentic OS layer and
   `harness/shared_factory/00-programs/execution_fabric/`.
2. Read `harness/config/execution-fabric.yml` through
   `agentic-os runtime config status`; record its effective source and
   fingerprint. Read `runtime.queue_mode` separately as the single writer
   selector.
3. Inventory producers, work classes, queue depth, worker/provider capacity,
   claims, retries, approvals, and interactive capacity needs.
4. Keep vendor-specific backends behind the Agentic OS task and queue contract.
5. Require atomic claims, idempotency, bounded concurrency, leases, retry
   budgets, dead letters, observability, and rollback before activation.
6. Validate with `agentic-os runtime config validate`. Preview
   `runtime config reconcile`, then apply only while `execution_fabric` is the
   authoritative mode. Refresh program discovery after an approved change.

## Guardrails

- Do not enable the program merely because it is installed.
- Do not dual-write between queue modes without an explicit migration contract.
- Do not place mutable runtime state or secrets in the program definition.
- Do not silently launch work when the selected queue or provider is saturated.
- Do not copy host identity, host routing, or alert policy into Execution
  Fabric config; use the canonical dependency paths reported by config status.
