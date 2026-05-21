# Feature Spec: Doctor, Validation, And Migrations

## Status

- Status: ready
- Owner: Genome
- Created: 2026-05-20
- Target OS layer: source package and installed runtime

## Problem

`agentic-os validate` checks required structure, but a running OS needs deeper health checks: stale active work, incomplete workflow specs, automations without permissions, run logs without final state, root-level drift, and installed files that need explicit migrations.

## Outcome

The OS can detect drift, propose safe repairs, and handle intentional file changes without violating the additive update contract.

## Commands

```bash
agentic-os doctor --root ~/agentic_os
agentic-os doctor --root ~/agentic_os --fix-missing
agentic-os migrate plan --root ~/agentic_os
agentic-os migrate apply <migration_id> --root ~/agentic_os
```

## Doctor Checks

- Required files and folders.
- Empty critical sections.
- Legacy root folders.
- Active work without next action.
- Projects without status or source map.
- Workflows without readiness.
- Automations without permissions, tests, logs, idempotency, or maturity.
- Run logs without final status.
- Archive candidates.
- Plans missing from shared knowledge.

## Migration Rules

- Default updates never overwrite installed runtime files.
- A migration must have an ID, purpose, affected files, preview diff, rollback note, and explicit approval requirement.
- Migration apply should fail if the target file changed after preview.

## Out Of Scope

- Automatic destructive cleanup.
- Auto-archiving without approval.
- Secret scanning.

## Acceptance Criteria

- Doctor reports severity as blocker, fix soon, cleanup, or observation.
- `--fix-missing` only creates missing managed files.
- Migration plan prints reviewable diffs.
- Migration apply requires an explicit migration ID.
- Tests cover missing files, stale run logs, and non-overwrite repair behavior.

## Validation

- `pytest -q`
- Temp OS with intentionally removed docs and incomplete run logs.
