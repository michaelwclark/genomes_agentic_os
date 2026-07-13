# Codex `config.toml` Plan For Genome's Agentic OS

Source reviewed: `config.toml.md`, snapshot date 2026-05-22.

This plan translates the Codex `config.toml` reference into the configuration
shape the Agentic OS installer should generate for installed OS instances. The
goal is not to move behavior into TOML. The goal is to let Codex discover the
right operating layer, routing files, shared skills, MCP surface, and safety
posture without duplicating Claude and Codex instructions.

## Operating Decision

Codex config should select runtime posture. Markdown files should carry durable
behavior.

| Concern | Source Of Truth | Codex Surface | Claude Surface |
| --- | --- | --- | --- |
| Shared operating behavior | `AGENTS.md` | loaded as harness-neutral entrypoint | included by `CLAUDE.md` |
| Routing and domain mapping | `ROUTER.md` | fallback doc plus route-read-cd-repeat instruction | referenced through `AGENTS.md` |
| Local run context | `CONTEXT.md` | fallback doc | referenced through `AGENTS.md` |
| Local rules and approvals | `RULES.md` | fallback doc, strictest-rule-wins | referenced through `AGENTS.md` |
| Layer tool registry | `TOOLS.md` | fallback doc plus generated skill/MCP paths | referenced through `AGENTS.md` |
| Memory policy and handoff | `MEMORY.md` | fallback doc plus memory MCP | referenced by `CLAUDE.md` |
| High-output context handling | `context-mode` package config | `mcp_servers.context_mode` | referenced from shared adapter |
| Durable unified memory | Unified Memory MCP package config | `mcp_servers.unified_memory` | referenced from shared adapter |
| Harness-specific entry point | generated from shared templates | `AGENTS.md` | `CLAUDE.md` |
| Runtime posture | generated config templates | `.codex/config.toml` | Claude settings where supported |

Do not maintain separate long-form `AGENTS.md` and `CLAUDE.md` bodies. Generate
`CLAUDE.md` as an include adapter for `AGENTS.md`. See
`spec/harness-context-contract.md` for the shared markdown contract.

## Config Layers To Generate

| Layer | Path | Purpose | Should installer write? |
| --- | --- | --- | --- |
| User harness | `~/.codex/config.toml` | personal defaults, global MCPs, global profiles, trusted roots | only with explicit user approval |
| Installed OS root | `~/agentic_os/.codex/config.toml` | default OS posture, fallback docs, shared skills, subagents, local hooks | yes |
| Customer OS root | `<customer_os>/.codex/config.toml` | customer boundary, customer-approved tools, stricter network/data posture | yes for customer installs |
| Domain or lane | `<os_root>/<domain_or_lane>/.codex/config.toml` | domain routing, narrower context, validation hooks | optional generated overlay |
| Workflow or task | `<os_root>/<workflow>/.codex/config.toml` | temporary workflow posture and validation rules | optional generated overlay |
| Product/client repo | `<repo>/.codex/config.toml` | repo-local profile only when trusted | only when explicitly attached |

## OS Package Manifest

Yes: the OS should have a `package.json`-style manifest at the OS layer. It
should not replace `config.toml`. It should define what the OS installs,
configures, verifies, and wires into each harness. The installer should resolve
that manifest into concrete files such as `.codex/config.toml`, `AGENTS.md`,
`CLAUDE.md`, MCP server entries, skill installs, command wrappers, hooks, and
doctor checks.

Recommended files:

| File | Purpose |
| --- | --- |
| `agentic-os.package.json` | Source manifest for OS packages, harness targets, MCP servers, skills, commands, hooks, and required checks. |
| `agentic-os.lock.json` | Resolved package versions, command paths, schema version, and install timestamps. |
| `agentic-os.local.json` | Host-local overrides ignored by Git; command paths, disabled optional tools, and local package paths. |
| `schemas/os-package.schema.json` | JSON Schema for the manifest. |

Use JSON for this manifest because it is schema-friendly, lockfile-friendly, and
familiar to package tooling. Keep existing YAML files for customer/domain data
where human editing is more important than lock-style resolution.

Package categories:

