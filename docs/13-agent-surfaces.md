# 13 · Agent Surfaces (Claude & Codex)

> **Purpose:** this is the deep-mechanics reference for how Genome's Agentic OS
> runs from Claude vs Codex. Every other page's "Running this from Claude vs
> Codex" callout links here for the full picture.
>
> **You'll use:** `agentic-os config install`, `agentic-os config install-tree`,
> `agentic-os config doctor`,
> `CLAUDE.md`/`AGENTS.md` adapters, `config.toml` layers, skills, and
> slash-commands.
> **Prereqs:** an installed OS root ([01 · Install & Quickstart](01-install-and-quickstart.md)).
> Architecture context: [02 · Architecture](02-architecture.md).

---

## The harness-neutral design

The most important fact about Genome's Agentic OS: **the OS itself does not know
which harness is driving it.** The CLI, the workflow and automation specs, the
routing logic, the run logs, the approval gates, and the operating loop are
identical whether Claude or Codex is in the seat. This is by design. From
`docs/07-agent-surfaces/`:

> **Cross-Harness Rule:** Claude and Codex should not have separate operating
> philosophies. They can have different mechanics, but they should read the same
> specs and produce the same run logs.

The difference between running from Claude and running from Codex is thin: it is
purely about *how* the harness discovers the OS context and which runtime posture
it adopts. Everything underneath — the specs, the logic, the outputs — is the
same.

---

## Shared core

Both harnesses read the same set of markdown files. These are **never duplicated
per-harness**.

| File | Scope | Role |
|---|---|---|
| `AGENTS.md` | universal entry point | Tells every agent: read the local router, context, rules, and tool registry; route before acting; repeat after changing directories |
| `CLAUDE.md` | Claude-only adapter | A single line: `@AGENTS.md` — includes the shared contract without duplicating it |
| `ROUTER.md` | local routing map | Chooses the domain, lane, workflow, automation, or source for the active request |
| `CONTEXT.md` | local room context | Describes how work inside this directory should be understood before acting |
| `RULES.md` | local constraints | Approval gates, safety boundaries, coding rules, and operating constraints |
| `TOOLS.md` | visible tool registry | Lists skills, commands, MCP servers, and when to use them — rendered by `capability_registry` for both harnesses |
| `MEMORY.md` | memory pointer | Describes what may be remembered when local memory policy is needed |
| `BRAIN.md` | universal agent brain | Cross-harness cognition policy: how to reason, when to escalate, how to scope work and close it |

The operating loop is also identical:

```
discover root → load AGENTS.md → route → build context →
execute allowed steps → validate → write run log →
update control plane → report
```

**Skills and commands** are also shared: the same `capability_registry` renders
the same 19 `os-*` slash-commands and 18 skills into `TOOLS.md` for both harnesses.

---

## Diagram

![Both harnesses reading the same shared markdown core (AGENTS.md, PROFILE.md, ROUTER.md, CONTEXT.md, RULES.md, TOOLS.md, MEMORY.md, BRAIN.md) and the same CLI, then diverging: Claude via the @AGENTS.md adapter plus skills, commands, and MCP in Claude config; Codex via config.toml layers, profiles, config install, and MCP in mcp_servers.*](diagrams/surfaces-harness-design.png)

---

## Claude surface

### Entry adapter

`CLAUDE.md` is intentionally minimal. At every scope level (global, project,
domain, workflow) it is a **single-line include**:

```md
@AGENTS.md
```

That line pulls in the shared context contract. Claude resolves the include, loads
`ROUTER.md` / `CONTEXT.md` / `RULES.md` / `TOOLS.md` in order, and enters the
route-read-cd-repeat loop. No OS logic lives in `CLAUDE.md`; local edits survive
regeneration.

### Project-local surface

Every project under `<domain>/02-projects/<project>/` has the same local
contract:

- `AGENTS.md`, `ROUTER.md`, `CONTEXT.md`, `RULES.md`, `TOOLS.md`, `MEMORY.md`
  explain the project for Claude, Codex, and any compatible harness.
- `config.toml` gives Codex the project layer posture.
- `config/*.yml` stores machine-readable project profile, workflows, output
  artifacts, validation, worktrees, memory, MCP, and tool defaults.
