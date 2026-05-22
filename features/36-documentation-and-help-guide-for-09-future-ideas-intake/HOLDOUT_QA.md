# Holdout QA

```bash
rg "plan capture|--kind os|--kind domain|--kind customer|future-ideas|raw-ideas|status.md" docs/13-feature-guides/09-future-ideas-intake.md
uv run --extra dev pytest -q
```
