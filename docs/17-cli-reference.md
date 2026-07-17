# 17 · CLI Reference

> **Purpose:** a navigable map of every `agentic-os` command — conventions up
> front, then every command grouped by the `cli/` package module that owns it,
> with its one-line `--help` behavior text. For exhaustive flag tables and real
> captured output, see [`docs/architecture/command-reference.md`](architecture/command-reference.md).
>
> **You'll use:** this page to find the command you need and confirm what it
> does; `<command> --help` for the exact flags.
> **Prereqs:** `agentic-os` installed and an OS root initialised
> ([01 · Install & Quickstart](01-install-and-quickstart.md)).

---

## Conventions

These rules apply to **every** `agentic-os` invocation. Memorise them once; they
never change.

| Convention | Rule |
| --- | --- |
| **Name format** | `snake_case` only — lowercase letters, digits, underscores. Hyphens are **rejected**. `weekly-report` fails; `weekly_report` works. |
| **`--root` default** | `~/agentic_os` (or `$AGENTIC_OS_ROOT` when set). Always pass `--root` explicitly in scripts; never rely on the default in automation. |
| **Exit 0** | Success. |
| **Exit 1** | Health check "not ok" — `doctor` / `validate` / `config doctor` report a problem. Fix it and re-run. |
| **Exit 2** | Argparse usage error **or** deliberate handled refusal — e.g. `here route` when routing confidence is low, a name with a hyphen. Exit 2 is not a crash; it is the OS saying "I won't guess." |
| **Dry-run by default** | Most commands that mutate files or call an external system (Notion, GitHub, SSH, runtime dispatch) preview their effect and require `--apply` to take effect; `--dry-run` is accepted too and is the default when neither flag is passed. Coverage has grown past any fixed list here — check `<command> --help` for the specific pair of flags on the command you're running. |
| **`backup run` prerequisite** | Requires `update register` first (generates an update grant); `backup push` degrades gracefully and logs locally when no grant exists. |
| **`config` subcommands** | Exactly `install`, `install-tree`, and `doctor` — no `config layers` subcommand exists. |

---

## Command-group map

![CLI command groups: thirteen clusters arranged around the agentic-os root — core lifecycle, domains/projects/routing, workflows/automations/runs, profiles/rooms, runtime/always-on, events/chains, connected sources, notion control plane, config, update/backup/license, migration/validation, and customer OS factory](diagrams/cli-command-groups.png)

The image predates the `cli/` package split into one module per group; the
tables below are the current, authoritative grouping.

---

## Command index

<!--
Generated from `--help` output; regenerate after CLI changes:
  1. cd into a checkout with the CLI installed (`pip install -e '.[dev]'`)
  2. Walk the full argparse tree via `genomes_agentic_os.cli.build_parser()`,
     recursing through every `_SubParsersAction`, and dump `format_help()` for
     each node (see git history of this file / AGE-37 work item for the
     one-off script used to do this, if it isn't checked in yet).
  3. Parse each node's "positional arguments:" block into (command path, help
     text) rows and group rows by which `cli/<module>.py` registers the
     top-level command (cross-check with `COMMAND_MODULES` in `cli/__init__.py`).
-->

Every table below is one `cli/` package module. The command column is the full
path you type after `agentic-os`; the description is verbatim from `--help`.

### Install & Scaffold — `cli/scaffold.py`

| Command | What it does |
| --- | --- |
| `domain` | Manage domains. |
| `domain create` | Create a domain scaffold. |
| `init` | Create the base installed OS tree. |
| `profile` | Manage room-first OS profiles. |
| `profile create` | Create an editable profile template. |
| `profile validate` | Validate a room-first profile. |
| `room` | Manage rooms. |
| `room create` | Create a room scaffold. |
| `room update` | Update a room from a profile. |

### Projects — `cli/project.py`