- `work-items/01-intake/` captures project-known rough ideas as indexed markdown
  files before they become specs, tickets, workflows, or implementation packets.
  Expanded intake can use an indexed packet folder when a duel/spec pass creates
  multiple files.
- `ideas/` is a compatibility index for older tools, not the lifecycle source
  of truth.
- `src/` is the canonical source symlink when a local repo is known.
- `worktrees/` contains visible symlinks to active branch checkouts, backed by
  `worktrees/index.yml` for routing.

Use Markdown for narrative context, rules, decisions, and idea capture. Use YAML
for values that the CLI or agents should parse. When a file needs both, use
Markdown with YAML front matter.

### Skills (18 total)

Skills are installed into the harness skill directory and surfaced in `TOOLS.md`
by `capability_registry`. All 18 are shared — Codex can invoke them too.

| Skill | When to use |
|---|---|
| `os-navigator` | Route work through installed OS rooms |
| `workflow-builder` | Create or improve reusable workflows |
| `automation-qualifier` | Decide whether a process is safe to automate |
| `os-doctor` | Audit installed OS structure and contracts |
| `run-logger` | Create and close run-log entries |
| `runtime-operator` | Manage the always-on loop: heartbeats, schedules |
| `event-graph-operator` | Emit and trace events and chains |
| `source-watcher` | Register and check connected sources |
| `control-plane-bootstrap` | Bootstrap the Notion control plane |
| `build-runner` | Execute build/test/validate runs |
| `context-pack-builder` | Assemble a context packet for a request |
| `context-audit` | Audit context file health at a layer |
| `domain-setup` | Create or update a domain/room |
| `room-builder` | Build or reconfigure a room structure |
| `integration-setup` | Wire a new integration to the OS |
| `learning-promoter` | Promote ephemeral learning to durable memory |
| `automation-qualifier` | Qualify an automation for the maturity ladder |
| `client-automation-brief` | Generate a customer automation brief |

### Slash-commands (21 command files; 19 are `os-*`)

Commands are installed to `harness/commands/` and exposed as slash-commands in
Claude. Two files are helpers (`composio-debug-bundle.md`,
`system-tool-registry.md`); the 19 `os-*` commands cover every OS operation:

| Command | Operation |
|---|---|
| `/os-route` | Route a request to the right domain/workflow |
| `/os-doctor` | Run an OS health audit |
| `/os-run-log` | Create or close a run log entry |
| `/os-create-workflow` | Scaffold a new workflow spec |
| `/os-create-automation` | Scaffold a new automation spec |
| `/os-heartbeat` | Emit a runtime heartbeat |
| `/os-runtime-init` | Initialize the always-on runtime |
| `/os-event` | Emit or inspect an OS event |
| `/os-chain` | Create or advance an event chain |
| `/os-sync-notion` | Sync the Notion control plane |
| `/os-watch-source` | Register or check a connected source |
| `/os-discover-rooms` | Discover and list installed rooms/domains |
| `/os-update` | Run the OS update flow |
| `/os-control-plane-bootstrap` | Bootstrap the control plane from scratch |
| `/os-integration-setup` | Wire a new integration |
| `/os-client-automation-brief` | Generate a customer automation brief |
| `/os-context-audit` | Audit context files at a layer |
| `/os-capture-plan` | Capture a plan into the OS |
| `/os-run-build-runner` | Execute a build-runner run |

### MCP (Claude)

MCP servers are registered via Claude's own MCP config (not `config.toml`). The
same server set as Codex is available: `notion`, `genomes_brain`, `github`,
`context_mode`, `filesystem_runtime`, and others.

---

## Codex surface

### Entry point

Codex reads `AGENTS.md` directly (no adapter indirection). A layered
`config.toml` provides the runtime posture that `CLAUDE.md` doesn't need to
supply.

### The seven config.toml layers

Scaffold commands write the matching `config.toml` when they create an OS root,
domain, project, workflow, or automation. `config install` can repair or merge one
layer at a time. The CLI `--layer` flag accepts these exact tokens:

