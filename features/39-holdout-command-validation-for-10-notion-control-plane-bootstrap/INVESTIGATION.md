# Investigation

Feature 10 exposes the Notion control-plane bootstrap through:

- `agentic-os notion bootstrap --root <root> --dry-run`
- `agentic-os notion bootstrap --root <root> --apply --verified-workspace "Genome's Notion" --parent-page-id <page_id>`

The implementation builds the bootstrap plan in
`src/genomes_agentic_os/notion_sync.py` and writes local mapping state to:

```text
.notion-control-plane/manifest.yml
```

The holdout verifies command behavior through a disposable initialized OS root.
Genome's Notion was verified through the direct Notion API before the apply
case, and no token values were printed or persisted.
