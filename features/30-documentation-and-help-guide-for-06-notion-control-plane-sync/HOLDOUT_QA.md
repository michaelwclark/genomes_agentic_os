# Holdout QA

1. Check guide references:

   ```bash
   rg "plan-sync|--dry-run|--apply|verified-workspace|Genome's Notion|source of truth|mapping" docs/13-feature-guides/06-notion-control-plane-sync.md
   ```

2. Run the full test suite:

   ```bash
   uv run --extra dev pytest -q
   ```

3. Confirm the guide index links to `06-notion-control-plane-sync.md`.
