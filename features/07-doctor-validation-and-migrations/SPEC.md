# Spec

Add deeper runtime health checks and explicit migration planning.

## Commands

```bash
agentic-os doctor --root ~/agentic_os
agentic-os doctor --root ~/agentic_os --fix-missing
agentic-os migrate plan --root ~/agentic_os
agentic-os migrate apply <migration_id> --root ~/agentic_os
```

## Acceptance

- Doctor reports validation, active work, project, workflow, automation, and run-log findings by severity.
- `--fix-missing` only runs additive managed-file repairs.
- Migration plan records purpose, affected file, preview diff, rollback note, and approval requirement.
- Migration apply fails if the target changed after preview.
