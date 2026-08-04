# Configuration Surfaces

This document describes every configuration system the Agentic OS reads at runtime, how they interact, and which CLI commands manage them.

## 1. config.toml — Codex / Harness Config

Managed by `agentic-os config install` and `agentic-os config install-tree`.

Each OS directory layer has its own `config.toml` that controls Codex profile, MCP scope, sandbox mode, and prompt-file loading. Layers are applied in order from broadest to narrowest; narrower layers override broader ones.

### Layers

| Layer key | Directory | Purpose |
|---|---|---|
| `global_harness` | `~/.codex/` | User-global Codex config (not OS-specific). |
| `agentic_os_root` | `~/agentic_os/` | OS root layer; sets the base OS profile and MCP servers. |
| `customer_os_root` | `~/agentic_os/<customer>/` | Customer OS root; customer-specific profile + MCP scope. |
| `domain_or_lane` | `~/agentic_os/<domain>/` | Domain room layer; domain-specific profile. |
| `project` | `~/agentic_os/<domain>/<project>/` | Project layer; project-specific profile and prompt files. |
| `workflow_or_task` | `~/agentic_os/<domain>/<lane>/<workflow>/` | Workflow layer; task-scoped config. |
| `automation` | `~/agentic_os/<domain>/<lane>/<automation>/` | Automation layer; automation-specific config. |

### CLI

```
agentic-os config install --layer <layer> [--apply]     Install one layer.
agentic-os config install-tree [--apply]                Install all layers across the OS tree.
agentic-os config doctor --layer <layer>                Validate a layer's config.toml.
```

---

## 2. harness/registries/*.yml — Capability and Tool Registries

Located at `~/agentic_os/harness/registries/`. Each file is a YAML registry for a specific capability surface. The registries are read by the OS CLI, skill runners, and agent harnesses.

| File | Contents |
|---|---|
| `alerts.yml` | Local macOS alert policy: severity, source routing, quiet hours, sound/DND behavior, anti-flood limits, and the 48-hour notification-history retention rule. |
| `backup-policy.yml` | Backup schedule and retention config. |
| `capabilities.yml` | Installed OS capabilities (commands, skills, MCP servers, plugins). |
| `commands.yml` | OS command registry: slash commands visible to agents. |
| `composio-tools.yml` | Composio tool bindings and connection audit state. |
| `customer-identity.json` | Customer identity and license metadata. |
| `hooks.yml` | Claude and Codex hook configuration sources. |
| `hosts-routing.yml` | Cross-host harness routing policy: eligible hosts, per-host project paths, least-active probe settings, Host-column overrides, artifact visibility, and shared memory-plane notes. |
| `intake-sync.yml` | Intake sync source bindings. |
| `libraries.yml` | Installed library references. |
| `mcp-servers.yml` | MCP server registry: names, commands, env requirements. |
| `plugins.yml` | Installed plugin surface registrations. |
| `rules.yml` | OS-level rules enforced by the harness. |
| `skills.yml` | Skill registry: skill names, paths, descriptions, triggers. |
| `tracker-routing.yml` | Tracker (Jira/Linear) routing rules. |
| `update-plan.yml` | Pending OS update plan (from `agentic-os update plan`). |
| `update-status.yml` | Current update status (from `agentic-os update status`). |
| `updates.yml` | Update history log. |

### CLI

```
agentic-os capability list                List registered capabilities.
agentic-os capability inventory           Show or regenerate INVENTORY.md.
agentic-os hook sync [--apply]            Point active hooks at installed OS hook scripts.
agentic-os update check                   Check for available updates.
agentic-os update plan                    Write an inspectable update plan.
agentic-os update apply [--apply]         Apply safe additive update changes.
```

---

## 3. Host identity registry

Located at `~/agentic_os/config/hosts.yml` in the historical package layout or
`~/agentic_os/harness/config/hosts.yml` in the installed harness-owned layout.
The host CLI resolves the existing source and writes back to it so it does not
create a parallel registry.

Stores SSH identity only: host alias, SSH alias, user, home/path-domain root, description, SSH options, and optional path metadata. Routing policy is deliberately separate in `harness/registries/hosts-routing.yml`, so credentials and dispatch decisions do not drift together.

Cross-host work distribution reads both files:

