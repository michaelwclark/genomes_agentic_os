# Running OS Roadmap

This roadmap turns the scaffold into a working operating system. The goal is not more folders; the goal is a loop where projects, workflows, automations, context, routing, cleanup, and Notion control-panel state reinforce each other.

## Current Foundation

V1 provides:

- Domain-first installed root.
- Root and domain `ROUTER.md` files.
- Workflow, automation, and run-log scaffolds.
- Runtime copies of templates, operating manual, commands, and skills.
- Validation for required structure and parseable YAML or JSON.

## Build Backlog

| Phase | Capability | User Outcome | Primary Command Or Skill |
| --- | --- | --- | --- |
| 1 | Project scaffold | Add active projects with status, decisions, source map, artifacts, and linked workflows. | `agentic-os project create` |
| 2 | Cwd-aware commands | Run commands from inside a domain or project without repeating root and domain args. | `agentic-os here ...` |
| 3 | Workflow completeness checks | Know whether a workflow is ready to dispatch. | `agentic-os workflow check` |
| 4 | Automation qualification | Convert proven workflows into safe automations with maturity levels. | `automation-qualifier` |
| 5 | Context builder | Build minimal agent context from domain, project, workflow, and source maps. | `context-pack-builder` |
| 6 | Routing auto-update | Update routing rules, active work, and lane READMEs when objects are created. | `os-navigator` plus create commands |
| 7 | Run closeout | Close sessions with evidence, status, next action, and promoted learning. | `agentic-os run-log close` |
| 8 | Periodic cleanup | Detect stale active work, incomplete workflows, unsafe automations, missing final states, and archive candidates. | `agentic-os doctor` |
| 9 | Notion control panel sync | Reflect domains, projects, runs, approvals, and status in Notion while keeping files as source. | `agentic-os notion sync` |
| 10 | Metrics and scorecards | Track workflow quality, automation safety, cycle time, and cleanup health. | `agentic-os metrics refresh` |

## Project Scaffold

Expected command:

```bash
agentic-os project create <domain> <project> --root ~/agentic_os
```

Expected shape:

```text
<domain>/02-projects/<project>/
  README.md
  project.yml
  status.md
  decisions.md
  source-map.md
  artifacts/
```

Required side effects:

- Add project row to `<domain>/00-control-plane/active-work.md`.
- Link known workflows and automations from `README.md`.
- Add Notion/Jira/GitHub/source IDs to `project.yml` when known.

## Automation To Project

Automations should be attachable to a project:

```bash
agentic-os automation create <domain> <lane> <automation> --project <project> --root ~/agentic_os
```

Required side effects:

- Create automation folder.
- Link automation from project status.
- Update routing rules when this automation should handle a request class.
- Keep maturity at `observe` or `prepare` until run evidence supports more authority.

## Auto Context Build

Context build should produce a concise context pack, not a chat dump.

Inputs:

- Root and domain routers.
- Domain `CONTEXT.md` and `REFERENCES.md`.
- Project `source-map.md`.
- Workflow or automation `context-pack.md`.
- Recent run logs and decisions when relevant.

Output:

- Ordered source list.
- Required files to read.
- Permission and approval risks.
- Known gaps.
- Handoff prompt for the agent.

## Routing Auto-Update

When the OS creates a project, workflow, automation, or skill, it should update the surfaces agents actually read:

| Created | Update |
| --- | --- |
| Project | active work, project index, related domain references. |
| Workflow | lane README, routing rules, project links. |
| Automation | automation lane README, permissions, routing rules, project links. |
| Skill | shared_factory skill index, harness command docs, relevant workflow quick references. |
| Run | activity log, workflow progress, metrics candidate. |

## Periodic Doctor

Doctor should run manually first, then as a scheduled automation.

Checks:

- Missing required files.
- Empty critical sections.
- Root-level drift.
- Active work without next action.
- Workflows without recent runs.
- Automations without permissions, tests, logs, or maturity level.
- Run logs without final state.
- Archive candidates.

## Notion Control Panel

Notion should be a cockpit over the filesystem OS.

Required sync objects:

- Domains.
- Projects.
- Work items.
- Workflows.
- Automations.
- Runs.
- Approvals.
- Metrics.

Filesystem remains the operational source for routers, templates, workflow specs, automation specs, and run logs. Notion holds dashboard views, approvals, and review-friendly status.

## Acceptance Criteria For A Running OS

- A new request can be routed without chat history.
- A new project can be created and appears in active work.
- A workflow can be created, completed, run, validated, and logged.
- A proven workflow can become an automation with explicit permissions.
- A fresh agent can build context from files.
- Routing rules change when new reusable objects are added.
- Cleanup can find drift and propose repairs.
- Notion reflects live status without becoming the only source of truth.
