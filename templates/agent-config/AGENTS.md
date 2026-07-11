# Agent Entry Point

This file is the harness-neutral entrypoint for this Agentic OS layer.

## Startup Loop

1. Read `ROUTER.md`, `CONTEXT.md`, `RULES.md`, and `TOOLS.md` in this directory.
2. Classify the request against `ROUTER.md`.
3. If the router points to a narrower directory, change to that directory and repeat this loop.
4. Act only after loading the final routed layer.
5. Record routing gaps, missing tools, and durable next actions in the run log or closeout artifact.

## Adaptive Observe Receipt

When the installed adaptive observation config is enabled and `CODEX_THREAD_ID`
is available, run `agentic-os adaptive-routing observe --root <root> "<original
user request>"` once per substantive user task before its first action. This is local,
non-executing, text-free telemetry; duplicate turn correlations are no-ops.

## Precedence

- Active user instructions win.
- The final routed layer is the working context.
- The strictest safety, approval, privacy, and destructive-action rule wins across all loaded `RULES.md` files.
- Use `TOOLS.md` as the visible tool contract before assuming a skill, MCP server, command, plugin, wrapper, or library is available.

Read `MEMORY.md` when present before writing durable memory.