| CLI layer token | `config.toml` path | Governs |
|---|---|---|
| `global_harness` | `~/.codex/config.toml` | Default profile, personal model defaults, trusted-project registry, global MCP, global safety hooks |
| `agentic_os_root` | `~/agentic_os/config.toml` | OS operating profile, shared skills/tooling, memory/control-plane conventions, Notion guardrails |
| `customer_os_root` | `<customer_os>/config.toml` | Customer data boundary, customer MCP, customer approval policy, telemetry posture |
| `domain_or_lane` | `<domain_or_lane>/config.toml` | Domain routing, model/reasoning profile, tool allow-list, validation hooks |
| `project` | `<domain>/02-projects/<project>/config.toml` | Project source boundary, project context, validation hooks |
| `workflow_or_task` | `<workflow>/config.toml` | Temporary profile override, workflow-specific context and validation |
| `automation` | `<automation>/config.toml` | Automation-scoped posture and context |

**Codex precedence (highest → lowest):** CLI override → `--profile` → project
layer `config.toml` → `~/.codex/config.toml` → `/etc/codex/config.toml` →
built-in defaults.

> **Note on naming:** The conceptual "global user harness" layer maps to the CLI
> token `global_harness` (not `global_user_harness`). Use `global_harness` in any
> runnable command. See [Guardrails](#guardrails--gotchas) for exit-code details.

### Profile keys

Each `config.toml` carries one canonical `[profiles.<name>]` section and, where
needed, compatibility aliases for older generated profile names. Navigation
layers use `gpt-5.4-mini` with medium reasoning; project, workflow, and
automation layers use `gpt-5.5` with high reasoning. The four keys that govern
runtime posture:

| Key | What it controls |
|---|---|
| `model` | Which model Codex uses for this layer |
| `model_reasoning_effort` | Reasoning budget: `low` / `medium` / `high` |
| `approval_policy` | When to pause for human approval: `on-request` / `never` / `always` |
| `sandbox_mode` | Filesystem access boundary: `workspace-write` / `read-only` |

### Security-sensitive keys

These keys require review before applying. The installer shows a diff for
confirmation:

- `approval_policy`, `approvals_reviewer`
- `sandbox_mode`, `default_permissions`, `permissions`
- `sandbox_workspace_write.network_access`
- `mcp_servers.*.env` (never put secrets inline — env var names only)

### MCP (Codex)

MCP servers are registered in `config.toml` under `[mcp_servers.*]`. The
`config install` command writes the standard set for each layer. Registration
points used by the OS:

| Server key | Endpoint / command |
|---|---|
| `filesystem_runtime` | `agentic-os config doctor` (local MCP) |
| `notion` | `https://mcp.notion.com/mcp` |
| `genomes_brain` | `http://127.0.0.1:3155/mcp` |
| `github` | `https://api.githubcopilot.com/mcp/` |
| `context_mode` | `/Users/genome/.local/bin/context-mode` |
| `sentry`, `datadog`, `supabase`, `playwright` | layer-dependent |

Policy: **no inline secrets**. Every `mcp_servers.*` entry uses `env var names
only` for credentials.

### The `config` subcommand

`config` has three subcommands: `install`, `install-tree`, and `doctor`. There is
no `config layers` or `config list` subcommand.

#### `config install`

Writes or merges `config.toml`, `PROFILE.md`, `config/codex-profile.yml`, and
the standard prompt files for one OS layer. Dry-run is the default; always
preview before applying.

`PROFILE.md` is the tool-visible role artifact. The same short role block is
mirrored into generated `AGENTS.md` because current `codex debug prompt-input`
loads `AGENTS.md` but not arbitrary `PROFILE.md` files.

```
agentic-os config install --layer <layer> [--root <path>] [--dry-run | --apply]
                          [--backup] [--confirm-conflicts]
```

| Flag | Default | Description |
|---|---|---|
| `--layer` | required | One of the seven layer tokens above |
| `--root` | `~/agentic_os` | Directory that should receive `config.toml` |
| `--dry-run` | default | Preview changes without writing files |
| `--apply` | — | Write changes to disk |
| `--backup` | — | Back up existing `config.toml` before applying |
| `--confirm-conflicts` | — | Apply non-conflicting additions; preserve conflicting keys |

Exits **2** when apply is blocked by unresolved conflicts. Dry-run reports
conflicts without writing files. Exits **0** on success or clean dry-run.

**Real output — `config install --dry-run` on a missing layer:**

```text
# CMD: agentic-os config install --root /tmp/aos-validate/config-layer \
#       --layer agentic_os_root --dry-run
root: /private/tmp/aos-validate/config-layer
layer: agentic_os_root
dry_run: true
created:
- /private/tmp/aos-validate/config-layer
- /private/tmp/aos-validate/config-layer/config.toml
- /private/tmp/aos-validate/config-layer/AGENTS.md
- /private/tmp/aos-validate/config-layer/PROFILE.md
- /private/tmp/aos-validate/config-layer/CLAUDE.md
- /private/tmp/aos-validate/config-layer/ROUTER.md
- /private/tmp/aos-validate/config-layer/CONTEXT.md
- /private/tmp/aos-validate/config-layer/RULES.md
- /private/tmp/aos-validate/config-layer/TOOLS.md
- /private/tmp/aos-validate/config-layer/MEMORY.md
- /private/tmp/aos-validate/config-layer/config
- /private/tmp/aos-validate/config-layer/config/codex-profile.yml
updated: []
skipped: []
backups: []
conflicts: []
blocked: false
diff: '--- /private/tmp/aos-validate/config-layer/config.toml:before
  +++ /private/tmp/aos-validate/config-layer/config.toml:after
  @@ -0,0 +1,50 @@
  +# Agentic OS Codex config template
  +# Layer: agentic_os_root
  +# Local edits are preserved by the installer. Review diffs before applying.
  +
  +model = "gpt-5.4-mini"
  +model_reasoning_effort = "medium"
  +approval_policy = "on-request"
  +sandbox_mode = "workspace-write"
  +project_root_markers = [".agentic_root", ".git", "agentic-os.package.json", ...]
  +project_doc_fallback_filenames = ["PROFILE.md", "ROUTER.md", "CONTEXT.md", ...]
  +
  +[profiles.agentic_os_root]
  +model = "gpt-5.4-mini"
  +model_reasoning_effort = "medium"
  +approval_policy = "on-request"
  +sandbox_mode = "workspace-write"
  +
  +[profiles.agentic_os_root.agentic_os]
  +layer = "agentic_os_root"
  +prompt_files = ["AGENTS.md", "PROFILE.md", "CLAUDE.md", "ROUTER.md",
  +                "RULES.md", "TOOLS.md", "MEMORY.md"]
  +context_contract = "route-read-cd-repeat"
  ...
  +[mcp_servers.filesystem_runtime]
  +command = "agentic-os"
  +args = ["config", "doctor"]
  +secret_policy = "no inline secrets"
  +
  +[mcp_servers.notion]
  +url = "https://mcp.notion.com/mcp"
  +secret_policy = "no inline secrets; env var names only"
  ...'
```

After reviewing the diff, apply:

```bash
agentic-os config install --root ~/agentic_os --layer agentic_os_root --apply --backup
```

#### `config install-tree`

Discovers the routed OS tree and installs or repairs every matching layer:
installed root, domains, projects, workflows, and automations. Dry-run remains
the default.

```
agentic-os config install-tree [--root <path>] [--dry-run | --apply]
                              [--backup] [--confirm-conflicts]
```

Use this after importing or repairing an existing tree; normal scaffold commands
already create config for newly created layers.

#### `config doctor`

Validates `config.toml` OTEL and MCP contracts for a layer.

```
agentic-os config doctor --layer <layer> [--root <path>]
```

Exits **1** when `ok: false`. The most common repair case is a legacy or imported
directory where `config.toml` is missing. Exit **0** when ok.

**Real output — `config doctor` on a scaffolded root (example #37):**

```text
# CMD: agentic-os config doctor --root /tmp/aos-validate/root \
#       --layer agentic_os_root
ok: true
root: /private/tmp/aos-validate/root
layer: agentic_os_root
findings: []
```

If a layer is missing config, the remediation text will point to the same
workflow: dry-run first, review, then apply `config install` for one layer or
`config install-tree` for the routed tree.

---

## Page → invocation mapping

Every other page in this handbook links here for setup. The table below is the
authoritative mapping from doc-page task to the specific Claude command/skill and
Codex equivalent. Use it to find the right trigger for any operation without
hunting through the installed `TOOLS.md`.

| Doc page / task | Claude: command / skill | Codex: equivalent |
|---|---|---|
| Install & quickstart | install skills + `CLAUDE.md`=`@AGENTS.md` | `agentic-os config install --layer global_harness`, `config install-tree` for repairs, then `agentic-os hook sync --root ~/agentic_os --target all --apply --backup` |
| Routing & context | `/os-route`, `os-navigator` skill | `agentic-os route` / `here route`; `domain_or_lane` profile |
| Workflows | `/os-create-workflow`, `workflow-builder` skill | `agentic-os workflow check`; author from `templates/workflow/` |
| Automations | `/os-create-automation`, `automation-qualifier` skill | `agentic-os automation check/set-maturity` |
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

The full skill and command definitions live in `harness/skills/` and
`harness/commands/` (repo) and in the installed `TOOLS.md` at each layer.

---

## Guardrails & gotchas

- **`global_harness`, not `global_user_harness`.** The CLI `--layer` token for
  the global Codex config is `global_harness`. The term "global user harness" is
  used conceptually in some docs, but passing `--layer global_user_harness` to the
  CLI will exit 2 with an argparse error. Always use the token from the layer
  table above.
- **Exit codes are meaningful.** `config install` exits 0 on success or clean
  dry-run; exits 2 when apply is blocked by conflicts. `config doctor` exits 0
  when ok; exits 1 when `ok: false` (including a missing `config.toml`). Treat a
  `doctor` exit 1 as a repair signal: run `config install` for one layer or
  `config install-tree` for the routed tree.
- **Dry-run is the default.** `config install` never writes files unless you pass
  `--apply`. The diff in the dry-run output is the ground truth for what will
  change. Read it.
- **Secrets never inline.** `mcp_servers.*.env` entries must reference env var
  names only. The installer enforces `secret_policy = "no inline secrets"` in
  generated config, but it cannot prevent manual edits. Review before committing
  any `config.toml`.
- **`config.toml` is not `CLAUDE.md`.** These are parallel surfaces: `CLAUDE.md`
  (a one-line adapter) tells Claude where to find the OS contract; `config.toml`
  tells Codex the runtime posture. Neither substitutes for the other, and they are
  not merged.
- **Filesystem is the source of truth.** The installed `TOOLS.md`, `AGENTS.md`,
  `ROUTER.md`, etc. govern what both harnesses see at runtime. If the installed
  files disagree with this doc, the files win. Run `config doctor` to check.
- **`config` has `install`, `install-tree`, and `doctor`.** There is no
  `config layers`, `config list`, or `config show` subcommand. To inspect the
  current state, read the `config.toml` file directly or run `config doctor`.
- **snake_case everywhere.** Layer tokens, domain names, workflow slugs: all
  snake_case. `domain_or_lane`, not `domain-or-lane`.

---

## Related

- [01 · Install & Quickstart](01-install-and-quickstart.md) — first-run Codex and Claude setup.
- [02 · Architecture](02-architecture.md) — the five-layer runtime model this surfaces.
- [03 · Operating Model](03-operating-model.md) — the route-read-cd-repeat loop.
- [14 · Config Update & Backup](14-config-update-backup.md) — keeping `config.toml` current across OS releases.
- [16 · Health, Doctor & Validation](16-health-doctor-validation.md) — `config doctor` in the broader health picture.
- [17 · CLI Reference](17-cli-reference.md) — complete flag reference for all subcommands.
- [18 · Troubleshooting & FAQ](18-troubleshooting-and-faq.md) — exit code errors, layer confusion, MCP registration failures.
- Atlas: [`.agentic-atlas/architecture/harness-modes.md`](../.agentic-atlas/architecture/harness-modes.md) · [`.agentic-atlas/architecture/command-reference.md`](../.agentic-atlas/architecture/command-reference.md) · [`.agentic-atlas/gap-register.md`](../.agentic-atlas/gap-register.md)
