---
name: quiet-async-runner
description: Govern any local process expected to exceed two minutes through a central durable registry, bounded logs and resources, semantic progress, pause/resume/cancel, recovery, terminal receipts, and quiet chat.
---

# Universal Long-Running Execution Safety

Use this skill for commands, tests, builds, installs, scans, syncs, imports,
exports, backfills, cleanup, watchers, deployments, and migrations expected to
run longer than two minutes.

## Required route

1. Start with `agentic-os long-run start` or the compatibility
   `agentic-os-quiet-run start` wrapper.
2. Set an explicit kind and wall-clock/no-progress budgets.
3. For mutating kinds, declare the checkpoint/restart/rollback strategy and a
   mutation lock or post-run invariant.
4. For import, export, backfill, cleanup, and migration, provide a bounded
   preflight that records complexity and performance evidence before apply.
5. Provide a cooperative progress JSON file when the tool supports phase,
   item, file, or byte counters.
6. Add collateral process ceilings for tools that can pressure `fseventsd`,
   Docker, indexing, or other host services.

## Operator controls

- `agentic-os long-run list --active` is the central source for running work.
- `status` reads one atomic run state.
- `pause`, `resume`, and `cancel` control the full child process group.
- `recover` detects orphaned registry rows and `--mark-stale` repairs them.
- A non-cooperative tool must still declare how it safely restarts, resumes
  from a checkpoint, or rolls back.

## Chat contract

- Emit one start message with the run directory.
- Do not narrate polling, percentages, or ETA guesses.
- Speak only for a terminal result, blocker, safety pause, or user decision.
- Every pass/fail claim cites `terminal-receipt.json`; inspect large logs with
  context-mode rather than copying them into chat.

## Artifacts

```text
<artifact-root>/async-runs/<dated-run-id>/
  command.json
  state.json
  events.jsonl
  output.log
  output.log.1 ...
  preflight.json
  terminal-receipt.json
  summary.md
```

Never place secrets in command arguments or artifacts. Secret-looking flags are
refused; use the process environment.

Configuration: `harness/config/long-running-execution.yml`.
Command contract: `harness/commands/os-quiet-run.md`.
