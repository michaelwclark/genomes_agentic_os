# Genome's Agentic OS

Genome's Agentic OS is a source package for creating a local operating system for AI-assisted work. It gives agents, automations, and humans the same durable structure for intake, context loading, execution, validation, approvals, and handoff.

The goal is simple: stop rebuilding the operating context from scratch in every chat.

## What This Creates

The CLI scaffolds an installed OS root, usually at `~/agentic_os`, with reusable folders for:

- Domains: operating boundaries such as `internal_product`, `client_operations`, or `candidate_pipeline`.
- Workflows: repeatable judgment-heavy processes with inputs, context, steps, validation, outputs, and handoff.
- Automations: trigger-driven processes with permissions, idempotency, audit rules, and approval gates.
- Context packs: compact, agent-readable facts about domains, systems, stakeholders, projects, and active work.
- Run logs: durable records of what an agent or automation did, what it loaded, what it changed, and how it validated.
- Notion mappings: cockpit structure for intake, approvals, dashboards, and human-facing status.
- Templates and schemas: copyable source objects that keep each installed OS consistent.

```text
~/agentic_os/
  domains/
  workflows/
  automations/
  inbox/
  runs/
  context/
  memory/
  notion/
  config/
  templates/
```

## Why This Matters

Most AI work fails quietly because state lives in the wrong places:

- Chat history holds decisions that should be durable.
- Prompts carry context that should be reusable.
- Notion pages become dashboards without execution records.
- Automations mutate systems before approval boundaries are explicit.
- Every new agent run spends time rediscovering repo paths, commands, owners, and prior decisions.

Agentic OS turns that into an operating loop:

```text
intake -> classify -> build context -> execute -> validate -> record -> route next action
```

The result is less prompt mass, fewer missed approvals, cleaner handoffs, and workflows that can be run by Codex, Claude, a scheduled automation, or a human without changing the underlying process.

![Agentic OS Value Flow](docs/diagrams/value-flow.svg)

## Core Model

Genome's Agentic OS separates source, runtime state, work repositories, and the human control plane.

| Layer | Source Of Truth | Purpose |
| --- | --- | --- |
| Product package | This repository | Reusable specs, templates, schemas, examples, diagrams, and CLI scaffold logic. |
| Installed OS | `~/agentic_os` | Live domain/workflow/automation files, context packs, run logs, and memory policy. |
| Work repos | `~/projects/*` | Actual product, client, content, or code repositories operated by the OS. |
| Notion control plane | Your Notion workspace or a client-owned workspace | Human cockpit for intake, approvals, status, dashboards, and review. |
| Future active state plane | Database or queue | High-volume mutable state, locking, dedupe, replay, matching, and event history. |

## The Operating Flow

Every meaningful work item should pass through the same lifecycle:

| Stage | What Happens | Durable Output |
| --- | --- | --- |
| Intake | Raw request, issue, PR, meeting note, message, or scheduled trigger arrives. | Inbox item or work item reference. |
| Classify | The OS chooses domain, lane, workflow or automation, urgency, and permission level. | Domain/lane/work type metadata. |
| Build Context | Agent loads only the context needed for the task. | Context pack references and source links. |
| Execute | Human, agent, or automation runs the declared process. | Changed files, drafted output, tickets, summaries, artifacts, or prepared actions. |
| Validate | Output is checked against tests, acceptance criteria, approval rules, and evidence requirements. | Validation evidence and gaps. |
| Record | The run log captures what happened and what state changed. | Run log, decisions, artifacts, and final status. |
| Route | Work moves to done, waiting, needs approval, retry, blocked, or archived. | Next action and owner. |

![Agentic OS Data Flow](docs/diagrams/data-flow.svg)

## Workflows, Automations, And Runs

A workflow is a repeatable process for work that still needs judgment. Examples: feature development, PR review, release planning, meeting notes to action items, production issue triage.

An automation is a workflow with a trigger and enough guardrails to run without a fresh human prompt. Automations start conservatively: observe, prepare, propose, then execute only after approval rules are proven.

A run is one execution of a workflow, automation, or skill. Runs are the audit trail. If a second agent cannot tell what happened from the run log, the system did not record enough.