| Category | Examples | Installed Into | Config Output |
| --- | --- | --- | --- |
| MCP servers | context-mode, Unified Memory, Notion, GitHub, Atlassian | host-local runtime or OS-managed bin dir | `[mcp_servers.*]` plus per-tool approval |
| Shared skills | build-runner, os-doctor, context-pack-builder | `shared_factory/05-knowledge/skills/` and harness skill dirs | `[skills].config` path selectors |
| Harness adapters | Codex, Claude | `AGENTS.md`, `CLAUDE.md`, harness config dirs | fallback docs and generated entrypoints |
| CLI commands | OS doctor, installer, run logger, package resolver | OS-managed bin dir or project scripts | hooks and doctor checks |
| Connectors/apps | Notion, Slack, Gmail, browser, Chrome | Codex app connector surface | `[apps]`, `[plugins]`, `[tool_suggest]` where supported |
| Runtime packages | Node, Python, uv, npm package deps, local binaries | host package manager or OS venv/tool cache | lockfile and doctor checks, not TOML literals |
| Context sources | docs indexes, source maps, command manuals | context-mode index/cache | context-mode package config and refresh hooks |

Example manifest shape:

```json
{
  "schema": "https://genome.local/schemas/os-package.schema.json",
  "name": "genomes-agentic-os",
  "version": "0.1.0",
  "harnessTargets": ["codex", "claude"],
  "codex": {
    "minVersion": "0.131.0-alpha.9",
    "configTemplate": "templates/agent-config/codex-root.config.toml",
    "profilesTemplate": "templates/agent-config/codex-profiles.toml"
  },
  "claude": {
    "entrypointTemplate": "templates/agent-config/CLAUDE.md"
  },
  "mcpServers": {
    "context_mode": {
      "package": "context-mode",
      "required": true,
      "command": "context-mode",
      "args": ["mcp"],
      "provides": [
        "ctx_batch_execute",
        "ctx_search",
        "ctx_execute_file",
        "ctx_fetch_and_index",
        "ctx_stats",
        "ctx_doctor"
      ]
    },
    "unified_memory": {
      "package": "unified-memory-mcp",
      "required": true,
      "command": "losmon-memory-mcp",
      "provides": [
        "memory_read",
        "memory_write",
        "memory_link",
        "memory_forget"
      ]
    }
  },
  "skills": [
    "build-runner",
    "context-pack-builder",
    "os-doctor",
    "run-logger",
    "workflow-builder"
  ],
  "doctorChecks": [
    "codex-version",
    "context-mode-mcp",
    "unified-memory-mcp",
    "shared-skills-installed",
    "harness-adapters-in-sync"
  ]
}
```

Installer flow:

1. Read `agentic-os.package.json`.
2. Resolve local command paths and versions.
3. Write or update generated harness files.
4. Write `.codex/config.toml` and host-local MCP fragments.
5. Install shared skills and commands.
6. Write `agentic-os.lock.json`.
7. Run doctor checks before declaring the OS installed.

## Baseline Installed OS Root Config

Write this at the installed OS root:

