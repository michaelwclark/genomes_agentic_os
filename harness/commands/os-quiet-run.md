# Universal Long-Running Execution

Every command, test, build, install, scan, sync, import, export, backfill,
cleanup, watcher, deployment, or migration expected to exceed two minutes runs
through the governed long-run control plane.

## Start

```bash
agentic-os long-run start \
  --root <os-root> \
  --kind test \
  --label "full source suite" \
  --work-dir "$PWD" \
  --wall-clock-minutes 60 \
  --no-progress-minutes 15 \
  -- pytest -q
```

Mutating kinds require an explicit checkpoint/restart/rollback strategy plus a
mutation lock or post-run invariant. High-risk import, export, backfill,
cleanup, and migration runs also require a bounded preflight that records both
complexity and performance evidence:

```bash
agentic-os long-run start \
  --kind migration \
  --label "artifact migration" \
  --checkpoint-strategy "resume from journal or restore verified backup" \
  --mutation-lock artifact-migration.lock \
  --preflight-check "agentic-os naming migrate --preflight" \
  --post-run-check "agentic-os naming migrate" \
  --progress-file <run-dir>/progress.json \
  -- command --apply
```

## Control and recovery

```bash
agentic-os long-run list --root <os-root> --active
agentic-os long-run status --run-dir <run-dir>
agentic-os long-run pause --run-dir <run-dir>
agentic-os long-run resume --run-dir <run-dir>
agentic-os long-run cancel --run-dir <run-dir>
agentic-os long-run recover --root <os-root>
agentic-os long-run recover --root <os-root> --mark-stale
```

The compatibility wrapper `agentic-os-quiet-run` delegates to the same command.

## Durable contract

- Central registry:
  `harness/shared_factory/00-control-plane/long-running-runs.json`.
- Per-run state: `command.json`, atomic `state.json`, fsynced
  `events.jsonl`, bounded rotating `output.log`, `summary.md`, and an
  automatic `terminal-receipt.json`.
- Budgets: wall clock, no-progress, log size/rotations, CPU, RSS, and configured
  collateral processes such as `fseventsd`.
- Control: process-group pause, resume, graceful cancel, forced cancel after a
  bounded grace period, signal-safe interruption, and orphan recovery.
- Progress: phase plus item/file/byte counters from a cooperative progress file;
  output bytes provide a liveness fallback for non-cooperative tools.
- Completion: post-run checks are recorded and can change a nominal exit-zero
  into a failed terminal receipt.

Configuration: `harness/config/long-running-execution.yml`.