| Command | What it does |
| --- | --- |
| `project` | Manage projects. |
| `project create` | Create a project scaffold. |
| `project exec` | Run a command on the remote host for a remote-authoritative project. |
| `project link-remote` | Attach a remote SSH source to an existing project. |
| `project link-source` | Create or repair a project-local src symlink to a local repository. |
| `project mount-remote` | Plan or execute an SSHFS mount for a declared remote source (dry-run by default). |
| `project onboard` | Create or repair the project-local agent/config surface. |
| `project sync-remote` | Refresh manifest.yml for declared remote SSH sources. |
| `project unmount-remote` | Plan or execute an SSHFS unmount for a declared remote source (dry-run by default). |
| `project work-item` | Manage project lifecycle work items. |
| `project work-item create` | Create a project lifecycle work item. |
| `project work-item finalize-lingering` | Move terminal-status packets out of active lanes, update indexes, and refresh the global active container. |
| `project work-item infer-complete` | Infer completed active work items from terminal evidence, closeout artifacts, and quiet conversation activity. |
| `project work-item repair` | Backfill missing lifecycle packet files and folders without overwriting local edits. |
| `project work-item sync-active` | Rebuild the root global active-work symlink container from work items, worktrees, and automations. |
| `project worktree` | Manage visible project worktree links. |
| `project worktree add` | Register a project-visible worktree. |
| `project worktree cleanup-closed` | Close registered worktrees whose cached Jira status or PR state is terminal. |
| `project worktree create` | Create an in-place git worktree under the project worktrees directory and register it. |

### Specs — `cli/spec.py`

| Command | What it does |
| --- | --- |
| `spec` | Manage canonical software Specs. |
| `spec add` | Add a policy-routed Spec through filesystem, Linear, or Jira. |
| `spec show` | Show one normalized Spec record. |
| `spec list` | List Specs with optional domain, project, status, and type filters. |
| `spec transition` | Transition a Spec to a canonical status or resume it from blocked. |
| `spec sync` | Reconcile one or all project Specs through a Linear or Jira adapter. |
| `spec doctor` | Validate layered Spec Engine policy and adapter configuration. |

All Spec commands emit YAML records or receipts. See
[29 · Spec Engine](29-spec-engine.md) for exact forms, lifecycle semantics,
adapter behavior, and compatibility commands.

### Workflows & Programs — `cli/workflow.py`

| Command | What it does |
| --- | --- |
| `instance-program` | Manage domain-local OS programs. |
| `instance-program create` | Create a domain-local InstanceOSProgram scaffold. |
| `program` | Manage shared OS programs. |
| `program create` | Create a shared OSProgram scaffold. |
| `workflow` | Manage workflows. |
| `workflow check` | Check workflow readiness. |
| `workflow create` | Create a workflow scaffold. |

### Hosts — `cli/hosts.py`

| Command | What it does |
| --- | --- |
| `host` | Manage the SSH host registry (config/hosts.yml). |
| `host add` | Add or update a host alias in the registry. |
| `host list` | List registered hosts. |
| `host routing` | Show cross-host routing policy and recent harness host receipts. |

### Automations — `cli/automation.py`

| Command | What it does |
| --- | --- |
| `automation` | Manage automations. |
| `automation attach` | Attach an automation to a project. |
| `automation check` | Check automation maturity readiness. |
| `automation create` | Create an automation scaffold. |
| `automation set-maturity` | Set the automation maturity level after evidence checks. |
| `automation-control` | Gate expensive automations behind cheap source-readiness probes. |
| `automation-control doctor` | Validate managed automation-control config. |
| `automation-control list` | List managed automation gates. |
| `automation-control run` | Evaluate configured automation gates and enqueue ready work. |

### Program and Automation operator query — `cli/operator_resources.py`

| Command | What it does |
| --- | --- |
| `operator-resource` | Query the read-only Program and Automation operator projection. |
| `operator-resource query` | List Program or Automation resources as `operator-resource-query/v1` JSON. |
| `operator-resource get` | Get one exact Program or Automation resource ID as `operator-resource-query/v1` JSON. |

