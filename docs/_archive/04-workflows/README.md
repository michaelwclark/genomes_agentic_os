# Workflows

A workflow is a repeatable human-or-agent process with explicit inputs, context, steps, validation, and outputs.

Workflows are used when judgment is required. Automations are used when the decision path is stable enough to run on triggers.

Workflows are the main unit of reusable agent work. A good workflow should be specific enough for an agent to execute, but general enough to run across many work items in the same domain and lane.

For complex work, use the [Cliefnotes Operating Guide](../11-cliefnotes-operating-guide/README.md) before dispatching execution.

Workflow specs live under the selected domain:

```text
<domain>/03-workflows/<lane>/<workflow>/
  workflow.md
  outcome-brief.md
  alignment-questions.md
  prd.md
  implementation-plan.md
  dispatch-handoff.md
  progress.md
  quick-reference.md
  state-machine.md
  context-pack.md
  approval-rules.md
  output-contract.md
  runbook.md
  examples/
  runs/
```

## Required Workflow Sections

Every workflow spec should include:

- Purpose.
- Pre-build gate.
- When to use.
- When not to use.
- Inputs.
- Preconditions.
- Context pack requirements.
- Steps.
- Validation.
- Outputs.
- State transitions.
- Failure handling.
- Handoff notes.

## Workflow Anatomy

| Section | Why It Exists |
| --- | --- |
| Purpose | Prevents agents from using the workflow for adjacent but wrong work. |
| Pre-Build Gate | Keeps brainstorming, planning, and handoff explicit before execution starts. |
| Use When / Do Not Use When | Creates routing boundaries and avoids accidental scope creep. |
| Inputs | Defines required identifiers, source objects, and requested outcome. |
| Preconditions | Blocks execution until required context and permissions exist. |
| Context Pack Requirements | Keeps prompt loading focused and repeatable. |
| Steps | Gives the agent an execution path. |
| Validation | Defines what must be checked before state changes. |
| Outputs | Names the artifacts, comments, files, or state updates expected. |
| State Transitions | Keeps the control plane and run logs consistent. |
| Failure Handling | Makes blocked or failed work resumable. |

## Workflow Execution Standard

Agents executing a workflow must:

1. Confirm the input object and domain.
2. Load the workflow spec.
3. Confirm `outcome-brief.md`, `alignment-questions.md`, `prd.md`, `implementation-plan.md`, and `dispatch-handoff.md` exist or create them before build work starts.
4. Build the context pack from declared sources.
5. Execute only the allowed steps.
6. Validate against the workflow's acceptance criteria.
7. Write a run log.
8. Update the control plane status.
9. Update `progress.md` with the resume point and next action when work remains open.

## Context Loading Contract

Before executing, an agent should load only what the workflow declares:

- Domain context.
- Source object content.
- Relevant project context.
- Prior run logs or decision records for the work item.
- Workflow-specific constraints.
- Approval rules.

If the agent needs context outside that list, it should record the additional source in the run log.

## Example Workflows

- `feature_dev`: build a feature from Jira/spec to PR.
- `pull_request_review`: review PRs when tagged or requested.
- `production_issue_triage`: track and summarize messy production threads.
- `meeting_notes_to_actions`: convert meeting notes into decisions, tasks, and workflow runs.
- `client_automation_build`: turn a client need into a scoped automation and deployment path.

## Workflow Boundary Rule

If the process changes business state, sends messages, creates tickets, deploys code, or mutates customer data, the workflow must include approval rules.

## Validation Examples

| Workflow Type | Validation Evidence |
| --- | --- |
| Feature development | Tests, lint/typecheck, code references, PR link, acceptance criteria mapping. |
| PR review | Findings with file/line references, test gaps, risk assessment, copy-ready comments. |
| Meeting notes to actions | Source note link, extracted decisions, owner/action mapping, created work items. |
| Production issue triage | Source thread, current status, timeline, affected systems, next owner. |
| Release planning | Included changes, excluded changes, deployment state, rollback notes. |

## Good Workflow Smells

- The workflow tells the agent when to stop and ask for approval.
- The validation section is concrete enough to fail.
- Outputs are named and located.
- State transitions use the shared status vocabulary.
- The handoff section tells the next agent what to load first.
