# Holdout QA Plan

## Checks

- Verify the source plan exists at `PLANS/00-current-state-and-gap-map.md`.
- Verify the installed runtime plan index exists at `~/agentic_os/shared_factory/05-knowledge/plans/README.md`.
- Verify the installed runtime future ideas plan exists at `~/agentic_os/shared_factory/05-knowledge/plans/09-future-ideas-intake.md`.
- Run the repo tests.
- Run installed runtime validation.
- Confirm the Notion card can be updated in Genome's Notion.

## Commands

```sh
uv run pytest -q
uv run agentic-os validate --root "$HOME/agentic_os"
```
