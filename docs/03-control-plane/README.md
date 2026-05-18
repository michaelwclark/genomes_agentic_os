# Control Plane

Notion is the human cockpit. It should show what exists, what is waiting, what is running, and what needs approval.

Notion should not be treated as the only durable execution layer for high-volume changing state. It is excellent for visibility, approvals, and structured review. Use a database when state needs locking, dedupe, replay, or high-volume querying.

## Required Notion Areas

| Area | Purpose |
| --- | --- |
| OS Home | Landing page for the domain or client OS. |
| Inbox | Raw and classified incoming work. |
| Work Items | Human-readable active work queue. |
| Workflows | Reusable workflow definitions and links to filesystem specs. |
| Automations | Recurring or event-driven automation definitions. |
| Runs | Execution records for workflows, skills, and automations. |
| Approvals | Items requiring human authorization. |
| Decisions | Durable architectural and operating decisions. |
| Meeting Notes | Meeting inputs and extracted actions. |
| Artifacts | Links to files, PRs, docs, exports, reports, and outputs. |

## Notion Responsibilities

Notion should:

- Make state visible.
- Let the human approve, reject, or reroute work.
- Link operating objects together.
- Provide dashboards for daily operations.
- Hold readable specs and run summaries.

Notion should not:

- Be the only queue if automations need concurrency.
- Be the only source of truth for code or large artifacts.
- Store secrets.
- Replace Git for templates/specs.
- Replace a database for rapidly changing operational state.

## Meeting Notes Intake

Meeting notes are first-class inputs:

```text
meeting notes -> extracted actions/decisions/risks -> work items -> workflow or automation -> run log
```

The key is to preserve the raw notes, then create structured records for the actions that agents can execute.
