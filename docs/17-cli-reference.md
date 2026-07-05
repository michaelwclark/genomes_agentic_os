# 17 · CLI Reference

> **Purpose:** a navigable map of every `agentic-os` command — conventions up front,
> commands grouped and cross-linked, and a direct pointer to the exhaustive 1,491-line
> reference that documents every flag and real output.
>
> **You'll use:** this page to orient quickly; then jump to the handbook section that
> owns each group, or straight to the atlas reference for flag detail.
> **Prereqs:** `agentic-os` installed and an OS root initialised
> ([01 · Install & Quickstart](01-install-and-quickstart.md)).

---

## Conventions

These rules apply to **every** `agentic-os` invocation. Memorise them once; they
never change.

| Convention | Rule |
| --- | --- |
| **Name format** | `snake_case` only — lowercase letters, digits, underscores. Hyphens are **rejected**. `weekly-report` fails; `weekly_report` works. |
| **`--root` default** | `~/agentic_os`. Always pass `--root` explicitly in scripts; never rely on the default in automation. |
| **Exit 0** | Success. |
| **Exit 1** | Health check "not ok" — `doctor` / `validate` commands report a problem. Fix it and re-run. |
| **Exit 2** | Argparse usage error **or** deliberate handled refusal — e.g. `here route` when routing confidence is low, `config install` when blocked by conflicts. Exit 2 is not a crash; it is the OS saying "I won't guess." |
| **Dry-run by default** | Mutating commands preview their effect and do nothing unless you add `--apply`. Affected: `runtime run-next`, `run-queue prune`, `schedule run-due`, `automation-control run`, `event process-due`, `event replay`, `backup run`, `heartbeat run`, `update pull`, `integration setup`, `watch-source poll`, `watch-source run-due`, `notion sync`, `notion bootstrap`, `notion track-runtime`, `config install`, `config install-tree`. |
| **`backup run` prerequisite** | Requires `update register` first (generates an update grant). |
| **`config` subcommands** | Exactly `install`, `install-tree`, and `doctor` — no `config layers` subcommand exists. |

---

## Command-group map

![CLI command groups: thirteen clusters arranged around the agentic-os root — core lifecycle, domains/projects/routing, workflows/automations/runs, profiles/rooms, runtime/always-on, events/chains, connected sources, notion control plane, config, update/backup/license, migration/validation, and customer OS factory](diagrams/cli-command-groups.png)

---

## Command index

Every row links to the handbook page that explains the **why and how**, and to the
atlas command reference for the full flag table and real captured output.

### Core lifecycle

| Command(s) | What it does | Handbook | Atlas |
| --- | --- | --- | --- |
| `init` | Scaffold a new OS root from templates | [01 · Install & Quickstart](01-install-and-quickstart.md) | [§2](../.agentic-atlas/architecture/command-reference.md) |
| `validate` | Check OS root structure integrity (exits 1 if not ok) | [16 · Health, Doctor & Validation](16-health-doctor-validation.md) | [§2](../.agentic-atlas/architecture/command-reference.md) |
| `doctor` | Full health check across all subsystems; `--fix-missing` auto-repairs | [16 · Health, Doctor & Validation](16-health-doctor-validation.md) | [§2](../.agentic-atlas/architecture/command-reference.md) |
| `docs install` | Install the handbook into `~/agentic_os/docs/` | [01 · Install & Quickstart](01-install-and-quickstart.md) | [§2](../.agentic-atlas/architecture/command-reference.md) |
| `docs update` | Pull handbook updates | [14 · Config, Update & Backup](14-config-update-backup.md) | [§2](../.agentic-atlas/architecture/command-reference.md) |

### Domains, projects & routing

