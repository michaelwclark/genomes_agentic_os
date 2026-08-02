# Agentic OS — Tool Catalog

An agent lands with a task and needs an answer in under two minutes: does a
tool for this already exist, where does it live, how is it invoked, and where
is its authority documented. This catalog is an **index with routing rules**,
not a restatement — every row points at the authoritative surface (a
registry, `TOOLS.md`, `command-reference.md`) instead of duplicating its full
content. Verified against the `command-center-foundation` worktree and the
installed OS at `/Users/genome/agentic_os` on 2026-07-22; counts and drift
notes are an as-of snapshot, not a guarantee.

## Table of contents

1. [Discovery protocol](#1-discovery-protocol)
2. [CLI: `agentic-os` / `aos`](#2-cli-agentic-os--aos)
3. [Harness registries](#3-harness-registries)
4. [Harness bins](#4-harness-bins)
5. [Control plane](#5-control-plane)
6. [Hooks](#6-hooks)
7. [Rules](#7-rules)
8. [Skills & commands](#8-skills--commands)
9. [MCP servers](#9-mcp-servers)
10. [State & memory planes](#10-state--memory-planes)
11. [Command Center app surfaces](#11-command-center-app-surfaces)
12. [Versioning & drift](#12-versioning--drift)

---

## 1. Discovery protocol

Reuse before you build. Two facts outrank everything else below and should be
read first, every time, per `harness/rules/os-authoring-rules.md`:

| Step | Surface | Path | Why read it first |
| --- | --- | --- | --- |
| 0a | Active work | `harness/shared_factory/00-control-plane/active-now.json` (installed) | Compact projection of work already in flight. Read before any broad context discovery — `state.db` is authoritative, but `active-now.json` is the cheap pre-read. |
| 0b | Versioned object index | `lib/registry/objects.json` (installed; 482KB, no worktree equivalent) | Compact canonical index for programs, workflows, automations, commands, skills, hooks, rules, references, templates, and toolkits. Each selected object's `object.yml` is canonical for mutation; files under `lib/registry` are generated read projections — never edit them directly. |

Once those two are checked, follow the tool-discovery chain:

| Step | Surface | Path | Why read it here |
| --- | --- | --- | --- |
| 1 | Visible tool contract | `harness/TOOLS.md` (installed-only — absent from this worktree, see §12) | Human-readable index of registries, MCP servers, Composio/direct-API routes, plugins, programs, hooks, rules, and a "when to use what" section. |
| 2 | Machine registries | `harness/registries/*.yml` (installed has 27; this worktree carries 8 — see §3, §12) | Structured source of truth `TOOLS.md` is generated from; read the `.yml` directly when you need exact ids, statuses, or provider order. |
| 3 | CLI command/flag reference | `docs/architecture/command-reference.md` (this repo, 2037 lines) | Every `agentic-os` subcommand and flag, organized into 15 numbered groups. See §2. |
| 4 | Project-level tool config | `domains/<domain>/02-projects/<project>/config/tools.yml` (installed OS) | Per-project toolchain facts (runtimes, test runners, CLIs, tracker access). Live examples: `domains/los/02-projects/los_app_los_django/config/tools.yml` and `domains/clarks_consulting/02-projects/genomes_agentic_os/config/tools.yml`. There is no repo-root `config/tools.yml` — this is a project-home surface, not a source-repo one. |
| 5 | Host tool registry | `harness/shared_factory/05-knowledge/host-tool-registry.<host>.yml` (installed) | Per-host tool availability. Only `host-tool-registry.bigmac.yml` exists today (this machine is bigmac). |

**Reuse-before-build rule**: `harness/registries/rules.yml` → `route-read-cd-repeat` — "Read local routing, context, rules, and tools before acting at each layer" — backed by `os-authoring-rules.md` Required Loop step 1 (load the routed `AGENTS.md` / `ROUTER.md` / `CONTEXT.md` / `RULES.md` / `TOOLS.md` before acting). Do not write a new script or skill until you have walked this chain and confirmed nothing already covers the capability.

**If you add a tool, register it**: `os-authoring-rules.md` Required Loop step 9 — adding or renaming a workflow, automation, command, skill, rule, hook, plugin, library, tool, MCP surface, tool route, or program requires updating every canonical registry and readable surface that owns that capability (the relevant `harness/registries/*.yml`, `TOOLS.md`, Codex/Claude adapter metadata, doc-config routes, and any configured external projection). An undocumented OS-level tool is treated as unshipped.

---

## 2. CLI: `agentic-os` / `aos`

Entry point: `src/genomes_agentic_os/cli/__init__.py` — argparse-based (not
Typer). Each command-group module exposes `register(subparsers)`; the
`COMMAND_MODULES` list in `__init__.py` is the authoritative registration
order (37 modules today). `AGENTIC_OS_ROOT` env var overrides the installed
root (default `~/agentic_os`). Full per-command flags: `agentic-os <command>
--help` or `docs/architecture/command-reference.md` — this table intentionally
carries no flags.

| # | Group (command-reference.md heading) | Key subcommands | Doc anchor |
| --- | --- | --- | --- |
| 1 | Conventions | (framing, not a command group) | L10 |
| 2 | Core lifecycle | `init`, `validate`, `doctor`, `docs install`, `docs update` | L28 |
| 3 | Domains, projects & routing | `domain`, `project`, `route`, `context`, `here` | L128 |
| 4 | Workflows, automations & run logs | `workflow`, `automation`, `run-log` | L472 |
| 5 | Profiles & rooms | `profile`, `room` | L658 |
| 6 | Runtime / always-on | `runtime`, `run-queue`, `heartbeat`, `schedule`, `integration`, `report` | L731 |
| 7 | Event graph & chains | `event`, `chain` | L1084 |
| 8 | Connected sources | `connected-system`, `watch-source` | L1235 |
| 9 | Notion | `notion` | L1371 |
| 10 | Codex config | `config` | L1451 |
| 11 | Update / backup / license | `update`, `backup`, `license` | L1541 |
| 12 | Migration & validation | `migrate`, `plan` | L1719 |
| 13 | Host registry & operator projection | `host` | L1783 |
| 13A | Program & automation operator projection | `operator-resource` | L1831 |
| 13B | First-class resource snapshot & tags | `resource-registry` | L1872 |
| 14 | Customer OS factory | `customer` | L1894 |
| 14* | AgenticOSGui desktop | `gui` (`gui snapshot`, `gui transcript`, `gui open`) | L1955 |
| 15 | Universal long-running execution | `long-run` | L2006 |

\* The doc numbers both "Customer OS factory" and "AgenticOSGui desktop" as
group 14 — verified as written in `command-reference.md`, not a transcription
error here.

CLI module inventory (`src/genomes_agentic_os/cli/*.py`, one file per group):
`scaffold, project, workflow, hosts, automation, run_lifecycle, routing,
cockpit, gui, customer, operator, config, notion, runtime, doctor, plans,
self_improvement, source_watch, event_graph, state, validate, docs,
capability, adaptive, spec, resource_graph, resource_actions, reporting,
activity, rules, operator_resources, first_class_registry, develop, library,
work, naming, long_run, work_item_archive`. Most names match a doc group above
by keyword (`workflow.py`↔group 4, `hosts.py`↔group 13, `operator_resources.py`
↔group 13A, `first_class_registry.py`↔group 13B, `long_run.py`↔group 15,
`naming.py`↔`migrate`, `plans.py`↔`plan` in group 12). A handful cover
subcommands nested under a numbered group rather than owning their own
heading (`cockpit`, `develop`, `spec`, `library`, `work`, `state`, `capability`,
`adaptive`, `activity`, `reporting`, `resource_actions`, `self_improvement`,
`work_item_archive`) — confirm their exact subcommands with `--help` rather
than assuming the mapping above.

`aos` is a shell alias for `agentic-os` (see `harness/registries/commands.yml`
→ `id: aos`).

---

## 3. Harness registries

Read from `harness/registries/<name>.yml`. Column 5 flags whether the
registry is version-controlled in this worktree or installed-only today (see
§12 for why that gap exists).

| Registry | Routes / purpose | Read when | In worktree source? |
| --- | --- | --- | --- |
| `alerts` | Alert policy: cooldowns, quiet hours, per-source delivery caps | Before sending any notification/alert | Yes |
| `analytics-metrics` | Presentation metadata for Command Center analytics; collectors own the values | Building analytics/dashboard views | Installed-only |
| `backup-policy` | What gets included in an OS backup (`AGENTS.md`, `ROUTER.md`, etc.) | Before running backup/restore | Installed-only |
| `capabilities` | Master capability list — commands/skills/tools with id, type, ref | Checking whether a capability already exists | Installed-only |
| `commands` | 117 slash-command entries: id/command/description/source doc | Resolving a `/command` to its doc + implementation | Installed-only |
| `composio-tools` | Composio route table: toolkit, use-when, provider order, known tool ids, boundary | Before any Composio-routed SaaS call | Installed-only |
| `harness-crossreview.schedule.snippet` | Scheduling snippet for `agentic-os-pr-crossreview` (paste into `runtime-registry.yml`) | Wiring cross-harness PR review scheduling | Yes |
| `harness-routing` | Routes task types to the Claude vs. Codex harness; PR cross-review author detection | Read by `agentic-harness-run` / `agentic-os-pr-crossreview` | Yes |
| `health-monitor` | Thresholds for `agentic-os-monitor` (queue depth, staleness, etc.) | Read by `agentic-os-monitor` at startup, 60s cache refresh | Yes |
| `hooks` | Structured hook registry: id/status/source/events, 11 entries (includes conceptual hooks beyond the 7 files in §6) | Checking what fires on which agent event | Installed-only |
| `hosts-routing` | Cross-host work-distribution policy; references `config/hosts.yml` for SSH identity | Read by `agentic-harness-run` for `--host auto`/`<name>` | Yes |
| `intake-routing` | NL keyword routing for the OS Work Intake "Project" field | Read by `agentic-os-intake-row --route-text` | Yes |
| `libraries` | Library/tool capability list (e.g. `context_mode`, `unified_memory`) | Checking available libraries | Installed-only |
| `mcp-servers` | MCP server table: id/use-when/boundary/install scope | Before calling any `mcp__*` tool | Installed-only |
| `notion-surfaces` | Slug → canonical Notion page/database ID registry | Before any Notion write, to resolve the target ID | Installed-only |
| `plugins` | Visible plugin list (browser, chrome, etc.) | Checking plugin availability/status | Installed-only |
| `report-artifacts` | Generated report artifact instances (rendered run output) | Finding a specific report's rendered output | Installed-only |
| `report-definitions` | Report templates/definitions (e.g. `daily_operator_report`) | Before authoring a new report | Installed-only |
| `report-runs` | Report run history/status | Checking a report's last run status | Installed-only |
| `reports` | Top-level reports index (empty list today) | As the reports feature grows | Installed-only |
| `rules` | Human-readable rule catalog, incl. `route-read-cd-repeat` | Backing `RULES.md`'s generated content | Installed-only |
| `skills` | 98 skill entries: id/name/description/source `SKILL.md` | Resolving a skill name to its doc | Yes |
| `tracker-routing` | Maps issue-key patterns (e.g. `FLYWL-`) to tracker kind/project | Routing a ticket key to Jira vs. Linear | Installed-only |
| `update-plan` | Computed update plan (installed version, channel, policy) | Read by `agentic-os update` before applying | Installed-only |
| `update-status` | Last-applied update result | Checking the currently applied version/status | Installed-only |
| `updates` | Update pointer (installed/latest version, `status_ref`) | Top-level "am I current" check | Installed-only |

`harness/registries/README.md` documents the directory's ownership contract,
not per-registry content — use the table above, not the README, to find a
specific registry.

---

## 4. Harness bins

### 4a. Source (`harness/bin/`, version-controlled — 16 executables)

| Bin | Purpose |
| --- | --- |
| `agentic-harness-run` | Run a prompt through Claude Code or Codex, with harness auto-routing via `harness-routing.yml` and optional cross-host SSH dispatch (`--host auto`/`<alias>`). |
| `agentic-os-auto-dev-resolve` | Resolve a work-item packet (project + NNN), check the lifecycle stage gate, run preflight checks, and (with `--run`) invoke `agentic-harness-run`. |
| `agentic-os-automation-run-summary` | Replace one automation's Notion last-run-summary page. |
| `agentic-os-claude-desktop-bridge` | Build/audit the Claude Desktop custom-skill + instructions package (Desktop doesn't read `CLAUDE.md` or hook settings). |
| `agentic-os-intake-row` | Create a row in the OS Work Intake Notion database, routing `Project` via `intake-routing.yml`. |
| `agentic-os-interim-executor` | Compatibility entry point that delegates all automation work to the runtime supervisor (kept for older LaunchAgents). |
| `agentic-os-jira` | Deterministic Jira wrapper (OAuth client-credentials first, basic-auth token fallback) for when MCP/Composio Jira routes are unhealthy. |
| `agentic-os-memory-analytics` | Run the read-only memory retrieval-analytics report on the configured analytics host; `export` copies artifacts to the active work item. |
| `agentic-os-monitor` | Real-time in-shell health monitor: queue depth, running agents per host, recent runs, token usage, host vitals, alert feed. |
| `agentic-os-notify` | Deliver governed alerts through macOS Notification Center; the single delivery seam for automations and watchers, records deliveries + suppressions. |
| `agentic-os-pr-crossreview` | Route a GitHub PR review to the harness OPPOSITE its author (Claude-authored PR → Codex reviews, and vice versa). |
| `agentic-os-quiet-run` | Compatibility launcher for the universal long-running execution contract. |
| `agentic-os-status-report` | Create durable Agentic OS status report artifacts. |
| `register-harness-skills` | Register skills into Agents/Codex/Claude-discoverable locations (`~/.agents/skills`, `~/.codex/skills`, `~/.claude/skills`). Run after any skill add/change. |

`register-codex-skills` also exists in `harness/bin/` but is a deprecated shim
that only forwards its arguments to `register-harness-skills` — use the
latter directly.

### 4b. Installed-only (local, unversioned)

Present at `/Users/genome/agentic_os/harness/bin/` but not in this worktree's
`harness/bin/` as of 2026-07-22:

| Bin | Purpose |
| --- | --- |
| `agentic-os-daily-handoff-report` | Generate local-first Agentic OS daily handoff report artifacts. |
| `agentic-os-dashboard-contributors-validate` | Validate `operator-attention-dashboard.yml`'s contributor registry (required fields, unique ids, `notion_surface` slugs against `notion-surfaces.yml`). |
| `agentic-os-los-config` | zsh wrapper: execs `lib/programs/domains/los/los_config/toolkit/los_config.py`. |
| `agentic-os-los-fast-worktree-health.py` | Fail-closed Auto-Dev Health teardown/readback proof for one LOS fast worktree (proves compose project, DB/cache namespaces, and registry row are absent). |
| `agentic-os-los-rules` | zsh wrapper: execs `lib/programs/domains/los/los_rules_engine/toolkit/los_rules.py`. |
| `agentic-os-los-tenant-data-updater` | sh wrapper: execs `lib/workflows/domains/los/los_tenant_data_updater/scripts/los_tenant_data_updater.py`. |
| `agentic-os-work-handoff-report` | Generate Agentic OS work handoff prompt-pack artifacts. |
| `agentic-os-work-item-archive` | Archive retained terminal work-item packets without deleting evidence. |
| `los-automation-codex-run` | Resolve the `codex` CLI and run one LOS engineering automation prompt headless. |
| `los-automation-config-refresh` | Refresh the machine-managed `jira:` block in the shared LOS automation config when stale (scheduled safety net; automations self-refresh first). |
| `los-genomesbox-automation-preflight` | Preflight checks (repo/gh/codex/jira) before moving the LOS `security_scan` automation runner to genomesbox. |

Excluded from both tables: `__pycache__/` and `tests/` (build/test artifacts,
not tools) and three timestamp-suffixed `.pre-*` files
(`agentic-os-interim-executor.pre-5c0ebd3`,
`agentic-os-interim-executor.pre-f7ccff3`,
`agentic-os-notify.pre-execution-fabric-20260719T2058Z`) — rollback snapshots
taken before overwriting a live script, not separate tools.

---

## 5. Control plane

`harness/shared_factory/00-control-plane/` (installed; 56 files total as of
2026-07-22). The rows below are the ones agents touch most — see the
directory itself for the full set (automation tracking, connected-systems,
chain-rules, event-graph, integration-registry, work-item-limits, etc.).

| File | Role | Read or mutate via |
| --- | --- | --- |
| `state.db` | SQLite work-lifecycle source of truth (30MB+) | `agentic-os work show` / `work list` — never raw writes |
| `active-now.json` | Compact read projection of current active work | Read FIRST, before broad context discovery (see §1) |
| `run-queue.yml` | Queued run entries | `agentic-os run-queue`; mutated by the runtime supervisor |
| `runtime-registry.yml` | Central always-on/scheduled runtime entry registry | `agentic-os runtime` / `heartbeat` / `schedule` |
| `long-running-runs.json` | Central long-running-execution registry: phase, progress, budgets | `agentic-os long-run`; required for any qualifying run per `os-authoring-rules.md` |
| `safe-action-allowlist.md` / `.yml` | Exact-string allowlist of commands a guarded/scheduled executor may run unattended | Read by the interim/guarded executor before running any scheduled command |
| `watch-sources.yml` | Connected/watched external source definitions | `agentic-os watch-source` |
| `doc-config.yml` | Document-capture routing config (filesystem + Notion destinations) | Read by the `doc-config-router` skill before any spec/bug/feature capture |
| `locks/` | Orphan-safe mutation locks for long-running/migration work | Never hand-edit; created/released by the owning tool |

---

## 6. Hooks

`harness/hooks/` — 8 entries (7 scripts + `README.md`). Install/sync with
`agentic-os hook sync --root ~/agentic_os --target all --apply --backup`;
never copy hook scripts into `~/.claude/hooks` or `~/.codex/hooks` as a
separate source of truth.

| Hook | Event(s) | Intercepts / does |
| --- | --- | --- |
| `session-prayer-start.sh` | `SessionStart` | Commits the session and work to Jesus before startup work begins. |
| `memory-session-start.sh` | `SessionStart` | Injects Genome's Brain memory discipline at session start/resume/clear and routes durable writes to the correct substrate (registered twice in `hooks.yml`, as `memory-session-start` and `memory-write-router`). |
| `memory-stop.sh` | `Stop` | Compatibility no-op stub — memory guidance now lives in `SessionStart` to avoid Stop-hook continuation loops. |
| `harness-emit-trace.sh` | `Stop` | Fire-and-forget `AGENT_TRACE` memory record built from hook payload metadata, plus per-tool-call byte accounting derived from the session transcript (`tool_byte_accounting`, appended to `~/.local/state/harness/tool-byte-accounting/<session>.jsonl`). Both are best-effort and never alter the hook's stdout contract. |
| `context-mode-cache-heal.mjs` | `SessionStart` | Repairs stale Claude context-mode plugin cache symlinks after auto-updates. |
| `conversation-auto-log.py` | `Stop` | Writes redacted conversation transcripts + tool-call sidecars to the routed project or active work item. |
| `work-item-routing-guard.py` | `PostToolUse` | Advisory only, never blocks (always exits 0): nudges an agent away from misfiling a lifecycle/handoff packet into a code repo's `.features/` instead of the canonical OS work item. |

`harness/registries/hooks.yml` is the fuller structured registry (11 entries)
— it also covers conceptual/external hooks with no file in this directory
(context-mode's own Codex hooks, MemPalace hooks, a planned stale-thread
finalizer sweep). Read the table above for the 7 real scripts; read the
registry when you need event wiring for the non-file entries too.

---

## 7. Rules

`harness/rules/` — installed has 5 entries (4 docs + `README.md`); this
worktree carries 4 of the 5 (missing `auto-dev-artifact-producers.md`, see
§12).

| Rule doc | Binds when |
| --- | --- |
| `harness/rules/os-authoring-rules.md` | Any time an agent adds, renames, or changes a workflow, automation, command, skill, rule, hook, plugin, library, tool, MCP surface, tool route, or program — the Required Loop and cross-registry registration rule (§1). |
| `harness/rules/work-lifecycle-standard.md` | Any work-item state transition (active/blocked/finished/documented/archived) — the canonical lifecycle field/state contract. |
| `harness/rules/notion-format-standard.md` | Any write to a Notion page or block — canonical block formatting rules. |
| `harness/rules/auto-dev-artifact-producers.md` | Any auto-dev workflow producing a tracker/PR/doc artifact. **Installed-only** — not yet present in this worktree. |
| `harness/rules/README.md` | Explains the directory is reserved for packaged, versioned rule sets; core operating rules are otherwise generated into `harness/RULES.md`, domain/project `RULES.md`, and `harness/registries/rules.yml`. |

---

## 8. Skills & commands

Counts as of 2026-07-22: installed `harness/skills/` = 86 skill directories,
`registries/skills.yml` = 98 entries; this worktree's `harness/skills/` = 54
(see §12). `registries/commands.yml` = 117 entries.

Registry paths: `harness/registries/skills.yml`, `harness/registries/commands.yml`.

Naming convention: a skill's directory name equals its `id` (kebab-case) and
holds a `SKILL.md` with YAML frontmatter (`name`, `description`);
`skills.yml` mirrors `id`/`name`/`description`/`source`. `commands.yml`
entries carry `id`/`command` (literal CLi invocation or `/slash-command`)/
`description`/`source`, where `source` points at `harness/commands/<name>.md`
or a direct CLI path.

Most load-bearing (10 of ~98/117 — do not restate the rest, resolve them
through the registries above):

| Skill / command | One-liner |
| --- | --- |
| `auto-dev` (family entry point) | Route programming work through the canonical polymorphic investigation, artifact, delivery, review, release, deployment, and closeout family. |
| `pr-review` | Canonical others'-PR review, batch reporting, engineering-health, and authority-aware standard squash-merge workflow using DEV_STANDARDS and GitFlow family coverage. |
| `watch-pr-quiet` | Monitor exact-head GitHub PR checks and required workflows through file-based watcher artifacts instead of repeated chat polling. |
| `doc-config-router` | Route document captures to the configured Agentic OS filesystem and Notion destinations. |
| `spec-intake-router` | Create spec and future-work intake items using doc-config before filesystem or Notion writes. |
| `status-report` | Generate recent-work Agentic OS status reports with filesystem markdown (plus optional Notion projection). |
| `cockpit` | Build or open the local engineering cockpit for conversations, work, reviews, reports, sources, hosts, automations, and hygiene. |
| `agentic-os-gui` | Operate the domain/project-focused desktop conversation driver over native Claude and Codex task state. |
| `orchestrate` | Coordinate subagents, verification, and integration. |
| `make-skill` | Codex-visible adapter for `/make-skill` — create or update reusable skills, commands, workflows, or invocation surfaces. |

---

## 9. MCP servers

Source: installed `harness/TOOLS.md` → "MCP Servers" table (condensed here;
read the full table there for install-status wording per server).

| Server | Use when | Boundary |
| --- | --- | --- |
| `notion` | Genome's Notion control-plane reads and approved writes. | Verify Genome's Notion before writing; never Michael Clark's personal workspace. |
| `genomes_brain` | Durable cross-session memory reads and non-secret writes. | No secrets; follow project rules and memory policy before writing. |
| `github` | Repository, issue, pull-request, and code-hosting work. | Least-privilege `GITHUB_PAT_TOKEN`; never commit or print token values. |
| `context_mode` | Large-file, repo, and session-memory analysis without flooding prompt context. | Analysis and retrieval only; not for file writes. |
| `sentry` | LOS error, trace, release, and incident investigation. | LOS layers only; production/customer-visible changes still need approval. |
| `datadog` | LOS observability: logs, metrics, traces, monitors. | LOS layers only; no customer data outside approved observability workflows. |
| `supabase` | Clark Consulting Supabase project work. | `clarks_consulting` layers only, unless a customer profile explicitly approves it. |
| `composio` | Federated SaaS tools, OAuth flows, triggers, app actions routed through `harness/registries/composio-tools.yml`. | Follow the route's provider order; verify target connection/workspace before any write; record unauthorized/not-connected fallback. |
| `orgo` | Isolated cloud desktop / computer-use execution target. | Only via an approved Orgo MCP bridge or runtime execution target. |
| `playwright` | Browser automation and UI validation. | Opt-in per layer; visible by default only where a layer explicitly owns browser automation. |

---

## 10. State & memory planes

| Plane | Access | Notes |
| --- | --- | --- |
| Genome's Brain MCP | `mcp__genomes_brain__memory_read` / `memory_write` / `memory_link` / `memory_forget` (+ `memory_analytics`, `memory_health`) | genomesbox:3166; durable cross-session facts/prefs/decisions. Router classifies each write and fans it across substrates. |
| Per-project `MEMORY.md` | `<project-root>/MEMORY.md`, sibling of `CLAUDE.md` | `PROJECT_RULE`-kind facts land here via `memory_write` — do not hand-append; the router auto-creates the file on first write. |
| context-mode MCP | `mcp__plugin_context-mode_context-mode__ctx_*` (`search`, `execute`, `batch_execute`, `fetch_and_index`) | Sandboxed analysis/derivation; auto-indexes session events (26 categories) — query with `ctx_search(sort:"timeline")`. |
| Control-plane work state | `agentic-os work show` / `work list` over `state.db` + `active-now.json` | Work-item lifecycle source of truth; mutate lifecycle state only through `agentic-os work`, never by moving packet folders. |
| Versioned object index | `agentic-os library refresh --apply` / `library doctor` over `lib/registry/objects.json` | Compact canonical index for programs/workflows/skills/etc.; each object's `object.yml` is canonical for mutation (see §1). |

---

## 11. Command Center app surfaces

Canonical architecture doc: `apps/agentic-os-gui/docs/ARCHITECTURE.md` —
system position, process/layer boundaries, IPC conventions (`aos:*`
channels), and services under `src/main/` for the Electron desktop command
center. Sibling docs in the same directory own recipes
(`FEATURE-PLAYBOOK.md`), data/event flow (`DATA-AND-EVENTS.md`), and the
visual system (`DESIGN-SYSTEM.md`); decisions live under `docs/adr/`. This
catalog only indexes that these exist — read them directly rather than
through this file.

---

## 12. Versioning & drift

Source repo `harness/` is meant to be the source of truth, deployed into
`~/agentic_os` by the installer/update flow (`agentic-os update`,
`register-harness-skills`, `agentic-os library refresh`, etc.). The installed
instance also carries genuine instance-local overlays — state files, run
logs, `artifact-config`, and the installed-only bins in §4b are expected to
live only under `~/agentic_os` and are already captured in this catalog's
installed-only tables. The wider brief for this catalog cites roughly 85
source-vs-installed differing files; that figure comes from the task
briefing, not from an independent recount here.

What was verified directly, side by side, on 2026-07-22 — this worktree
(`feat/command-center-foundation`) is missing more than instance-local
overlays; whole surfaces of the harness contract are absent from source:

| Surface | Worktree (source) | Installed (`~/agentic_os`) |
| --- | --- | --- |
| Root contract docs (`AGENTS.md`, `ROUTER.md`, `CONTEXT.md`, `RULES.md`, `TOOLS.md`, `MEMORY.md`) | Absent | Present |
| `harness/registries/*.yml` | 8 files | 27 files (19 exist only installed — see §3) |
| `harness/bin/` (real executables) | 16 | 27 (11 installed-only — see §4b) |
| `harness/rules/` | 4 files | 5 files |
| `harness/skills/` | 54 dirs | 86 dirs |
| `harness/mcp/`, `harness/libraries/`, `harness/plugins/` | `README.md` stub only | Populated via `lib/` + registries |
| `lib/` (versioned object library) | Does not exist at the worktree root | Present, 482KB `registry/objects.json` |

Rule: change tools in the **source** repo and deploy via the update flow —
never fork an installed copy silently. The only exception is instance-local
overlays (`state.db`, run logs, `active-work.md`, `artifact-config`, and the
§4b installed-only bins), which are expected to exist only in the installed
root and must stay listed in this catalog's installed-only tables rather than
being ported into source.

Given the scale of the gap measured above, treat this worktree as behind the
full harness contract for anything outside `apps/agentic-os-gui/` — verify
against the installed OS (or a freshly fetched `origin/main`) before assuming
a source-tree registry, bin, rule, or skill listing here is exhaustive.
