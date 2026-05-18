# Operating Model

The OS is built around a small loop that repeats across domains, workflows, and automations.

![Genome's Agentic OS Lifecycle](../diagrams/os-lifecycle.svg)

```text
intake -> classify -> build context -> execute -> validate -> record -> route next action
```

That loop is the contract. A human can run it manually, Codex can run it from a repo, Claude can run it from a broader operating surface, and future automations can run it from a trigger. The state names and records should stay the same.

## Object Flow

| Stage | Output |
| --- | --- |
| Intake | Raw external message, Jira, PR, meeting note, Slack thread, email, or manual request. |
| Classify | Domain, lane, work type, urgency, owner, and whether automation is allowed. |
| Build Context | Context pack with project facts, linked artifacts, prior state, constraints, and active instructions. |
| Execute | Workflow run, automation run, skill run, or human-approved task. |
| Validate | Tests, source checks, approval criteria, evidence, and failure handling. |
| Record | Run log, decisions, artifacts, status, and next state. |
| Route | Done, waiting, needs approval, retry, blocked, or escalated. |

## Data Flow

![Agentic OS Data Flow](../diagrams/data-flow.svg)

The important separation is:

- Source templates and specs live in this repository.
- Installed operating state lives in `~/agentic_os`.
- Project work happens in product or client repos.
- The control plane shows human-facing state and approvals.
- A future active state plane owns high-volume mutable state.

Agents should not blur those layers. For example, a run log can link to a pull request, but the pull request remains in the work repo. A Notion page can summarize a workflow, but the workflow template remains in Git.

## Core States

Use a small status vocabulary everywhere:

| State | Meaning |
| --- | --- |
| `new` | Captured but not classified. |
| `triaged` | Classified and linked to a domain/lane. |
| `ready` | Context exists and execution can begin. |
| `running` | An agent, automation, or human is actively working. |
| `waiting` | Blocked on human, external system, customer, CI, or time. |
| `needs_approval` | Output is ready but needs human approval before action. |
| `done` | Desired outcome completed and recorded. |
| `archived` | No longer active but retained for search/history. |
| `failed` | Execution failed and needs retry, redesign, or manual intervention. |

## Workflow Versus Automation

![Workflow And Automation Lifecycle](../diagrams/workflow-automation-lifecycle.svg)

| Object | Use When | Human Role |
| --- | --- | --- |
| Workflow | The process needs judgment, context interpretation, or variable execution. | Start, supervise, approve, or review. |
| Automation | The trigger and allowed action are stable enough to run repeatedly. | Define permissions, review evidence, approve mutations. |
| Run log | Any workflow, automation, or skill did meaningful work. | Read evidence, continue work, or audit decisions. |

## Run Discipline

Every non-trivial agent run should produce:

- Input reference.
- Chosen workflow or automation.
- Context sources used.
- Actions taken.
- Validation performed.
- Artifacts created or changed.
- Final state.
- Next action.

This is the minimum record needed for another agent to resume without rereading the whole world.

## Completion Standard

A run is not complete just because an agent produced output. It is complete when:

- The output exists in the right destination.
- Validation evidence is recorded.
- Any required approval is requested or resolved.
- The state transition is clear.
- The next action has an owner or the item is marked done.
