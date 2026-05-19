# Automations

An automation is a workflow with a trigger and enough guardrails to run without a fresh human prompt.

Automations should be conservative at first. Start by capturing, classifying, summarizing, and proposing action. Only mutate external systems after the approval and rollback rules are clear.

The best first automation is usually not "do the whole job." It is "watch the input, classify it correctly, draft the next action, and record evidence."

Automation specs live under the selected domain:

```text
<domain>/04-automations/<lane>/<automation>/
  automation.md
  inputs.md
  outputs.md
  permissions.md
  failure-modes.md
  runbook.md
  tests.md
  logs/
```

## Required Automation Sections

Every automation spec should include:

- Trigger.
- Schedule or event source.
- Allowed domains.
- Input filters.
- Idempotency key.
- Permissions.
- Context sources.
- Action policy.
- Approval gates.
- Output destinations.
- Retry policy.
- Failure policy.
- Audit log requirements.

## Automation Levels

| Level | Allowed Behavior |
| --- | --- |
| `observe` | Read systems and write summaries. |
| `prepare` | Draft work items, comments, replies, or plans. |
| `propose` | Recommend actions and request approval. |
| `execute_approved` | Execute actions after explicit approval. |
| `execute_guarded` | Execute within pre-approved limits and record evidence. |

Default to `observe` or `prepare` until the workflow is proven.

## Automation Lifecycle

| Phase | Question |
| --- | --- |
| Trigger | What event or schedule starts the automation? |
| Filter | Which inputs are allowed, ignored, or escalated? |
| Idempotency | How does the automation avoid duplicate work? |
| Context | What domain, workflow, and source context can it load? |
| Action | What is it allowed to read, draft, propose, or mutate? |
| Approval | What requires explicit human authorization? |
| Audit | What evidence must be written to the run log or control plane? |
| Retry | What happens when the action fails or partial state exists? |

![Workflow And Automation Lifecycle](../diagrams/workflow-automation-lifecycle.svg)

## Production Issue Automation

For production-support channels, automation should:

- Capture new threads.
- Keep appending replies as evidence.
- Maintain one issue case per incident.
- Track status changes over time.
- Summarize current state without losing raw messages.
- Escalate only when rules are met.

This volume should eventually use a database-backed active state plane, with Notion showing the cockpit.

## Permission Design

Automation permissions should be narrow and reviewable:

| Permission Area | Example Boundary |
| --- | --- |
| Read | Which channels, repositories, folders, databases, or queues can be read. |
| Write | Which destinations can receive drafts, comments, files, or state updates. |
| External visibility | Whether output can be seen by customers, vendors, or partners. |
| Production impact | Whether the automation can touch deployed systems or operational data. |
| Cost impact | Whether it can launch jobs, use paid APIs, or spend budget. |
| Data movement | Whether it can copy data between tools or security boundaries. |

## Promotion Path

Promote automation levels only after evidence exists:

1. `observe`: collect inputs and write summaries.
2. `prepare`: draft work items, replies, comments, or reports.
3. `propose`: recommend action and request approval.
4. `execute_approved`: execute after explicit human approval.
5. `execute_guarded`: execute within documented limits, with audit evidence and rollback path.

Each promotion should update the automation spec and approval policy before the automation runs at the higher level.
