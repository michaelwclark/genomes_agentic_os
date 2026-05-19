# Automation Permissions

## Automation Level

| Level | Meaning |
| --- | --- |
| `observe` | Read and summarize only. |
| `prepare` | Draft records or outputs without sending. |
| `propose` | Recommend actions and request approval. |
| `execute_approved` | Execute only after explicit approval. |
| `execute_guarded` | Execute inside narrow pre-approved limits. |

## Permission Record

| System | Read | Write | Approval Required | Notes |
| --- | --- | --- | --- | --- |
| Notion | yes | yes | depends | Control-plane updates are usually allowed. |
| GitHub | yes | no | yes | Comments, labels, merges, and PR changes need rules. |
| Slack | yes | no | yes | Sending messages usually needs approval. |
| Jira | yes | no | yes | Ticket mutation needs rules. |
| Production systems | no | no | yes | Default deny. |

## Ask-Before-Acting Rules

Use these defaults for inbox, calendar, browser, support, or operations automations until a narrower domain rule exists.

| Action Type | Default |
| --- | --- |
| Read and summarize | Allowed when source access is approved. |
| Draft a reply, ticket, event, or status update | Allowed as `prepare`; do not send. |
| Send an email, Slack message, calendar invite, customer ticket comment, or external note | Ask first. |
| Archive, delete, unsubscribe, cancel, merge, deploy, bill, sign, or modify legal records | Ask first unless a written domain rule explicitly pre-approves the exact action. |
| Handle money, contracts, HR, medical, legal, credentials, production data, or key client commitments | Ask first. |

## Secret Handling

- Never store secrets in Notion.
- Never write secrets to run logs.
- Never paste secrets into prompts.
- Use environment variables or secret managers.
