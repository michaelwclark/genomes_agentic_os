---
name: aos-product-orchestrator
description: Groom Agentic OS self-improvement proposals into spec packets and Linear issues. Use for AOS Product Orchestrator or Auto Groom.
---

# AOS Product Orchestrator

Use this skill to turn Agentic OS ideas, self-improvement suggestions, and rough
operating-system changes into execution-ready specs and Linear issues.

The default automation invocation is a self-improvement proposal from the
`Self Improvement` Notion database with `Auto Groom` checked.

## Skill Suite

Use the relevant Agentic OS skills as needed:

- `$os-navigator`
- `$spec-intake-router`
- `$auto-spec-intake`
- `$context-audit`
- `$workflow-builder`
- `$automation-qualifier`
- `$linear-product-orchestrator`

Do not run implementation unless the user or queued action explicitly asks for
implementation. Auto Groom is a product/spec grooming action.

## Operating Contract

1. Load the routed Agentic OS layer before acting.
2. Read `harness/rules/os-authoring-rules.md` for changes to skills, commands,
   workflows, automation, runtime templates, tools, or registries.
3. Read the proposal source first: Notion row properties, proposal YAML, linked
   run report, evidence excerpts, and existing work item context.
4. Search existing Agentic OS work items and Linear issues before creating new
   work. Update a matching item instead of duplicating it.
5. Inspect relevant filesystem source, config, tests, docs, and current runtime
   state before writing technical notes.
6. Create or update a local Agentic OS spec packet as the source of truth.
7. Create or update a Linear issue in the `Agentic OS` project after verifying
   Linear workspace, team, project, and duplicate status.
8. Leave a receipt that names the spec packet, Linear issue identifier/URL,
   evidence used, skipped items, and blockers.

## Write Safety

- Verify the Linear workspace, team, and `Agentic OS` project before any Linear
  write.
- Never put secrets, credential values, local filesystem paths, private Notion
  links, internal agent/tooling details, or private run-log paths in Linear.
- Use sanitized evidence names, repo-relative paths when public enough for the
  target audience, issue identifiers, PR URLs, commit hashes, and short source
  descriptions.
- Genome's Notion is the only default Notion destination. Stop if Notion access
  resolves to Michael Clark's personal Notion or another workspace.
- Filesystem work items and receipts remain source of truth; Notion and Linear
  are projections.

## Decision Tree

### Start With Proposal Framing When

- the proposal is a raw self-improvement suggestion,
- the problem statement is unclear,
- the proposed artifact is generic,
- or acceptance criteria are missing.

### Start With Existing Work Audit When

- a matching work item, spec packet, Linear issue, or active implementation lane
  already exists,
- the proposal is likely a duplicate,
- or the fastest path is to strengthen existing planning.

### Start With Technical Mapping When

- the idea affects runtime scheduling, queues, skills, registries, Notion sync,
  memory, project routing, or source package behavior,
- implementation notes need likely files, commands, tests, or migration impact,
- or validation has to distinguish installed OS tree changes from source package
  changes.

### Start With QA And Rollout When

- the proposal touches automations, external writes, queues, Notion/Linear sync,
  memory writes, destructive actions, or recurring schedules,
- release sequencing and backout matter,
- or user trust depends on auditability.

## End-To-End Flow

1. Resolve context.
   - Confirm the request/proposal ID, Notion page, local proposal YAML, run
     report, and owning Agentic OS project/work item.
   - Search for matching local work items and Linear issues.

2. Draft the spec packet.
   - Capture problem, evidence, impact, non-goals, scope, acceptance criteria,
     technical notes, QA, rollout, risks, dependencies, and open questions.
   - Prefer updating an existing packet when it represents the same problem.
   - Use `spec-intake-router` or `auto-spec-intake` for packet placement.

3. Map the implementation.
   - Identify likely OS files, source package files, tests, commands, configs,
     schedulers, registries, and external integrations.
   - Record current behavior and the intended behavioral change.
   - Separate confirmed facts from assumptions and questions.

4. Build the Linear issue.
   - Resolve the Linear `Agentic OS` project and owning team.
   - Match by title, proposal ID, problem statement, and labels before creating.
   - Create or update the issue with sanitized content:
     Problem, Evidence, Impact, Scope, Acceptance Criteria, Technical Notes,
     QA / Validation, Rollout, Risk, Dependencies, Open Questions.
   - Add child issues only for separable implementation, QA, migration, or
     rollout work.

5. Close the loop.
   - Update the local worklog/NEXT file with the Linear receipt.
   - If invoked by self-improvement automation, update the Notion row action
     status/log only after verifying Genome's Notion.
   - If blocked, leave a blocker-grade receipt instead of guessing.

## Handoff Bundle

Maintain this compact bundle while grooming:

### Confirmed Facts

### Assumptions

### Open Questions

### Draft Spec

### Linear Draft

### Receipts

Populate only sections that are mature enough for the current stage.

## Done Condition

The skill is complete when the Agentic OS proposal has a source-backed spec
packet, a verified Linear issue under the `Agentic OS` project, sanitized
evidence, QA/rollout notes, and a local receipt describing what was created,
updated, skipped, or blocked.
