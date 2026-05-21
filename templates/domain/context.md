# Context: <domain_name>

Use this file as the room guide for one operating domain. Keep it short enough to load before domain work, and move stable reference material into `05-knowledge/` or `REFERENCES.md`.

## Purpose

This domain is for <kind of work>.

## Inputs

- <input type> from <source system or path>
- <input type> from <source system or path>

## Process

1. Read this file, `ROUTER.md`, and any rows in the load table that match the task.
2. Locate the existing project, workflow, automation, or run log before creating a new one.
3. Read only the required references for the routed task.
4. Create or update the output in the expected folder.
5. Record validation, next action, and any durable learning before ending.

## Output Folders

- `00-control-plane/` - routing, approvals, active work, and decisions.
- `01-inbox/` - untriaged capture and routing notes.
- `02-projects/` - project-specific state, source maps, status, and artifacts.
- `03-workflows/` - repeatable judgment-heavy processes.
- `04-automations/` - triggerable processes with declared permissions and logs.
- `05-knowledge/` - source maps, glossary, memory policy, and reference material.
- `06-runs-and-logs/` - execution records, failures, and activity history.
- `07-metrics/` - baselines and scorecards.
- `08-archive/` - inactive or historical material.

## What To Load

| Task Type | Read First | Read When Needed | Do Not Load By Default | Output Path |
| --- | --- | --- | --- | --- |
| Raw capture | `01-inbox/raw-ideas.md` | `REFERENCES.md` | workflow internals | `01-inbox/raw-ideas.md` |
| Route work | `ROUTER.md`, `00-control-plane/routing-rules.md` | `00-control-plane/active-work.md` | unrelated domain folders | `01-inbox/triage.md` or target object |
| Project work | `02-projects/<project>/status.md`, `source-map.md` | linked repo, linked Notion/Jira | unrelated projects | `02-projects/<project>/` |
| Workflow run | `03-workflows/<lane>/<workflow>/quick-reference.md`, `context-pack.md` | runbook, examples, source maps | automations unless the workflow says so | `06-runs-and-logs/runs/` |
| Automation review | `04-automations/<lane>/<automation>/automation.md`, `permissions.md` | tests, logs, failure modes | unrelated workflows | `04-automations/<lane>/<automation>/` |

## Tools And Skills

| Tool Or Skill | Use When | Notes |
| --- | --- | --- |
| <tool or skill> | <trigger condition> | <what it should do here> |

## Done Means

- Work landed in the expected folder.
- Required approval gates were respected.
- Validation evidence is recorded.
- Active work, project status, workflow progress, or run log has the next action.
- Durable learning was promoted to `CONTEXT.md`, `REFERENCES.md`, source maps, memory policy, or a shared template when appropriate.

## Update Rule

Update this file when a stable domain rule, source system, work style preference, routing pattern, tool trigger, or repeated failure mode becomes durable.