The fixed forms are `operator-resource query <program|automation>` and
`operator-resource get <program|automation> <resource-id>`. Both accept
`--root`; JSON is the only output mode.

### First-class resource registry — `cli/first_class_registry.py`

| Command | What it does |
| --- | --- |
| `resource-registry refresh` | Reconcile source resources and atomically replace the local snapshot. |
| `resource-registry query` | Read/filter the local snapshot without scanning the OS tree. |
| `resource-registry tags list` | Return merged, derived, and custom tags for one exact stable resource ID. |
| `resource-registry tags add` | Normalize and atomically add one durable custom tag, refresh, and emit a receipt. |
| `resource-registry tags remove` | Atomically remove one custom tag, refresh, and emit a receipt. |

### Runs & Thread Lifecycle — `cli/run_lifecycle.py`

| Command | What it does |
| --- | --- |
| `archive` | Alias for agentic-os thread archive. |
| `cleanup-thread` | Alias for agentic-os thread cleanup. |
| `end-chat` | Alias for agentic-os thread end. |
| `finalize` | Alias for agentic-os thread finalize. |
| `ps` | Show Agentic OS work running right now; use --active for the broader dashboard. |
| `run-log` | Manage run logs. |
| `run-log close` | Close a run log with audit evidence. |
| `run-log create` | Create a timestamped run log. |
| `thread` | Manage thread lifecycle closeouts. |
| `thread archive` | Finalize and archive when no unresolved next action remains. |
| `thread cleanup` | Finalize and classify generated dirt without deletion. |
| `thread end` | Finalize the current thread without archiving. |
| `thread finalize` | Alias for thread end. |
| `thread stale-finalize` | Dry-run or apply stale thread finalization. |

### Routing & Context — `cli/routing.py`

| Command | What it does |
| --- | --- |
| `context` | Build deterministic context packets. |
| `context build` | Build a context packet. |
| `here` | Route from the current working directory. |
| `here context` | Build context from the current directory. |
| `here context build` | Build context from the current directory. |
| `here route` | Route a request from the current directory. |
| `route` | Route a request to a domain, project, or workflow. |

### Cockpit — `cli/cockpit.py`

| Command | What it does |
| --- | --- |
| `cockpit` | Build or open the local engineering-lead OS cockpit. |
| `cockpit build` | Build snapshot.json and a self-contained index.html. |
| `cockpit open` | Build and open the cockpit in the default browser. |
| `cockpit snapshot` | Write the versioned cockpit JSON snapshot. |
| `conversation-reports` | Mine local conversation-report JSONL sidecars for repeated OS hardening signals. |
| `conversation-reports scan` | Scan conversation-report sidecars and optionally write report artifacts. |

### AgenticOSGui — `cli/gui.py`

| Command | What it does |
| --- | --- |
| `gui` | Inspect or open the native local desktop conversation driver. |
| `gui snapshot` | Emit the versioned domain/project and active Claude/Codex conversation index. |
| `gui transcript` | Read the selected visible user/assistant transcript through a provider adapter. |
| `gui open` | Open the packaged AgenticOSGui application or report the development build command. |

### Customer OS Factory — `cli/customer.py`

| Command | What it does |
| --- | --- |
| `customer` | Manage customer Agentic OS installs. |
| `customer brief` | Scaffold a client-automation-brief instance into a customer install domain. |
| `customer init` | Create a customer OS from a profile. |
| `customer update` | Add missing customer OS assets. |
| `customer validate` | Validate a customer OS root. |

### Operator (Update, Backup, License, Fleet, Metrics) — `cli/operator.py`

