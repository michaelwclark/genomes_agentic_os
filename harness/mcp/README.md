# Harness MCP

Reserved for local MCP server specs, wrappers, and bundles owned by the installed
Agentic OS harness.

Required runtime MCP integrations are configured in `harness/config.toml` and
listed in `harness/registries/mcp-servers.yml`:

- `context_mode`: large-output and session-memory analysis via
  `/Users/genome/.local/bin/context-mode`.
- `genomes_brain`: Genome's Brain, backed by MemPalace and CoCoIndex. The
  managed local HTTP default is `http://127.0.0.1:3166/mcp`. A configured custom
  URL or native SSH-stdio transport takes precedence and must be preserved.

Changing a generated default does not migrate an existing additive installation
or prove service health. Use the guarded
[memory endpoint migration runbook](../../docs/development/memory-endpoint-migration.md)
after separately qualifying the current service on the intended host.

This folder can be empty when those servers are external binaries or services.
Put files here only for MCP assets that the Agentic OS package itself owns.
