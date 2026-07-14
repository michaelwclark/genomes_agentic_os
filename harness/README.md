# Harness

`harness/` is the source blueprint for the harness-facing and shared-runtime
parts of an Agentic OS installation. It stays outside the Python import package
because most of its contents are copied, registered, or executed as files rather
than imported as Python modules.

During install or update, `genomes_agentic_os.scaffold` projects these assets
into the installed OS. The installed `harness/shared_factory/` then becomes the
cross-domain runtime room: it owns shared programs, control-plane configuration,
knowledge, and run evidence. Source files here are defaults; live mutable state
belongs in the installed OS.

| Folder | Purpose |
| --- | --- |
| [`bin/`](bin/) | Executable helpers and registration utilities that complement the Python CLI. |
| [`commands/`](commands/) | Human- and harness-readable command contracts; see the complete command table. |
| `hooks/` | Shared lifecycle hooks installed for Claude and Codex surfaces. |
| `libraries/` | Documentation and seed material for registered OS libraries. |
| `mcp/` | MCP server seed material and installation guidance. |
| `plugins/` | Plugin registry guidance and source defaults. |
| [`registries/`](registries/) | Version-controlled capability, routing, alert, host, and intake registries. |
| `rules/` | Reusable authoring and operating rules. |
| [`shared_factory/`](shared_factory/) | Source-owned shared programs and assets that become the installed cross-domain factory. |
| `skills/` | Canonical reusable skill definitions shared by Claude and Codex. |

The Python code that installs and validates these assets lives under
[`src/genomes_agentic_os/`](../src/genomes_agentic_os/).
