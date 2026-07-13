---
name: cockpit
description: Build or open the local Agentic OS engineering cockpit for conversations, work, reviews, reports, sources, hosts, automations, and hygiene.
---

# Agentic OS Cockpit

Use when the user asks for the OS cockpit, a unified engineering-lead view, a
conversation/work/report inventory, or host/source/cleanup visibility.

## Procedure

1. Route through the installed Agentic OS before acting.
2. Prefer `agentic-os cockpit open --root /Users/genome/agentic_os` for the
   normal local experience.
3. Use `cockpit build` when an artifact should be refreshed without opening it.
4. Use `cockpit snapshot --json` for machine-readable inspection.
5. Report the generated artifact path and any collector diagnostics.

## Boundaries

- The cockpit is a read-only projection over canonical files.
- Do not run suggested cleanup commands unless the user explicitly asks.
- Do not enable suggested sources automatically.
- Do not claim unsupported control of Claude or Codex proprietary GUI threads.
- Do not write to Notion or any external service while generating the cockpit.
