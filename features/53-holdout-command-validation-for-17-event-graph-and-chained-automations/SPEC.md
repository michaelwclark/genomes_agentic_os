# Spec

Validate feature 17, Event Graph And Chained Automations, against the current
command surface.

Scope:

- Use a fresh temporary installed OS root.
- Confirm managed event knowledge can be restored by `agentic-os docs update`.
- Validate event append and ledger index creation.
- Validate chain doctor and chain test.
- Validate dry-run processing, apply queue writes, idempotency skips, and replay.
- Validate dead-letter records for a broken enabled chain rule.
- Validate run-log closeout event emission.
- Run the full source-package pytest suite.

Out of scope:

- External event ingestion.
- Provider-specific notification delivery.
- Changes to source implementation.

Acceptance criteria:

- The canonical Build Runner artifact set exists.
- Temp-root init succeeds.
- Removing `os-event.md` and `templates/runtime/event-envelope.yml`, then
  running docs update, restores both managed files.
- `validate` passes.
- `event append`, `chain doctor`, `chain test`, `event process-due --dry-run`,
  `event process-due --apply`, and `event replay` pass.
- Apply mode writes a `documentation_update` queue item.
- Repeated apply skips the already processed idempotency key.
- A broken enabled rule produces a dead-letter record.
- `run-log close --emit-events` writes event evidence.
- Full pytest passes from the worktree.
