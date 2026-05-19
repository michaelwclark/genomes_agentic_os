# Notion Control Plane: <domain>

## OS Home

- Page title:
- Parent page:
- Page ID:
- Workspace:

## Databases

| Database | ID | Purpose |
| --- | --- | --- |
| Inbox |  | Raw and classified inputs. |
| Work Items |  | Active work queue. |
| Workflows |  | Workflow specs and status. |
| Automations |  | Automation specs and status. |
| Runs |  | Execution history. |
| Approvals |  | Human approval queue. |
| Decisions |  | Durable decisions. |
| Meeting Notes |  | Meeting inputs and extracted actions. |
| Artifacts |  | Outputs and evidence. |

## Required Views

- Active Work
- Waiting On Me
- Needs Approval
- Failed Runs
- Recent Decisions
- Meeting Actions
- Automation Health

## Sync Rules

- Filesystem specs are the source for workflow and automation definitions.
- Notion displays and links those specs.
- Notion approval decisions must be reflected in run logs.
- Notion IDs are stored in the domain's `domain.yml` or `05-knowledge/source-map.md`.