| Command(s) | What it does | Handbook | Atlas |
| --- | --- | --- | --- |
| `domain create <slug>` | Scaffold a new domain directory | [04 · Information Architecture](04-information-architecture.md) | [§3](../.agentic-atlas/architecture/command-reference.md) |
| `project create <domain> <slug>` | Scaffold a project inside a domain | [04 · Information Architecture](04-information-architecture.md) | [§3](../.agentic-atlas/architecture/command-reference.md) |
| `project link-source <domain> <slug>` / `project src <domain> <slug>` | Create or repair a project-local `src` symlink to a local repository | [01 · Install & Quickstart](01-install-and-quickstart.md) | [§3](../.agentic-atlas/architecture/command-reference.md) |
| `project onboard <domain> <slug>` | Repair missing project-local agent/config/work-item/worktree files | [13 · Agent Surfaces](13-agent-surfaces.md) | [§3](../.agentic-atlas/architecture/command-reference.md) |
| `project work-item create <domain> <slug>` | Capture indexed project ideas and lifecycle packets in `work-items/` lanes | [13 · Agent Surfaces](13-agent-surfaces.md) | [§3](../.agentic-atlas/architecture/command-reference.md) |
| `project work-item repair <domain> <slug>` | Backfill missing lifecycle packet files and folders without overwriting local edits | [13 · Agent Surfaces](13-agent-surfaces.md) | [§3](../.agentic-atlas/architecture/command-reference.md) |
| `project work-item infer-complete` | Infer completed active work items from terminal evidence, closeout artifacts, and quiet conversation activity | [13 · Agent Surfaces](13-agent-surfaces.md) | [§3](../.agentic-atlas/architecture/command-reference.md) |
| `project work-item finalize-lingering` | Move terminal-status packets out of active lanes, update active-work indexes, and refresh the global active container | [13 · Agent Surfaces](13-agent-surfaces.md) | [§3](../.agentic-atlas/architecture/command-reference.md) |
| `project work-item sync-active` | Rebuild the root `00-control-plane/active/` symlink view from active work items, worktrees, and automations | [13 · Agent Surfaces](13-agent-surfaces.md) | [§3](../.agentic-atlas/architecture/command-reference.md) |
| `project worktree cleanup-closed` | Move cached terminal-status or merged-PR worktree registrations to `worktrees/closed.yml` and optionally remove merged in-project worktree directories unless `REOPEN.md` is present | [13 · Agent Surfaces](13-agent-surfaces.md) | [§3](../.agentic-atlas/architecture/command-reference.md) |
| `project worktree add <domain> <slug> <name> --path <path>` | Register a visible worktree symlink and routing index entry | [05 · Routing & Context](05-routing-and-context.md) | [§3](../.agentic-atlas/architecture/command-reference.md) |
| `host add <alias>` | Add or update an SSH host identity, including the host path-domain root | [23 · Configuration Surfaces](23-configuration-surfaces.md) | pending |
| `host list` | List registered SSH host identities | [23 · Configuration Surfaces](23-configuration-surfaces.md) | pending |
| `host routing` | Show cross-host routing policy and recent remote harness receipts | [23 · Configuration Surfaces](23-configuration-surfaces.md) | pending |
| `route <request>` | Deterministically route a free-text request to a domain/project | [05 · Routing & Context](05-routing-and-context.md) | [§3](../.agentic-atlas/architecture/command-reference.md) |
| `context build --domain <d>` | Build a `ContextPacket` without a request string | [05 · Routing & Context](05-routing-and-context.md) | [§3](../.agentic-atlas/architecture/command-reference.md) |
| `here route <request>` | Route from the current working directory (exits 2 on low confidence) | [05 · Routing & Context](05-routing-and-context.md) | [§3](../.agentic-atlas/architecture/command-reference.md) |
| `here context build` | Context-build scoped to cwd | [05 · Routing & Context](05-routing-and-context.md) | [§3](../.agentic-atlas/architecture/command-reference.md) |

### Programs

| Command(s) | What it does | Handbook | Atlas |
| --- | --- | --- | --- |
| `program create <name>` | Scaffold a shared OSProgram under `harness/shared_factory/00-programs/` | [21 · OS Programs](21-os-programs.md) | pending |
| `instance-program create <domain> <name>` | Scaffold a domain-local InstanceOSProgram under `<domain>/00-programs/` | [21 · OS Programs](21-os-programs.md) | pending |

### Workflows, automations & run logs

