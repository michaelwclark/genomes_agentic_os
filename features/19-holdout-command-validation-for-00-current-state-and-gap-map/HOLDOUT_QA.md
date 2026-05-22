# Holdout QA

Run from the repository root:

```bash
python features/19-holdout-command-validation-for-00-current-state-and-gap-map/scripts/validate_feature_00_holdout.py --repo .
uv run --extra dev pytest -q
```

The script must pass without requiring Notion credentials or writing to the Kanban board.
