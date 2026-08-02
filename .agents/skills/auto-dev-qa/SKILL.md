---
name: auto-dev-qa
description: Run project-configured risk-based QA as a standalone receipt-backed workflow. Use when the user asks for Agentic OS `auto-dev-qa` work or when the routed Agentic OS skill registry selects `auto-dev-qa`.
---

<!-- generated-by: agentic-os register-harness-skills -->

# Auto-Dev QA

Harness-visible adapter for the Agentic OS `auto-dev-qa` skill.

## Procedure

1. Start from `/Users/genome/agentic_os`.
2. Follow the Agentic OS startup loop: read `AGENTS.md`, then `ROUTER.md`,
   `CONTEXT.md`, `RULES.md`, and `TOOLS.md`; when routed deeper, repeat there.
3. Read `harness/rules/os-authoring-rules.md` before editing Agentic OS
   commands, skills, workflows, automations, tools, registries, or runtime
   templates.
4. Read `harness/skills/auto-dev-qa/SKILL.md` after routing.
5. Update `harness/registries/skills.yml` and the relevant `TOOLS.md` surface
   when changing this visible skill invocation.
6. Validate with the smallest focused check available.
