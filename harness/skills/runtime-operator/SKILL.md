---
name: runtime-operator
description: Operate Genome's Agentic OS runtime registries, heartbeats, schedules, run queues, and guarded Notion runtime tracking from file-backed state.
---

# Runtime Operator

Use this skill when a task asks to initialize, inspect, dry-run, or diagnose the installed Agentic OS runtime.

## Workflow

1. Confirm the target root, defaulting to `~/agentic_os`.
2. Run `agentic-os runtime init --root <root>` if runtime registries are missing.
3. Inspect `shared_factory/00-control-plane/runtime-registry.yml` and `run-queue.yml`.
4. Prefer dry-run commands:
   - `agentic-os heartbeat run <heartbeat_id> --root <root> --dry-run`
   - `agentic-os schedule run-due --root <root> --dry-run`
5. Run `agentic-os runtime doctor --root <root>` or `agentic-os heartbeat doctor --root <root>` before treating the runtime as healthy.
6. Use `agentic-os notion track-runtime --root <root> --dry-run` before any apply.

## Guardrails

- Do not execute external effects from chat.
- Do not write to Notion until the workspace has been verified as Genome's Notion.
- Do not store credential values in runtime registries, run logs, or Notion tracking records.
- Keep heartbeat logs in `shared_factory/06-runs-and-logs/heartbeats/`.
