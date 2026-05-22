# Holdout QA

Run a fresh temp-root command matrix:

```bash
uv run agentic-os init --target <temp-root>
rm <temp-root>/shared_factory/05-knowledge/commands/os-event.md
rm <temp-root>/shared_factory/05-knowledge/templates/runtime/event-envelope.yml
uv run agentic-os docs update --root <temp-root>
uv run agentic-os validate --root <temp-root>
uv run agentic-os event append --root <temp-root> --type github.pull_request.merged --source github:genomes_agentic_os:pull/123 --summary "PR 123 merged into main."
uv run agentic-os chain doctor --root <temp-root>
uv run agentic-os chain test feature_merged_to_docs_update --event <event-file> --root <temp-root>
uv run agentic-os event process-due --root <temp-root> --dry-run
uv run agentic-os event process-due --root <temp-root> --apply
uv run agentic-os event process-due --root <temp-root> --apply
uv run agentic-os event replay <event-id> --root <temp-root> --dry-run
```

Then add a broken enabled chain rule and confirm `chain doctor` fails and
`event process-due --apply` writes a dead-letter record.

Close a run log with event emission enabled and confirm an event file is
written.

Run full tests:

```bash
uv run --extra dev pytest -q
```
