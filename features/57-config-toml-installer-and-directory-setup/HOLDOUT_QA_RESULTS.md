# Holdout QA Results

Passed.

- `uv run --extra dev pytest -q`: 44 passed in 3.10s.
- `uv run agentic-os config install --root /tmp/agentic-os-config-holdout --layer workflow_or_task --dry-run`: passed and reported planned files plus unified diff without writing the target directory.
