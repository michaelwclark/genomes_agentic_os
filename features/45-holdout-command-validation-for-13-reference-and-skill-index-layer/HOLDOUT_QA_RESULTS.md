# Holdout QA Results

Passed.

- `uv run --extra dev pytest -q`: `39 passed in 3.40s`.
- Initialized a disposable OS root.
- Confirmed runtime reference files exist under `shared_factory/05-knowledge/references/`.
- Confirmed reference templates exist under `shared_factory/05-knowledge/templates/reference/`.
- `uv run agentic-os context build --root <temp-root> --domain shared_factory` included naming, tool index, source priority, and style/output references.
- Confirmed `decision-log.md` is installed.
- `uv run agentic-os validate --root <temp-root>` returned `valid: <temp-root>`.
