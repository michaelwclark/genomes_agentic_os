# Holdout QA

## Checks

- Run `uv run --extra dev pytest -q`.
- Create a temp installed root.
- Remove one newly managed command and one runtime template.
- Run `agentic-os docs update --root <temp-root>`.
- Run `agentic-os validate --root <temp-root>`.
- Run `agentic-os runtime init --root <temp-root>`.
- Run `agentic-os runtime doctor --root <temp-root>`.
- Dry-run `granola_recent_notes_sync`.
- Create and dry-run a schedule.
- Dry-run Granola integration setup.
- Dry-run Notion runtime tracking.
- Apply Notion runtime tracking only with `--verified-workspace "Genome's Notion"` and confirm a local manifest is written.
