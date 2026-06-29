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

## Invocation Contract

| Surface | Value |
| --- | --- |
| Primary command or skill |  |
| Registry entry | `harness/registries/commands.yml` or `harness/registries/skills.yml` |
| Authoring rules | `harness/rules/os-authoring-rules.md` |
| Convention reference | `harness/shared_factory/05-knowledge/references/os-conventions.md` |

## Pre-Build Gate

Do not dispatch build work until these files are complete enough for a fresh agent to execute:

- `outcome-brief.md` - one-sentence definition of done, scope, constraints, and acceptance criteria.
- `alignment-questions.md` - operator questions that must be answered before the PRD is trusted.
- `prd.md` - problem, users, requirements, scope, source systems, and validation contract.
- `implementation-plan.md` - build stages, file or system scope, risks, and validation plan.
- `dispatch-handoff.md` - source loading, ownership, constraints, stop conditions, and verification.
- `progress.md` - current status, blockers, resume point, and next action.
- Matching command or skill registry entry - required before this workflow is marked active.

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

1. Brainstorm the real outcome and write `outcome-brief.md`.
2. Ask and answer alignment questions in `alignment-questions.md`.
3. Write or update `prd.md`.
4. Plan the work and write `implementation-plan.md`.
5. Create `dispatch-handoff.md` for the agent or human doing the execution.
6. Confirm domain and work type.
7. Create or update the work item.
8. Build the context pack.
9. Execute the workflow steps.
10. Validate output.
11. Record artifacts and decisions.
12. Update `progress.md`, state, and next action.
13. Update the relevant work item `WORKLOG.md` and domain/project control
    surface when this workflow changes durable state.

## Validation

- Required output exists.
- Source links are preserved.
- Approval rules were followed.
- Run log is complete.

## Outputs

- Outcome brief.
- Alignment questions.
- PRD.
- Implementation plan.
- Dispatch handoff.
- Progress update.
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
