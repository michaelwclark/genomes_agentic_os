# 31 Holdout Command Validation For 06 Notion Control Plane Sync

Validate feature 06 through the public `agentic-os notion` CLI in a disposable
runtime root.

## Source Feature

- `features/06-notion-control-plane-sync/SPEC.md`
- `features/06-notion-control-plane-sync/HOLDOUT_QA.md`
- `src/genomes_agentic_os/notion_sync.py`

## Acceptance Mapping

- Sync planning discovers domains, projects, active work, workflows,
  automations, runs, approvals, decisions, and metrics.
- Apply refuses without a verified workspace.
- Genome roots require `Genome's Notion`.
- Apply stores a deterministic local mapping.
- Subsequent dry run reports no-op actions when source files are unchanged.
