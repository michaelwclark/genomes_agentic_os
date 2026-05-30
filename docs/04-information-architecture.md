# 04 · Information Architecture

> **Purpose:** understand how the installed OS is organized on disk — the root
> layout, the five default domains, the eight numbered operating lanes inside each
> domain, and the context files that make every layer agent-readable. This is the
> physical shape that routing matches against.
>
> **You'll use:** `agentic-os init`, `agentic-os domain create`, `agentic-os validate`.
> **Prereqs:** an installed OS root ([01 · Install & Quickstart](01-install-and-quickstart.md)).

---

## The idea

The installed OS is **domain-first**. The top level is not `workflows/` or
`automations/`; those are lanes inside each domain. Every domain owns its own
policy, context files, projects, and run history. The filesystem is the source of
truth — Notion mirrors it, agents read it, but nothing is invented at runtime.

The hierarchy has three levels:

| Level | Examples | Created by |
| --- | --- | --- |
| **OS root** | `~/agentic_os/` | `agentic-os init` |
| **Domain** | `personal/`, `los/`, `clarks_consulting/` | `init` (defaults) or `domain create` |
| **Numbered lane** | `00-control-plane/` … `08-archive/` | created inside every domain |

---

## The OS root

Running `agentic-os init` (default target: `~/agentic_os`) produces:

```text
~/agentic_os/
  .agentic_root          ← boundary marker read by all harnesses
  AGENTS.md              ← harness-neutral entry point
  CLAUDE.md              ← one-line adapter: @AGENTS.md
  ROUTER.md              ← tells agents which domain owns which work
  CONTEXT.md             ← OS-wide operating context
  RULES.md               ← OS-wide approval and safety rules
  TOOLS.md               ← skill and command inventory (rendered by capability_registry)
  README.md
  registries/            ← capabilities.yml, commands.yml, skills.yml, …
  personal/
  clarks_consulting/
  los/
  shared_factory/
  archive/
```

The `.agentic_root` marker is how `here route` and `here context build` find the
OS boundary — they walk up the directory tree until they hit it.

---

## Domains

The five **default domains** installed by `init`:

| Domain | What it owns |
| --- | --- |
| `personal` | Personal administration, household operations, learning, planning, and life logistics. |
| `clarks_consulting` | Client delivery, consulting operations, sales, marketing, and reusable service workflows. |
| `los` | Loan origination system and lender-related product work, support, releases, implementation, and operational knowledge. |
| `shared_factory` | Shared patterns, templates, routers, reusable automations, schemas, and cross-domain tools. |
| `archive` | Inactive work, retired projects, historical runs, and preserved decisions. |

> `los` is the home for all lender-related work. It is not a separate top-level
> concept. The alias `lenders` routes to `los` automatically.

Additional domains are created with `agentic-os domain create <name>`. The name
must be snake_case; hyphens are rejected. Custom domains get the same numbered
structure as the defaults.

---

## Domain anatomy diagram

![Domain anatomy: the OS root holds five default domains; each domain contains harness context files plus eight numbered operating lanes (00-control-plane through 08-archive); the 03-workflows and 04-automations lanes are each sub-divided into the eight standard lanes](diagrams/infoarch-domain-anatomy.png)

---

## The eight numbered operating lanes

Every domain contains the same numbered structure, created atomically by the
scaffolder:

| Lane | Purpose | Files created |
| --- | --- | --- |
| `00-control-plane/` | Active work, routing, approvals, and decisions. | `active-work.md`, `decisions.md`, `routing-rules.md`, `approval-rules.md` |
| `01-inbox/` | Raw capture and triage — where unprocessed input lands first. | `raw-ideas.md`, `triage.md` |
| `02-projects/` | One folder per active project; local repositories are linked as each project's `src/`. | `README.md` |
| `03-workflows/` | Repeatable human-and-agent workflow specs, divided by lane. | `README.md` + one sub-folder per standard lane |
| `04-automations/` | Trigger-driven automation specs and logs, divided by lane. | `README.md` + one sub-folder per standard lane |
| `05-knowledge/` | Source maps, glossary, memory policy, and reference material. | `source-map.md`, `glossary.md`, `memory-policy.md` |
| `06-runs-and-logs/` | Execution records, artifacts, failures, and activity logs. | `activity-log.md`, `runs/README.md`, `failures/README.md` |
| `07-metrics/` | Baselines and scorecards. | `baselines.md`, `scorecards.md` |
| `08-archive/` | Closed or inactive material. | `README.md` |

