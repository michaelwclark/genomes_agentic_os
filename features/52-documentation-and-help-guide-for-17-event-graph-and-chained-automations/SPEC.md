# Spec

Add an operator-facing guide for feature 17, Event Graph And Chained
Automations.

The guide must describe installed runtime files, the event and chain command
surface, event append/list behavior, chain testing, dry-run/apply processing,
idempotency, dead letters, replay, run closeout event emission, validation, and
source artifacts.

Acceptance criteria:

- `docs/13-feature-guides/17-event-graph-and-chained-automations.md` exists.
- The guide references real feature 17 files and command surfaces.
- The guide does not use Mermaid.
- Build Runner artifacts exist for feature 52.
- Repository tests pass.
- A guide source-reference check passes.
