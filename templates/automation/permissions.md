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

## Secret Handling

- Never store secrets in Notion.
- Never write secrets to run logs.
- Never paste secrets into prompts.
- Use environment variables or secret managers.
