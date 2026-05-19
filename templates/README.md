# Templates

Templates are copied into an installed OS under `shared_factory/05-knowledge/templates/` and then filled with domain-specific information.

Agents should not invent new document shapes when a template exists. They should copy the template, fill the required fields, and leave irrelevant optional sections empty or marked `not_applicable`.

## Template Groups

| Group | Purpose |
| --- | --- |
| `domain/` | Domain setup and context boundary. |
| `workflow/` | Repeatable process specs, context packs, run logs, and approvals. |
| `automation/` | Triggered process specs, permissions, and failure policies. |
| `notion/` | Notion control-plane mapping and page structure. |
| `memory/` | Memory policy for durable agent context. |

The installed OS should not create root-level `templates/`, `workflows/`, or `automations/` folders for active work. Reusable templates belong in `shared_factory`; active workflow and automation specs belong under the selected domain.
