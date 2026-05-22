# Holdout QA

Run:

```bash
uv run --extra dev pytest -q
uv run --extra dev agentic-os validate-source --source .
tmpdir=$(mktemp -d)
uv run --extra dev agentic-os init --target "$tmpdir/os"
uv run --extra dev agentic-os validate --root "$tmpdir/os"
```

Expected:

- Pytest passes.
- Source validation exits zero with optional warnings until feature 55 assets are merged.
- Generated install validation exits zero and does not mutate after validation.
