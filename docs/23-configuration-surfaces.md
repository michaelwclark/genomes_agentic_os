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
| `alerts.yml` | Alert routing rules and recipients. |
| `backup-policy.yml` | Backup schedule and retention config. |
| `capabilities.yml` | Installed OS capabilities (commands, skills, MCP servers, plugins). |
| `commands.yml` | OS command registry: slash commands visible to agents. |
| `composio-tools.yml` | Composio tool bindings and connection audit state. |
| `customer-identity.json` | Customer identity and license metadata. |
| `hooks.yml` | Claude and Codex hook configuration sources. |
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

## 3. agentic-os.lock.json — Install Lock

Located at `~/agentic_os/agentic-os.lock.json`.

Records the installed package version, install timestamp, and hash of the installed tree. Used by `agentic-os update` to detect drift and plan safe updates. Do not edit manually.

---

## 4. doc-config.yml — Document Routing Config

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

## 5. Control-Plane YAMLs — Runtime State

Located at `~/agentic_os/harness/shared_factory/00-control-plane/`. These files are the live runtime state of the OS. Most are managed by CLI commands; do not edit manually while the OS is running.

| File | Managed by | Contents |
|---|---|---|
| `runtime-registry.yml` | `agentic-os runtime`, `agentic-os heartbeat`, `agentic-os schedule`, `agentic-os integration` | Schedules, heartbeats, and integrations. |
| `run-queue.yml` | `agentic-os runtime run-next` | Pending and dispatched run-queue items. |
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

`agentic-os docs upkeep` reads the live control-plane
`documentation-upkeep.yml` first. If that file is missing, it falls back to the
installed template at
`harness/shared_factory/05-knowledge/templates/runtime/documentation-upkeep.yml`
inside the OS root. The source-repo template is only a development fallback for
editable/source checkouts.

---

## 6. Per-Tool Environment Variables

Each tool reads env vars from the process environment, with automatic fallback to `~/.zshenv` when running in a non-login shell.

### agentic-os (Python CLI)

| Variable | Default | Read by |
|---|---|---|
| `AGENTIC_OS_ROOT` | `~/agentic_os` | All subcommands as `--root` fallback. |

### agentic-os-jira

| Variable | Default | Auth route |
|---|---|---|
| `ATLASSIAN_CLIENT_ID` / `JIRA_OAUTH_CLIENT_ID` | — | OAuth (preferred) |
| `ATLASSIAN_CLIENT_SECRET` / `JIRA_OAUTH_CLIENT_SECRET` | — | OAuth |
| `ATLASSIAN_VENTURESGO_CLOUDID` / `ATLASSIAN_JIRA_CLOUDID` / `JIRA_CLOUD_ID` / `ATLASSIAN_CLOUD_ID` | — | OAuth cloud ID |
| `ATLASSIAN_BASE_URL` / `JIRA_OAUTH_BASE_URL` | Derived from cloud ID | OAuth gateway URL |
| `ATLASSIAN_OAUTH_AUDIENCE` | `api.atlassian.com` | OAuth audience |
| `JIRA_VENTURESGO_API_TOKEN` / `JIRA_API_TOKEN` | — | Basic auth (fallback) |
| `JIRA_VENTURESGO_EMAIL` / `JIRA_EMAIL` | `svc_jiraapi@thesummitgrp.com` | Basic auth email |
| `JIRA_VENTURESGO_BASE_URL` | `https://venturesgo.atlassian.net` | Basic auth base URL |

### agentic-os-automation-run-summary

| Variable | Default | Purpose |
|---|---|---|
| `GENOMES_NOTION_PAT` | — | Primary Notion API token (required for live writes). |
| `GENOMES_NOTION_CONNECTOR` | — | Alternative Notion token (checked when PAT is absent). |

### agentic-os-quiet-run

| Variable | Default | Purpose |
|---|---|---|
| `AGENTIC_OS_ACTIVE_WORK_ITEM` | — | Sets the async-run base directory when `--artifact-dir` is omitted. |

### agentic-os-status-report

No env vars are read directly. The collector script (`agentic_status.py`) may read `AGENTIC_OS_ROOT` and similar variables from `~/.zshenv`.

### agentic-os-memory-analytics

No env vars are read directly. Authentication to the remote memory service is via SSH BatchMode (key-based auth only).

---

## 7. Summary — What Reads What

| Config surface | Primary reader | CLI to inspect |
|---|---|---|
| `config.toml` (all layers) | Codex / Claude harnesses | `agentic-os config doctor --layer <layer>` |
| `harness/registries/skills.yml` | Skill runner, `register-harness-skills` | `agentic-os capability list` |
| `harness/registries/commands.yml` | Agent harnesses | `agentic-os capability list --type commands` |
| `harness/registries/mcp-servers.yml` | Codex harness | `agentic-os capability list --type mcp_servers` |
| `harness/registries/hooks.yml` | `agentic-os hook` | `agentic-os hook doctor` |
| `00-control-plane/runtime-registry.yml` | `agentic-os runtime` | `agentic-os runtime doctor` |
| `00-control-plane/run-queue.yml` | `agentic-os runtime run-next` | `agentic-os ps --active` |
| `00-control-plane/self-improvement.yml` | `agentic-os self-improvement` | `agentic-os self-improvement status` |
| `00-control-plane/automation-run-tracking.yml` | `agentic-os-automation-run-summary` | Read directly (YAML) |
| `doc-config.yml` | `agentic-os doc-config` | `agentic-os doc-config doctor` |
| `agentic-os.lock.json` | `agentic-os update` | `agentic-os update status` |
