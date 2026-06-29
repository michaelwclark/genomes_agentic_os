---
name: os-authoring-guard
description: Apply compact Agentic OS authoring rules when creating or updating commands, skills, workflows, automations, tools, registries, runtime templates, project worktrees, or reusable OS conventions.
---

# OS Authoring Guard

Use this skill before changing Agentic OS operating surfaces.

## Checklist

1. Read `harness/rules/os-authoring-rules.md`.
2. Confirm the active work item or create one through `/add-spec` or
   `/auto-add-spec`. Legacy `/new-feature`, `/add-feature`, `/new-idea`, and
   `/auto-add-feature` requests route to those same workflows.
3. Confirm source work uses the project `worktrees/` registry when an external
   checkout is involved.
4. Pair directly invokable workflows/automations with command docs and skills.
5. Update command, skill, rule, hook, plugin, library, tool, and MCP registries
   when adding visible surfaces.
6. Update readable `TOOLS.md` surfaces.
7. Add a focused validation check or test.

## Context Budget

Load the rule, registry rows, changed command/skill/workflow docs, and active
work item. Do not load the full operating manual by default.