| Command | What it does |
| --- | --- |
| `backup` | Plan or run GitHub-backed OS state backups. |
| `backup push` | Record a local backup push run log. Skips remote push when update grant is absent (no creds); always logs locally. |
| `backup restore-plan` | Build a read-only operator restore plan from the latest backup log and policy. |
| `backup run` | Plan or record a backup run. |
| `fleet` | Operator fleet management commands. |
| `fleet push` | Record a simulated operator-push event for a customer installation. V1 local-only: no real SSH or network calls. |
| `license` | Manage customer OS license metadata. |
| `license activate` | Activate a customer license without printing or storing the raw key. |
| `metrics` | Compute and view OS metrics scorecards. |
| `metrics refresh` | Compute a metrics scorecard from run logs, doctor findings, and automation maturity. Writes result to harness/shared_factory/07-metrics/scorecard.yml. |
| `update` | Check, plan, apply, and report installed OS updates. |
| `update apply` | Apply safe additive update changes. |
| `update check` | Check for available updates without mutating files. |
| `update phone-home` | Emit a heartbeat-safe operational metadata payload. |
| `update plan` | Write an inspectable update plan. |
| `update pull` | Plan or record an operator-pushed update pull. |
| `update register` | Generate local update/backup SSH keys and write an update grant. |
| `update rollback` | Record rollback against the latest update snapshot. |
| `update status` | Show local update status. |

### Config & Doc Routing — `cli/config.py`

| Command | What it does |
| --- | --- |
| `config` | Install or update Codex config.toml conventions. |
| `config doctor` | Validate config.toml OTEL and MCP contracts. |
| `config install` | Install or merge config.toml for an OS directory. |
| `config install-tree` | Install or merge config.toml across the routed OS root, domains, projects, workflows, and automations. |
| `doc-config` | Plan and validate document-routing config. |
| `doc-config doctor` | Check doc-config.yml contracts. |
| `doc-config init` | Install doc-config.yml if missing. |
| `doc-config plan` | Build a deterministic document-routing plan. |
| `hook` | Sync active Claude/Codex hooks to installed OS hook sources. |
| `hook doctor` | Validate active hook settings use installed OS hooks. |
| `hook sync` | Point active harness hook settings at installed OS hooks. |

Valid `--layer` values (used by `config install`, `config install-tree --layer`
overrides, and `config doctor`): `agentic_os_root`, `automation`,
`customer_os_root`, `domain_or_lane`, `global_harness`, `project`,
`workflow_or_task`.

### Notion Control Plane — `cli/notion.py`

| Command | What it does |
| --- | --- |
| `notion` | Plan and apply filesystem-to-Notion sync. |
| `notion active-work-sync` | Plan or apply guarded Notion sync for the generated OS Active Work database. |
| `notion bootstrap` | Plan or apply the Notion control-plane bootstrap. |
| `notion plan-sync` | Build a reviewable Notion sync plan. |
| `notion sync` | Run a guarded Notion sync. |
| `notion track-runtime` | Plan or apply guarded Notion tracking for runtime registries and runs. |
| `notion-org` | Check Notion IA organization before page moves. |
| `notion-org doctor` | Check Notion organization config and backup readiness. |

`notion sync` / `notion bootstrap` / `notion track-runtime` call the real
Notion API (`https://api.notion.com/v1`, stdlib `urllib`, bearer token from
`GENOMES_NOTION_PAT`) — this is wired, not a stub. All three default to
dry-run; pass `--apply` to write.

### Runtime & Always-On — `cli/runtime.py`

