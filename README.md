# Genome's Agentic OS

Genome's Agentic OS is the source package and CLI (`agentic-os`, aliased `aos`)
that scaffolds, validates, updates, and operates a local, file-first agentic
operating system. An installed OS is domain-first: domain roots hold
workflows, automations, and run logs, sitting alongside a shared harness
control plane and knowledge lanes. Codex, Claude, and human operators read
and write the same filesystem state instead of each chat rebuilding its own
operating context from scratch.

> **New here?** Read the handbook in [`docs/`](docs/README.md). Maintainers and
> agents: start at [`docs/architecture/system-architecture.md`](docs/architecture/system-architecture.md) —
> the maintained architecture map and command reference, so you never
> re-analyze the repo from scratch.

![Agentic OS Value Flow](docs/diagrams/value-flow.svg)

## What It Can Do

Every row below is a family of commands. For the why-and-how, read the linked
handbook page in [`docs/README.md`](docs/README.md); for every flag and
subcommand, see [`docs/17-cli-reference.md`](docs/17-cli-reference.md).

| Capability | What it does | Primary command |
| --- | --- | --- |
| Install / scaffold + update | Creates a complete domain-first OS tree from templates in one pass (`init`), then applies additive updates later without overwriting local edits (`update apply`). | `agentic-os init --target ~/agentic_os` |
| Domains | Scaffolds a new top-level domain with the same numbered lanes as the defaults: control plane, programs, inbox, projects, workflows, automations, knowledge, runs, metrics, archive. | `agentic-os domain create <name>` |
| Workflows | Scaffolds a repeatable, human-reviewed process folder (outcome brief, PRD, implementation plan, context pack, runbook, approvals) and checks it against a readiness checklist. | `agentic-os workflow create <domain> <lane> <name>` |
| Automations | Scaffolds a trigger-driven automation folder and advances it through a maturity ladder — `observe` → `prepare` → `propose` → `execute_approved` → `execute_guarded` — as evidence accumulates. | `agentic-os automation create <domain> <lane> <name>` |
| Programs | Scaffolds a named, reusable capability bundle (skills, commands, workflows, automations, docs, state) shared across the whole OS or scoped to one domain. | `agentic-os program create <name>` |
| Run logs & runs | Opens a timestamped run log before work starts and closes it with audit evidence; `ps` shows what is running right now. | `agentic-os run-log create <domain> <workflow_or_automation>` |
| Validate / doctor / health | Checks required folder structure and file parseability, then runs a full health check across every subsystem with an auto-repair option. | `agentic-os doctor --fix-missing` |
| Config surfaces | Installs or repairs a layered Codex `config.toml` (root, domain, project, workflow, automation) and the matching `AGENTS.md` → `CLAUDE.md` adapter that Claude reads. | `agentic-os config install --layer <layer> --apply` |
| Runtime / always-on | Runs one supervisor tick across heartbeats, schedules, watch sources, events, and the run queue; each piece is also independently manageable. | `agentic-os runtime supervise --apply` |
| Intake / tracker sync | Plans where a capture request should land across the filesystem and Notion, polls connected external systems (Jira, Linear, GitHub, Slack, and others) into local events, and syncs OS state into a Notion control plane. | `agentic-os doc-config plan --request "..."` |
| Self-improvement | Reviews local evidence — conversation reports, doctor findings — and proposes OS improvements for review; nothing lands without an explicit approve/promote step. | `agentic-os self-improvement run` |
| Cockpit | Builds a local, read-only, self-contained HTML dashboard over conversations, work, reviews, reports, connected sources, hosts, automations, and hygiene, and opens it. | `agentic-os cockpit open` |
| State plane | A local SQLite state plane at `<os-root>/00-control-plane/state.db` holds the events ledger, run queue, and watch cursors as queryable rows alongside the markdown files, with commands to initialize it, check its status, import existing files into it, query it, and prune old rows. | `agentic-os state status` |
| Customer OS factory | Scaffolds an isolated client OS from a profile, blocks Genome's private operator-identity terms from leaking into it, and keeps it current. | `agentic-os customer init <slug>` |

