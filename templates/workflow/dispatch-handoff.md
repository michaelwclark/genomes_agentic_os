# Dispatch Handoff: <workflow_name>

## Metadata

| Field | Value |
| --- | --- |
| Domain | `<domain>` |
| Lane | `<lane>` |
| Owner | `<owner>` |
| Created | `<yyyy-mm-dd>` |
| Target Agent / Harness | `codex_or_claude_or_human` |

## Outcome

Copy the one-sentence definition of done from `outcome-brief.md`.

## Required Sources To Load

| Source | Location | Why Required |
| --- | --- | --- |
| Workflow spec | `workflow.md` | Execution contract. |
| Outcome brief | `outcome-brief.md` | Definition of done. |
| Alignment questions | `alignment-questions.md` | Operator answers and unresolved ambiguity. |
| PRD | `prd.md` | Requirements, scope, safety, and validation contract. |
| Implementation plan | `implementation-plan.md` | Build order and risks. |
| Context pack | `context-pack.md` | Source-linked task context. |
| Progress | `progress.md` | Current state and resume point. |

## Ownership

| File / System / Responsibility | Owner | Notes |
| --- | --- | --- |
|  |  |  |

## Instructions

1. Confirm the outcome and scope before editing.
2. Load only the required sources unless discovery is needed.
3. Preserve unrelated user or agent work.
4. Stop at approval gates.
5. Record discoveries that change the plan.
6. Validate with the declared checks.
7. Write the run log before ending.

## Constraints

- Allowed reads:
- Allowed writes:
- Approval gates:
- Out-of-scope actions:

## Verification

| Check | Command Or Evidence | Required |
| --- | --- | --- |
|  |  | yes |

## Stop Conditions

- Scope conflicts with the outcome brief.
- Required context or credentials are missing.
- A validation check cannot be run and no substitute evidence exists.
- The work requires an external, destructive, production, billing, legal, or customer-visible action without approval.

## Handoff Back

- Run log:
- Artifacts:
- State update:
- Next action:
