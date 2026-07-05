# os-run-queue

Operate the file-backed runtime run queue.

## Commands

```bash
agentic-os run-queue prune --root ~/agentic_os --dry-run
agentic-os run-queue prune --root ~/agentic_os --apply
agentic-os runtime prune --root ~/agentic_os --dry-run
```

## Operating Rules

- Dry-run before rewriting the queue.
- Archive pruned queue rows under `shared_factory/06-runs-and-logs/run-queue-prune/` unless there is a specific reason to pass `--no-archive`.
- Use status-specific TTLs instead of deleting the whole queue: active rows default to 24 hours, done rows to 2 days, failed/blocked rows to 7 days, and skipped/dry-run rows to 1 day.
- Treat `run-queue.yml.backup*` files as temporary operational backups; the prune command removes backups older than the configured backup TTL.

## Expected Files

- Run queue: `shared_factory/00-control-plane/run-queue.yml`
- Prune archives: `shared_factory/06-runs-and-logs/run-queue-prune/`
- Runtime schedule: `shared_factory/00-control-plane/runtime-registry.yml` entry `run_queue_prune_daily`
