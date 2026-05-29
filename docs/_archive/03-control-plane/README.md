# Control Plane

Notion is the human cockpit. It should show what exists, what is waiting, what is running, and what needs approval.

Notion should not be treated as the only durable execution layer for high-volume changing state. It is excellent for visibility, approvals, and structured review. Use a database when state needs locking, dedupe, replay, or high-volume querying.

The control plane exists for people. The filesystem and future active state plane exist so agents and automations have durable execution records.

For the first top-level Notion cockpit, use `templates/notion/agentic-os-control-plane.md` and the bootstrap plan in `PLANS/10-notion-control-plane-bootstrap.md`. Filesystem OS state remains the source of truth; Notion is the dashboard, kickoff, approval, and review surface.

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

## Control Plane Data Flow

```text
raw input -> inbox -> work item -> workflow or automation run -> approval or done -> artifact links
```

Each Notion object should link back to source evidence:

| Notion Object | Should Link To |
| --- | --- |
| Inbox item | Raw message, note, ticket, PR, email, form submission, or manual prompt. |
| Work item | Domain, workflow, current run, owner, status, and next action. |
| Run | Filesystem run log, artifacts, validation evidence, and approval record. |
| Approval | Proposed external write, production change, customer-visible output, or permission escalation. |
| Decision | Decision record, source discussion, affected workflows, and review date. |

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

## Approval Discipline

Approval records should be explicit when a workflow or automation can:

- Send messages externally.
- Create, update, or close tickets.
- Change production state.
- Publish customer-visible content.
- Spend money or consume significant resources.
- Move data across security boundaries.

The approval record should include the proposed action, evidence, destination, rollback or correction path, and the exact human decision.

## What Notion Should Not Hide

Do not let the control plane become the only place where operational truth exists. A future agent should be able to reconstruct the work from:

- The source object.
- The domain context.
- The workflow or automation spec.
- The run log.
- The artifacts.
- The approval or decision record.

Notion can summarize that state, but it should not be the only copy of execution evidence.
