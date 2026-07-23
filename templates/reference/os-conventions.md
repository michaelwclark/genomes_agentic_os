# Agentic OS Conventions

Use this file when creating or changing Agentic OS specs, workflows,
automations, commands, skills, or filesystem/Notion routing rules. Do not load it
for ordinary task execution unless a local command, skill, or validator asks for
it.

## Default Work Flow

1. Route to the narrowest OS layer and read that layer's `ROUTER.md`,
   `CONTEXT.md`, `RULES.md`, `TOOLS.md`, and active work item.
2. For new specs, proposed features, plans, questions, worklogs, or Notion spec pages,
   run `agentic-os doc-config plan` before creating filesystem or Notion
   destinations.
3. Keep the Agentic OS project `work-items/` object as lifecycle source of truth
   unless project config explicitly declares another owner.
4. Append receipt-backed progress to the relevant `WORKLOG.md` and update the
   domain/project control surface that future agents will read.
5. Register external source checkouts through the project `worktrees/` surface
   before using them for project work.
6. Run the declared validation before handoff and record the evidence path.

## Spec And Notion Mirrors

- Project-known future work and proposed features belong in
  `<domain>/02-projects/<project>/work-items/01-intake/` as the single
  canonical Spec object.
- Active work belongs in
  `<domain>/02-projects/<project>/work-items/<index>_<slug>/`.
- The standard packet files are `SPEC.md`, `PLAN.md`, `WORKLOG.md`,
  `NEXT.md`, and optional `QUESTIONS.md`, `DECISIONS.md`, and artifact indexes.
- Existing `IDEA.md` files are legacy capture aliases. New packets put raw
  capture in `SPEC.md`.
- Human-readable work history belongs in `WORKLOGS/` or `worklogs/`, matching
  local folder casing. Lowercase `logs/` is raw system output, transcripts, and
  runtime state.
- Source repository `features/` or `.features/` folders are mirrors or
  implementation artifacts unless `config/work-lifecycle.yml` says otherwise.
- If a repository already uses `/features` for product code or tests, do not
  overload it with OS lifecycle state. Use the OS work item as the canonical
  mirror and add only a source-side artifact folder when project config declares
  one.
- External source checkouts belong behind visible `worktrees/<name>` links and
  `worktrees/index.yml`. A bare path under `~/projects` is not enough for OS
  routing and future agents.
- Notion is the human control-plane projection. Verify the workspace before
  writing and mirror the configured bucket names instead of inventing a second
  taxonomy.

## Bug Intake

- Use `/add-bug` for product bugs, missed enforcement, routing drift, stale
  registries, broken logging, and unexpected OS behavior.
- Route Agentic OS bugs to the installed Agentic OS product project unless a
  more specific project owns the failure.
- Capture affected area, severity, current behavior, expected behavior,
  reproduction/evidence, suspected source, owner/status, and next action.
- Keep raw logs, transcripts, screenshots, and large evidence in `artifacts/`;
  link them from the bug packet instead of pasting them into chat.

## Spec Intake

- Use `/add-spec` for explicit future-work or proposed-feature requests.
- Use `/auto-add-spec` when a long OS-shaping request would otherwise live only
  in chat.
- `/new-feature`, `/add-feature`, `/new-idea`, and `/auto-add-feature` are
  compatibility aliases during migration.
- Search active and intake work-items before creating a new packet.
- Create or update `SPEC`, `PLAN`, `WORKLOG`, `NEXT`, conditional
  `QUESTIONS`, and `CONVENTIONS` when reusable rules are being proposed.
- During orchestration, delegate this bookkeeping to a subagent when possible so
  the main agent can stay focused on product and engineering decisions.

## Workflow Authoring

- Create workflows with `agentic-os workflow create`.
- Fill the outcome brief, alignment questions, PRD, implementation plan,
  dispatch handoff, context pack, approval rules, output contract, runbook,
  quick reference, and progress file before dispatch.
- A workflow that is meant to be invoked repeatedly needs an invocation
  contract: a slash command, CLI command, or skill name plus the registry entry
  that exposes it.
- Update domain `00-control-plane/state-index.md`, related project state, and
  `MEMORY.md` when the workflow creates a stable routing or operating rule.

## Automation Authoring

- Create automations with `agentic-os automation create` only after a workflow or
  runbook has successful evidence.
- Start at `observe` or `prepare`; do not advance execution maturity until
  `agentic-os automation check` has no blockers.
- Every automation needs an invocation or trigger contract and a matching
  command, skill, source watcher, schedule, or runtime registry entry.
- External writes, customer-visible output, production, destructive, billing,
  legal, and secret-touching actions stop at approval gates.

## Command And Skill Authoring

- Command docs live under `harness/commands/` and must have matching entries in
  `harness/registries/commands.yml`.
- Skill docs live under `harness/skills/<skill>/SKILL.md` and must have matching
  entries in `harness/registries/skills.yml`. Shared skills that ship with the
  source package must also stay listed in `harness/skills/skill-registry.yml`.
- If a command or skill becomes reusable for installed roots, make sure
  `agentic-os docs update` or the update channel can copy it into
  `harness/shared_factory/05-knowledge/`.
- Keep command and skill bodies focused. Link to this convention file when the
  full rule set is needed instead of pasting the checklist into every prompt.

## Compact Rule

For normal authoring, read `harness/rules/os-authoring-rules.md` first. Load
this reference only when the compact rule is not enough.

## Context Creep Guard

- Default startup loads only local routing, context, rules, tools, memory policy,
  and the active work item.
- Load this file only for authoring, validating, or debugging Agentic OS
  conventions.
- Put large examples, raw logs, screenshots, and generated artifacts in
  `artifacts/` or run logs. Keep active rule files small enough for agents to
  read every time.
