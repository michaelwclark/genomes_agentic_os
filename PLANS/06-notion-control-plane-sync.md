# Feature Spec: Notion Control Plane Sync

## Status

- Status: draft
- Owner: Genome
- Created: 2026-05-20
- Target OS layer: installed runtime and Notion control plane

## Problem

Notion is intended to be the human cockpit, but the filesystem remains the operational source of truth. There is no sync command that reflects domains, projects, approvals, runs, or metrics into Notion while preserving the workspace boundary.

## Outcome

Genome's Notion can show OS status, approvals, projects, and runs without becoming the only source of truth. Customer Notion workspaces are used only when explicitly configured and verified.

## Workspace Rule

Before any write, verify the target parent page or workspace is Genome's Notion unless the user explicitly names a customer workspace. Do not write to Michael Clark's personal Notion or a fallback workspace.

## Proposed Commands

```bash
agentic-os notion plan-sync --root ~/agentic_os
agentic-os notion sync --root ~/agentic_os --dry-run
agentic-os notion sync --root ~/agentic_os --apply
```

## Objects To Sync

- Domains.
- Projects.
- Active work.
- Workflows.
- Automations.
- Runs.
- Approvals.
- Metrics.
- Decisions.

## Required Files

- Domain `domain.yml` Notion IDs.
- Domain active work.
- Project `project.yml` and `status.md`.
- Run logs.
- Approval rules.

## Required Side Effects

- Dry run produces a reviewable sync plan.
- Apply records Notion IDs back to source files when new records are created.
- Files remain source of truth for routers, workflow specs, automation specs, run logs, and templates.

## Out Of Scope

- Notion as runtime database.
- Unverified workspace writes.
- Large binary artifact sync.

## Acceptance Criteria

- Sync refuses to write without verified Genome's Notion or explicitly configured customer Notion.
- Dry run lists create/update/no-op actions.
- Apply is idempotent.
- Tests cover mapping logic without live Notion credentials.

## Validation

- Unit tests for mapping and workspace guardrails.
- Manual dry run against a test parent page before any production write.