| Command(s) | What it does | Handbook | Atlas |
| --- | --- | --- | --- |
| `workflow create <domain> <lane> <name>` | Scaffold a workflow definition | [06 · Workflows](06-workflows.md) | [§4](../.agentic-atlas/architecture/command-reference.md) |
| `workflow check <domain> <lane> <name>` | Validate a workflow's readiness checklist | [06 · Workflows](06-workflows.md) | [§4](../.agentic-atlas/architecture/command-reference.md) |
| `automation create <domain> <lane> <name>` | Scaffold an automation scaffold in a lane | [07 · Automations](07-automations.md) | [§4](../.agentic-atlas/architecture/command-reference.md) |
| `automation check <domain> <lane> <name>` | Validate automation definition | [07 · Automations](07-automations.md) | [§4](../.agentic-atlas/architecture/command-reference.md) |
| `automation attach <domain> <lane> <name> <project>` | Attach automation to a project | [07 · Automations](07-automations.md) | [§4](../.agentic-atlas/architecture/command-reference.md) |
| `automation set-maturity <domain> <lane> <name> <level>` | Advance maturity: `observe` → `prepare` → `propose` → `execute_approved` → `execute_guarded` | [07 · Automations](07-automations.md) | [§4](../.agentic-atlas/architecture/command-reference.md) |
| `run-log create <domain> <workflow_or_automation>` | **Required first step** — open a timestamped run log; returns the `run_id` needed by `run-log close` | [08 · Runs & Run Logs](08-runs-and-run-logs.md) | [§4](../.agentic-atlas/architecture/command-reference.md) |
| `run-log close <domain> <run_id> --status <s>` | Close a run log; `--status done` requires `--validation` evidence; `run_id` comes from `run-log create` | [08 · Runs & Run Logs](08-runs-and-run-logs.md) | [§4](../.agentic-atlas/architecture/command-reference.md) |

### Profiles & rooms

| Command(s) | What it does | Handbook | Atlas |
| --- | --- | --- | --- |
| `profile create` | Create a harness profile (agent persona) | [13 · Agent Surfaces](13-agent-surfaces.md) | [§5](../.agentic-atlas/architecture/command-reference.md) |
| `profile validate` | Validate profile structure (exits 1 if not ok) | [13 · Agent Surfaces](13-agent-surfaces.md) | [§5](../.agentic-atlas/architecture/command-reference.md) |
| `room create <slug>` | Scaffold a room (lightweight domain-like directory) | [04 · Information Architecture](04-information-architecture.md) | [§5](../.agentic-atlas/architecture/command-reference.md) |
| `room update <slug>` | Update room metadata | [04 · Information Architecture](04-information-architecture.md) | [§5](../.agentic-atlas/architecture/command-reference.md) |

### Runtime & always-on