---

## The eight standard lanes

`03-workflows/` and `04-automations/` are each subdivided into the same eight
**standard lanes**:

| Lane slug | Scope |
| --- | --- |
| `engineering` | Code, infrastructure, releases, tooling. |
| `marketing` | Content, campaigns, positioning. |
| `sales` | Pipeline, proposals, outreach. |
| `support` | Customer or stakeholder help, escalations. |
| `operations` | Process, tooling, vendor management. |
| `finance` | Budgets, invoices, financial records. |
| `personal_admin` | Scheduling, personal logistics, admin tasks. |
| `learning` | Research, reading, courses, skill-building. |

A workflow spec lives at e.g. `los/03-workflows/engineering/deploy_release/`.
An automation spec lives at e.g. `los/04-automations/support/ticket_intake/`.

---

## Context files at every routeable layer

The OS places the same set of context files at both the root and at each domain.
These are what agents read on entry before any tool is called:

| File | Role |
| --- | --- |
| `AGENTS.md` | Harness-neutral entry point. Tells the agent to read the remaining files, route to the narrowest layer, and repeat the read loop after changing directory. |
| `CLAUDE.md` | Single-line Claude adapter: `@AGENTS.md`. Not a separate doc — it is the harness shim. |
| `ROUTER.md` | Routing table mapping work topics to domains (root level) or to lanes and projects (domain level). |
| `CONTEXT.md` | Operating context: purpose, active outcomes, source systems, approval rules. |
| `RULES.md` | Approval gates, never-allowed actions, safety constraints. |
| `TOOLS.md` | Rendered inventory of skills, commands, and MCP servers available at this layer (generated from `capability_registry`). |
| `REFERENCES.md` | *(domain level only)* Source maps, linked repos, external systems, glossary pointers. |
| `domain.yml` | *(domain level only)* Machine-readable domain config: slug, display name, purpose. |

`MEMORY.md` and `BRAIN.md` may also appear here if the memory system has written
to this layer; they are not scaffolded by `init` but are part of the full context
contract (see [05 · Routing & Context](05-routing-and-context.md)).

---

## Naming rules

- **All filesystem names are snake_case.** `clarks_consulting`, `launch_blog`,
  `ticket_intake` — not `clarks-consulting`, `launch-blog`, `ticket-intake`.
  The CLI validates this at creation time and exits 1 if the name contains hyphens
  or uppercase letters.
- **Notion page titles are human-readable.** Snake_case is for the filesystem;
  "Clark's Consulting" is for display.
- **Do not encode transient status in filenames.** Use YAML front matter or the
  `status:` field in `project.yml` instead.
- **Stable IDs in sidecar config.** If an object maps to Notion, Jira, GitHub, or
  a database row, keep the external ID in `project.yml` or `domain.yml`, not in
  the folder name.

---

## Real output: `domain create`

Running `agentic-os domain create acme --root ~/agentic_os` produces (abbreviated):

