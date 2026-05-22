# Templates

Templates are copied into an installed OS under `shared_factory/05-knowledge/templates/` and then filled with domain-specific information.

Agents should not invent new document shapes when a template exists. They should copy the template, fill the required fields, and leave irrelevant optional sections empty or marked `not_applicable`.

## Template Groups

| Group | Purpose |
| --- | --- |
| `domain/` | Domain setup, room context, and context-loading boundaries. |
| `room/` | Customer/operator room context, routing tables, read/skip rules, output folders, and room-local tool routing. |
| `stage/` | Stage contracts for numbered pipelines where one stage output becomes the next stage input. |
| `reference/` | Naming conventions, tool indexes, style/output rules, source priority, and decisions. |
| `profile/` | Customer OS profile shape for room/domain discovery and generated installs. |
| `customer/` | Customer discovery, automation-fit, and handoff templates for custom OS builds. |
| `workflow/` | Repeatable process specs, outcome briefs, alignment questions, PRDs, implementation plans, dispatch handoffs, progress files, context packs, run logs, and approvals. |
| `automation/` | Triggered process specs, permissions, and failure policies. |
| `notion/` | Notion control-plane mapping, page structure, and bootstrap templates. |
| `memory/` | Memory policy for durable agent context. |
| `planning/` | Feature specs and future-idea capture for OS product work. |

The installed OS should not create root-level `templates/`, `workflows/`, or `automations/` folders for active work. Reusable templates belong in `shared_factory`; active workflow and automation specs belong under the selected domain.

Run `agentic-os validate-source --source <repo>` before install or sync to confirm required Codex config sources are present. Missing profile-layer configs are warning-level until the layer profile templates are installed.
