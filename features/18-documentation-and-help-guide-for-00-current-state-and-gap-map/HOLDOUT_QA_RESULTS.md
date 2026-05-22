# Holdout QA Results

Passed.

- `rg "Table Of Contents|shared_factory/05-knowledge/plans|PLANS/00-current-state-and-gap-map.md|uv run agentic-os validate" docs/13-feature-guides/00-current-state-and-gap-map.md`: found every required guide reference.
- `rg "Mermaid|mermaid" docs/13-feature-guides/00-current-state-and-gap-map.md`: no matches.
- `uv run pytest -q`: `39 passed in 3.13s`.

Residual risk: this documentation validates references and source-faithfulness,
not a fresh runtime install. Fresh install smoke coverage remains with the
separate holdout validation card.
