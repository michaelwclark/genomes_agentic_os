# Spec

Add a guarded Notion sync planning surface that keeps filesystem files as the source of truth.

## Commands

```bash
agentic-os notion plan-sync --root ~/agentic_os
agentic-os notion sync --root ~/agentic_os --dry-run
agentic-os notion sync --root ~/agentic_os --apply --verified-workspace "Genome's Notion"
```

## Acceptance

- Sync planning discovers domains, projects, active work, workflows, automations, runs, approvals, decisions, and metrics.
- Dry run prints create/update/no-op actions without writing files.
- Apply refuses to run without a verified workspace.
- Genome roots require `Genome's Notion`; customer roots require their configured customer workspace.
- Apply stores a deterministic local mapping and subsequent dry runs become no-op when source files are unchanged.
