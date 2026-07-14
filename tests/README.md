# Tests

The pytest suite covers the Python CLI, installed-root scaffolding, templates,
harness assets, migrations, runtime state, and safety boundaries.

```bash
.venv/bin/python -m pytest -q
```

Focused tests should live beside the concern they verify by filename. Tests
that inspect repository navigation or packaged assets must use tracked paths,
not developer-specific absolute paths.
