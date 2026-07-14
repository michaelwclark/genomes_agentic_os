# OS Capture Plan

Use when a future spec, implementation gap, customer OS need, or validation
finding should become durable OS planning material.

## Where To Put New Plans

| Plan Type | Source Repo Location | Installed Location |
| --- | --- | --- |
| OS product spec or roadmap item | Do not create a source-repo planning file | Installed Agentic OS project `work-items/01-intake/<NNN>_<slug>/SPEC.md` |
| Installed project spec | Do not create a source-repo planning file | Installed project `work-items/01-intake/<NNN>_<slug>/SPEC.md` |
| Customer-specific OS need | Customer domain inbox or project folder | Link the reusable pattern back to shared plans |
| Loose request not yet scoped | `shared_factory/01-inbox/raw-ideas.md` | — |
| Already-scoped spec ready to plan | Installed project `work-items/02-active/<NNN>_<slug>/SPEC.md` | — |

## Naming Convention

Specs use a sequential three-digit number prefix: `NNN-slug-with-dashes.md`.
Read the highest existing number in the installed project's `work-items/` lanes
and increment by one. Allocate the number before writing; do not let parallel
agents pick the same number.

## Procedure

1. Route the request to a domain if it is domain-specific.
2. If it is reusable OS product work, record it under `shared_factory/05-knowledge/plans/`.
3. If it is customer-specific, record it in the customer domain inbox or project folder
   and link the reusable pattern back to shared plans.
4. Use the `templates/planning/feature-spec.md` template structure until a
   dedicated spec template replaces it.
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

A numbered plan file at the correct location, referencing relevant prior plans
under `Relationship To Other Plans`.