| Command | What it does |
| --- | --- |
| `heartbeat` | Manage runtime heartbeats. |
| `heartbeat doctor` | Check runtime heartbeat health. |
| `heartbeat list` | List configured heartbeats. |
| `heartbeat run` | Run or dry-run a heartbeat. |
| `integration` | Manage runtime integrations. |
| `integration doctor` | Check integration setup contracts. |
| `integration list` | List configured integrations. |
| `integration setup` | Dry-run or record integration setup. |
| `run-queue` | Manage the runtime run queue. |
| `run-queue prune` | Prune stale run-queue items and old run-queue backups. |
| `runtime` | Manage file-backed runtime state. |
| `runtime doctor` | Check runtime registry health. |
| `runtime init` | Create runtime registries and log folders. |
| `runtime prune` | Prune stale run-queue items and old run-queue backups. |
| `runtime run-next` | Dispatch the next safe queued runtime item. |
| `runtime supervise` | Run one supervisor tick across the runtime surface (heartbeats, schedules, sources, events, run queue) plus a health check. |
| `schedule` | Manage runtime schedules. |
| `schedule create` | Create a schedule in the runtime registry. |
| `schedule delete` | Delete a disabled schedule with no active queue references. |
| `schedule disable` | Plan or apply disabling one schedule. |
| `schedule enable` | Plan or apply enabling one schedule. |
| `schedule get` | Read and validate one schedule. |
| `schedule list` | List configured schedules in stable ID order. |
| `schedule queue-now` | Queue one schedule without dispatching it. |
| `schedule run-due` | Queue due schedules without executing external effects. |
| `schedule update` | Plan or apply an allowlisted schedule-field update. |

Every command in this table executes **one tick and exits**. None of them is a
persistent background process — "always-on" means something external (cron,
launchd, a wrapper script) calls these on a cadence, not that a daemon ships
in this package.

### Governed resources — `cli/resource_actions.py`

| Command | What it does |
| --- | --- |
| `resource list` | List registry-backed or filesystem-backed resources from canonical locations. |
| `resource get` | Read one canonical resource, operator metadata, and drift hash. |
| `resource create` | Dry-run or create a supported scaffold or managed registry resource without running it. |
| `resource update` | Change allowlisted registry or filesystem metadata with the kind-specific contract. |
| `resource disable` | Pause a filesystem resource; automations are also marked disabled. |
| `resource repair` | Repair canonical lifecycle metadata while preserving unknown overlay fields. |
| `resource archive` | Move a managed resource to reversible archived state without deleting it. |
| `resource restore` | Restore a managed archived resource. |
| `resource rollback` | Restore a managed resource from an identity-bound fixed backup ID. |
| `resource run-now automation` | Queue one idempotent automation request without dispatching it. |
| `resource schedule-get automation` | Read the schedule derived for one automation identity. |
| `resource schedule-configure automation` | Configure a derived automation schedule without accepting a caller command. |
| `resource validate` | Validate readiness, structural completeness, or registry/source/projection consistency. |

`--json` returns the stable `resource-actions/v1` contract used by local GUI
clients. Mutations are dry-run by default and require `--apply`. Registry
authoring supports `rule`, `report`, `skill`, and `command` at `system`,
`domain`, or `project` scope. The CLI derives every target; it accepts no
arbitrary path, shell command, executable, or query field.

Filesystem metadata lifecycle applies also require `--expected-drift-hash`
from the immediately preceding dry-run or get response. Queue-only run-now
records current drift directly. See
[Filesystem Resource Lifecycle](33-filesystem-resource-lifecycle.md).

### Effective rules — `cli/rules.py`

| Command | What it does |
| --- | --- |
| `rules effective` | Resolve context-aligned system/domain/project/workflow/automation rules, stable numbering, strictest-applicable winners, and conflict evidence. |

The command accepts a contained `--path` or validated domain/project/workflow/
automation selectors. `--query`, repeatable `--scope` / `--effect`,
`--local-only`, and `--conflicts-only` filter the typed `rules/v1` projection.
`--json` is intended for Command Center. See
[35 · Effective Rule Hierarchy](35-effective-rule-hierarchy.md).

### State — `cli/state.py`

A local SQLite state plane at `<os-root>/00-control-plane/state.db`, tracking
events, the run queue, and cursors as queryable rows alongside the existing
markdown files. Command group: `agentic-os state <subcommand>`.

