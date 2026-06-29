---
name: spec-intake-router
description: Create or update Agentic OS spec intake using doc-config routing, project work items, and optional Notion projection. Use when the user asks for /add-spec, a new spec, proposed feature, future plan, rough request, or where to put future work in Agentic OS or Notion.
---

# Spec Intake Router

This skill turns rough future work into the configured Agentic OS work surface.
It makes doc-config mandatory instead of relying on memory.

## Intake Loop

1. Load the routed OS layer and active project context.
2. Read `harness/rules/os-authoring-rules.md` when the request changes
   conventions, workflow/automation setup, command/skill surfaces, filesystem
   mirror rules, or project worktrees.
3. Run:

```bash
agentic-os doc-config plan --root <root> --request "<request>" [--domain <domain>] [--project <project>] [--questions-present]
```

4. Resolve the narrowest domain/project/work item. Ask only when the plan cannot
   infer the required destination.
5. Ensure the project surface exists with `agentic-os project onboard`.
6. Create or repair a captured packet work item with
   `agentic-os project work-item create ... --status captured --format packet`.
7. Register external source checkouts with `agentic-os project worktree add`
   before using them for project work.
8. Fill the configured bucket files:
   - `SPEC` captures raw user language, outcome, scope, behavior, acceptance
     criteria, risks, and why now.
   - `PLAN` captures implementation sequence and validation.
   - `WORKLOG` captures timestamped receipts.
   - `QUESTIONS` is present whenever unresolved questions exist.
9. Project to Notion only after workspace verification, using the configured
   `Specs` namespace, color variation, rich blocks, and cross-links.
10. Update `WORKLOG.md`, `NEXT.md`, and the project/domain control surface when
    the capture changes durable state or routing.

## Promotion Rule

Leave the item in intake until `SPEC` and `PLAN` are coherent enough for
implementation. Move it to active only when there is an owner, build path, and
validation plan.

## Completion Standard

A fresh agent should be able to open the work item and know:

- where the spec lives in the filesystem,
- where it should live in Notion,
- what questions remain,
- what to build first,
- what evidence is required before closeout.

## Guardrails

- Filesystem/work-item content remains source of truth.
- Source repository `features/` or `.features/` folders are mirrors/artifacts by
  default, not lifecycle owners.
- `QUESTIONS` is conditional on unresolved questions, but must be created when
  any exist.
- Do not create fallback Notion pages outside Genome's Notion.
- Do not skip `doc-config plan`; this skill exists to enforce that first step.
- Do not skip the project `worktrees/` registry when source work happens outside
  the installed OS tree.
- Do not generate `IDEA.md` for new packets. Existing `IDEA.md` files remain
  readable legacy capture.