- `config/hosts.yml` resolves the SSH identity used by `agentic-harness-run --host <alias>`.
- `harness/registries/hosts-routing.yml` decides whether that host is eligible for a project and how paths/artifacts are mapped.

### CLI

```
agentic-os host add <alias> --ssh-alias <ssh-name> --home <path> [--description "..."]
agentic-os host list [--json]
agentic-os host routing [--recent-runs N] [--json]
```

---

## 3A. Execution Fabric instance configuration

`~/agentic_os/harness/config/execution-fabric.yml` is the one editable
instance policy for named queues, worker pools, global/provider admission
limits, queue depth, worker capacity, leases, and retries. Source-package
updates install the shipped default only when the file is absent, so local
operator changes are preserved. Package-owned schemas are upgraded by checksum
manifest; an edited installed schema is retained and the new package copy is
written beside it with a `.new` suffix for explicit reconciliation.

The runtime reports the exact effective source and a deterministic SHA-256
fingerprint:

```bash
agentic-os runtime config status --root ~/agentic_os --json
agentic-os runtime config show --root ~/agentic_os --json
agentic-os runtime config diff --root ~/agentic_os --json
agentic-os runtime config validate --root ~/agentic_os
agentic-os runtime config reconcile --root ~/agentic_os
agentic-os runtime config reconcile --root ~/agentic_os --apply
agentic-os runtime config reload --root ~/agentic_os --expected-fingerprint <sha256>
agentic-os runtime config reload --root ~/agentic_os --expected-fingerprint <sha256> --apply
```

Reconciliation is dry-run-first and writes only while `execution_fabric` is
the selected queue writer. Queue, pool, enablement, capacity, admission,
lease, and retry rows update in one SQLite transaction, followed by exact
readback. The file does not duplicate host or alert settings: status points to
the active `config/hosts.yml` or `harness/config/hosts.yml`,
`harness/registries/hosts-routing.yml`, and `harness/registries/alerts.yml`.
Every host overlay must resolve in both canonical host registries. Remote reload
uses the distinct admin credential, verifies an expected fingerprint, performs
observer pre-read and readback, fences both current and candidate fingerprints
server-side, and writes a redacted durable receipt.

---

## 4. agentic-os.lock.json — Install Lock

Located at `~/agentic_os/agentic-os.lock.json`.

Records the installed package version, install timestamp, and hash of the installed tree. Used by `agentic-os update` to detect drift and plan safe updates. Do not edit manually.

---

## 5. doc-config.yml — Document Routing Config

Located at:
- `~/agentic_os/<domain>/<project>/doc-config.yml` — per-project routing
- `~/agentic_os/harness/shared_factory/doc-config.yml` — shared factory fallback

Controls where documents, specs, briefs, and notes are written for a given project. Defines buckets (SPEC, FEATURE, BRIEF, NOTES, etc.) mapped to filesystem paths and Notion destinations.

### CLI

```
agentic-os doc-config init [--domain D] [--project P]   Install doc-config.yml.
agentic-os doc-config doctor                             Check contracts.
agentic-os doc-config plan --request "..."               Get a routing decision.
```

---

## 5A. Five Nested Auto-Dev Markdown Policy Planes

Auto-Dev workflow behavior is configured by ordered 1-N Markdown folders. A
new `.md` file is consumed on the next run without a Python or registry change.
Every resolver records ordered sources and a content fingerprint.

All five live under the `auto_dev/` parent at root, domain, and project scope.
Auto-Dev behavior is the Markdown directly in that parent; the other four use
nested directories. Artifact and investigation configuration remain adjacent
contracts and are not counted as development planes.

