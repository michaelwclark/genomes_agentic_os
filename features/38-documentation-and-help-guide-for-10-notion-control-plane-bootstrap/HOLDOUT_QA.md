# Holdout QA

```bash
rg "notion bootstrap|--dry-run|--apply|verified-workspace|parent-page-id|manifest.yml|Agentic OS" docs/13-feature-guides/10-notion-control-plane-bootstrap.md
uv run --extra dev pytest -q
```
