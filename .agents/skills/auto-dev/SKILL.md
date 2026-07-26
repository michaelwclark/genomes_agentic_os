---
name: auto-dev
description: Run a Jira or Linear tracker item through project-aware SDLC orchestration, state-machine receipts, finishing review, commit/push/PR delivery, PR/CI/Copilot loops, and handoff to secondary review/finalization. Auto-Dev never merges. An explicit all-the-way-to-PR request must not strand at a human review transport pause. LOS Work Plan rows are a queue adapter. Use when the user asks for Agentic OS `auto-dev` work or when the routed Agentic OS skill registry selects `auto-dev`.
---

<!-- generated-by: agentic-os register-harness-skills -->

# Auto Dev

Harness-visible adapter for the Agentic OS `auto-dev` skill.

## Procedure

1. Start from `/Users/genome/agentic_os`.
2. Follow the Agentic OS startup loop: read `AGENTS.md`, then `ROUTER.md`,
   `CONTEXT.md`, `RULES.md`, and `TOOLS.md`; when routed deeper, repeat there.
3. Read `harness/rules/os-authoring-rules.md` before editing Agentic OS
   commands, skills, workflows, automations, tools, registries, or runtime
   templates.
4. Read `harness/skills/auto-dev/SKILL.md` after routing.
5. Update `harness/registries/skills.yml` and the relevant `TOOLS.md` surface
   when changing this visible skill invocation.
6. Validate with the smallest focused check available.