| Plane | Root | Domain | Project | CLI |
| --- | --- | --- | --- | --- |
| Auto-Dev behavior | `harness/shared_factory/05-knowledge/auto_dev/` | `config/auto_dev/` | `config/auto_dev/` | `agentic-os develop policy ... --plane auto_dev` |
| Environment access | `harness/shared_factory/05-knowledge/auto_dev/environment_access/` | `config/auto_dev/environment_access/` | `config/auto_dev/environment_access/` | `agentic-os develop policy ... --plane environment_access` |
| Development standards | `harness/shared_factory/05-knowledge/auto_dev/dev_standards/` | `config/auto_dev/dev_standards/` | `config/auto_dev/dev_standards/` | `agentic-os develop policy ... --plane dev_standards` |
| QA gates | `harness/shared_factory/05-knowledge/auto_dev/qa_gates/` | `config/auto_dev/qa_gates/` | `config/auto_dev/qa_gates/` | `agentic-os develop policy ... --plane qa_gates` |
| Gitflow topology | `harness/shared_factory/05-knowledge/auto_dev/gitflow_topology/` | `config/auto_dev/gitflow_topology/` | `config/auto_dev/gitflow_topology/` | `agentic-os develop policy ... --plane gitflow_topology` |
| Artifact contracts | `harness/artifact-config/` | `artifact-config/` | `artifact-config/` | `agentic-os artifacts resolve ... --explain` |
| Investigation sources | `harness/investigation-config/` | `investigation-config/` | `investigation-config/` | `agentic-os detective resolve ... --explain` |

Projects may replace a plane's ordered folders through
`config/development.yml policies.<plane>.paths`. Artifact contracts compose
`any/any`, `any/<type>`, `<provider>/any`, and `<provider>/<type>` at each scope.
Narrower scopes may specialize behavior but cannot weaken inherited safety,
approval, sanitization, target verification, or readback.

New domain policy always writes to `domains/<domain>/config/auto_dev/`. The
resolver retains `domains/<domain>/05-knowledge/auto_dev/` as a fallback only
when the canonical domain plane has no active Markdown; it never merges the
two domain roots.

Use `agentic-os artifacts doctor` after changing artifact contracts and
`agentic-os detective doctor` after changing investigation packs. Applied
development runs snapshot all five development planes in
`state/development-runs/<run-id>/effective-policies.json`.

---

## 6. Control-Plane YAMLs — Runtime State

Located at `~/agentic_os/harness/shared_factory/00-control-plane/`. These files are the live runtime state of the OS. Most are managed by CLI commands; do not edit manually while the OS is running.

| File | Managed by | Contents |
|---|---|---|
| `runtime-registry.yml` | `agentic-os runtime`, `agentic-os heartbeat`, `agentic-os schedule`, `agentic-os integration` | Schedules, heartbeats, and integrations. |
| `run-queue.yml` | `agentic-os runtime run-next`, `agentic-os run-queue prune` | Pending and dispatched run-queue items plus bounded pruning. |
| `automation-run-tracking.yml` | `agentic-os-automation-run-summary` | Per-automation Notion page IDs and tracking config. |
| `self-improvement.yml` | `agentic-os self-improvement` | Self-improvement proposal queue, run records, and review config. |
| `chain-rules.yml` | `agentic-os chain` | Event chain rules linking event types to follow-up actions. |
| `connected-systems.yml` | `agentic-os connected-system` | Registered connected external systems. |
| `watch-sources.yml` | `agentic-os watch-source` | Watch source configurations (Notion databases, etc.). |
| `watch-cursors.yml` | `agentic-os watch-source poll` | Poll cursors for each watch source (last-seen state). |
| `event-graph.yml` | `agentic-os event` | File-backed event ledger. |
| `event-cursors.yml` | `agentic-os event process-due` | Event processing cursors. |
| `integration-registry.yml` | `agentic-os integration` | Integration setup records. |
| `automation-control.yml` | `agentic-os automation-control` | Automation gate configurations and source-readiness probes. |
| `doc-config.yml` | `agentic-os doc-config` | Shared-factory document routing config. |
| `documentation-upkeep.yml` | `agentic-os docs upkeep` | Documentation upkeep registry and drift planner config. |
| `notion-tracking.yml` | `agentic-os notion` | Notion workspace, parent page id, and control-plane tracking config. |
| `notion-organization.yml` | `agentic-os notion-org` | Notion IA organization config for pre-move validation. |
| `source-providers.yml` | Internal | Source provider registry for watch sources. |
| `doctor-snapshot.yml` | `agentic-os doctor` | Latest doctor findings snapshot. |
| `decisions.md` | Manual / `agentic-os self-improvement` | Architecture and operating decisions log. |
| `active-work.md` | `agentic-os project work-item sync-active` | Generated index of active work items and worktrees. |
| `routing-rules.md` | Manual | Domain and project routing rules for the OS navigator. |
| `approval-rules.md` | Manual | Approval gate rules for gated automation steps. |
| `managed-templates.yml` | `agentic-os docs` | Managed documentation template registry. |
| `../../config/long-running-execution.yml` | `agentic-os long-run` | Two-minute qualification threshold, run budgets, collateral ceilings, high-risk requirements, and terminal artifact contract. |

