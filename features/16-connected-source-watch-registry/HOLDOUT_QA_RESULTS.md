# Holdout QA Results

- `uv run --extra dev pytest -q`: 36 passed in 2.64s.
- Temp-root smoke: docs update restored `os-watch-source.md`, validation passed, a watch source was created, dry-run poll returned a normalized event, and apply wrote a local source event file.
