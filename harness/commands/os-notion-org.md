# Command: `agentic-os notion-org`

Use this before Notion reorganization, page moves, linked database setup, or dashboard cleanup.

## Commands

```bash
agentic-os notion-org doctor --root ~/agentic_os --backup-dir <backup-dir>
```

## Rules

- Run a local Notion backup before live page moves.
- Verify Genome's Notion before any Notion write.
- Treat filesystem work-items and OS runtime artifacts as source of truth.
- Use Notion for operator-facing dashboards, rows, summaries, and links.
- Tag old pages before moving them in batches.

## Canonical Buckets

- `Dashboard`
- `Specs`
- `Worklogs`
- `Active Work`
- `Automations`
- `Workflows`
- `Runs`
- `PRs`
- `Docs`
- `Archive`
