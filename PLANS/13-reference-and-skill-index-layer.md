# Feature Spec: Reference And Skill Index Layer

## Status

- Status: ready
- Owner: Genome
- Created: 2026-05-20
- Target OS layer: source package, installed runtime, Codex, and Claude

## Problem

The current OS has `source-map.md`, `glossary.md`, and `memory-policy.md`, but the factory templates show a missing layer: lightweight shared references that agents can load selectively without reading entire rooms or workflows.

The OS also lists installed skills, but it does not yet route skills by room, task, or stage in a way that helps the agent decide when to use each one.

## Outcome

Every installed OS should have a shared reference layer and room-level skill routing so agents know:

- naming conventions,
- which tools and skills exist,
- when to use each skill,
- which style/output rules apply,
- which sources are authoritative,
- what to avoid loading by default.

## New Reference Templates

```text
templates/reference/naming-conventions.md
templates/reference/tool-index.md
templates/reference/style-and-output-rules.md
templates/reference/source-priority.md
templates/reference/decision-log.md
```

## Runtime Placement

Source templates install to:

```text
shared_factory/05-knowledge/templates/reference/
```

Customer/runtime references generated from those templates should live in:

```text
<domain-or-room>/05-knowledge/
```

or, for global cross-domain references:

```text
shared_factory/05-knowledge/references/
```

## Tool Index Shape

```markdown
| Tool Or Skill | Type | Use When | Available In | Approval Risk | Notes |
| --- | --- | --- | --- | --- | --- |
```

## Room Skill Routing Shape

```markdown
| Task Or Stage | Skill / Tool | Why | Required Inputs | Stop Conditions |
| --- | --- | --- | --- | --- |
```

This should be generated inside each room `CONTEXT.md` or room router.

## Source Priority Shape

```markdown
| Source | Trust Level | Use For | Refresh Rule | Do Not Use For |
| --- | --- | --- | --- | --- |
```

## Acceptance Criteria

- Reference templates are copied into installed OS roots.
- Room `CONTEXT.md` templates include task-specific skill/tool routing.
- Context builder plan consumes reference files as optional inputs.
- The top-level router remains short; detailed reference material moves out of root files.
- Tests verify new templates are installed additively.

## Validation

- `pytest -q`
- `agentic-os docs update --root <tmp-root>`
- `agentic-os validate --root <tmp-root>`
