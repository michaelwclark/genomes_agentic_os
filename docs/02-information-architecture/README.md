# Information Architecture

Top-level folders represent operating domains. Functional lanes belong inside those domains.

The purpose of the information architecture is to make the next agent's loading path obvious. If a folder exists, it should tell the agent what kind of object it contains and what authority that object has.

## Source Package Versus Installed OS

| Location | Role |
| --- | --- |
| This repository | Product source for templates, schemas, documentation, examples, and CLI code. |
| `~/agentic_os` | Runtime operating state for real domains, workflows, automations, context packs, and run logs. |
| `~/projects/*` | Product, client, content, or code repositories the OS operates on. |
| Genome's Notion or an explicitly selected client workspace | Human cockpit, dashboards, approvals, and readable status. |

## Installed Root

The installed OS should start with domain roots:

```text
~/agentic_os/
  AGENTS.md
  AGENT.md
  README.md
  personal/
  clarks_consulting/
  los/
  shared_factory/
  archive/
```

Lender-related work belongs inside `los/`; it is not a separate top-level domain.

Avoid making `engineering`, `marketing`, `sales`, `workflows`, or `automations` the top-level split. Those are operating lanes inside a domain.

## Domain Layout

Each domain should be able to stand alone:

```text
<domain>/
  AGENTS.md
  AGENT.md
  README.md
  domain.yml
  00-control-plane/
  01-inbox/
  02-projects/
  03-workflows/
    README.md
  04-automations/
    README.md
  05-knowledge/
  06-runs-and-logs/
  07-metrics/
  08-archive/
```

The domain is the unit of operating policy. Put access rules, approval rules, source systems, stakeholder context, and default routing there.

## Domain Router

Every domain has `AGENTS.md`. That file tells an agent:

- Where raw intake goes.
- Where project work goes.
- Where workflow specs live.
- Where automation specs live.
- Where knowledge and source maps live.
- Where run logs and failure records go.
- Which approval rules apply before external or risky action.

`AGENT.md` is a compatibility pointer to `AGENTS.md`.

## Standard Lanes

Workflow and automation lanes repeat inside each domain:

```text
03-workflows/
  README.md
  engineering/
    README.md
  marketing/
  sales/
  support/
  operations/
  finance/
  personal_admin/
  learning/

04-automations/
  README.md
  engineering/
    README.md
  marketing/
  sales/
  support/
  operations/
  finance/
  personal_admin/
  learning/
```

Lanes should not own global state. They group reusable workflow and automation specs inside the domain boundary.

## Object Placement

| Object | Preferred Location | Notes |
| --- | --- | --- |
| Domain router | `<domain>/AGENTS.md` | First file an agent should read after root routing. |
| Domain config | `<domain>/domain.yml` | Stable ID, display name, lanes, directory map, approval defaults, and source systems. |
| Active work | `<domain>/00-control-plane/active-work.md` | Current work and next actions. |
| Routing rules | `<domain>/00-control-plane/routing-rules.md` | How to choose lane, project, workflow, or automation. |
| Approval rules | `<domain>/00-control-plane/approval-rules.md` | Human gates and never-do-without-approval actions. |
| Inbox | `<domain>/01-inbox/` | Raw capture and triage. |
| Project | `<domain>/02-projects/<project>/` | Project-specific state and links. |
| Workflow spec | `<domain>/03-workflows/<lane>/<workflow>/workflow.md` | Process for judgment-heavy repeated work. |
| Workflow lane router | `<domain>/03-workflows/<lane>/README.md` | What belongs in that lane and the workflow folder contract. |
| Automation spec | `<domain>/04-automations/<lane>/<automation>/automation.md` | Triggered process with permissions and audit rules. |
| Automation lane router | `<domain>/04-automations/<lane>/README.md` | What belongs in that lane and the automation folder contract. |
| Knowledge | `<domain>/05-knowledge/` | Source maps, glossary, memory policy, and references. |
| Run log | `<domain>/06-runs-and-logs/runs/<run-id>/run-log.md` | One execution record, not a reusable spec. |
| Failure record | `<domain>/06-runs-and-logs/failures/` | Failed runs and recovery notes. |
| Metrics | `<domain>/07-metrics/` | Baselines and scorecards. |
| Archive | `<domain>/08-archive/` | Inactive or historical material. |
| Shared template copy | `shared_factory/05-knowledge/templates/` | Runtime copy of source templates. |

## Workflow Folder

```text
<domain>/03-workflows/<lane>/<workflow>/
  workflow.md
  state-machine.md
  context-pack.md
  approval-rules.md
  output-contract.md
  runbook.md
  examples/
    README.md
  runs/
    README.md
```

## Automation Folder

```text
<domain>/04-automations/<lane>/<automation>/
  automation.md
  inputs.md
  outputs.md
  permissions.md
  failure-modes.md
  runbook.md
  tests.md
  logs/
    README.md
```

## Naming Rules

- Use lowercase snake case for filesystem names.
- Use human-readable titles in Notion.
- Keep stable object IDs in YAML front matter or sidecar config when an object maps to Notion, Jira, GitHub, Slack, or a database row.
- Do not encode transient status in filenames.

## Example: LOS Feature Work

```text
los/
  03-workflows/
    engineering/
      feature_dev/
        workflow.md
        state-machine.md
        context-pack.md
        approval-rules.md
        output-contract.md
        runbook.md
  04-automations/
    support/
      production_thread_intake/
        automation.md
        inputs.md
        outputs.md
        permissions.md
        failure-modes.md
        runbook.md
        tests.md
        logs/
```

This keeps LOS as the operating boundary while allowing engineering and support to have separate repeatable patterns.

## Anti-Patterns

Avoid these shapes:

- One global `workflows/` folder with no domain ownership.
- One global `domains/` folder that hides the actual domain roots.
- Client-specific forks of the whole source package.
- Status in filenames, such as `feature_dev_done.md`.
- Secrets inside context packs or Notion mapping files.
- Chat transcript dumps as the only run evidence.
- Separate Claude and Codex workflows for the same operating process.
