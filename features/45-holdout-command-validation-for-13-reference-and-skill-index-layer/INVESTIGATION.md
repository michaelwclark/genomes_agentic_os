# Investigation

Feature 13 is validated through installed runtime files and the public context
builder command.

The holdout uses:

- `uv run --extra dev pytest -q`
- `uv run agentic-os init --target <temp-root>`
- `uv run agentic-os context build --root <temp-root> --domain shared_factory`
- `uv run agentic-os validate --root <temp-root>`

The context packet contract includes naming conventions, tool index, source
priority, and style/output references. `decision-log.md` is installed and
validated, but it is not part of the default context packet reference set.
