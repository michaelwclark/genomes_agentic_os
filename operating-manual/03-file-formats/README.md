# File Formats

Agents should use these files instead of inventing new document shapes.

## Domain

| File | Put In It |
| --- | --- |
| `ROUTER.md` | How to route work inside the domain. |
| `CONTEXT.md` | Standing purpose, people, systems, work style, and durable rules. |
| `REFERENCES.md` | Source systems, repo paths, Notion pages, Jira projects, examples. |
| `domain.yml` | Stable IDs, lanes, directories, source systems, approval defaults. |
| `00-control-plane/active-work.md` | Current work, status, owner, next action, link. |
| `00-control-plane/routing-rules.md` | How to choose lane, project, workflow, or automation. |
| `00-control-plane/approval-rules.md` | Human gates and never-do-without-approval actions. |

## Project

Expected project folder:

```text
02-projects/<project>/
  README.md
  project.yml
  status.md
  decisions.md
  source-map.md
  artifacts/
```

Use projects for active outcomes that may use multiple workflows or automations.

## Workflow

Expected workflow folder:

```text
03-workflows/<lane>/<workflow>/
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

## Automation

Expected automation folder:

```text
04-automations/<lane>/<automation>/
  automation.md
  inputs.md
  outputs.md
  permissions.md
  failure-modes.md
  runbook.md
  tests.md
  logs/
```

## Run

Expected run folder:

```text
06-runs-and-logs/runs/<run-id>/
  run-log.md
  artifacts/
```

Every non-trivial session should leave input, context loaded, actions taken, validation, artifacts, final status, and next action.
