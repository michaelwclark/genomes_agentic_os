# Feature Spec: Factory Template Import Backlog

## Status

- Status: ready
- Owner: Genome
- Created: 2026-05-20
- Target OS layer: source package, installed runtime, and customer OS installs

## Problem

`/Users/genome/projects/factory` contains useful agent-native workspace templates, context contracts, diagnostic builder skills, constraints, and Notion/manual drafts. Those patterns are not yet systematically represented in `genomes_agentic_os`.

The product source should not blindly copy all factory content. It needs an import policy that pulls durable structures into templates and plans while avoiding stale examples, private content, and course-specific explanation that does not belong in generated customer OS roots.

## Valuable Factory Sources

| Source | Value To Import |
| --- | --- |
| `workspace-blueprint/CLAUDE.md` | Layer 1 map pattern, quick navigation, naming conventions, file placement rules, token management, tool index. |
| `workspace-blueprint/CONTEXT.md` | Layer 2 task router with `Your Task`, `Go Here`, and `You'll Also Need`. |
| `workspace-blueprint/*/CONTEXT.md` | Room contracts with token-budget `What to Load` tables, folder structure, tools/skills, cross-room handoffs, and anti-patterns. |
| `workspace-blueprint/production/workflows/CONTEXT.md` | Stage pipeline pattern: input, also load, output, skills at stage, forward-only handoff. |
| `notion-drafts/os-folder-structure-guide.md` | Generalized map/rooms/work model and starter context template. |
| `vault-toolkit/architectures/*` | Reference architectures for client delivery, content production, and small-business operations. |
| `vault-toolkit/skill-starters/*` | Diagnostic question sets that should become installer wizard packs. |
| `vault-toolkit/constraints/03-context-hygiene.md` | Context hygiene rule: load only what the stage needs. |
| `vault-toolkit/constraints/06-layer-triage.md` | Separate deterministic, rule-based, and LLM-needed work before automating. |
| `vault-toolkit/constraints/07-scaling-vs-automating.md` | Scale by documentation and stage contracts before automating judgment. |
| `vault-toolkit/constraints/08-handoff-readiness.md` | Handoff checklist for map, context, stage contracts, references, and decisions. |
| `_notion_school/07-client-factory-playbook.md` | Customer discovery questions, good/bad first automation filters, client brief fields, value metrics, and data boundaries. |
| `_notion_school/08-skill-roadmap.md` | Future skill shapes for intake, planning, session closeout, context audit, memory distillation, and client automation briefs. |
| `_notion_clarks_consulting_school/04-notion-control-plane.md` | Queue database shape, activity log fields, engine controls, stable planning page, and control-plane anti-patterns. |
| `_notion_clarks_consulting_school/06-client-automation-playbook.md` | Automation fit matrix, two-week pilot shape, customer handoff deliverables, security notes, and training path. |
| `_notion_agentic_operating_system_manual/*` | Domain/lane source-of-truth model, workflow/automation layouts, and practical walkthrough candidates. |

## Import Now

Add first-class templates:

```text
templates/room/context.md
templates/room/router.md
templates/room/routing-table.md
templates/reference/naming-conventions.md
templates/reference/tool-index.md
templates/reference/style-and-output-rules.md
templates/reference/source-priority.md
templates/stage/stage-context.md
templates/profile/customer-os-profile.yml
templates/customer/client-automation-brief.md
templates/customer/automation-fit-matrix.md
templates/customer/customer-handoff-checklist.md
templates/notion/control-plane-database-spec.md
```

Add docs:

```text
docs/12-factory-patterns/README.md
```

Add skills or command prompts:

```text
harness/commands/os-discover-rooms.md
harness/skills/room-builder/SKILL.md
```

Capture as follow-up playbook work:

```text
PLANS/14-client-automation-and-control-plane-playbooks.md
harness/commands/os-client-automation-brief.md
harness/commands/os-control-plane-bootstrap.md
harness/commands/os-context-audit.md
harness/skills/client-automation-brief/SKILL.md
harness/skills/control-plane-bootstrap/SKILL.md
harness/skills/context-audit/SKILL.md
```

## Adapt, Do Not Copy Blindly

- Keep the three-layer concept, but map names to Agentic OS vocabulary:
  - Map: root `ROUTER.md`, `AGENTS.md`, `CLAUDE.md`, `AGENT.md`.
  - Rooms: customer-specific domains or domain rooms with `CONTEXT.md`.
  - Work: projects, workflows, automations, stage folders, outputs, run logs.
- Keep factory examples sanitized. Do not install `Acme`, course, school, or Eduba-specific examples into customer roots unless they are explicitly under examples/docs.
- Convert teaching comments into product docs or examples, not generated runtime files.
- Preserve the stricter Agentic OS additions: approvals, run logs, Notion control plane, automation maturity, doctor checks, and update contract.

## Avoid

- Copying every factory file into `templates/`.
- Installing course material into customer OS roots.
- Replacing Agentic OS domain/run/approval structure with a simpler folder-only model.
- Loading every constraint by default.
- Treating Notion as the execution source of truth.

## Implementation Steps

1. Create a factory inventory doc that lists copied, adapted, referenced, and rejected assets.
2. Add room, stage, reference, and profile templates.
3. Add installer wizard plan and command prompt for room discovery.
4. Update docs to explain room-first customer installs versus Genome's personal profile.
5. Add tests that verify templates are installed into `shared_factory/05-knowledge/templates/`.
6. Add a scrub check for private/client/course names in generated customer-facing templates.

## Acceptance Criteria

- A fresh install includes room, stage, reference, and profile templates.
- Customer install plans can generate 3-5 operator-named rooms without using Genome defaults.
- Each generated room can declare read-first, read-when-needed, do-not-load, tools/skills, output folders, and done criteria.
- Factory-derived content is sanitized and categorized as copied, adapted, referenced, or rejected.
- Existing `agentic-os docs update` remains additive and preserves installed runtime edits.

## Validation

- `pytest -q`
- `agentic-os docs update --root <tmp-root>`
- `agentic-os validate --root <tmp-root>`
- Grep generated templates for disallowed private/example-only names.
