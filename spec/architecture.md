# Architecture

## Layers

| Layer | Responsibility |
| --- | --- |
| Scaffold package | This repo. Owns standards, templates, schemas, docs, and installers. |
| Installed OS | Live filesystem for domains, workflows, automations, context, and run logs. |
| Agent harnesses | Claude and Codex read OS specs and execute workflows. |
| Control plane | Notion exposes inboxes, approvals, dashboards, decisions, and run summaries. |
| Runtime state | Optional database for active queues, events, dedupe, locks, and replay. |
| Integrations | GitHub, Jira, Slack, email, calendar, Notion, Sentry, client APIs. |

## Request Lifecycle

| Step | Description | Durable Record |
| --- | --- | --- |
| 1 | External input arrives. | Inbox item. |
| 2 | Classifier assigns domain, lane, type, and allowed action level. | Work item. |
| 3 | Context builder assembles minimal source-backed context. | Context pack. |
| 4 | Agent selects workflow or automation. | Run record. |
| 5 | Execution happens with validation. | Artifacts and evidence. |
| 6 | Status updates and approval requests are written. | Notion and run log. |
| 7 | Next action is routed. | Work item state transition. |

## Source Of Truth Rules

- Specs, templates, and context packs live in Git/filesystem.
- Human operating state and approvals are visible in Notion.
- High-volume changing state lives in a database once needed.
- Agent memory accelerates retrieval but does not own active truth.
- Project code remains in project repos.

## V1 Runtime Assumption

V1 can operate without a database if the first workflows are mostly manual, low-concurrency, and file-backed. The architecture should still keep a clean path to a database-backed state plane.
