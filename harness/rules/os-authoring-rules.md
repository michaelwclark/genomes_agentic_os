# OS Authoring Rules

Use these rules when creating or changing Agentic OS features, programs,
workflows, automations, commands, skills, tools, registries, runtime templates,
rules, hooks, or project worktrees.

## Required Loop

1. Load the routed layer: `AGENTS.md`, `ROUTER.md`, `CONTEXT.md`, `RULES.md`,
   `TOOLS.md`, and the active work item when one exists.
2. Run doc-config before creating new spec, proposed feature, bug, workflow,
   automation, program, or Notion structure.
3. Keep the filesystem work item as source of truth. Notion is a projection
   unless local config explicitly says otherwise.
4. Update the relevant program docs, `WORKLOG.md`, `NEXT.md`, project
   `status.md`, domain active-work, or run log when OS state changes.
5. Use the project `worktrees/` registry/link surface for external source
   checkouts. Register active checkouts with `agentic-os project worktree add`.
6. When a workflow or automation should be directly invoked by a harness, add a
   matching command doc and skill.
7. When a command or skill should be visible in Codex or Claude Code, create or
   update a skill adapter under `.agents/skills/<skill-name>/SKILL.md` with
   valid `name` and `description` YAML frontmatter, and ensure
   `$HOME/.codex/skills/<skill-name>/agents/openai.yaml` exists for desktop
   `$`/`/` launcher visibility.
8. Run `harness/bin/register-harness-skills --root /Users/genome/agentic_os --user-scope`
   after adding or changing Agentic OS skills so Codex repo adapters,
   `$HOME/.agents/skills` registrations, `$HOME/.codex/skills` launcher
   metadata, and `$HOME/.claude/skills` symlinks are all regenerated.
   (`register-codex-skills` is a deprecated shim that forwards to this tool.)
9. When adding or renaming workflows, automations, commands, skills, rules,
   hooks, plugins, libraries, tools, MCP surfaces, tool routes, or programs,
   update every canonical OS registry and readable surface that owns that
   capability. This includes the relevant `harness/registries/*.yml`, `TOOLS.md`,
   Codex/Claude adapter metadata, domain or project state indexes, run tracking
   manifests, doc-config routes, and any configured external documentation or
   control-plane projection such as Genome's Notion.
10. If an external projection is configured but cannot be written after target
   workspace/account verification, record the blocker in the canonical local
   registry entry. Do not leave the external registry or Notion projection
   silently stale.
11. Add validation or tests for new reusable conventions.
12. Do not ship undocumented OS-level behavior. Every new OS-level feature must
   document ownership, context routing, validation, and projection updates.

## Cross-Model Reviewer Transport

- Run Anthropic-family finishing reviews through the installed `claude` CLI,
  not a direct Anthropic SDK or HTTP client.
- Remove `ANTHROPIC_API_KEY` and `ANTHROPIC_AUTH_TOKEN` from the Claude CLI
  subprocess environment so host CLI authentication remains authoritative.
- If the CLI is missing, unauthenticated, out of credit, or otherwise cannot
  complete the review, write a sanitized unavailable-review receipt and continue
  through the remaining validation and delivery gates by default.
- A project may set `finishing_review.unavailable_policy: block` when an
  independent cross-model review is a mandatory risk control. Actual reviewer
  findings such as `changes_required` remain blocking under every policy.

## Context Budget

Load the compact rule, registry row, command doc, Codex adapter skill, harness
skill doc, program descriptor, and active work item needed for the current task.
Do not load the full operating manual, every historical work item, every command,
every skill, or large logs unless the route requires that evidence.

## Program Work

Use `/create-program` or `agentic-os program create` for reusable shared OS
capabilities. Use `/create-instance-program` or
`agentic-os instance-program create` for instance/domain-only capabilities.

Update `program.md`, `components.yml`, `context-pack.md`, `crud.md`,
`documentation.md`, `runbook.md`, `tests.md`, and `worklog.md` when a program's
behavior, ownership, routing, validation, external projection, schedule, or
linked component list changes.

## Versioned Installed Object Library

When an installed root contains lib/registry/objects.json, treat that compact
registry as the first read surface for programs, workflows, automations,
commands, skills, hooks, rules, references, templates, and toolkits.

- Each object.yml manifest is canonical for mutation.
- Generated files under lib/registry are canonical read projections and must
  not be edited directly.
- Use agentic-os library refresh --apply after changing an object.
- Use agentic-os library doctor before committing or projecting adapters.
- Put mutable logs, runs, state, caches, receipts, artifacts, secrets, and
  worktrees under runtime, never in the versioned object definition.
- During migration, legacy paths are compatibility aliases. New definitions and
  normal writes target lib.

Work state is not a library object. Read `active-now.json` before broad context,
then use `agentic-os work show/list` for detail. Mutate lifecycle state,
attention, resume context, source identity, and verification timestamps through
`agentic-os work`; do not infer or change state by moving packet folders.

## Bug Intake

Use `/add-bug` for missed enforcement, broken routing, logging gaps, or product
bugs. A bug report must name the affected area, current behavior, expected
behavior, severity, evidence, owner/status, and next action.

## Feature Intake

Use `/add-spec` for explicit future-work or proposed-feature requests and
`/auto-add-spec` when a long OS-shaping request would otherwise live only in
chat. `/new-feature`, `/add-feature`, `/new-idea`, and `/auto-add-feature` are
legacy aliases during migration.
