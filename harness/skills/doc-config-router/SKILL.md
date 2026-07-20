---
name: doc-config-router
description: Route document captures to configured Agentic OS filesystem and Notion destinations. Use when the user says to add something to Notion, save a note/spec/plan/question/worklog, reorganize docs, or decide where a new page belongs.
---

# Doc Config Router

Use this skill before writing or moving documentation in Agentic OS, especially when a request is phrased broadly like "Add this to Notion."

## Routing Loop

1. Load the nearest Agentic OS route layer: `ROUTER.md`, `CONTEXT.md`, `RULES.md`, `TOOLS.md`, and active work item files.
2. Read `harness/rules/os-authoring-rules.md` when the request creates or
   changes spec/worklog mirrors, workflows, automations, commands, skills, tools,
   project worktrees, or reusable convention policy. Use
   `harness/shared_factory/05-knowledge/references/os-conventions.md` only when
   deeper background is needed.
3. Run a dry plan:

```bash
agentic-os doc-config plan --root <root> --request "<request>" [--domain <domain>] [--project <project>] [--work-item <work_item>] [--questions-present]
```

4. Follow the returned search methods in priority order.
5. Verify Genome's Notion before any Notion write.
6. Search existing destinations before creating a new page/folder.
7. Write source-of-truth content to filesystem/work-item files first when a routed work item exists.
8. Use Notion color variation and rich blocks from `doc-config.yml` when creating or updating Notion pages.

## Bucket Convention

- Use `SPEC` for raw concept, user language, scope, behavior contracts, and acceptance criteria.
- Use `PLAN`/`PLANS` for implementation sequence and validation.
- Use `WORKLOGS` for timestamped receipt-backed progress. Per-work packets still use `WORKLOG.md`.
- Use `QUESTIONS` whenever unresolved questions exist.
- Use `DECISIONS`, `ARTIFACTS`, and `CONVENTIONS` only when enabled or clearly useful.

## Guardrails

- Do not create fallback pages in the wrong Notion workspace.
- Do not create a child `FEATURES` bucket inside a spec page by default; `Specs` is the namespace.
- Do not disable filesystem authority unless an explicit local config says another system owns the source of truth.
- Do not store secrets, raw tokens, or private connector payloads in doc config or routing artifacts.

## Boundary with Create Artifacts

Doc Config owns destination, workspace, parent, create-versus-update intent,
and information architecture. It returns that decision as target evidence.
`$auto-dev-create-artifacts` owns provider/type content, validation, approval,
apply handoff, and readback. Do not invent artifact prose in the router or let
an artifact contract invent a destination.
