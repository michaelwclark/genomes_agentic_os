# 18 · Execution Fabric

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

## Admission and recovery

The SQLite substrate uses WAL mode and `BEGIN IMMEDIATE` transactions. A claim
must satisfy all of these limits before it changes a task from `queued` to
`running`:

- queue concurrency;
- worker-pool concurrency and maximum active workers;
- individual worker capacity and live worker lease;
- task due time and task lease availability.

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
