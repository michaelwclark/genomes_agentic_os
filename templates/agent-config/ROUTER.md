# Agent Router

Use this file to choose the narrowest correct operating surface before acting.
After routing to a narrower directory, read that directory's `ROUTER.md`,
`CONTEXT.md`, `RULES.md`, and `TOOLS.md`, then repeat the routing decision.

## Routing Table

| Request Type | Route To | Read First |
| --- | --- | --- |
| Idea, rough thought, or product/system concept | matching domain `01-inbox/` | domain `ROUTER.md` |
| Raw capture | `01-inbox/` | `CONTEXT.md` |
| Active project work | `02-projects/<project>/` | project `status.md` and `source-map.md` |
| Repeatable workflow | `03-workflows/<lane>/<workflow>/` | workflow `quick-reference.md`, `context-pack.md`, and `runbook.md` |
| Triggered automation | `04-automations/<lane>/<automation>/` | automation `automation.md`, `permissions.md`, and `tests.md` |
| Shared template or skill | `shared_factory/` or `05-knowledge/` | relevant template, source map, or skill |
| Shell, terminal, package-manager, runtime, or cleanup work | system registry | `shared_factory/05-knowledge/host-tool-registry.<host>.yml` |
| Historical material | `08-archive/` | archive index or linked run log |
| Reported bug, QA failure, ticket comment, error/log/alert, incident, suspected cause, or RCA | Auto-Dev Detective, then routed domain/project | `harness/skills/auto-dev-detective/SKILL.md` |
| Create/update Jira, Linear, Notion, Confluence, GitHub, Slack, PR text, RCA, report, or local artifact | Auto-Dev Create Artifacts | `harness/skills/auto-dev-create-artifacts/SKILL.md` |
| Take a tracker item through every applicable SDLC step | Auto-Dev Everything | `harness/skills/auto-dev-everything/SKILL.md` |
| Renovate/Dependabot dependency-update PR to a governed merge | `auto-dev-dep-updater` | project `dep_updater` policy |
| Own-PR continuous delivery to merged, released, and documented | `auto-dev-continuous-release` | project `continuous_release` + `release` policy |
| Implement, fix, build, review/repair, release, deploy, or close out code | Auto-Dev / Development Delivery | `harness/shared_factory/00-programs/auto_dev/program.md` |
| Audit receipts and retire reconstructable local resources after verified delivery | Auto-Dev Health | `harness/skills/auto-dev-health/SKILL.md` |

## Routing Rules

- Choose a domain or room before creating work.
- Route explicit ideas to the matching domain inbox before promoting them into projects, workflows, automations, Jira, or implementation work.
- Read `CONTEXT.md`, `RULES.md`, and `TOOLS.md` before acting in the routed layer.
- Repeat the route-read-cd loop after changing directories.
- Reuse an existing project, workflow, automation, or run log when it fits.
- Create new workflow or automation folders only when the pattern should repeat.
- Record unclear routing decisions in the local run log or triage file.
- Select Auto-Dev workflows by intent; the user does not need to say
  “Auto-Dev.” Domain/project configuration specializes shared behavior.

## Output Rule

Write artifacts in the routed folder, not beside unrelated context.
