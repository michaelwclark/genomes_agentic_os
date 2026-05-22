# Holdout QA Results

Passed.

- `uv run --extra dev pytest -q`: 46 passed in 3.16s.
- `agentic-os config doctor` on an installed `agentic_os_root` config: passed.
- Secret-safe OTEL/MCP content check: passed for env var name references and
  no sample token/password values in docs, templates, or config operation code.
