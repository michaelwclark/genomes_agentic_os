# os-heartbeat

Operate runtime heartbeats from local registry files.

## Commands

```bash
agentic-os heartbeat list --root ~/agentic_os
agentic-os heartbeat run granola_recent_notes_sync --root ~/agentic_os --dry-run
agentic-os heartbeat doctor --root ~/agentic_os
agentic-os schedule create daily_agentic_os_doctor --root ~/agentic_os --cadence daily
agentic-os schedule run-due --root ~/agentic_os --dry-run
```

## Operating Rules

- Dry-run before any scheduled or provider-backed execution.
- Treat heartbeat logs as source-of-truth evidence for what ran.
- Use `schedule run-due` to queue intended work; do not directly execute external effects from chat.
- Link successful or blocked runs into Notion only through the guarded runtime tracking command.

## Expected Files

- Runtime registry: `shared_factory/00-control-plane/runtime-registry.yml`
- Run queue: `shared_factory/00-control-plane/run-queue.yml`
- Heartbeat logs: `shared_factory/06-runs-and-logs/heartbeats/`
