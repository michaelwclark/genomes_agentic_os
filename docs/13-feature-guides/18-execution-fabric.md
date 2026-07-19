# 18 · Execution Fabric

Capture the selected backend at one moment without mutating it:

```bash
agentic-os runtime snapshot --root ~/agentic_os
agentic-os runtime snapshot --queue codex --status queued --json --root ~/agentic_os
agentic-os runtime snapshot --output runtime-snapshot.json --root ~/agentic_os
```

The snapshot contains aggregate status, named queues, worker pools, safe worker
metadata, and a bounded task sample. Command Center consumes the same contract
for its interactive Execution Fabric detail view. Fabric reads use one SQLite
read transaction and filesystem reads use one parsed YAML document, so totals
and rows describe the same instant. Raw task payloads, commands, prompts,
references, free-form failure text, and lease tokens are intentionally not
projected. Command Center labels its latest-200 task sample and applies filters
only to that sample; the CLI supports queue/status filtering and `--all` when
an exhaustive receipt is required.

Execution Fabric is an optional shared OSProgram for named queues and bounded
worker pools. It is installed into every Agentic OS root, but presence never
activates it:

```toml
enabled = false

[runtime]
queue_mode = "filesystem"
```

This preserves existing installs and upgrades. If `runtime.queue_mode` is
missing from the installed runtime registry, the effective mode is still
`filesystem`.

## What ships

The source-owned program is under
`harness/shared_factory/00-programs/execution_fabric/`. It contains:

- inactive, bounded queue definitions for Codex, Claude, and non-LLM work;
- matching worker-pool definitions with worker, task, lease, and retry limits;
- JSON Schemas for queue configuration, worker pools, and task envelopes;
- routing, CRUD, runbook, testing, and rollback contracts.

Mutable state never lives in that program folder. Filesystem mode owns
`run-queue.yml`; execution-fabric mode owns the `run_queue`, queue, pool, and
worker tables in `state.db`.

## Selecting the writer

Inspect and preflight first:

```bash
agentic-os runtime queue-mode status --root ~/agentic_os
agentic-os runtime queue-mode plan execution_fabric --root ~/agentic_os
agentic-os runtime queue-mode apply execution_fabric --root ~/agentic_os
```

The final command above is still a dry-run. Apply explicitly:

```bash
agentic-os runtime queue-mode apply execution_fabric \
  --root ~/agentic_os --apply
```

Activation imports the existing YAML queue idempotently, initializes the local
SQLite schema, writes the selector atomically, and reads it back. Producers and
`runtime run-next` then use only the selected backend. A shared advisory lock
serializes queue mutation with mode changes.

If activation finds historical nonterminal SQLite rows that are missing from or
status-drifted against YAML, it refuses the switch. Reconcile from filesystem
mode before trying again:

```bash
agentic-os runtime queue-mode reconcile --root ~/agentic_os
agentic-os runtime queue-mode reconcile --root ~/agentic_os --apply
```

Reconcile is dry-run-first. Apply archives the exact affected rows, cancels only
missing stale nonterminal rows, aligns status drift to filesystem authority,
clears their leases, and writes a terminal receipt. It never deletes history.

## Admission and recovery

The SQLite substrate uses WAL mode and `BEGIN IMMEDIATE` transactions. A claim
must satisfy all of these limits before it changes a task from `queued` to
`running`:

- queue concurrency;
- worker-pool concurrency and maximum active workers;
- individual worker capacity and live worker lease;
- task due time and task lease availability.

`admission.max_interactive_running` separately caps native Command Center turns
only while `execution_fabric` is selected. Filesystem mode retains the legacy
uncapped cross-conversation behavior.

At capacity, the task remains queued. Heartbeats extend worker and task leases.
Expired work is requeued until its attempt budget is exhausted, then moves to a
dead-letter state or configured dead-letter queue. Completion, retry,
cancellation, and pruning clear or respect leases transactionally.

## Rollback

Rollback is also dry-run-first:

```bash
agentic-os runtime queue-mode rollback --root ~/agentic_os
agentic-os runtime queue-mode rollback --root ~/agentic_os --apply
```

Rollback is rejected if an active lease exists or if queued/running work exists
only in SQLite. This first slice does not pretend that an unsafe reverse export
has happened.

## Backend boundary

SQLite is the included coordinator because it provides safe local concurrency
without another service. Temporal remains the intended durable cross-host
adapter/pilot boundary. Celery is not an installation dependency. Producers use
the Agentic OS enqueue contract so a later backend adapter does not require each
workflow, automation, program, or interactive session to call a vendor API.