| Command(s) | What it does | Handbook | Atlas |
| --- | --- | --- | --- |
| `runtime init` | Initialise the runtime queue registry | [09 · Runtime & Always-On](09-runtime-and-always-on.md) | [§6](../.agentic-atlas/architecture/command-reference.md) |
| `runtime doctor` | Health-check the runtime registry (exits 1 if not ok) | [09 · Runtime & Always-On](09-runtime-and-always-on.md) | [§6](../.agentic-atlas/architecture/command-reference.md) |
| `runtime run-next` | Preview or dispatch the next safe queued item (`--apply` to dispatch) | [09 · Runtime & Always-On](09-runtime-and-always-on.md) | [§6](../.agentic-atlas/architecture/command-reference.md) |
| `run-queue prune` / `runtime prune` | Preview or prune stale run-queue rows and old queue backups (`--apply` to rewrite) | [09 · Runtime & Always-On](09-runtime-and-always-on.md) | [§6](../.agentic-atlas/architecture/command-reference.md) |
| `ps --active` | Show active runtime work, including recent remote harness receipts from cross-host dispatch | [09 · Runtime & Always-On](09-runtime-and-always-on.md) | pending |
| `heartbeat list` | List all configured heartbeats | [09 · Runtime & Always-On](09-runtime-and-always-on.md) | [§6](../.agentic-atlas/architecture/command-reference.md) |
| `heartbeat run` | Trigger a heartbeat (dry-run by default) | [09 · Runtime & Always-On](09-runtime-and-always-on.md) | [§6](../.agentic-atlas/architecture/command-reference.md) |
| `heartbeat doctor` | Health-check heartbeat config | [09 · Runtime & Always-On](09-runtime-and-always-on.md) | [§6](../.agentic-atlas/architecture/command-reference.md) |
| `schedule create <name>` | Define a named cron-style schedule | [09 · Runtime & Always-On](09-runtime-and-always-on.md) | [§6](../.agentic-atlas/architecture/command-reference.md) |
| `schedule run-due` | Preview or enqueue schedules that are due (`--apply` to enqueue) | [09 · Runtime & Always-On](09-runtime-and-always-on.md) | [§6](../.agentic-atlas/architecture/command-reference.md) |
| `automation-control list` | List source-gated automation targets | [09 · Runtime & Always-On](09-runtime-and-always-on.md) | pending |
| `automation-control doctor` | Validate source-gated automation config | [09 · Runtime & Always-On](09-runtime-and-always-on.md) | pending |
| `automation-control run` | Preview or enqueue source-gated automation targets (`--apply` to enqueue) | [09 · Runtime & Always-On](09-runtime-and-always-on.md) | pending |
| `integration list` | List registered integrations | [11 · Connected Sources](11-connected-sources.md) | [§6](../.agentic-atlas/architecture/command-reference.md) |
| `integration doctor` | Health-check integration credentials | [11 · Connected Sources](11-connected-sources.md) | [§6](../.agentic-atlas/architecture/command-reference.md) |
| `integration setup` | Configure an integration (dry-run by default) | [11 · Connected Sources](11-connected-sources.md) | [§6](../.agentic-atlas/architecture/command-reference.md) |

### Events & chains

| Command(s) | What it does | Handbook | Atlas |
| --- | --- | --- | --- |
| `event append` | Append a typed event to the graph | [10 · Events & Chains](10-events-and-chains.md) | [§7](../.agentic-atlas/architecture/command-reference.md) |
| `event list` | List recent events | [10 · Events & Chains](10-events-and-chains.md) | [§7](../.agentic-atlas/architecture/command-reference.md) |
| `event summary` | Summarise the event graph | [10 · Events & Chains](10-events-and-chains.md) | [§7](../.agentic-atlas/architecture/command-reference.md) |
| `event process-due` | Preview or fire events that are due (dry-run by default) | [10 · Events & Chains](10-events-and-chains.md) | [§7](../.agentic-atlas/architecture/command-reference.md) |
| `event replay` | Re-fire historical events (dry-run by default) | [10 · Events & Chains](10-events-and-chains.md) | [§7](../.agentic-atlas/architecture/command-reference.md) |
| `chain list` | List configured chain rules | [10 · Events & Chains](10-events-and-chains.md) | [§7](../.agentic-atlas/architecture/command-reference.md) |
| `chain test` | Dry-run a chain rule against a sample event | [10 · Events & Chains](10-events-and-chains.md) | [§7](../.agentic-atlas/architecture/command-reference.md) |
| `chain doctor` | Health-check chain rule definitions | [10 · Events & Chains](10-events-and-chains.md) | [§7](../.agentic-atlas/architecture/command-reference.md) |

### Connected sources

| Command(s) | What it does | Handbook | Atlas |
| --- | --- | --- | --- |
| `connected-system list` | List registered connected systems | [11 · Connected Sources](11-connected-sources.md) | [§8](../.agentic-atlas/architecture/command-reference.md) |
| `connected-system doctor` | Health-check connected-system credentials | [11 · Connected Sources](11-connected-sources.md) | [§8](../.agentic-atlas/architecture/command-reference.md) |
| `watch-source list` | List all watch source definitions | [11 · Connected Sources](11-connected-sources.md) | [§8](../.agentic-atlas/architecture/command-reference.md) |
| `watch-source create <id>` | Create a file-backed watch source (slug must be `snake_case`) | [11 · Connected Sources](11-connected-sources.md) | [§8](../.agentic-atlas/architecture/command-reference.md) |
| `watch-source doctor` | Health-check watch source definitions | [11 · Connected Sources](11-connected-sources.md) | [§8](../.agentic-atlas/architecture/command-reference.md) |
| `watch-source poll` | Poll a source for new items (dry-run by default) | [11 · Connected Sources](11-connected-sources.md) | [§8](../.agentic-atlas/architecture/command-reference.md) |
| `watch-source run-due` | Poll all sources whose cadence is due (dry-run by default) | [11 · Connected Sources](11-connected-sources.md) | [§8](../.agentic-atlas/architecture/command-reference.md) |

