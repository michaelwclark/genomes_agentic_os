# Example Domain: Clark's Consulting

Clark's Consulting work uses the OS as a client-delivery and automation-school factory: capture requests, turn them into reusable workflows, build guarded automations, and preserve handoff evidence.

## Suggested Lanes

- `operations`
- `support`
- `sales`
- `marketing`

## First Workflows

| Workflow | Purpose |
| --- | --- |
| `client_request_intake` | Classify incoming client or prospect requests and route them to the right workflow. |
| `meeting_notes_to_actions` | Extract actions, decisions, risks, and work items from meetings. |
| `automation_build` | Scope, build, validate, and hand off client automations. |
| `client_status_update` | Produce concise client-visible status from work items and run logs. |

## First Automations

| Automation | Level | Purpose |
| --- | --- | --- |
| `weekly_digest_prepare` | `prepare` | Draft a weekly client/workstream summary from approved sources. |
| `inbound_message_triage` | `observe` | Classify inbound messages by domain, lane, intent, risk, and confidence. |

## Approval Bias

Customer-visible messages and external system writes should require approval until the workflows are proven.
