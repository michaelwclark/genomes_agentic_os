# Agent Router

Use this file to choose the narrowest correct operating surface before acting.

## Routing Table

| Request Type | Route To | Read First |
| --- | --- | --- |
| Raw capture | `01-inbox/` | `CONTEXT.md` |
| Active project work | `02-projects/<project>/` | project `status.md` and `source-map.md` |
| Repeatable workflow | `03-workflows/<lane>/<workflow>/` | workflow `quick-reference.md`, `context-pack.md`, and `runbook.md` |
| Triggered automation | `04-automations/<lane>/<automation>/` | automation `automation.md`, `permissions.md`, and `tests.md` |
| Shared template or skill | `shared_factory/` or `05-knowledge/` | relevant template, source map, or skill |
| Historical material | `08-archive/` | archive index or linked run log |

## Routing Rules

- Choose a domain or room before creating work.
- Reuse an existing project, workflow, automation, or run log when it fits.
- Create new workflow or automation folders only when the pattern should repeat.
- Record unclear routing decisions in the local run log or triage file.

## Output Rule

Write artifacts in the routed folder, not beside unrelated context.