### Notion control plane

| Command(s) | What it does | Handbook | Atlas |
| --- | --- | --- | --- |
| `notion plan-sync` | Show what a Notion sync would do (always read-only) | [12 · Control Plane — Notion](12-control-plane-notion.md) | [§9](../.agentic-atlas/architecture/command-reference.md) |
| `notion sync` | Push OS state to Notion (dry-run by default; `--apply` to write) | [12 · Control Plane — Notion](12-control-plane-notion.md) | [§9](../.agentic-atlas/architecture/command-reference.md) |
| `notion bootstrap` | Create or update Notion databases and dashboard (dry-run by default) | [12 · Control Plane — Notion](12-control-plane-notion.md) | [§9](../.agentic-atlas/architecture/command-reference.md) |
| `notion track-runtime` | Record runtime stats in Notion (dry-run by default) | [12 · Control Plane — Notion](12-control-plane-notion.md) | [§9](../.agentic-atlas/architecture/command-reference.md) |

### Config

| Command(s) | What it does | Handbook | Atlas |
| --- | --- | --- | --- |
| `config install --layer <l>` | Install or merge `config.toml` at a named layer (dry-run by default; apply exits 2 on conflicts) | [14 · Config, Update & Backup](14-config-update-backup.md) | [§10](../.agentic-atlas/architecture/command-reference.md) |
| `config install-tree` | Install or repair `config.toml` across the routed OS tree (root, domains, projects, workflows, automations) | [13 · Agent Surfaces](13-agent-surfaces.md) | [§10](../.agentic-atlas/architecture/command-reference.md) |
| `config doctor --layer <l>` | Validate `config.toml` OTEL and MCP contracts (exits 1 when absent) | [14 · Config, Update & Backup](14-config-update-backup.md) | [§10](../.agentic-atlas/architecture/command-reference.md) |
| `hook sync` / `hook doctor` | Point active Claude/Codex hook settings at `~/agentic_os/harness/hooks` and verify no copied hook scripts remain authoritative | [13 · Agent Surfaces](13-agent-surfaces.md) | [§10](../.agentic-atlas/architecture/command-reference.md) |

Valid `--layer` values: `agentic_os_root`, `automation`, `customer_os_root`,
`domain_or_lane`, `global_harness`, `project`, `workflow_or_task`.

### Update, backup & license

| Command(s) | What it does | Handbook | Atlas |
| --- | --- | --- | --- |
| `update register` | Register the OS installation and generate an update grant (required before `backup run`) | [14 · Config, Update & Backup](14-config-update-backup.md) | [§11](../.agentic-atlas/architecture/command-reference.md) |
| `update check` | Check for available updates | [14 · Config, Update & Backup](14-config-update-backup.md) | [§11](../.agentic-atlas/architecture/command-reference.md) |
| `update plan` | Preview what an update would change | [14 · Config, Update & Backup](14-config-update-backup.md) | [§11](../.agentic-atlas/architecture/command-reference.md) |
| `update pull` | Record an operator-pushed update pull (dry-run by default) | [14 · Config, Update & Backup](14-config-update-backup.md) | [§11](../.agentic-atlas/architecture/command-reference.md) |
| `update apply` | Apply a pulled update | [14 · Config, Update & Backup](14-config-update-backup.md) | [§11](../.agentic-atlas/architecture/command-reference.md) |
| `update rollback` | Roll back the last applied update | [14 · Config, Update & Backup](14-config-update-backup.md) | [§11](../.agentic-atlas/architecture/command-reference.md) |
| `update status` | Show current update state | [14 · Config, Update & Backup](14-config-update-backup.md) | [§11](../.agentic-atlas/architecture/command-reference.md) |
| `update phone-home` | Report telemetry | [14 · Config, Update & Backup](14-config-update-backup.md) | [§11](../.agentic-atlas/architecture/command-reference.md) |
| `backup run` | Plan or execute a GitHub-backed state backup (dry-run by default; needs `update register` first) | [14 · Config, Update & Backup](14-config-update-backup.md) | [§11](../.agentic-atlas/architecture/command-reference.md) |
| `backup push` | Record a local backup push run log; skips remote push when no update grant is present, always logs locally | [14 · Config, Update & Backup](14-config-update-backup.md) | [§11](../.agentic-atlas/architecture/command-reference.md) |
| `fleet push <customer_slug>` | Record a simulated operator-push event for a customer installation (V1 local-only, no real network calls) | [14 · Config, Update & Backup](14-config-update-backup.md) | [§11](../.agentic-atlas/architecture/command-reference.md) |
| `license activate` | Activate a license key | [14 · Config, Update & Backup](14-config-update-backup.md) | [§11](../.agentic-atlas/architecture/command-reference.md) |
| `metrics refresh` | Compute a scorecard from run logs, doctor findings, and automation maturity; writes to `07-metrics/scorecard.yml` | [07 · Automations](07-automations.md) | [§11](../.agentic-atlas/architecture/command-reference.md) |

