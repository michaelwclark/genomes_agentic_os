# Capability Registry Spec

Genome's Agentic OS should make its installed capabilities visible at the top
level of the OS root. The installed OS should not rely on hidden harness folders
or operator memory to explain what is available.

This spec borrows the architectural idea from registry-heavy systems like
LedgerLine: keep feature/runtime code behind ports and adapters, and use
registries as the explicit composition surface. For Agentic OS, the same idea
means commands, skills, MCP servers, hooks, plugins, libraries, and rules should
all register themselves before they are considered installed.

## Goals

- Make every installed capability discoverable from the OS root.
- Keep Codex, Claude, and future harnesses aligned through one capability
  registry model.
- Separate source packages from installed runtime state.
- Give agents a predictable place to inspect available commands, skills, MCPs,
  libraries, hooks, and rules.
- Generate harness-specific dot-folder config from visible OS registry state.

## Installed Root Shape

```text
~/agentic_os/
  .agentic_root
  INVENTORY.md
  agentic-os.package.json
  agentic-os.lock.json
  agentic-os.local.json

  bin/
  commands/
  skills/
  mcp/
  plugins/
  libraries/
  hooks/
  rules/
  registries/

  projects -> ~/projects
  shared_factory/
  personal/
  clarks_consulting/
  los/
  archive/
```

Dot folders such as `.codex/` and `.claude/` may exist, but they are generated
adapters. They are not the primary source of truth.

## Registry Files

| Registry | Path | Purpose |
| --- | --- | --- |
| Capability registry | `registries/capabilities.yml` | Unified list of installed capabilities and their status. |
| Command registry | `registries/commands.yml` | Slash commands, CLI wrappers, aliases, and harness targets. |
| Skill registry | `registries/skills.yml` | Shared skills, install paths, harness targets, and update policy. |
| MCP registry | `registries/mcp.yml` | MCP servers, commands, env var requirements, exposed tools, and approval modes. |
| Plugin registry | `registries/plugins.yml` | Codex/Claude plugins and connector bundles. |
| Library registry | `registries/libraries.yml` | Local libraries and third-party systems such as MemPalace, CoCoIndex, and context-mode. |
| Hook registry | `registries/hooks.yml` | Lifecycle hooks, trigger events, allowed side effects, and rollback behavior. |
| Rule registry | `registries/rules.yml` | Shared rules consumed by harness entrypoints. |

`INVENTORY.md` is generated from these registries and should be optimized for
human and agent scanning.

## Capability Record

Every registry item should normalize to a capability record:

```yaml
id: context-mode
type: mcp
display_name: Context Mode
status: installed
visibility: operator
customer_safe: false
source:
  package: context-mode
  registry: registries/mcp.yml
install:
  target: mcp/context-mode/
  command: context-mode
  args: ["mcp"]
harness_targets:
  codex:
    config_output: .codex/config.toml
    mcp_server: context_mode
  claude:
    docs_output: CLAUDE.md
provides:
  tools:
    - ctx_batch_execute
    - ctx_search
    - ctx_execute_file
requires:
  env: []
  commands:
    - context-mode
doctor:
  checks:
    - command-resolves
    - mcp-starts
update:
  policy: additive_non_destructive
```

## Capability Types

### Commands

Commands are visible entrypoints, not buried prompt snippets.

Initial command candidates:

- `/make-skill`
- `/make-domain`
- `/make-automation`
- `/make-workflow`
- `/orchestrate`
- `/os-doctor`
- `/os-update`
- `/os-inventory`

Each command must declare:

- description
- input shape
- output artifact
- allowed harnesses
- required skills or libraries
- customer-safe status

### Skills

Skills live in `skills/<skill-id>/SKILL.md` and register in
`registries/skills.yml`.

The registry must track:

- canonical source path
- installed path
- harness targets
- dependencies
- whether the skill is operator-only or customer-safe
- update policy

### MCP Servers

MCP server definitions live in `mcp/<server-id>/mcp.yml` and register in
`registries/mcp.yml`.

The initial first-class MCPs are:

- `context-mode`
- Unified Memory MCP backed by MemPalace and CoCoIndex
- Notion, with Genome's Notion workspace verification
- GitHub
- Atlassian

MCP records must never contain literal secrets. They may name env vars.

### Libraries

Libraries are support systems used by commands, skills, MCPs, or hooks.

Initial library records:

- `mempalace`
- `cocoindex`
- `context-mode`
- local Python package for `genomes_agentic_os`
- Node/Python runtime dependencies needed by installed commands

Libraries should declare whether they are embedded, linked, globally installed,
or externally managed.

### Hooks And Rules

Hooks should be explicit and auditable. A hook record must declare:

- trigger event
- command invoked
- allowed filesystem roots
- external network behavior
- timeout
- rollback or failure behavior
- whether it can run for customer OS installs

Rules should be visible in `rules/`, with `AGENTS.md` and `CLAUDE.md` acting as
adapters that load or summarize those shared rules.

## Install Contract

Installer flow:

1. Read `agentic-os.package.json`.
2. Install or link visible package folders.
3. Write registry files.
4. Generate `INVENTORY.md`.
5. Generate harness adapters such as `.codex/config.toml`, `AGENTS.md`, and
   `CLAUDE.md`.
6. Run doctor checks.
7. Write `agentic-os.lock.json`.

The installer should fail if a declared capability cannot be represented in the
registries.

## Doctor Checks

`agentic-os doctor` should report:

- missing visible registry files
- installed capabilities missing from `INVENTORY.md`
- registry entries whose command paths do not resolve
- MCP entries that cannot start
- skills not copied or linked into target harnesses
- hooks without explicit allowed side effects
- customer OS installs with operator-only capabilities enabled

## Open Decisions

- Whether `shared_factory/05-knowledge/skills/` should remain as a compatibility
  mirror or become generated entirely from top-level `skills/`.
- Whether commands should be represented as Markdown prompts, executable shims,
  or both.
- Whether plugin packages should follow Codex plugin layout directly or use an
  OS-native wrapper that can emit Codex/Claude-specific adapters.