`agentic-os docs upkeep` reads the live control-plane
`documentation-upkeep.yml` first. If that file is missing, it falls back to the
installed template at
`harness/shared_factory/05-knowledge/templates/runtime/documentation-upkeep.yml`
inside the OS root. The source-repo template is only a development fallback for
editable/source checkouts.

---

## 7. Per-Tool Environment Variables

Each tool reads env vars from the process environment, with automatic fallback to `~/.zshenv` when running in a non-login shell.

### agentic-os (Python CLI)

| Variable | Default | Read by |
|---|---|---|
| `AGENTIC_OS_ROOT` | `~/agentic_os` | All subcommands as `--root` fallback. |

### agentic-os-jira

| Variable | Default | Auth route |
|---|---|---|
| `GENOMES_JIRA_BRIDGE_COMMAND` | — | Reviewed `@genomes/jira` bridge argv; required for live operations |
| `JIRA_OAUTH_TOKEN` / `ATLASSIAN_ACCESS_TOKEN` | — | Injected OAuth bearer (preferred) |
| `ATLASSIAN_JIRA_CLOUDID` / `JIRA_CLOUD_ID` / `ATLASSIAN_CLOUD_ID` | — | OAuth cloud ID |
| `ATLASSIAN_BASE_URL` / `JIRA_OAUTH_BASE_URL` | Derived from cloud ID | OAuth gateway URL |
| `JIRA_API_TOKEN` | — | Basic auth (fallback) |
| `JIRA_EMAIL` | — | Basic auth email |
| `JIRA_BASE_URL` | — | Basic-auth tenant URL; Spec Engine and source-watch bridge base |
| `JIRA_BROWSE_BASE` | — | Wrapper tenant site URL for identity preflight |
| `JIRA_SITE_URL` | — | Auto-Dev live tracker tenant site URL for identity preflight |
| `JIRA_DEFAULT_ISSUE_TYPE_ID` | — | Expected issue-type ID for mutation preflight |
| `JIRA_ACCOUNT_ID` / `ATLASSIAN_ACCOUNT_ID` | — | Optional expected account ID for mutation preflight |

The wrapper no longer mints OAuth client-credential tokens or constructs Jira
HTTP requests. A bearer/session provider must inject the short-lived bearer;
the reviewed platform bridge owns Jira transport, retries, safe errors, and
provider readback.

### Linear call sites

| Variable | Default | Purpose |
|---|---|---|
| `GENOMES_LINEAR_BRIDGE_COMMAND` | — | Reviewed `@genomes/linear` bridge argv; required for resolver, intake-sync, and live Spec Engine operations |
| `LINEAR_TOKEN` / `LINEAR_API_KEY` / `LINEAR_API_TOKEN` | — | Exactly one Linear credential, injected only into the bridge child environment |
| project `token_env` | `LINEAR_TOKEN` | Selects a custom host environment variable for a multi-workspace tracker; the wrapper remaps it to child `LINEAR_TOKEN` |

The migrated callers do not own a Linear endpoint, GraphQL document, header,
retry loop, or provider error parser. Build the reviewed platform revision and
point `GENOMES_LINEAR_BRIDGE_COMMAND` at
`packages/linear/dist/bridge.js`; the shared bridge owns pagination, identity
preflight, mutation readback, bounded retries, safe errors, and exact marker
reconciliation.

### Notion bridge call sites

| Variable | Default | Purpose |
|---|---|---|
| `GENOMES_NOTION_BRIDGE_COMMAND` | — | Reviewed `@genomes/notion` bridge argv; required for migrated live operations |
| `GENOMES_NOTION_PAT` | — | Notion credential injected only into the bridge child environment |
| `GENOMES_NOTION_WORKSPACE` | `Genome's Notion` | Exact workspace identity required for mutations |
| `GENOMES_NOTION_PARENT_PAGE_ID` | — | Exact approved parent identity required for mutations |
| `GENOMES_NOTION_BOT_ID` | — | Optional exact bot identity required by stricter mutation routes |

