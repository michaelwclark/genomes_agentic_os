# Holdout QA Results

Passed.

- `uv run --extra dev pytest -q`: `39 passed in 3.20s`.
- `uv run agentic-os notion bootstrap --root <temp-root> --dry-run`: returned a plan with `home_page: Agentic OS` and `databases`.
- `uv run agentic-os notion bootstrap --root <temp-root> --apply --verified-workspace "Genome's Notion"`: refused with `cannot bootstrap Notion control plane without an approved parent page id`.
- `uv run agentic-os notion bootstrap --root <temp-root> --apply --verified-workspace "Michael Clark" --parent-page-id <id>`: refused with `refusing Notion write`.
- `uv run agentic-os notion bootstrap --root <temp-root> --apply --verified-workspace "Genome's Notion" --parent-page-id <id>`: returned `applied: true`.
- Manifest check: `.notion-control-plane/manifest.yml` exists and includes `Genome's Notion`, the approved parent page id, and database mappings.
