# Context Pack Builder

Use when preparing the minimum useful context for an agent run.

## Workflow

1. Load domain context and references.
2. Load project status and source map if a project is involved.
3. Load workflow or automation context files.
4. List exact source paths, URLs, tickets, or pages in `context-pack.md` or the run log.
5. Promote stable new sources back into `REFERENCES.md` or `source-map.md`.

## Guardrails

Do not paste secrets or large private documents into context packs. Link to sources instead.
