# Factory Patterns Inventory

This document categorizes factory-derived assets — from `~/projects/factory` — by how they were treated when building `genomes_agentic_os`. The four categories below reflect the decision made for each source at import time.

- **Copied** — content transferred verbatim (or with minor name-changes) into a template or doc.
- **Adapted** — pattern, structure, or constraint adopted but reworded, renamed to Agentic OS vocabulary, or generalized away from course-specific context.
- **Referenced** — not imported; documented here so future contributors know the pattern exists.
- **Rejected** — explicitly not imported, with reason.

---

## Categorization Table

| Factory Source | Category | What Was Done | Agentic OS Artifact |
| --- | --- | --- | --- |
| `workspace-blueprint/CLAUDE.md` — layer-1 map, navigation, naming, token management | Adapted | Layer map concept → root `ROUTER.md` + harness `AGENTS.md` pattern. Token management language → `CONTEXT.md` What-to-Load tables. | `templates/room/CONTEXT.md`, `templates/room/router.md` |
| `workspace-blueprint/CONTEXT.md` — layer-2 task router with `Your Task / Go Here / You'll Also Need` | Adapted | Three-column router → `Task / Read First / Output` routing table in room `CONTEXT.md`. | `templates/room/CONTEXT.md`, `templates/room/routing-table.md` |
| `workspace-blueprint/*/CONTEXT.md` — room contracts with token-budget What-to-Load tables, folder structure, tools/skills, cross-room handoffs, anti-patterns | Adapted | Full load-contract section set (read-first, read-when-needed, do-not-load, tools/skills, output folders, done criteria) added to room template. Handoff and anti-pattern language generalized. | `templates/room/CONTEXT.md` |
| `workspace-blueprint/production/workflows/CONTEXT.md` — stage pipeline: input, also load, output, skills at stage, forward-only handoff | Adapted | Stage pattern → `templates/stage/stage-context.md`. Stage routing rows added to room routing table. | `templates/stage/stage-context.md` |
| `notion-drafts/os-folder-structure-guide.md` — generalized map/rooms/work model and starter context template | Adapted | Map → Rooms → Work naming encoded in docs and `install_profile_os`. Room-first profile concept. | `docs/15-customer-os-factory.md`, `room_profile.py` |
| `vault-toolkit/architectures/*` — client delivery, content production, small-business reference architectures | Referenced | Structural patterns noted; not directly templated because they are too business-specific for a generic installer. | — |
| `vault-toolkit/skill-starters/*` — diagnostic question sets | Referenced | Discovery question flow captured in `harness/commands/os-discover-rooms.md`. Full wizard-pack form deferred. | `harness/commands/os-discover-rooms.md` |
| `vault-toolkit/constraints/03-context-hygiene.md` — load only what the stage needs | Adapted | Load-contract fields (read-first / read-when-needed / do-not-load) placed in every room CONTEXT.md. Context audit skill captures the rule. | `templates/room/CONTEXT.md`, `harness/skills/context-audit/SKILL.md` |
| `vault-toolkit/constraints/06-layer-triage.md` — separate deterministic / rule-based / LLM-needed / human-judgment work | Adapted | Step-classification table added to `templates/customer/client-automation-brief.md`. Layer-triage procedure encoded in `harness/skills/client-automation-brief/SKILL.md`. | `templates/customer/client-automation-brief.md`, `harness/skills/client-automation-brief/SKILL.md` |
| `vault-toolkit/constraints/07-scaling-vs-automating.md` — scale by docs and stage contracts before automating judgment | Adapted | Automation-fit rules (good/bad first automation gates) encoded in `templates/customer/automation-fit-matrix.md` and brief skill. | `templates/customer/automation-fit-matrix.md`, `harness/skills/client-automation-brief/SKILL.md` |
| `vault-toolkit/constraints/08-handoff-readiness.md` — handoff checklist: map, context, stage contracts, references, decisions | Adapted | Handoff checklist → `templates/customer/customer-handoff-checklist.md`. | `templates/customer/customer-handoff-checklist.md` |
| `_notion_school/07-client-factory-playbook.md` — discovery questions, good/bad first automation filters, client brief fields, value metrics, data boundaries | Adapted | Brief fields → `templates/customer/client-automation-brief.md`. Discovery questions → `harness/commands/os-discover-rooms.md`. Fit filters → brief skill. Private/school context stripped. | `templates/customer/client-automation-brief.md`, `harness/skills/client-automation-brief/SKILL.md` |
| `_notion_school/08-skill-roadmap.md` — skill shapes for intake, planning, session closeout, context audit, memory distillation, client automation briefs | Referenced | Skill shapes are tracked in the installed project's canonical `work-items/` lifecycle. Three skills instantiated (`client-automation-brief`, `control-plane-bootstrap`, `context-audit`). Remaining shapes are future work. | `harness/skills/client-automation-brief/`, `harness/skills/control-plane-bootstrap/`, `harness/skills/context-audit/` |
| `_notion_clarks_consulting_school/04-notion-control-plane.md` — queue database shape, activity log fields, engine controls, stable planning page, anti-patterns | Adapted | Five-database control-plane shape and queue row fields encoded in `harness/skills/control-plane-bootstrap/SKILL.md`. Anti-patterns (don't make Notion the execution source of truth) added as workspace-verification guard. Clark's Consulting identifiers stripped. | `harness/skills/control-plane-bootstrap/SKILL.md` |
| `_notion_clarks_consulting_school/06-client-automation-playbook.md` — automation fit matrix, two-week pilot shape, customer deliverables, security notes, training path | Adapted | Fit matrix → `templates/customer/automation-fit-matrix.md`. Pilot shape → brief template `Pilot Scope` section. Security notes → `Data Boundaries` section. Training path deferred. | `templates/customer/automation-fit-matrix.md`, `templates/customer/client-automation-brief.md` |
| `_notion_agentic_operating_system_manual/*` — domain/lane source-of-truth model, workflow/automation layouts, practical walkthroughs | Referenced | Domain/lane model already encoded in `scaffold.py`. Workflow/automation layouts match existing `WORKFLOW_FILES` / `AUTOMATION_FILES`. Walkthroughs are candidate tutorial content. | `src/genomes_agentic_os/scaffold.py`, `docs/06-workflows.md`, `docs/07-automations.md` |

---

## Rejected Assets

| Factory Source | Reason |
| --- | --- |
| Course-specific Acme/Eduba example databases and workflow instances | Private course material. Installing course examples into customer OS roots would leak training-context identifiers. The `PRIVATE_TERMS` scrub in `customer.py` enforces this at generation time. |
| `_notion_clarks_consulting_school/*` — client-specific Notion database IDs and Clark's Consulting workspace credentials | Private client identifiers (`clarks_consulting`, `los`, `lenders`). Added to `PRIVATE_TERMS` in `customer.py`. Never templated into reusable assets. |
| Full instructor commentary and teaching narrative from school files | Teaching comments belong in docs or examples, not in generated runtime files. Preserved only as summarized patterns in plans and skills. |
| Pricing and ROI calculation worksheets | Business-specific; too variable to generalize into a reusable template without becoming misleading. Brief template retains `Metrics Baseline` for ROI inputs only. |
| Runtime job workers and webhook receivers from factory examples | Executable workers require a working approval gate, run log, and control-plane database to exist first. Deferred until those are established per customer. |

---

## Adapt, Do Not Copy — Rule Summary

Per the factory-template import work item in the installed OS:

1. Map factory vocabulary to Agentic OS vocabulary: Map → Router/AGENTS.md; Rooms → Domains with CONTEXT.md; Work → Projects/Workflows/Automations/Run logs.
2. Strip private, course-specific, and client-identifying names before any template is installed into a customer root.
3. Convert teaching comments into product docs or examples — never into generated runtime files.
4. Preserve Agentic OS additions (approvals, run logs, Notion control plane, automation maturity gates, doctor checks, update contract) when adapting simpler factory patterns.

---

## Related Plans

- Installed project factory-template import work item — source of the import policy and acceptance criteria this doc satisfies.
- Installed project client-automation/control-plane work item — playbook deliverables that complete the factory import.
