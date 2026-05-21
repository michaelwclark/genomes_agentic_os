# os-runtime-init

Initialize file-backed runtime state for an installed Agentic OS.

## Command

```bash
agentic-os runtime init --root ~/agentic_os
agentic-os runtime doctor --root ~/agentic_os
```

## Use When

- The installed OS needs runtime registries for heartbeats, schedules, integrations, and run queues.
- A fresh install needs the runtime templates and plans copied into `shared_factory/05-knowledge/`.
- A runtime pilot needs deterministic local state before any connector or Notion write is attempted.

## Guardrails

- This command is additive and file-backed.
- It must not execute external provider actions.
- Notion writes remain blocked until `agentic-os notion track-runtime --apply` receives a verified Genome's Notion workspace.

## Output

The command creates or preserves:

- `shared_factory/00-control-plane/runtime-registry.yml`
- `shared_factory/00-control-plane/integration-registry.yml`
- `shared_factory/00-control-plane/run-queue.yml`
- `shared_factory/06-runs-and-logs/heartbeats/`