```toml
# ~/agentic_os/.codex/config.toml

profile = "agentic_os_root"

project_doc_fallback_filenames = [
  "AGENTS.md",
  "ROUTER.md",
  "CONTEXT.md",
  "RULES.md",
  "TOOLS.md",
  "MEMORY.md",
]
project_doc_max_bytes = 65536
project_root_markers = [".agentic_root", ".git", "pyproject.toml", "package.json", "agentic-os.package.json", "agentic_os.yml"]

model_reasoning_effort = "medium"
model_verbosity = "medium"
sandbox_mode = "workspace-write"
approval_policy = "on-request"
web_search = "cached"

[agents]
max_threads = 4
max_depth = 1
job_max_runtime_seconds = 1800
interrupt_message = true

[agents.builder]
description = "Build Agentic OS cards, features, templates, schemas, and docs from scoped plans."
config_file = ".codex/roles/builder.config.toml"
nickname_candidates = ["builder", "implementer"]

[agents.reviewer]
description = "Read-only reviewer focused on blockers, regressions, missing validation, and OS contract drift."
config_file = ".codex/roles/reviewer.config.toml"
nickname_candidates = ["reviewer", "qa"]

[agents.context_mapper]
description = "Read-only mapper for routing, domain context, source maps, and cross-harness duplication checks."
config_file = ".codex/roles/context-mapper.config.toml"
nickname_candidates = ["mapper", "researcher"]

[skills]
include_instructions = true
config = [
  { path = "~/agentic_os/shared_factory/05-knowledge/skills/build-runner/SKILL.md", enabled = true },
  { path = "~/agentic_os/shared_factory/05-knowledge/skills/os-doctor/SKILL.md", enabled = true },
  { path = "~/agentic_os/shared_factory/05-knowledge/skills/context-pack-builder/SKILL.md", enabled = true },
  { path = "~/agentic_os/shared_factory/05-knowledge/skills/run-logger/SKILL.md", enabled = true },
  { path = "~/agentic_os/shared_factory/05-knowledge/skills/workflow-builder/SKILL.md", enabled = true },
]

[skills.bundled]
enabled = true

[shell_environment_policy]
inherit = "core"
include_only = [
  "^PATH$",
  "^HOME$",
  "^USER$",
  "^SHELL$",
  "^TMPDIR$",
  "^GENOMES_",
  "^NOTION_",
  "^GITHUB_",
  "^ATLASSIAN_",
]
exclude = [
  ".*TOKEN.*",
  ".*SECRET.*",
  ".*PASSWORD.*",
]
experimental_use_profile = false

[history]
persistence = "save-all"

[memories]
use_memories = true
generate_memories = true

[otel]
exporter = "none"
trace_exporter = "none"
metrics_exporter = "none"
log_user_prompt = false
environment = "agentic_os"
```

Notes:

- Keep secret values out of TOML. Use env var names only.
- Do not set literal MCP tokens, HTTP headers, or Notion credentials in shared
  config.
- `web_search = "cached"` is the root default. Domain or research overlays can
  use `live` when current external facts are part of the work.
- The shell env allow-list permits known OS integration env names while the
  explicit exclude still blocks obvious secret-shaped names from shell context.
  MCP entries can forward exact env var names when a server needs them.

## Role Config Files

Generate these role configs next to the root config:

```toml
# ~/agentic_os/.codex/roles/builder.config.toml
model_reasoning_effort = "medium"
sandbox_mode = "workspace-write"
approval_policy = "on-request"
web_search = "cached"
```

```toml
# ~/agentic_os/.codex/roles/reviewer.config.toml
model_reasoning_effort = "high"
sandbox_mode = "read-only"
approval_policy = "on-request"
web_search = "cached"
```

```toml
# ~/agentic_os/.codex/roles/context-mapper.config.toml
model_reasoning_effort = "medium"
sandbox_mode = "read-only"
approval_policy = "on-request"
web_search = "live"
```

## Profile Set

Install a shared profile set in the user config or in a generated profile
fragment that can be imported or copied into `~/.codex/config.toml`.

```toml
[profiles.global_user_harness]
model_reasoning_effort = "medium"
sandbox_mode = "workspace-write"
approval_policy = "on-request"
web_search = "cached"

[profiles.agentic_os_root]
model_reasoning_effort = "medium"
sandbox_mode = "workspace-write"
approval_policy = "on-request"
web_search = "cached"

[profiles.customer_os_root]
model_reasoning_effort = "medium"
sandbox_mode = "workspace-write"
approval_policy = "on-request"
web_search = "cached"

[profiles.domain_or_lane]
model_reasoning_effort = "medium"
sandbox_mode = "workspace-write"
approval_policy = "on-request"
web_search = "cached"

[profiles.workflow_or_task]
model_reasoning_effort = "medium"
sandbox_mode = "workspace-write"
approval_policy = "on-request"
web_search = "cached"

[profiles.review]
model_reasoning_effort = "high"
sandbox_mode = "read-only"
approval_policy = "on-request"
web_search = "cached"

[profiles.research]
model_reasoning_effort = "medium"
sandbox_mode = "read-only"
approval_policy = "on-request"
web_search = "live"
```

Do not hardcode `model` globally in generated OS config unless the installer is
explicitly asked to pin a model. The user-level harness should own personal
model preference. OS roots should mostly set posture, not provider identity.

## Domain Or Lane Overlay

Use this when a subdirectory owns a domain, room, lane, or client workstream:

```toml
# <os_root>/<domain_or_lane>/.codex/config.toml

profile = "domain_or_lane"

project_doc_fallback_filenames = [
  "ROUTER.md",
  "CONTEXT.md",
  "MEMORY.md",
]
project_doc_max_bytes = 65536

[agents]
max_threads = 3
max_depth = 1
job_max_runtime_seconds = 1200
interrupt_message = true
```

