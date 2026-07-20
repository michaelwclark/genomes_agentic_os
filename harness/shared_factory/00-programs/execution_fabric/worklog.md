# Execution Fabric Worklog

## Baseline

- Source-distributed optional OSProgram established.
- Installed default remains inactive and filesystem-backed.
- Transactional named-queue backend, authoritative read adapters, and guarded
  mode migration are implemented behind `runtime.queue_mode`.
- All first-class producers converge on the shared enqueue boundary; stale YAML
  readers and the direct interim execution bypass were removed.
- The supervisor claims up to five tasks per tick and executes them concurrently
  under transactional admission. One of six total slots stays reserved for the
  native Command Center.
- Provider inference routes legacy shell-wrapped Codex/Claude work correctly;
  detached quiet-run and watcher children remain covered by their outer lease.
- Command Center and the local cockpit now show queue/worker health.
- Hourly health enforcement creates idempotent Codex self-heal work and governed
  local notifications for degraded or critical incidents.
- Added a backend-neutral point-in-time runtime snapshot command and an expanded
  Command Center Execution Fabric view with named queue depth, pool utilization,
  registered workers, task filters, and a safe task-detail drawer.
- Opposing review hardened the operator contract: one read transaction/document
  now backs each snapshot, free-form task details stay outside the renderer,
  receipt writers use unique temporary siblings, legacy GUI v1 snapshots remain
  valid, refreshes are single-flight/sequenced, and modal focus is contained and
  restored.
- Command Center now separates operational state from retained history: running
  work is explicit, task exploration defaults to active states, safe workload
  identifiers receive readable labels, and only live or unhealthy workers are
  projected as rows while retired ephemeral workers remain summarized history.
