# Factory Pattern Import Inventory

This inventory records which durable patterns from `/Users/genome/projects/factory` belong in Genome's Agentic OS source package and which do not.

## Copied

| Pattern | Agentic OS Target | Notes |
| --- | --- | --- |
| Room context contract | `templates/room/context.md` | Generalized into room/domain vocabulary. |
| Room router | `templates/room/router.md` | Keeps root map -> room router flow. |
| Routing table fragment | `templates/room/routing-table.md` | Reusable table shape for task routing. |
| Stage context contract | `templates/stage/stage-context.md` | Forward-only stage handoff pattern. |
| Reference rules | `templates/reference/*.md` | Naming, source priority, tools, style, and decision logs. |

## Adapted

| Source Pattern | Adaptation |
| --- | --- |
| Layer 1 map | Root `ROUTER.md` plus `AGENTS.md`, `CLAUDE.md`, and `AGENT.md` pointer files. |
| Layer 2 room contracts | Domain/room `CONTEXT.md` and `ROUTER.md`. |
| Workspace stage pipelines | Workflow runbooks, stage context templates, and closeout logs. |
| Client automation playbook | Customer automation brief, fit matrix, handoff checklist, and automation maturity rules. |

## Referenced

| Source Pattern | Reason |
| --- | --- |
| Diagnostic builder questions | Feed future installer wizard packs and room-builder skills. |
| Context hygiene constraints | Feed reference docs and doctor checks. |
| Control plane drafts | Feed Notion bootstrap and sync planning, not runtime source of truth. |

## Rejected

| Content Type | Reason |
| --- | --- |
| Course-specific explanation | Teaching material does not belong in generated customer roots. |
| Private/client examples | Must stay in examples or source docs, not runtime templates. |
| Whole-factory copies | Import policy is adapt-by-pattern, not mirror-by-folder. |

## Sanitization Rules

- Customer-facing templates must not contain private source-owner names.
- Examples may contain placeholders, but not real client/course identifiers.
- Generated runtime files must preserve Agentic OS additions: approvals, run logs, Notion workspace guardrails, automation maturity, doctor checks, and additive update contracts.
