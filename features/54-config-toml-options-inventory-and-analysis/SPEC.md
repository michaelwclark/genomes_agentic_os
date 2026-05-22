# Spec

Build the authoritative Codex `config.toml` research base for Agentic OS.

Acceptance criteria:

- Document supported options, defaults, examples, and unsupported or unknown
  areas.
- Map options to Agentic OS layers: global user, OS root, customer root,
  domain/lane, and workflow/task.
- Call out prompt-file stitching behavior for `AGENTS.md`, `CLAUDE.md`,
  `BRAIN.md`, `ROUTER.md`, `CONTEXT.md`, and related conventions.
- Identify security-sensitive options, MCP hooks, OTEL settings, sandbox
  behavior, and desktop-vs-CLI differences.