Domain overlays should narrow context and validation. They should not redefine
global MCP credentials, model providers, auth settings, or long behavior text.

## Workflow Or Task Overlay

Use this for generated workflow folders such as build runs, audits, and
customer-deliverable packages:

```toml
# <os_root>/<workflow>/.codex/config.toml

profile = "workflow_or_task"

project_doc_fallback_filenames = [
  "CONTEXT.md",
  "MEMORY.md",
]
project_doc_max_bytes = 32768

[agents]
max_threads = 4
max_depth = 1
job_max_runtime_seconds = 1800
interrupt_message = true
```

Workflow overlays should be small and disposable, but they may need real
orchestration capacity. Use `max_threads = 4` as the default for workflows that
run `orchestrate`, build-runner, review fan-out, multi-repo validation, or
parallel research. Use `max_threads = 2` only for tightly coupled single-surface
tasks where extra agents are likely to collide. They can tune concurrency and
context size, but should not create new source-of-truth rules.

## Customer OS Root Overlay

Use this for customer-specific installed OS instances:

```toml
# <customer_os>/.codex/config.toml

profile = "customer_os_root"

project_doc_fallback_filenames = [
  "AGENTS.md",
  "ROUTER.md",
  "CONTEXT.md",
  "RULES.md",
  "TOOLS.md",
  "MEMORY.md",
  "customer.yml",
]
project_doc_max_bytes = 65536

sandbox_mode = "workspace-write"
approval_policy = "on-request"
web_search = "cached"

[agents]
max_threads = 3
max_depth = 1
job_max_runtime_seconds = 1800
interrupt_message = true

[otel]
exporter = "none"
trace_exporter = "none"
metrics_exporter = "none"
log_user_prompt = false
environment = "customer_os"
```

Customer overlays should enforce customer data boundaries through `ROUTER.md`,
`CONTEXT.md`, customer profile files, and allowed MCP servers. Do not put
customer secrets in TOML.

## MCP Server Plan

MCP server entries belong primarily in user-level config because they often
depend on host-specific commands and credentials. Installed OS roots may include
required local servers only when the command path is installed by the OS.

Context-mode and Unified Memory are first-class OS packages. They should be
declared in `agentic-os.package.json`, resolved into host-local command paths,
then emitted into Codex config. `config.toml` is the resolved harness config;
the manifest is the install contract.

Recommended shape:

```toml
# ~/.codex/config.toml or host-local generated fragment

[mcp_servers.context_mode]
command = "context-mode"
args = ["mcp"]
enabled = true
required = true
startup_timeout_sec = 10
tool_timeout_sec = 60
supports_parallel_tool_calls = true

[mcp_servers.unified_memory]
command = "losmon-memory-mcp"
enabled = true
required = true
startup_timeout_sec = 10
tool_timeout_sec = 60
supports_parallel_tool_calls = true

[mcp_servers.notion]
command = "notion-mcp"
enabled = true
required = false
env_vars = ["GENOMES_NOTION_PAT", "GENOMES_NOTION_CONNECTOR"]
startup_timeout_sec = 10
tool_timeout_sec = 60
```

Rules:

- Use `env_vars` or `bearer_token_env_var`, not literal `env` values, for
  secrets.
- Set `required = true` only for OS core packages such as context-mode and
  Unified Memory when the installer has verified their command paths.
- Set `required = false` for optional integrations so Codex still starts when a
  connector is unauthorized.
- Use per-tool approval modes for write-heavy MCP tools.
- Keep Genome's Notion workspace guardrails in `AGENTS.md`/`RULES.md`, not only
  in MCP config.

## Section-By-Section Decisions From `config.toml.md`

### Load Order

Use load order as the core installer model:

1. User harness config owns personal defaults and global services.
2. Installed OS root config owns OS posture.
3. Customer/domain/workflow configs narrow posture as the user moves deeper.

Do not rely on a subdirectory config to weaken a customer boundary or security
posture.

### Common Value Sets

Use a small default value set:

