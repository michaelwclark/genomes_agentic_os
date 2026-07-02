---
name: orchestrate
description: Coordinate Agentic OS subagents, verification, and integration. Use when the user asks for /orchestrate, delegation, fan-out, parallel agents, implementation planning, or verified merge/integration work.
---

# Orchestrate

Use this skill for Agentic OS work that needs decomposition, subagents,
verification, and integration.

## Procedure

1. Route through the active Agentic OS layer before planning.
2. Read the local `AGENTS.md`, `ROUTER.md`, `CONTEXT.md`, `RULES.md`, and
   `TOOLS.md` files for the final routed layer.
3. Define concrete bounded work units before spawning agents.
4. Give subagents exact files, constraints, expected outputs, and validation
   requirements.
5. Keep the primary agent responsible for synthesis, final verification, and
   user-facing closeout.
6. Record durable outcomes in the relevant worklog, run log, registry, or next
   action surface when OS state changes.

## Boundaries

For LOS coding, testing, PR checks, or CI lifecycle work, prefer
`quiet-workon-orchestrate` after the final LOS layer is loaded.
