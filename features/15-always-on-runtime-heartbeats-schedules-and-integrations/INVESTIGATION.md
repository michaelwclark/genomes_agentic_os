# Investigation

The existing installer already copies repository `templates/`, `harness/commands`, `harness/skills`, and `PLANS/` into `shared_factory/05-knowledge/`.

The missing runtime pieces were:

- `templates/runtime/heartbeat.yml`
- `templates/runtime/schedule.yml`
- `templates/runtime/execution-target.yml`
- `templates/runtime/integration.yml`
- `templates/runtime/run-queue-item.yml`
- `templates/notion/runtime-tracking-database-spec.md`
- `harness/commands/os-runtime-init.md`
- `harness/commands/os-heartbeat.md`
- `harness/commands/os-integration-setup.md`
- `harness/skills/runtime-operator/SKILL.md`
- `harness/skills/integration-setup/SKILL.md`
- file-backed CLI operations for runtime registries, heartbeat logs, run queue items, integration setup, and guarded Notion runtime tracking

The implementation keeps provider actions as local dry-run or setup records. That matches the plan's risk rules because the first runtime layer needs observable state before any external connector execution.