- `sandbox_mode = "workspace-write"` for build-capable roots.
- `sandbox_mode = "read-only"` for reviewer and mapper roles.
- `approval_policy = "on-request"` by default.
- `web_search = "cached"` by default, `"live"` for explicit research lanes.
- `model_reasoning_effort = "medium"` for normal work, `"high"` for review.

Avoid `danger-full-access` and `approval_policy = "never"` in generated shared
config.

### Recommended Personal Baseline

Treat the reference baseline as user-level guidance, not something the source
package should silently overwrite. The installer may offer to write or merge it
into `~/.codex/config.toml`, but the installed OS root should use the narrower
root baseline above.

### Top-Level Keys

Set only the keys the OS needs:

- `profile`
- `project_doc_fallback_filenames`
- `project_doc_max_bytes`
- `project_root_markers`
- model reasoning and verbosity, without provider pinning
- `sandbox_mode`
- `approval_policy`
- `web_search`
- `[agents]`
- `[skills]`
- `[shell_environment_policy]`
- `[history]`
- `[memories]`
- `[otel]`

Leave managed, experimental, desktop, auth, realtime, audio, Windows, and
debugging keys alone unless an installer flow explicitly enables them.

### Project Instruction Discovery

This is the most important section for reducing duplication between Claude and
Codex.

Codex should discover:

- `AGENTS.md`: shared harness-neutral entrypoint and route bootstrap.
- `ROUTER.md`: routing, mapping, domain/source rules.
- `CONTEXT.md`: local operating context.
- `RULES.md`: safety, approval, and local operating constraints.
- `TOOLS.md`: visible skills, commands, MCPs, plugins, and wrappers.
- `MEMORY.md`: local memory policy and handoff.

Claude should read the same universal files through `CLAUDE.md`. Generate
`CLAUDE.md` as the adapter that includes `AGENTS.md` instead of duplicating
instructions.

Do not include `CLAUDE.md` in Codex fallback docs by default. It is a harness
adapter, not shared behavior.

### Agents

Use subagents as mapped operating roles, not generic parallelism.

Root defaults:

- `max_threads = 4`
- `max_depth = 1`
- `job_max_runtime_seconds = 1800`
- `interrupt_message = true`

Workflow/project orchestration defaults:

- `max_threads = 4` for folders expected to run `orchestrate`, build-runner,
  PR review, multi-repo validation, or independent research lanes.
- `max_threads = 2` only for narrow task folders with a small shared edit
  surface.
- `max_depth = 1` remains the default. More breadth is safer than nested
  delegation unless the workflow explicitly needs nested agents.

Role defaults:

- `builder`: write-capable, scoped to OS source and installed OS artifacts.
- `reviewer`: read-only, high reasoning, blocker-focused.
- `context_mapper`: read-only, routing/source-map focused, can use live web.

Raise `max_threads` before increasing depth. Deeply nested agents are the risky
part; 4+ sibling agents in an orchestrated project folder is an expected use
case.

### Skills

Enable bundled skills and explicitly enable installed Agentic OS shared skills
by path. This avoids name collisions and keeps Claude/Codex skill installation
aligned with `OS_SHARED_SKILLS_*` settings in `CONFIG.md`.

`config.toml` should not define skill metadata. Skill metadata belongs in each
`SKILL.md` and the shared skill registry.

### Models And Providers

Keep provider identity in user-level config. The OS can define profile posture
and reasoning effort, but should not silently change the user's provider.

Local model providers, model catalog files, and API base URLs are host-level
concerns. Use generated host-local fragments if needed.

### Approval, Permissions, And Sandbox

Generated configs should default to `workspace-write` and `on-request`.

Use `read-only` for reviewer/mapping profiles. Use granular approval only after
there is a concrete policy to encode. Do not generate `danger-full-access` in
shared templates.

Customer OS roots can further restrict permission through customer profile and
router files, and through narrower MCP allow-lists.

### Shell Environment

Use `inherit = "core"` and a small `include_only` list. Permit OS integration
env prefixes, but do not set secret values in TOML.

If an MCP server needs a token, configure that server with `env_vars` or
`bearer_token_env_var`.

### MCP Servers

Use MCP config to make Codex aware of OS services such as context-mode, durable
memory, Notion, GitHub, Atlassian, and other approved control-plane tools.

Context-mode should be installed as the default high-output reconnaissance
surface. Agent instructions can require it for large command output, while
`config.toml` makes the MCP server available and the package manifest defines
how it is installed and verified.

