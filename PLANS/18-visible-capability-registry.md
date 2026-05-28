# 18 - Visible Capability Registry

## Intent

Make the installed Agentic OS self-describing. Operators and agents should be
able to inspect the OS root and understand what commands, skills, MCP servers,
libraries, hooks, plugins, and rules make up the system.

## Source Spec

- `spec/capability-registry.md`

## Build Order

1. Add top-level installed directories: `bin/`, `commands/`, `skills/`, `mcp/`,
   `plugins/`, `libraries/`, `hooks/`, `rules/`, and `registries/`.
2. Add registry schemas for capabilities, commands, MCP servers, libraries,
   hooks, plugins, and rules.
3. Add `INVENTORY.md` generation from registries.
4. Move or mirror existing shared skills and commands into visible top-level
   installed paths.
5. Generate Codex and Claude adapters from registry state.
6. Add doctor checks for missing, stale, or hidden capabilities.

## Acceptance Criteria

- Fresh installs include the visible directories and registry files.
- `INVENTORY.md` lists installed capabilities by type.
- Context-mode and Unified Memory appear in the MCP/library registries.
- `/make-skill`, `/make-domain`, `/make-automation`, `/make-workflow`, and
  `/orchestrate` appear in the command registry once installed.
- Dot-folder harness config is generated from visible registry state.
- Validation fails when a declared capability is missing from its registry.

## Notes

The registry pattern should follow the LedgerLine-style idea of explicit
composition through registries, while adapting it to an OS/harness runtime
instead of a web service.

