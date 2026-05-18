# Templates

Templates are copied into an installed OS and then filled with domain-specific information.

Agents should not invent new document shapes when a template exists. They should copy the template, fill the required fields, and leave irrelevant optional sections empty or marked `not_applicable`.

## Template Groups

| Group | Purpose |
| --- | --- |
| `domain/` | Domain setup and context boundary. |
| `workflow/` | Repeatable process specs, context packs, run logs, and approvals. |
| `automation/` | Triggered process specs, permissions, and failure policies. |
| `notion/` | Notion control-plane mapping and page structure. |
| `memory/` | Memory policy for durable agent context. |