Unified Memory should be installed as the durable memory surface backed by
MemPalace and CoCoIndex. Agent instructions should require `memory_read` before
non-trivial reconnaissance and `memory_write` after substantive work; the MCP
config makes the tools available, and the package manifest makes the dependency
explicit.

Default location:

- user-level config for host-specific MCP servers and secrets.
- OS root config only for local servers installed by the OS.
- customer root config for customer-approved tools and deny-lists.

All Notion writes must still obey the Genome's Notion workspace guardrail from
the shared instructions.

### Apps, Connectors, Plugins, And Tool Suggestions

Use this section lightly.

Installer may suggest discoverable plugins/connectors that match OS features,
but should not assume they are installed or authenticated. Installed app policy
should be conservative for destructive/open-world tools.

### Built-In Tools And Web Search

Use `web_search = "cached"` for normal OS work. Use `live` for research,
standards, product docs, current API behavior, or recommendation workflows.

If a lane has a known allowed research boundary, set
`[tools.web_search].allowed_domains` in that lane overlay.

### Profiles

Profiles are the right place to encode OS layer posture:

- `global_user_harness`
- `agentic_os_root`
- `customer_os_root`
- `domain_or_lane`
- `workflow_or_task`
- `review`
- `research`

Profiles should not duplicate long behavior. They should select model posture,
sandbox posture, approval posture, tool posture, and optional TUI posture.

### TUI And Notifications

Leave terminal preferences in user config. Do not force OS-level notification
or TUI behavior from installed OS roots.

### History And Memories

Keep history enabled so OS work can be audited and summarized. Codex built-in
memory can be enabled, but the Agentic OS memory substrate remains the durable
source. `MEMORY.md` is a local handoff and policy file, not a replacement for
the memory plane.

### Hooks

Hooks are powerful but version-sensitive. Use them only for small wrappers that
call OS-owned commands.

Good candidates:

- `SessionStart`: lightweight OS context check.
- `Stop`: run-log closeout candidate.
- `PostCompact`: memory handoff candidate.
- `PreToolUse` or `PostToolUse`: only for audited, non-invasive logging.

Avoid heavy hooks that modify worktrees or call external APIs without explicit
approval.

### Telemetry, Auth, And Notices

Keep auth and notices user-managed. Set OTEL exporters to `none` and
`log_user_prompt = false` in generated OS templates unless the user explicitly
enables telemetry.

### Marketplaces

Treat marketplace entries as Codex-managed. Do not generate marketplace state
in OS root config. The OS can install skills/plugins through explicit installer
flows.

### Realtime, Audio, Windows, Debug, And Compatibility

Do not set these in default OS templates. Add per-host or per-experiment
fragments only when an explicit workflow needs them.

### Feature Flags

Do not generate broad `features.*` defaults. Feature flags are unstable and
version-sensitive. If an OS feature needs a Codex feature flag, gate it behind a
doctor check that verifies the local Codex version.

### Practical Rules

Installer rules:

- Put durable behavior in markdown, not TOML.
- Generate config only for trusted roots.
- Keep secrets out of shared config.
- Prefer profile overlays over duplicated instructions.
- Prefer subagent breadth over nested subagents.
- Keep model provider and auth decisions user-level unless explicitly pinned.

## Installer Work Items

1. Add `agentic-os.package.json`, `agentic-os.lock.json`, and
   `schemas/os-package.schema.json`.
2. Add package entries for context-mode and Unified Memory MCP, including
   command resolution and doctor checks.
3. Add templates for root, customer, domain, workflow, and role configs.
4. Add a generator that writes `AGENTS.md`, `ROUTER.md`, `CONTEXT.md`,
   `RULES.md`, and `TOOLS.md`, with `CLAUDE.md` as an include adapter.
5. Add an install-time merge flow for `~/.codex/config.toml` that presents a
   diff before writing user-level config.
6. Add a doctor check that reports the resolved Codex version, profile, fallback
   docs, shared skills, context-mode status, Unified Memory status, and MCP
   server availability.
7. Add a duplication check that fails when `CLAUDE.md` contains long-form
   behavior instead of the `AGENTS.md` include adapter.
8. Add a safety check that rejects generated TOML containing literal token-like
   values.
