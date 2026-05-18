# Failure Modes

Use this file to define predictable automation failures and how agents should recover.

## Failure Table

| Failure | Detection | Action | State |
| --- | --- | --- | --- |
| Missing input | Required field absent | Mark work item blocked and request missing data. | `waiting` |
| Duplicate input | Idempotency key exists | Link to existing work item and append evidence. | `triaged` |
| Permission denied | Tool/API error | Stop and request access or approval. | `waiting` |
| Validation failed | Check fails | Preserve artifacts and route to manual review. | `failed` |
| External system unavailable | Timeout or 5xx | Retry within policy, then escalate. | `waiting` |

## Escalation Rule

Escalate when retrying would risk duplicate external actions, data corruption, customer-visible mistakes, or hidden state drift.
