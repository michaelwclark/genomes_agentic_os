# Approval Rules: <workflow_or_domain>

## Default Rule

External writes, customer-visible output, production changes, and destructive actions require approval unless a more specific pre-approved rule exists.

## Approval Matrix

| Action | Approval Required | Approver | Notes |
| --- | --- | --- | --- |
| Read source systems | no |  |  |
| Draft internal summary | no |  |  |
| Create internal work item | no |  |  |
| Send external message | yes |  |  |
| Comment on customer-visible ticket | yes |  |  |
| Merge PR | yes |  |  |
| Deploy production change | yes |  |  |

## Pre-Approved Actions

- 

## Never Allowed Without Explicit Human Instruction

- Delete customer data.
- Rotate or expose secrets.
- Merge or deploy production code.
- Send customer-visible messages.
- Modify billing or legal records.
