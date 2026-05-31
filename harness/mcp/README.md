# Harness MCP

Reserved for local MCP server specs, wrappers, and bundles owned by the installed
Agentic OS harness.

Required runtime MCP integrations are configured in `harness/config.toml` and
listed in `harness/registries/mcp-servers.yml`:

- `context_mode`: large-output and session-memory analysis via
  `/Users/genome/.local/bin/context-mode`.
- `genomes_brain`: the custom losmon-memory MCP at `http://127.0.0.1:3155/mcp`,
  backed by MemPalace and CoCoIndex.

This folder can be empty when those servers are external binaries or services.
Put files here only for MCP assets that the Agentic OS package itself owns.
