# Holdout QA

Run:

```bash
uv run --extra dev pytest -q
```

Run a source-reference check that verifies:

- inventory document exists
- layer map template exists
- required official source URLs are present
- required key terms are present
- local Codex version evidence is present