### Migration & validation

| Command(s) | What it does | Handbook | Atlas |
| --- | --- | --- | --- |
| `migrate plan` | Preview schema or data migrations | [16 · Health, Doctor & Validation](16-health-doctor-validation.md) | [§12](../.agentic-atlas/architecture/command-reference.md) |
| `migrate apply` | Apply pending migrations | [16 · Health, Doctor & Validation](16-health-doctor-validation.md) | [§12](../.agentic-atlas/architecture/command-reference.md) |
| `losmon validate` | Cross-validate OS state against a losmon export | [16 · Health, Doctor & Validation](16-health-doctor-validation.md) | [§12](../.agentic-atlas/architecture/command-reference.md) |
| `plan capture` | Snapshot current plan state to a dated file | [03 · Operating Model](03-operating-model.md) | [§12](../.agentic-atlas/architecture/command-reference.md) |

### Customer OS factory

| Command(s) | What it does | Handbook | Atlas |
| --- | --- | --- | --- |
| `customer init <slug>` | Scaffold a new customer OS root from factory templates | [15 · Customer OS Factory](15-customer-os-factory.md) | [§13](../.agentic-atlas/architecture/command-reference.md) |
| `customer update <slug>` | Push factory updates into an existing customer OS | [15 · Customer OS Factory](15-customer-os-factory.md) | [§13](../.agentic-atlas/architecture/command-reference.md) |
| `customer validate <slug>` | Validate a customer OS against factory schema | [15 · Customer OS Factory](15-customer-os-factory.md) | [§13](../.agentic-atlas/architecture/command-reference.md) |

---

## Real examples

```bash
# Bootstrap a fresh OS, run doctor, then open the Notion control plane
agentic-os init --root ~/agentic_os
agentic-os doctor --root ~/agentic_os
agentic-os notion bootstrap --root ~/agentic_os --dry-run   # preview first
agentic-os notion bootstrap --root ~/agentic_os --apply

# Route a request and build the context packet
agentic-os route "ship the launch blog post" --root ~/agentic_os
agentic-os context build --domain acme --project launch --root ~/agentic_os

# Advance an automation through the maturity ladder
agentic-os automation set-maturity acme support ticket_intake prepare \
  --root ~/agentic_os

# Install a config layer for Codex, then verify it
agentic-os config install-tree --root ~/agentic_os --dry-run
agentic-os config install --layer domain_or_lane --root ~/agentic_os/acme --dry-run
agentic-os config install --layer domain_or_lane --root ~/agentic_os/acme --apply --backup
agentic-os config doctor --layer domain_or_lane --root ~/agentic_os/acme

# Run what is due, all dry-run by default
agentic-os schedule run-due --root ~/agentic_os
agentic-os event process-due --root ~/agentic_os
agentic-os watch-source run-due --root ~/agentic_os
# Commit any of the above: add --apply
```

