# Holdout QA

Run these checks before merge:

```bash
uv run --extra dev pytest -q
```

Run a guide source-reference check that verifies:

- the feature 16 guide exists
- required command names appear in the guide
- required source files referenced by the guide exist
- the guide does not contain Mermaid syntax