![Workflow And Automation Lifecycle](docs/diagrams/workflow-automation-lifecycle.svg)

## Installable V1

Install the CLI from this repository:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

For local test development, include the optional pytest dependency:

```bash
python -m pip install -e '.[dev]'
```

The installed command is generic:

```bash
agentic-os --help
```

### Smoke Test

Run this against a temporary directory before using a real OS root:

```bash
tmpdir=$(mktemp -d)
agentic-os init --target "$tmpdir/os"
agentic-os domain create internal_product --root "$tmpdir/os"
agentic-os workflow create internal_product engineering feature_dev --root "$tmpdir/os"
agentic-os automation create internal_product support production_thread_intake --root "$tmpdir/os"
agentic-os run-log create internal_product feature_dev --root "$tmpdir/os"
agentic-os validate --root "$tmpdir/os"
find "$tmpdir/os" -maxdepth 4 -type f | sort
```

For a real install, use the default root or pass an explicit target:

```bash
agentic-os init --target ~/agentic_os
```

## V1 Command Surface

| Command | Creates Or Checks |
| --- | --- |
| `agentic-os init --target ~/agentic_os` | Base OS folders and copied templates. |
| `agentic-os domain create <name> --root ~/agentic_os` | Domain folder, config, context placeholders, workflow/automation folders, decisions, and Notion mapping folder. |
| `agentic-os workflow create <domain> <lane> <name> --root ~/agentic_os` | Workflow Markdown spec from the workflow template. |
| `agentic-os automation create <domain> <lane> <name> --root ~/agentic_os` | Automation Markdown spec from the automation template. |
| `agentic-os run-log create <domain> <workflow-or-automation> --root ~/agentic_os` | Timestamped run log under `runs/`. |
| `agentic-os validate --root ~/agentic_os` | Required folder checks plus JSON/YAML parseability. |

## What V1 Does

- Creates a working local OS tree under `~/agentic_os` or a supplied target.
- Copies repository templates into the installed `templates/` folder.
- Creates domain folders, domain config, context placeholders, workflow folders, automation folders, decision folders, and Notion mapping folders.
- Creates workflow and automation Markdown specs from the repository templates.
- Creates timestamped run logs under `runs/`.
- Validates required folders plus JSON/YAML parseability.
- Keeps generated files safe to rerun by not overwriting existing hand-authored content.

## What V1 Does Not Do

- It does not call the Notion API or create pages/databases in your Notion workspace.
- It does not install Claude or Codex skills into local harness folders.
- It does not execute automations, schedule jobs, or manage long-running state.
- It does not store secrets.
- It does not perform full JSON Schema validation of workflow or automation content yet.
- It does not replace project repositories, task trackers, or the human approval process.

## Repository Map

```text
docs/       Human-readable operating manual and diagrams.
spec/       Product and implementation specs.
templates/  Copyable source templates for installed OS objects.
schemas/    JSON schemas for future stricter validation.
examples/   Example domain operating systems.
skills/     Claude and Codex skill entrypoints.
installers/ Installer and scaffold planning notes.
config/     Example configuration files.
src/        Installable Python CLI package.
tests/      CLI and scaffold smoke tests.
```

Key starting points:

- [Documentation index](docs/README.md)
- [CLI and install guide](docs/10-cli-and-install/README.md)
- [Operating model](docs/01-operating-model/README.md)
- [Workflow guide](docs/04-workflows/README.md)
- [Automation guide](docs/05-automations/README.md)
- [Storage model](docs/09-storage-model/README.md)
- [Spec index](spec/README.md)
- [Templates](templates/README.md)

## Public Customization

Keep this repository generic. Put organization-specific names, private project references, workspace IDs, channel names, credentials, and secrets only in an installed OS root or a separate private overlay.

Use filesystem-safe names that match `^[a-z0-9_]+$`, such as:

- `internal_product`
- `client_operations`
- `candidate_pipeline`
- `shared_services`

Customize domain context, workflow choices, automation permissions, Notion views, and integration adapters. Do not fork the core object vocabulary, run log format, approval state model, context pack contract, or audit evidence requirements unless the product spec changes too.
