# Workflow: <workflow_name>

## Metadata

| Field | Value |
| --- | --- |
| Domain | `<domain>` |
| Lane | `<lane>` |
| Status | `draft` |
| Owner | `<owner>` |
| Allowed Agents | `codex, claude` |
| Last Reviewed | `<yyyy-mm-dd>` |

## Purpose

State the concrete outcome this workflow produces.

## Use When

- The input matches this workflow's work type.
- The required context sources are available.
- The workflow's approval rules are acceptable for the requested action.

## Do Not Use When

- The work belongs to a different domain.
- The input is missing required identifiers.
- The requested action exceeds this workflow's permission level.

## Inputs

| Input | Required | Notes |
| --- | --- | --- |
| Source object | yes | Jira, PR, Slack thread, email, meeting note, or manual prompt. |
| Domain | yes | Must map to a known domain. |
| Desired outcome | yes | Must be stated or inferred and recorded. |

## Preconditions

- Domain context pack exists.
- Approval rules are known.
- Output destination is known.

## Context Pack Requirements

- Domain context.
- Relevant project context.
- Prior work item state.
- Source object content.
- Workflow-specific constraints.

## Steps

1. Confirm domain and work type.
2. Create or update the work item.
3. Build the context pack.
4. Execute the workflow steps.
5. Validate output.
6. Record artifacts and decisions.
7. Update state and next action.

## Validation

- Required output exists.
- Source links are preserved.
- Approval rules were followed.
- Run log is complete.

## Outputs

- Updated work item.
- Run log.
- Artifacts.
- Next action.

## State Transitions

| From | To | Condition |
| --- | --- | --- |
| `new` | `triaged` | Domain and workflow selected. |
| `triaged` | `ready` | Context pack complete. |
| `ready` | `running` | Agent starts execution. |
| `running` | `needs_approval` | Output requires approval. |
| `running` | `done` | Output validated and no approval needed. |
| `running` | `failed` | Execution cannot complete. |

## Failure Handling

Record the failure, preserve partial artifacts, update the work item, and route to retry, approval, or manual intervention.
