# Holdout QA

## Checks

- Confirm the guide has a table of contents.
- Confirm the guide documents source/runtime separation.
- Confirm the guide names the runtime plan path and validation commands.
- Confirm no Mermaid diagram was added.

## Commands

```bash
rg "Table Of Contents|shared_factory/05-knowledge/plans|PLANS/00-current-state-and-gap-map.md|uv run agentic-os validate" docs/13-feature-guides/00-current-state-and-gap-map.md
rg "Mermaid|mermaid" docs/13-feature-guides/00-current-state-and-gap-map.md
```

