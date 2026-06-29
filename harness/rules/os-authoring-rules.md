# OS Authoring Rules

Use these rules when creating or changing Agentic OS features, workflows,
automations, commands, skills, tools, registries, runtime templates, or
project worktrees.

## Required Loop

1. Load the routed layer: `AGENTS.md`, `ROUTER.md`, `CONTEXT.md`, `RULES.md`,
   `TOOLS.md`, and the active work item when one exists.
2. Run doc-config before creating new spec, proposed feature, bug, workflow, automation,
   or Notion structure.
3. Keep the filesystem work item as source of truth. Notion is a projection
   unless local config explicitly says otherwise.
4. Update the relevant `WORKLOG.md`, `NEXT.md`, project `status.md`, domain
   active-work, or run log when OS state changes.
5. Use the project `worktrees/` registry/link surface for external source
   checkouts. Register active checkouts with `agentic-os project worktree add`.
6. When a workflow or automation should be directly invoked by a harness, add a
   matching command doc and skill.
7. When adding or renaming commands, skills, rules, hooks, plugins, libraries,
   tools, or MCP surfaces, update the visible registries and readable `TOOLS.md`
   surfaces.
8. Add validation or tests for new reusable conventions.

## Context Budget

Load the compact rule, registry row, command doc, skill doc, and active work item
needed for the current task. Do not load the full operating manual, every
historical work item, every command, every skill, or large logs unless the route
requires that evidence.

## Bug Intake

Use `/add-bug` for missed enforcement, broken routing, logging gaps, or product
bugs. A bug report must name the affected area, current behavior, expected
behavior, severity, evidence, owner/status, and next action.

## Feature Intake

Use `/add-spec` for explicit future-work or proposed-feature requests and
`/auto-add-spec` when a long OS-shaping request would otherwise live only in
chat. `/new-feature`, `/add-feature`, `/new-idea`, and `/auto-add-feature` are
legacy aliases during migration.
