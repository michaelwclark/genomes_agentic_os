# Holdout QA

Run:

```bash
uv run --extra dev pytest -q
uv run agentic-os config install --root /tmp/agentic-os-config-holdout --layer workflow_or_task --dry-run
```

Expected results:

- Test suite passes.
- Dry-run reports target files and a diff without creating the target directory.
- Existing configs keep local values unless the operator confirms conflicts.
- Backups are created only when requested.
