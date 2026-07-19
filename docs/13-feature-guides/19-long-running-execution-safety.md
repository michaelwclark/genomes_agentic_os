# Universal Long-Running Execution Safety

Agentic OS uses one contract for any local process expected to exceed two
minutes, regardless of whether the work is a command, test, build, install,
scan, sync, import, export, backfill, cleanup, watcher, deployment, or
migration.

## Why this exists

A detached PID and a large log are not enough. Operators need one place to see
what is truly running, whether it is making useful progress, how to pause or
stop it, and how to recover if the monitor or host exits.

The canonical central read surface is:

```text
harness/shared_factory/00-control-plane/long-running-runs.json
```

Each row links to an immutable per-run directory containing command metadata,
atomic state, a fsynced event journal, bounded rotating logs, preflight results,
post-run invariants, and a terminal receipt.

## Safety model

- Wall-clock and no-progress watchdogs stop open-ended work.
- CPU, RSS, log, and collateral-process budgets constrain host impact.
- Process-group pause, resume, and cancel cover children as well as the direct
  process.
- Mutating kinds declare their checkpoint/restart/rollback strategy and use a
  mutation lock or post-run invariant.
- High-risk bulk work proves bounded complexity and performance in preflight.
- Cooperative tools expose phase and item/file/byte progress through JSON.
- Non-cooperative tools still emit output-byte liveness and must explain safe
  restart or rollback.
- Orphan recovery marks stale registry rows without deleting historical logs.

Runtime queue dispatch automatically enrolls general subprocess commands whose
declared timeout exceeds the configured threshold. Existing callers therefore
gain the same registry, controls, budgets, bounded output, and terminal receipt
without embedding a second monitor. Purpose-built watchers keep their own
worker-state contract and must launch through the governed wrapper when their
`--once` controller can outlive the threshold.

## Command Center

GUI snapshots include active and recent long-running registry rows. Safety
pauses and watchdog terminals are visible without reading raw logs.

## Queue-mode incident guard

Execution-fabric activation now compares every nonterminal SQLite task with the
authoritative filesystem queue before switching. Activation refuses stale or
status-drifted rows. `runtime queue-mode reconcile` first archives the exact
affected rows, then cancels missing stale work or aligns status drift, leaving a
receipt before activation can proceed.

This prevents historical SQLite imports from becoming newly executable work.

## Configuration

`harness/config/long-running-execution.yml` controls the two-minute threshold,
default budgets, collateral ceilings, mutating/high-risk classifications, and
required terminal artifacts.
