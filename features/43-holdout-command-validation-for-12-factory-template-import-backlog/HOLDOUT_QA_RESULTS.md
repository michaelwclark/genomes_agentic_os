# Holdout QA Results

Passed.

- `uv run --extra dev pytest -q`: `39 passed in 3.17s`.
- Initialized a disposable OS root.
- Removed `shared_factory/05-knowledge/templates/room/context.md`.
- `uv run agentic-os docs update --root <temp-root>` restored the missing room template.
- `uv run agentic-os validate --root <temp-root>` returned `valid: <temp-root>`.
- Confirmed runtime template families exist for room, stage, reference, profile, and customer templates.
- Confirmed `docs/12-factory-patterns/README.md` includes copied/adapted/referenced/rejected policy terms.
- Confirmed customer-facing template text does not include scanned private source names.
