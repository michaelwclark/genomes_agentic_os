# Holdout QA

Run:

```bash
uv run --extra dev pytest -q
```

Then verify:

- `docs/07-agent-surfaces/universal-agent-brain.md` names `AGENTS.md`,
  `CLAUDE.md`, `BRAIN.md`, `ROUTER.md`, `CONTEXT.md`, `MEMORY.md`, and
  workflow-local files.
- The guide explains universal, harness-specific, and generated files.
- The guide includes migration guidance and a nested prompt stitching example.
- `templates/agent-config/prompt-stitching-map.yml` includes root, customer,
  domain, and workflow layers.
