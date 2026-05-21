# Spec

Add runtime checks that tell an agent whether a workflow is ready to run and add a closeout command that turns a run log into a durable audit record.

## Commands

```bash
agentic-os workflow check <domain> <lane> <workflow> --root ~/agentic_os
agentic-os run-log close <domain> <run-id> --status done|waiting|failed|needs_approval --root ~/agentic_os
```

## Acceptance

- Required workflow files and key sections are checked.
- Readiness findings use `blocker`, `fix-soon`, `cleanup`, and `observation` severities.
- Closing a run records final state, summary, validation, artifacts, approval gates, next action, owner, and learning.
- `done` closeout requires validation evidence.
- Closeout updates the domain activity log, workflow progress, and linked project status when supplied.
