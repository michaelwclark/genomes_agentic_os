# Holdout QA

Run the matrix recorded in `VALIDATION_LOG.md`, then run:

```bash
uv run --extra dev pytest -q
```

Verify docs include TOCs, how-to flows, config examples, and the SVG diagram.