```text
created: ~/agentic_os/acme
created: ~/agentic_os/acme/README.md
created: ~/agentic_os/acme/ROUTER.md
created: ~/agentic_os/acme/AGENTS.md
created: ~/agentic_os/acme/CLAUDE.md
created: ~/agentic_os/acme/CONTEXT.md
created: ~/agentic_os/acme/RULES.md
created: ~/agentic_os/acme/TOOLS.md
created: ~/agentic_os/acme/REFERENCES.md
created: ~/agentic_os/acme/domain.yml
created: ~/agentic_os/acme/00-control-plane
created: ~/agentic_os/acme/01-inbox
created: ~/agentic_os/acme/02-projects
created: ~/agentic_os/acme/03-workflows
created: ~/agentic_os/acme/04-automations
created: ~/agentic_os/acme/05-knowledge
created: ~/agentic_os/acme/06-runs-and-logs
created: ~/agentic_os/acme/06-runs-and-logs/runs
created: ~/agentic_os/acme/06-runs-and-logs/failures
created: ~/agentic_os/acme/07-metrics
created: ~/agentic_os/acme/08-archive
created: ~/agentic_os/acme/00-control-plane/active-work.md
created: ~/agentic_os/acme/00-control-plane/decisions.md
created: ~/agentic_os/acme/00-control-plane/routing-rules.md
created: ~/agentic_os/acme/00-control-plane/approval-rules.md
created: ~/agentic_os/acme/01-inbox/raw-ideas.md
created: ~/agentic_os/acme/01-inbox/triage.md
created: ~/agentic_os/acme/05-knowledge/source-map.md
created: ~/agentic_os/acme/05-knowledge/glossary.md
created: ~/agentic_os/acme/05-knowledge/memory-policy.md
created: ~/agentic_os/acme/06-runs-and-logs/activity-log.md
created: ~/agentic_os/acme/07-metrics/baselines.md
created: ~/agentic_os/acme/07-metrics/scorecards.md
```

Exit code: **0**. Re-running is safe — existing files are not overwritten.

---

## Running this from Claude vs Codex

> Same filesystem layout, same context files, same `domain create` output — only the trigger differs.

- **Claude:** run the `/os-discover-rooms` command or invoke the **`domain-setup`**
  skill to scaffold a new domain interactively. `CLAUDE.md` at the domain root is
  the `@AGENTS.md` adapter the harness picks up automatically.
- **Codex:** run `agentic-os domain create <name> --root ~/agentic_os` directly,
  or use `agentic-os init` to install the full default set. The `agentic_os_root`
  profile in `config.toml` points Codex at the installed root so it reads the
  context files on every session start.

Full mechanics: [13 · Agent Surfaces](13-agent-surfaces.md).

---

## Guardrails & gotchas

- **snake_case only.** `agentic-os domain create my-domain` exits 1 immediately.
  Use `my_domain`.
- **`--root` defaults to `~/agentic_os`.** All commands accept `--root` to target
  a different installed root. Customer OSes always pass an explicit `--root`.
- **Scaffold is idempotent.** Re-running `init` or `domain create` against an
  existing tree adds missing files but never overwrites hand-authored content.
  Exit 0 in both the create and the no-op case.
- **`shared_factory` is not a scratch pad.** It holds shared templates, schemas,
  skills, and commands surfaced to all domains. Put reusable assets there, not
  one-off project notes.
- **`archive` is not a trash can.** Move work there when it should no longer
  appear in active routing — but keep it for audit and historical reference.
- **`06-runs-and-logs/` has two sub-directories by design.** `runs/` holds
  timestamped run folders (see [08 · Runs & Run Logs](08-runs-and-run-logs.md));
  `failures/` holds failure records separated for easy triage.
- **No top-level lanes.** `~/agentic_os/engineering/` is wrong. Engineering work
  lives at `~/agentic_os/<domain>/03-workflows/engineering/`.

---

## Related

- [03 · Operating Model](03-operating-model.md) — how agents traverse this layout in the operating loop.
- [05 · Routing & Context](05-routing-and-context.md) — how `route` matches a request against this structure.
- [06 · Workflows](06-workflows.md) — what goes inside `03-workflows/<lane>/`.
- [07 · Automations](07-automations.md) — what goes inside `04-automations/<lane>/`.
- [08 · Runs & Run Logs](08-runs-and-run-logs.md) — how `06-runs-and-logs/` is used.
- [15 · Customer OS Factory](15-customer-os-factory.md) — creating OS roots for other organizations.
- [16 · Health, Doctor & Validation](16-health-doctor-validation.md) — validating a root's structural correctness.
- Atlas: [`architecture/system-architecture.md` §3](../.agentic-atlas/architecture/system-architecture.md) · [`command-reference.md`](../.agentic-atlas/architecture/command-reference.md)
