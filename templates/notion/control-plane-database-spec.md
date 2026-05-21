# Notion Control Plane Database Spec: <os_or_customer>

## Workspace Gate

Verify the target workspace or parent page before creating or updating anything.

## Core Databases

| Database | Purpose | Required For MVP |
| --- | --- | --- |
| Work Items | Active queue across rooms, projects, workflows, and automations. | Yes |
| Runs | Execution history, validation evidence, outputs, and failures. | Yes |
| Approvals | Human review queue for risky actions. | Yes |
| Activity Log | Event stream consumed by operators and agents. | Yes |
| Sources | Repos, folders, Notion pages, Slack channels, dashboards, and tools. | Yes |
| Workflows | Reusable workflow catalog. | Later |
| Automations | Automation maturity, triggers, permissions, and health. | Later |
| Decisions | Durable decisions and rationale. | Later |

## Queue Database Properties

| Property | Type | Notes |
| --- | --- | --- |
| Name | Title | Human-readable work item. |
| Status | Status | State machine, not decoration. |
| Ready | Checkbox | Optional explicit trigger. |
| Priority | Select | High, Medium, Low. |
| Owner | Person/Text | Human owner or team. |
| Agent | Select/Text | Worker responsible for transition. |
| Source | Select/Text/URL | Where the item came from. |
| Output URL | URL | Published artifact, PR, doc, post, etc. |
| Notes | Rich text | Timestamped errors and human context. |
| Last Run | Date | Last agent attempt. |
| Retry Count | Number | Prevent infinite loops. |

## Activity Log Properties

| Property | Type | Notes |
| --- | --- | --- |
| Actor | Text/Select | Human, agent, script, or automation. |
| Type | Select | Tight event taxonomy. |
| Summary | Title/Text | Short event summary. |
| Detail | Rich text | Evidence and links. |
| Related | Relation/URL/Text | Work item, run, source, or artifact. |
| Created Time | Created time | Not manually edited. |

## Operating Rules

- Notion shows intent, state, approvals, and review.
- Files remain source of truth for routers, workflow specs, automation specs, templates, and run logs.
- Scripts should execute narrow transitions and record evidence.
- Customer-visible, production, destructive, billing, legal, or external-send actions need approval.