| Command | What it does |
| --- | --- |
| `state init` | Create the state.db and apply schema migrations. |
| `state status` | Show db path, schema version, and per-table counts. |
| `state import` | Import run-queue/events/cursors YAML into state.db. |
| `state query` | Query rows from one state table. |
| `state prune` | Delete old terminal run_queue items, or old events. |
| `state verify-import` | Compare source file counts against table counts and report drift. |

### Doctor & Migrations — `cli/doctor.py`

| Command | What it does |
| --- | --- |
| `doctor` | Run installed OS health checks. |
| `migrate` | Plan and apply explicit migrations. |
| `migrate apply` | Apply an approved migration by ID. |
| `migrate plan` | Create a reviewable migration plan. |

### Plans — `cli/plans.py`

| Command | What it does |
| --- | --- |
| `plan` | Capture future OS ideas and plans. |
| `plan capture` | Capture a future idea in the right OS location. |

### Self-Improvement — `cli/self_improvement.py`

| Command | What it does |
| --- | --- |
| `self-improvement` | Review local evidence for proposal-only OS improvements. |
| `self-improvement actions` | Consume checked Notion action boxes on self-improvement suggestion pages. |
| `self-improvement approve` | Approve one proposal for a specific draft target. |
| `self-improvement list` | List self-improvement proposals. |
| `self-improvement nightly-apply` | Auto-approve low-risk proposals and queue them into OS Work Intake (dry-run by default). |
| `self-improvement promote` | Promote an approved proposal into a draft artifact. |
| `self-improvement reconcile-queue` | Mark stale self-improvement review queue rows done when covered by a later successful run. |
| `self-improvement reject` | Reject one proposal and start cooldown. |
| `self-improvement run` | Run a self-improvement review (dry-run by default; use --apply to persist + document). |
| `self-improvement show` | Show one self-improvement proposal. |
| `self-improvement status` | Summarize self-improvement run and proposal state. |

Nothing in this group applies an OS change without an explicit `approve` /
`promote` step — `run` only proposes.

### Connected Sources — `cli/source_watch.py`

| Command | What it does |
| --- | --- |
| `connected-system` | Manage connected source systems. |
| `connected-system doctor` | Check a connected system. |
| `connected-system list` | List connected systems and selected providers. |
| `watch-source` | Manage connected source watchers. |
| `watch-source create` | Create a file-backed watch source. |
| `watch-source doctor` | Check a watch source. |
| `watch-source list` | List watch sources. |
| `watch-source poll` | Poll one watch source. |
| `watch-source run-due` | Poll enabled watch sources. |

### Activity Analytics — `cli/activity.py`

| Command | What it does |
| --- | --- |
| `activity list` | List opted-in activity source definitions. |
| `activity validate` | Validate provider, scope, opt-in, and metric bindings. |
| `activity ingest` | Dry-run or apply credential-free paginated provider records. |
| `activity health` | Read freshness, completeness, cursor, rate-limit, and last-error state. |
| `activity collect-local` | Collect bounded metadata-only local event and run receipts. |

### Event Graph — `cli/event_graph.py`

| Command | What it does |
| --- | --- |
| `chain` | Manage event chain rules. |
| `chain doctor` | Check chain rule safety. |
| `chain list` | List chain rules. |
| `chain test` | Test a chain rule against an event file. |
| `event` | Manage the file-backed event ledger. |
| `event append` | Append a normalized event. |
| `event list` | List recent events. |
| `event process-due` | Process matching chain rules. |
| `event replay` | Replay one event against chain rules. |
| `event summary` | Summarize recent events and pending follow-up. |

### Validate — `cli/validate.py`

| Command | What it does |
| --- | --- |
| `validate` | Validate an installed OS root. |

### Docs — `cli/docs.py`

| Command | What it does |
| --- | --- |
| `docs` | Install or update runtime OS documentation. |
| `docs install` | Install runtime templates, manual, commands, skills, and plans. |
| `docs update` | Add missing runtime template, manual, command, skill, and plan assets without overwriting local edits. |
| `docs upkeep` | Run the observe-mode documentation upkeep registry and drift planner. |

