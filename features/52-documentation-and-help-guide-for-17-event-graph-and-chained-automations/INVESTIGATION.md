# Investigation

Feature 17 adds a file-backed event ledger and chain processor.

The implementation lives in `src/genomes_agentic_os/event_graph.py` and is
exposed through `agentic-os event` and `agentic-os chain`. Runtime templates
live under `templates/runtime/`, the command prompts live at
`harness/commands/os-event.md` and `harness/commands/os-chain.md`, and the
operating skill lives at `harness/skills/event-graph-operator/SKILL.md`.

Tests in `tests/test_cli_scaffold.py` verify event append, ledger index
creation, chain test, dry-run processing, apply queue writes, idempotency,
dead-letter records, and run closeout event emission.
