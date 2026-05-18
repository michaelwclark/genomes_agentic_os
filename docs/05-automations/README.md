# Automations

An automation is a workflow with a trigger and enough guardrails to run without a fresh human prompt.

Automations should be conservative at first. Start by capturing, classifying, summarizing, and proposing action. Only mutate external systems after the approval and rollback rules are clear.

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

## Production Issue Automation

For production-support channels, automation should:

- Capture new threads.
- Keep appending replies as evidence.
- Maintain one issue case per incident.
- Track status changes over time.
- Summarize current state without losing raw messages.
- Escalate only when rules are met.

This volume should eventually use a database-backed active state plane, with Notion showing the cockpit.
