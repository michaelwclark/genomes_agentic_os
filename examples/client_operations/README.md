# Example Domain: Client Operations

Client operations work should use Notion as the visible client control plane, with the OS handling intake, meeting notes, approvals, runs, and artifacts.

## Suggested Lanes

- `operations`
- `support`
- `client_delivery`

## First Workflows

| Workflow | Purpose |
| --- | --- |
| `meeting_notes_to_actions` | Extract actions, decisions, risks, and work items from meetings. |
| `client_request_intake` | Classify incoming requests and route them to the right workflow. |
| `automation_build` | Scope, build, validate, and hand off client automations. |

## Approval Bias

Customer-visible messages and external system writes should require approval until the workflows are proven.
