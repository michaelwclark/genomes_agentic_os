---
name: os-runtime-cold-recovery
description: Plan and perform one externally fenced offline standalone recovery.
---

# Manual cold recovery

`agentic-os runtime cold-recovery` implements a dedicated offline protocol for a complete recovery set and stopped restored stores. Normal standalone promotion/failback refusals remain intact.

Read [the operator runbook](../../docs/development/execution-fabric-cold-recovery.md) before use. Configure an exact cluster, allowed hosts, independent recovery/fence signing keys and qualified actor hashes in `harness/config/execution-fabric-cold-recovery.json`. The supplied policy is disabled. An old backup cannot establish its own freshness.

Every operation requires explicit `--request`, `--policy`, `--anchor`, `--journal-dir`, `--service-root` and `--database-url-file`. The service root resolves only the two fixed built cold recovery entrypoints; actual bytes must match the reviewed policy. A source build is distinct from an installed release.

`inspect` and `status` read only. Other operations default to a validated dry run; `--apply` executes the exact operation. `initialize-anchor` requires independent signed baseline evidence and refuses existing anchors. `prepare`, `approve`, `apply` and `resume` keep restored work held. `canary` and `accept` require the exact approved harmless canary and current authority. They do not authorize historical task/provider replay or reset the separate personal fallback latch.

Missing state, external fencing, freshness proof, signature, component hashes or current authority refuses recovery. Interrupted cross-store transitions retain a durable held journal and resume forward. Reverse failback is a second explicit fenced recovery with a new complete backup.

