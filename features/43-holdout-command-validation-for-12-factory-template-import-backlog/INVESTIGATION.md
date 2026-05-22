# Investigation

Feature 12 is validated through public CLI commands and direct filesystem
checks against a disposable installed root.

The holdout uses:

- `uv run --extra dev pytest -q`
- `uv run agentic-os init --target <temp-root>`
- `uv run agentic-os docs update --root <temp-root>`
- `uv run agentic-os validate --root <temp-root>`

The source factory import policy remains in `docs/12-factory-patterns/README.md`.
Runtime templates install under
`shared_factory/05-knowledge/templates/`.
