# Genome's Agentic OS

Scaffold reusable AI operating systems for client and internal workflows: Notion control planes, agent rules, workflow specs, automations, context packs, and run logs.

This repo is the source package for building installed operating systems for agentic work. It should contain the reusable standards, templates, installer logic, schemas, and examples. The installed OS lives outside this repo, usually at `~/agentic_os`, while individual product repos stay in `~/projects/*`.

## Core Model

Genome's Agentic OS separates four concerns:

| Layer | Source Of Truth | Purpose |
| --- | --- | --- |
| Product package | This repository | Reusable specs, templates, schemas, examples, and installers. |
| Installed OS | `~/agentic_os` | Live domain/workflow/automation files, context packs, run logs, and memory policy. |
| Work repos | `~/projects/*` | Actual software projects, client assets, and codebases. |
| Notion control plane | Your Notion workspace or a client-owned workspace | Human cockpit for intake, approvals, status, and operating dashboards. |

## What This Builds

- A consistent filesystem for operating agents, automations, workflows, and context.
- Notion scaffolds for inboxes, work items, runs, approvals, decisions, meeting notes, and artifacts.
- Claude and Codex rules/skills so either harness can enter the OS and build context predictably.
- Specs for workflows and automations that agents can execute without re-discovering the operating model every time.
- Storage guidance for when a simple filesystem is enough and when a database-backed state plane is required.

## V1 Direction

V1 should optimize for a working single-operator system:

- Make the standards concrete before building heavy runtime code.
- Keep the file tree Git-friendly and inspectable.
- Use Notion as the cockpit, not as the only data plane.
- Use a database only for active, changing operational state that needs queries, locking, dedupe, or replay.
- Preserve project-specific differences through domain overlays instead of forking the whole architecture.

## Suggested Installed Layout

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

## Current Repo Map

```text
docs/       Human-readable operating manual.
spec/       Product and implementation specs.
templates/  Copyable source templates for installed OS objects.
schemas/    JSON schemas for validation.
examples/   Example domain operating systems.
skills/     Claude and Codex skill entrypoints.
installers/ Planned installer/scaffold command docs.
config/     Example configuration files.
```

Key starting points:

- [Documentation index](docs/README.md)
- [Spec index](spec/README.md)
- [Product spec](spec/product-spec.md)
- [Architecture spec](spec/architecture.md)
- [Data model spec](spec/data-model.md)
- [Templates](templates/README.md)

## First Build Milestone

The first useful version is not a full automation runtime. It is a scaffold that can create a clean OS for a client or internal domain and give agents enough structure to:

1. Classify incoming work.
2. Build the right context pack.
3. Run the right workflow or automation.
4. Store decisions and artifacts.
5. Resume later without burning tokens rediscovering state.

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

### What V1 Does

- Creates the base installed OS tree under `~/agentic_os` or a supplied target.
- Copies repository templates into the installed `templates/` folder.
- Creates domain folders, domain config, context placeholders, workflow folders, automation folders, decision folders, and Notion mapping folders.
- Creates workflow and automation Markdown specs from the repository templates.
- Creates timestamped run logs under `runs/`.
- Validates required folders plus JSON/YAML parseability.

### What V1 Does Not Do

- It does not call the Notion API or create pages/databases in your Notion workspace.
- It does not install Claude or Codex skills into local harness folders.
- It does not execute automations, schedule jobs, or manage long-running state.
- It does not overwrite existing hand-authored files.
- It does not perform full JSON Schema validation of workflow or automation content yet.

### Public Customization

Keep the source package generic. Put organization-specific names, private project references, workspace IDs, channel names, and secrets only in the installed OS root or in a separate private overlay. Use domains such as `internal_product`, `client_operations`, or another filesystem-safe name that matches `^[a-z0-9_]+$`.
