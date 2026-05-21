# Spec

Add a guarded Notion control-plane bootstrap manifest.

## Command

```bash
agentic-os notion bootstrap --root ~/agentic_os --dry-run
agentic-os notion bootstrap --root ~/agentic_os --apply --verified-workspace "Genome's Notion" --parent-page-id <page_id>
```

## Acceptance

- Bootstrap plan includes the `Agentic OS` home page, MVP databases, dashboard views, and recent run seeds.
- Apply requires verified workspace and approved parent page ID.
- Blocked personal Notion workspaces are refused.
- Apply writes `.notion-control-plane/manifest.yml` as local source-of-truth mapping state.