## Quickstart

Install the CLI from this repository:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
```

`'.[dev]'` adds pytest for local test development; drop it for a plain
runtime install. The installed command is `agentic-os` (short alias: `aos`).

Smoke-test against a temporary directory before touching a real OS root. This
exact sequence — init, then validate, then install a Codex config layer, then
confirm it with doctor — is verified end-to-end:

```bash
tmpdir=$(mktemp -d)
agentic-os init --target "$tmpdir/os"
agentic-os validate --root "$tmpdir/os"
agentic-os config install --root "$tmpdir/os" --layer agentic_os_root --apply
agentic-os config doctor --root "$tmpdir/os" --layer agentic_os_root
find "$tmpdir/os" -maxdepth 2 | sort
```

Order matters: `config doctor` looks for a `config.toml` that only
`config install` (or `config install-tree`) creates. Running `config doctor`
right after a bare `init`, before `config install`, is a deliberate failure
(exit 1, "config.toml is missing") — it is telling you which step you
skipped, not signaling a bug.

For a real install, use the default root or pass an explicit target:

```bash
agentic-os init --target ~/agentic_os
```

## Repository Map

```text
src/genomes_agentic_os/  Installable Python package.
  cli/                    The `agentic-os` CLI: one module per command group
                          (23 today — scaffold, project, workflow, automation,
                          runtime, notion, customer, and others), registered in
                          cli/__init__.py's COMMAND_MODULES list.
  state/                  Local SQLite state plane: events ledger, run queue,
                          cursors, and importers from the file formats.
docs/                     The handbook: numbered pages, tutorials, feature
                          guides, the architecture atlas, and rendered diagrams.
SPECS/                    Source-package future-work specs and planning
                          backlog. The legacy PLANS/ directory was
                          consolidated into this folder; numbered files kept
                          their numbers.
templates/                Copyable source templates for installed OS objects.
schemas/                  JSON schemas for stricter validation.
examples/                 Example domain operating systems: acme_consulting,
                          lending_ops, personal.
harness/                  Source-of-truth harness assets an install copies in:
                          commands, skills, hooks, registries, rules, and the
                          shared_factory knowledge base.
operating-manual/         The operator/agent manual copied into an installed
                          OS's shared_factory knowledge lane.
installers/               Installer and scaffold planning notes and scripts.
config/                   Example configuration files (hosts, OS, projects).
customer_profiles/        Example customer-profile YAML for the customer OS
                          factory.
skills/                   Claude and Codex skill entrypoints for this source
                          repository itself.
system/                   Host-level shell, terminal, runtime, and
                          package-manager conventions.
tests/                    CLI and scaffold test suite (pytest).
```

Key starting points:

- [Documentation index](docs/README.md)
- [CLI reference](docs/17-cli-reference.md)
- [Architecture atlas](docs/architecture/system-architecture.md)
- [Information architecture](docs/04-information-architecture.md)
- [Install & quickstart](docs/01-install-and-quickstart.md)
- [Spec backlog](SPECS/README.md)
- [Templates](templates/README.md)

## Customization

Domain, project, workflow, and automation names must be filesystem-safe:
lowercase letters, digits, and underscores only (`^[a-z0-9_]+$`); hyphens are
rejected with a suggested snake_case fix. Add more domains with
`agentic-os domain create <name>` — a custom domain gets the same numbered
lane structure as the defaults, so an agent that has learned one domain can
navigate any of them.

Customize domain context, workflow choices, automation permissions, Notion
views, and integration adapters freely. Do not fork the core object
vocabulary, run log format, automation maturity ladder, context pack
contract, or audit evidence requirements without changing the product spec
too — those are the parts every domain and every harness agree on.

Deeper docs: the [handbook](docs/README.md) is the canonical guide for
evaluating, installing, or extending this source package. Once you are
operating inside an installed OS at `~/agentic_os`, use the
[operating manual](operating-manual/README.md) copied there instead — it
covers what to create, where to put it, and what evidence to leave behind.
