# Factory Patterns

The `/Users/genome/projects/factory` repository contains useful agent-native workspace patterns that should inform Genome's Agentic OS. These patterns should be adapted into durable product templates, not copied wholesale into customer installs.

## What To Preserve

| Factory Pattern | Agentic OS Use |
| --- | --- |
| Three-layer map/router/workspace model | Root router, room/domain router, and room `CONTEXT.md` contracts. |
| Short always-loaded map | Keep root `ROUTER.md`, `AGENTS.md`, `CLAUDE.md`, and `AGENT.md` concise. |
| Task routing table | Add `Task`, `Go To`, `Read First`, `Create Output In`, and `Optional Tools` to routers. |
| Room `CONTEXT.md` token-budget table | Require read-first, read-when-needed, skip/default exclusions, and tools by task. |
| Stage pipelines | Support numbered stage folders with explicit inputs, outputs, handoffs, and review checkpoints. |
| Skill integration points | Attach skills by room, task, stage, or format rather than listing them generically. |
| Naming conventions | Treat names as lightweight state and install naming templates. |
| Diagnostic builder skills | Make customer OS installs ask questions before creating rooms. |
| Client automation brief | Capture current manual workflow, systems, risk gates, pilot scope, rollback, and measurable value before building. |
| Automation fit matrix | Score whether a workflow should stay manual, become a documented workflow, or become a guarded automation. |
| Notion control plane shape | Use queue, runs, approvals, activity log, sources, and stable plan pages as the operator cockpit. |

## What To Avoid

- Do not install course or teaching commentary into customer runtime roots.
- Do not copy private/client-specific examples into public templates.
- Do not replace Agentic OS approvals, run logs, Notion control plane, or automation maturity with a simpler folder-only model.
- Do not force Genome's personal default domains into customer profiles.
- Do not copy customer-specific Notion IDs, course labels, or Clark's Consulting examples into generated customer roots.

## Import Policy

Use four categories:

| Category | Meaning |
| --- | --- |
| Copy | Generic templates safe for runtime installs. |
| Adapt | Valuable factory idea that needs Agentic OS vocabulary or safety rails. |
| Reference | Useful source material for docs/examples but not installed by default. |
| Reject | Stale, private, course-specific, or incompatible material. |

## Current Backlog

See:

- `PLANS/11-room-first-installer-and-routing.md`
- `PLANS/12-factory-template-import-backlog.md`
- `PLANS/13-reference-and-skill-index-layer.md`
- `PLANS/14-client-automation-and-control-plane-playbooks.md`
