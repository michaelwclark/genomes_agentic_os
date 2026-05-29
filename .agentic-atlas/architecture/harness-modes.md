# Harness Modes — Claude vs Codex (authoritative)

> **Read this before writing any "Claude mode / Codex mode" doc content.** It is
> the single source of truth for how the two harnesses differ. Every doc page's
> mode sections must be consistent with this file — do not re-derive per page.

---

## The finding: the OS is harness-neutral (the difference is thin)

`agentic-os` (the CLI), the workflow/automation specs, routing, run logs, approval
gates, and the operating loop are **identical** regardless of harness. This is by
design. The repo's own rule (`docs/07-agent-surfaces`):

> **Cross-Harness Rule:** Claude and Codex should not have separate operating
> philosophies. They can have different mechanics, but they should read the same
> specs and produce the same run logs.

Both harnesses share the **same requirements**: OS discovery, context loading,
workflow execution, run-log writing, approval handling, tool safety, and Notion
control-plane updates. The **only** real differences are **(1) how each harness is
configured/installed** and **(2) the invocation surface** (how you trigger the
same underlying work).

**Doc consequence:** per-page "modes" should be a **compact, task-specific
callout** — "from Claude do X; from Codex do Y" — naming the *specific* skill,
command, or profile relevant to that page. They should NOT be two long parallel
essays repeating the same concept (that's bloat). The deep mechanics live once on
the **Agent Surfaces** page; every other page links to it and shows only the
short callout.

---

## What is identical (do not write per-harness variants of these)

| Concern | Shared mechanism |
| --- | --- |
| The CLI | `agentic-os …` — same binary, same flags, same exit codes |
| Operating loop | discover root → load `AGENTS.md` → route → build context → execute allowed steps → validate → write run log → update control plane → report |
| Context contract | `AGENTS.md` (neutral entry), `ROUTER.md`, `CONTEXT.md`, `RULES.md`, `TOOLS.md`, `MEMORY.md`, `BRAIN.md` |
| Workflow/automation specs | identical files + readiness rules |
| Run logs, approvals, safety | identical |
| Skills & commands | the **same** registry (`capability_registry`) renders the **same** skills/commands into `TOOLS.md` for both harnesses |

## What differs (this is all of it)

| Aspect | Claude | Codex |
| --- | --- | --- |
| **Entry adapter** | `CLAUDE.md` is a one-line include: `@AGENTS.md` | `AGENTS.md` directly + a layered `config.toml` |
| **Config mechanism** | global/project `CLAUDE.md` adapters; skills & slash-commands installed to the harness | `config.toml` with `profiles.*` (`model`, `model_reasoning_effort`, `approval_policy`, `sandbox_mode`) across 5 OS layers |
| **Config command** | (adapter is just `@AGENTS.md`; skills/commands provisioned to harness dirs) | `agentic-os config install --layer <layer> --dry-run/--apply` writes the right `config.toml` |
| **MCP registration** | via Claude's MCP config | via `config.toml` `mcp_servers.*` (registration points: notion, genomes_brain, github, context_mode, sentry, datadog, supabase, playwright, filesystem_runtime) |
| **Invocation surface** | slash-commands (`/os-route`, `/os-doctor`, …) + skills (`workflow-builder`, `os-navigator`, …) | profiles + the same skills/commands surfaced through `TOOLS.md`; or call `agentic-os …` directly |
| **Telemetry** | Claude-side | `config.toml` OTEL env (`AGENTIC_OS_OTEL_EXPORTER_OTLP_ENDPOINT`, `AGENTIC_OS_OTEL_HEADERS`) |

### Codex config.toml layer model (6 config layers + Codex precedence)

> **CLI tokens vs descriptive keys:** the `config install --layer` flag accepts
> exactly six tokens — `agentic_os_root`, `automation`, `customer_os_root`,
> `domain_or_lane`, `global_harness`, `workflow_or_task`. (`codex-config-layer-map.yml`
> documents the global layer under the descriptive key `global_user_harness`, but
> the CLI token is `global_harness`.)

Codex precedence (highest→lowest): CLI override → `--profile` → project `.codex/config.toml` → `~/.codex/config.toml` → `/etc/codex/config.toml` → built-in defaults.

| OS layer | `config.toml` path | Governs |
| --- | --- | --- |
| `global_harness` | `~/.codex/config.toml` | default profile, personal model defaults, trusted-project registry, global MCP, global safety hooks |
| `agentic_os_root` | `~/agentic_os/.codex/config.toml` | OS operating profile, shared skills/tooling, memory/control-plane conventions, Notion guardrails |
| `customer_os_root` | `<customer_os>/.codex/config.toml` | customer data boundary, customer MCP, customer approval policy, telemetry posture |
| `domain_or_lane` | `<domain_or_lane>/.codex/config.toml` | domain routing, model/reasoning profile, tool allow-list, validation hooks |
| `workflow_or_task` | `<workflow>/.codex/config.toml` | temporary profile override, workflow-specific context + validation |
| `automation` | `<automation>/.codex/config.toml` | automation-scoped profile + approval/sandbox posture for one automation |

Security-sensitive keys (require care on install): `approval_policy`,
`approvals_reviewer`, `sandbox_mode`, `default_permissions`, `permissions`,
`sandbox_workspace_write.network_access`, `mcp_servers.*.env`.

---

## Page → invocation mapping (use this to write each page's mode callout)

Each doc page should show its task in both harnesses using the **specific** skill /
command / profile below — that's what makes the callout non-boilerplate.

| Doc page / task | Claude: command / skill | Codex: equivalent |
| --- | --- | --- |
| Install & quickstart | install skills + `CLAUDE.md`=`@AGENTS.md` | `agentic-os config install --layer global_harness` then `agentic_os_root` |
| Routing & context | `/os-route`, `os-navigator` skill | `agentic-os route` / `here route`; `domain_or_lane` profile |
| Workflows | `/os-create-workflow`, `workflow-builder` skill | `agentic-os workflow check`; author from `templates/workflow/` |
| Automations | `os-create-automation`, `automation-qualifier` skill | `agentic-os automation check/set-maturity` |
| Runs & run logs | `/os-run-log`, `run-logger` skill | `agentic-os run-log create/close` |
| Runtime / always-on | `/os-runtime-init`, `/os-heartbeat`, `runtime-operator` skill | `agentic-os runtime/heartbeat/schedule …`; supervisor (see gap A) |
| Events & chains | `/os-event`, `/os-chain`, `event-graph-operator` skill | `agentic-os event/chain …` |
| Connected sources | `/os-watch-source`, `source-watcher` skill | `agentic-os watch-source/connected-system …` |
| Notion control plane | `/os-sync-notion`, `control-plane-bootstrap` skill | `agentic-os notion plan-sync/sync` |
| Doctor & health | `/os-doctor`, `os-doctor` skill | `agentic-os doctor`, `* doctor` |
| Customer OS factory | `client-automation-brief` skill | `agentic-os customer init/validate` |
| Context audits | `/os-context-audit`, `context-audit` / `context-pack-builder` skills | `agentic-os context build` |
| Rooms / domains | `/os-discover-rooms`, `domain-setup` / `room-builder` skills | `agentic-os domain create`, `room create/update` |
| Updates | `/os-update`, `update` flows | `agentic-os update …` |

Inventory: **21 harness commands** (`harness/commands/os-*.md`) and **18 skills**
(`harness/skills/`), both shared and surfaced into `TOOLS.md` by
`capability_registry`. The full lists live in
[`command-reference.md`](command-reference.md) and the installed `TOOLS.md`.

---

## Recommended per-page doc convention (apply consistently)

Each `docs/` page ends its how-to with a short block like:

```md
### Running this from Claude vs Codex
- **Claude:** `/os-route "<request>"` — or invoke the `os-navigator` skill.
- **Codex:** `agentic-os route "<request>" --root ~/agentic_os` — governed by the
  `domain_or_lane` profile in that folder's `config.toml`.
> Same routing logic, same `ContextPacket`, same run log. Only the trigger differs.
> Full setup: [Agent Surfaces](13-agent-surfaces.md).
```

This honors "Claude and Codex mode for each page" while keeping the deep mechanics
in one place. **Open product decision (flagged for the user):** whether to keep
this compact callout form, or expand to full dual `## Claude mode` / `## Codex
mode` sections per page.