---

## How to read the full reference

The table above is the **navigator**. Every flag, every real captured output
(`stdout` / `stderr` / exit code), and every edge case lives in the exhaustive
atlas document:

> **[`.agentic-atlas/architecture/command-reference.md`](../.agentic-atlas/architecture/command-reference.md)**
> — 1,491 lines, 13 sections, one subsection per concrete invocation.

When the index row above says "§4", that is the atlas section number. Open the
atlas reference, jump to section 4, and you will find the full flag table and a
verbatim real-output block for every subcommand in that group.

---

## Validated baseline

Tested by `.agentic-atlas/tools/validate-cli.sh` against a scratch root:

| Status | Count | Meaning |
| --- | --- | --- |
| **OK** | 53 | Exits 0 as expected |
| **GUARDED** | 2 | `here route` and `config doctor` guardrail exits by design |
| Crashes / tracebacks | 0 | None |
| **Total validated** | 55 | Full matrix: [`.agentic-atlas/validation/RESULTS.md`](../.agentic-atlas/validation/RESULTS.md) |

Commands not yet in the 55-invocation matrix (e.g. `room`, `watch-source create`,
`notion sync`, `update apply`, `customer update`) are structurally sound — argparse
definitions and handlers exist — but lack captured real-output evidence. They are
listed here for navigation; treat them with normal care and run `--dry-run` first.

---

## Running this from Claude vs Codex

> Same commands, same exit codes, same `--root` rules — only the trigger differs.

- **Claude:** invoke `/os-doctor` (full health check), `/os-route` (routing), or
  the relevant skill (e.g. `workflow-builder`, `runtime-operator`, `source-watcher`).
  Skills wrap the CLI call and surface the result inline.
- **Codex:** call `agentic-os <command> --root ~/agentic_os` directly. The config
  layer for the target directory (`domain_or_lane`, `agentic_os_root`, etc.) in
  `config.toml` governs model, tool allow-list, and approval hooks for that context.

Full mechanics: [13 · Agent Surfaces](13-agent-surfaces.md).

---

## Guardrails & gotchas

- **Hyphens are rejected in slugs.** `weekly-report` silently produces the wrong
  path; use `weekly_report`. This applies to all positional `<slug>` arguments —
  domains, projects, automations, watch sources, customers.
- **Dry-run is default, not optional.** If a mutating command does nothing and
  produces no error, check whether you forgot `--apply`.
- **Exit 2 is not a crash.** `here route` exits 2 when cwd does not map confidently
  to a known domain. `cd` into the domain directory or use `route` with `--root`
  instead.
- **`config` has three subcommands.** There is no `config layers` or
  `config list`. The subcommands are `install`, `install-tree`, and `doctor`.
- **`backup run` requires `update register` first.** Running `backup run` without a
  prior `update register` will fail — register generates the update grant that
  backup depends on.
- **`run-log create` must come before `run-log close`.** Run
  `agentic-os run-log create <domain> <workflow_or_automation> --root <root>`
  first; it returns a `run_id`. Pass that `run_id` to `run-log close`. Skipping
  the create step is the most common reason `run-log close` fails.
- **`run-log close --status done` requires `--validation` evidence.** Missing
  evidence is a guardrail (exits non-zero with an explanation), not a crash. Add
  `--validation "..."` and re-run.

---

## Related

- [01 · Install & Quickstart](01-install-and-quickstart.md) — get `agentic-os` onto your machine.
- [05 · Routing & Context](05-routing-and-context.md) — deep-dive on the routing commands.
- [16 · Health, Doctor & Validation](16-health-doctor-validation.md) — all the `doctor` / `validate` commands in context.
- [14 · Config, Update & Backup](14-config-update-backup.md) — `config`, `update`, `backup`, `license` in context.
- [18 · Troubleshooting & FAQ](18-troubleshooting-and-faq.md) — what to do when a command exits unexpectedly.
- Atlas: [`command-reference.md`](../.agentic-atlas/architecture/command-reference.md) (exhaustive) · [`validation/RESULTS.md`](../.agentic-atlas/validation/RESULTS.md) (status matrix)
