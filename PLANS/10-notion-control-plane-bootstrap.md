# Feature Spec: Notion Control Plane Bootstrap

## Status

- Status: ready
- Owner: Genome
- Created: 2026-05-20
- Target OS layer: Genome's Notion and installed runtime

## Current Blocker

The Notion connector is currently returning `UNAUTHORIZED`, so no workspace could be verified and no Notion pages or databases were created.

Do not create fallback pages in another workspace. Resume only after the active connector can verify Genome's Notion or the user provides a Genome's Notion parent page URL.

## Problem

The filesystem OS has routers, workflows, automations, run logs, plans, and templates, but the human control plane is not testable yet. The user needs a top-level Notion surface where they can see what is happening, kick off work, approve risky actions, inspect outputs, and understand what each agent or automation did.

## Outcome

Create a top-level Notion page named `Agentic OS` in Genome's Notion with the minimum databases and views needed to operate the OS day to day.

## Bootstrap Flow

```text
verify Genome's Notion
  -> create Agentic OS home page
  -> create core databases
  -> add dashboard views
  -> seed records from ~/agentic_os
  -> write Notion IDs back to OS files
  -> dry-run sync
```

## Workspace Gate

Before writing:

1. Fetch the current Notion user.
2. Search for known Genome pages, such as `Genome's Harness`.
3. Fetch or use the user-provided Genome's Notion parent page.
4. Confirm the parent is in Genome's Notion.
5. Stop if the connector is unauthorized or appears to be Michael Clark's personal workspace.

## Minimum Viable Control Plane

Create these first:

| Object | Purpose |
| --- | --- |
| `Agentic OS` page | Top-level operating cockpit. |
| `OS Inbox` database | Capture requests, rough ideas, Slack/email/Jira inputs, and kickoff records. |
| `Work Items` database | Active work queue across domains, projects, workflows, and automations. |
| `Runs` database | Execution history, validation evidence, artifacts, and final state. |
| `Approvals` database | Human approval queue for external, production, destructive, billing, legal, or customer-visible actions. |
| `Domains` database | Domain catalog with root paths, owners, source systems, and Notion IDs. |

Add these after the MVP works:

| Object | Purpose |
| --- | --- |
| `Workflows` database | Reusable workflow catalog and readiness state. |
| `Automations` database | Automation maturity, triggers, permissions, and health. |
| `Decisions` database | Durable decisions linked to runs and work items. |
| `Sources` database | Repositories, folders, Jira projects, Slack channels, docs, and dashboards. |
| `Artifacts` database | Outputs, summaries, files, PRs, deploy notes, and evidence links. |

## Required Dashboard Views

The top page should show:

- Needs Approval.
- Active Work.
- Waiting On Me.
- Running Or Failed Runs.
- Recent Outputs.
- Automation Health.
- Inbox To Triage.
- Decisions This Week.

## Kickoff Model

The first practical kickoff path should be a Notion inbox record:

```text
new OS Inbox row
  -> route to domain/lane/work type
  -> create or link Work Item
  -> create Run when dispatched
  -> update approval state if a gate is crossed
  -> attach outputs/artifacts
```

Notion should initiate and display work. The filesystem remains source of truth for routers, workflow specs, automation specs, templates, and run logs.

## Required Files In OS Runtime

- `~/agentic_os/ROUTER.md`
- `<domain>/domain.yml`
- `<domain>/00-control-plane/active-work.md`
- `<domain>/00-control-plane/approval-rules.md`
- `<domain>/06-runs-and-logs/activity-log.md`
- `<domain>/06-runs-and-logs/runs/*/run-log.md`

## Implementation Steps

1. Reauthorize the Notion connector.
2. Verify Genome's Notion and target parent page.
3. Create top-level `Agentic OS` page from `templates/notion/agentic-os-control-plane.md`.
4. Create MVP databases under the top-level page.
5. Add dashboard linked views to the top-level page.
6. Seed `Domains` from the installed OS.
7. Seed `Runs` from recent run logs.
8. Save created Notion page/database IDs into a local manifest before writing IDs into OS files.
9. Add a dry-run `agentic-os notion sync` plan before automated updates.

## Out Of Scope

- Treating Notion as the only source of truth.
- Creating pages in an unverified workspace.
- Running automations directly from Notion before approval and logging contracts exist.
- Customer workspace bootstrapping before Genome's Notion is proven.

## Acceptance Criteria

- Connector workspace is verified before any write.
- `Agentic OS` page exists under an approved Genome's Notion parent.
- MVP databases exist and have enough properties to route, approve, run, and inspect work.
- Top-level page includes dashboard views for work, approvals, runs, outputs, and inbox.
- At least one real run appears in the `Runs` database with a link back to a filesystem run log.
- Notion IDs are recorded in OS files or a manifest without overwriting local runtime edits.

## Validation

- Notion search/fetch confirms the parent page and created control-plane page.
- Notion query confirms each MVP database exists.
- Dry-run sync can read OS state and report create/update/no-op actions.
- A manual test work item can move from inbox to run to done without chat history.
