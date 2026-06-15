# OS Capture Plan

Use when a future idea, implementation gap, customer OS need, or validation
finding should become durable OS planning material.

## Where To Put New Plans

| Plan Type | Source Repo Location | Installed Location |
| --- | --- | --- |
| OS product feature or roadmap item | Do not create a source-repo planning file | Installed project `SPECS/<slug>/SPEC.md` |
| Customer-specific OS need | Do not create a source-repo planning file | Customer domain inbox or project `work-items/01-intake/` |
| Loose idea not yet scoped | Do not create a source-repo planning file | Installed domain `01-inbox/raw-ideas.md` |
| Already-scoped idea ready to plan | Do not create a source-repo planning file | Installed project `SPECS/<slug>/SPEC.md` or `work-items/02-active/<slug>/` |

## Naming Convention

Specs use the installed OS project naming convention. Allocate the destination
through the project work-item/spec intake surface before writing; do not let
parallel agents pick the same number or slug.

## Procedure

1. Route the idea to a domain if it is domain-specific.
2. If it is reusable OS product work, record it under the installed OS project
   `SPECS/` or `work-items/`.
3. If it is customer-specific, record it in the customer domain inbox or project folder
   and link the reusable pattern back to shared plans.
4. Use `SPEC.md` as the raw-capture plus refined-spec file.
5. Capture problem, user outcome, scope, non-goals, affected surfaces,
   acceptance criteria, validation, and rollout notes.
6. Update active work only when the plan is ready to build.

## Spec Sections Required

- **Status** — draft | review | approved | in-progress | done
- **Problem** — what user or operator problem this solves
- **Outcome** — what should be true when complete
- **Scope** and **Out Of Scope** — boundaries
- **Affected Surfaces** — CLI, installer, runtime OS files, harness, Notion, tests
- **Acceptance Criteria** — verifiable, one per line
- **Validation** — how to confirm the AC is met
- **Rollout Notes** — install behavior (additive, write-if-missing, etc.)

## Output

A spec/work-item path in the installed OS project, referencing related specs or
work items where useful.