### Capability — `cli/capability.py`

| Command | What it does |
| --- | --- |
| `capability` | Inspect installed OS capabilities. |
| `capability inventory` | Show or regenerate INVENTORY.md. |
| `capability list` | List capabilities from installed registry. |

### Adaptive Routing — `cli/adaptive.py`

| Command | What it does |
| --- | --- |
| `adaptive-routing` | Read-only operator controls for adaptive routing. |
| `adaptive-routing evaluate` | Run the supplied holdout against the built-in catalog and explicit baseline. |
| `adaptive-routing observe` | Build and durably record one non-executing route for the active Codex task. |
| `adaptive-routing plan` | Build a canonical, non-executing adaptive routing plan. |
| `adaptive-routing report` | Analyze observed routes against actual Codex session telemetry. |
| `adaptive-routing rollback-plan` | Build non-mutating Feature 62 static rollback instructions. |
| `adaptive-routing status` | Show policy lifecycle, version, and enforce eligibility without changes. |

### Reports — `cli/reporting.py`

| Command | What it does |
| --- | --- |
| `report init` | Add missing versioned report registries without overwriting data. |
| `report query definition\|run\|artifact` | Return typed resource projections and definition/run/artifact relationships. |
| `report get definition\|run\|artifact <id>` | Read one independently addressable report resource. |
| `report validate` | Validate a definition schema and schedule/source references. |
| `report create` / `report update` | Plan or apply a receipted definition mutation. |
| `report archive` / `report restore` | Plan or apply a reversible lifecycle change. |
| `report run-now` | Plan or produce a source-evidenced run plus JSON/Markdown artifact. |
| `report rollback` | Optimistically restore a lifecycle registry backup. |
| `report consolidate-plan` | Find duplicate, stale, and legacy candidates without deleting them. |

Lifecycle and run actions are dry-run by default. See
[31 · First-Class Report Engine](31-report-engine.md) for schemas, projection
guards, and examples.

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

The tables above are the **navigator**. Every flag, every real captured output
(`stdout` / `stderr` / exit code), and every edge case lives in the exhaustive
atlas document:

> **[`docs/architecture/command-reference.md`](architecture/command-reference.md)**
> — the full flag table and a verbatim real-output block for every subcommand,
> organized by the same command groups.

---

## Validated baseline

`docs/architecture/tools/validate-cli.sh` exercises a real invocation matrix
against a scratch root and reports OK / GUARDED / crash counts. Re-run it for
current numbers — this page does not track a frozen count because the CLI
surface (52 top-level commands, ~197 parser nodes as of this write-up) keeps
growing:

```bash
bash docs/architecture/tools/validate-cli.sh
```

Commands not yet in that invocation matrix are still structurally sound —
argparse definitions and handlers exist — but lack captured real-output
evidence. Treat them with normal care and run `--dry-run` first.

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

- **Hyphens are rejected in slugs.** `weekly-report` exits 2 with a suggested
  `weekly_report` fix. This applies to all positional `<slug>` arguments —
  domains, projects, automations, watch sources, customers.
- **Dry-run is default, not optional.** If a mutating command does nothing and
  produces no error, check whether you forgot `--apply`.
- **Exit 2 is not a crash.** `here route` exits 2 when cwd does not map confidently
  to a known domain. `cd` into the domain directory or use `route` with `--root`
  instead.
- **`config` has three subcommands.** There is no `config layers` or
  `config list`. The subcommands are `install`, `install-tree`, and `doctor`.
- **`config doctor` needs `config install` first.** A fresh `init` does not
  create the layer's `config.toml` at every directory — `config doctor` on an
  un-installed layer fails with "config.toml is missing" by design.
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
- Atlas: [`command-reference.md`](architecture/command-reference.md) (exhaustive)
