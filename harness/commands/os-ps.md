# OS PS

Use when the operator needs a read-only snapshot of active Agentic OS runtime and workflow state.

## Command

```bash
agentic-os ps --root ~/agentic_os
agentic-os ps --root ~/agentic_os --active
agentic-os ps --root ~/agentic_os --all
agentic-os ps --root ~/agentic_os --json
agentic-os ps --root ~/agentic_os --active --color always
```

## Shows

- By default: only work that is running right now from live quiet-run process state and `running` run-queue rows.
- With `--active`: queued work, enabled schedules and heartbeats, enabled connected-source watches, managed automation-control gates, active-work automation links, active project workflow packets, and stale thread closeout candidates.
- With `--all`: disabled and terminal registry/queue rows for audit.

## Guardrails

- This command is read-only.
- It does not run probes, dispatch queued work, write receipts, or query external systems.
- Default mode intentionally hides backlog and configured-but-idle surfaces.
- Use `--active` when you want the broader operating dashboard.
- Use `--all` when auditing the full configured surface.

## Output

The default output is a grouped, colorized table for humans when the terminal supports ANSI color. Use `--json` for automation-friendly row data and rollup counts.