Build the pinned platform revision and point
`GENOMES_NOTION_BRIDGE_COMMAND` at `packages/notion/dist/bridge.js`. The shared
bridge uses Notion API `2026-03-11` and owns pagination, deadlines, bounded read
retries, safe errors, mutation ancestry checks, and provider readback. The
live Notion read and mutation families use this bridge. The only retained
urllib seam is credential-free, fixture-only, and targets the synthetic
`notion-fixture.invalid` host.

### agentic-os-automation-run-summary

| Variable | Default | Purpose |
|---|---|---|
| `GENOMES_NOTION_PAT` | — | Primary Notion API token (required for live writes). |
| `GENOMES_NOTION_CONNECTOR` | — | Alternative Notion token (checked when PAT is absent). |

### agentic-os-quiet-run

| Variable | Default | Purpose |
|---|---|---|
| `AGENTIC_OS_ACTIVE_WORK_ITEM` | — | Sets the async-run base directory when `--artifact-dir` is omitted. |

### agentic-os-notify

| Variable | Default | Purpose |
|---|---|---|
| `AGENTIC_OS_ROOT` | `~/agentic_os` | Resolves `harness/registries/alerts.yml` and the canonical alert history. |

`agentic-os-notify` writes delivery and suppression decisions to
`harness/shared_factory/06-runs-and-logs/alerts/alerts.jsonl`. It prunes all
alert-history segments older than the configured 48-hour default before each
non-dry-run delivery. `--history` reads that retained history and `--cleanup`
performs maintenance without sending an alert.

The registry controls severity (`info`, `warning`, `error`, `critical`), quiet
hours, source-level minimum severity, sound, click URL support, DND override,
repeat cooldowns, and hourly delivery caps. Notifications are local macOS
notifications: banner versus alert style and Apple-device mirroring remain user
settings in macOS Notification Center and iCloud, respectively.

### Agent invocation and source registration

Agents use the visible `/notify` command or `notification-operator` skill when
a receipt-backed, operator-actionable condition needs local attention. The
command takes a stable source id, severity, concise title and message, and a
stable `--dedupe-key`. It is not a progress-reporting channel and does not
authorize Slack, email, tracker, or other external communication.

New watcher or automation sources must first add an inherited entry under
`sources` in `alerts.yml`, then verify wiring with `--dry-run`. The source entry
should retain the conservative cooldown and hourly cap unless there is a
documented reason to change them. See `harness/commands/os-notify.md` for the
copyable invocation and source-policy recipe.

### agentic-os-status-report

No env vars are read directly. The collector script (`agentic_status.py`) may read `AGENTIC_OS_ROOT` and similar variables from `~/.zshenv`.

### agentic-os-memory-analytics

No env vars are read directly. Authentication to the remote memory service is via SSH BatchMode (key-based auth only).

---

## 8. Summary — What Reads What

| Config surface | Primary reader | CLI to inspect |
|---|---|---|
| `config.toml` (all layers) | Codex / Claude harnesses | `agentic-os config doctor --layer <layer>` |
| `harness/registries/skills.yml` | Skill runner, `register-harness-skills` | `agentic-os capability list` |
| `harness/registries/commands.yml` | Agent harnesses | `agentic-os capability list --type commands` |
| `harness/registries/mcp-servers.yml` | Codex harness | `agentic-os capability list --type mcp_servers` |
| `harness/registries/hooks.yml` | `agentic-os hook` | `agentic-os hook doctor` |
| `config/hosts.yml` | `agentic-os host`, `agentic-harness-run --host` | `agentic-os host list` |
| `harness/registries/hosts-routing.yml` | `agentic-harness-run --host auto`, Notion work-intake watcher | `agentic-os host routing` |
| `00-control-plane/runtime-registry.yml` | `agentic-os runtime` | `agentic-os runtime doctor` |
| `00-control-plane/run-queue.yml` | `agentic-os runtime run-next`, `agentic-os run-queue prune` | `agentic-os ps --active` |
| `00-control-plane/self-improvement.yml` | `agentic-os self-improvement` | `agentic-os self-improvement status` |
| `00-control-plane/automation-run-tracking.yml` | `agentic-os-automation-run-summary` | Read directly (YAML) |
| `doc-config.yml` | `agentic-os doc-config` | `agentic-os doc-config doctor` |
| `agentic-os.lock.json` | `agentic-os update` | `agentic-os update status` |
