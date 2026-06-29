# Automation: <automation_name>

## Metadata

| Field | Value |
| --- | --- |
| Domain | `<domain>` |
| Lane | `<lane>` |
| Status | `draft` |
| Level | `observe` |
| Owner | `<owner>` |
| Last Reviewed | `<yyyy-mm-dd>` |

## Purpose

State what the automation does and what decision it helps with.

## Invocation Contract

| Surface | Value |
| --- | --- |
| Trigger or command |  |
| Registry entry | `harness/registries/commands.yml`, `harness/registries/skills.yml`, source watcher, schedule, or runtime registry |
| Authoring rules | `harness/rules/os-authoring-rules.md` |
| Convention reference | `harness/shared_factory/05-knowledge/references/os-conventions.md` |

## Trigger

- Type: `schedule | webhook | message | manual | state_change`
- Source:
- Frequency:

## Worth Automating Check

Do not move beyond `observe` or `prepare` unless this checklist is true.

| Question | Answer |
| --- | --- |
| Does this happen weekly or more often? |  |
| Are the steps stable and repeatable? |  |
| Can the automation finish without complex judgment? |  |
| Are login, CAPTCHA, and permission issues handled? |  |
| Is there a clear approval boundary before external writes? |  |
| Is there a run log and failure path? |  |

## Input Filters

- 

## Readiness Checks

| Check | Passes | Evidence |
| --- | --- | --- |
| Repeats often enough to justify automation |  |  |
| Steps are stable and inspectable |  |  |
| Inputs can be filtered before action |  |  |
| Done state is observable |  |  |
| Duplicate handling is clear |  |  |
| External writes stop at approval gates |  |  |
| Failures route to a human |  |  |

## Idempotency

- Key:
- Duplicate handling:

## Permissions

- Read:
- Write:
- Requires approval:
- Default action before approval: `observe | prepare | propose`

## Context Sources

- 

## Steps

1. Capture input.
2. Classify input.
3. Build or update work item.
4. Prepare output or proposed action.
5. Stop for approval when the action writes externally, changes production, changes money/legal state, deletes data, or becomes customer-visible.
6. Run the allowed action.
7. Validate result.
8. Record run.
9. Route next action.
10. Update the relevant work item `WORKLOG.md` and domain/project control
    surface when automation state changes.

## Outputs

- 

## Retry Policy

- Retry count:
- Retry delay:
- Stop condition:

## Failure Policy

- 

## Audit Requirements

- Input reference.
- Action taken.
- External systems touched.
- Result.
- Evidence.
