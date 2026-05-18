# Diagrams

Diagrams in this repo should be SVG or PNG.

Do not use Mermaid for durable documentation here. The intended publishing targets include Notion and agent-readable markdown, and SVG/PNG assets are easier to preserve consistently across those surfaces.

## Available Diagrams

| Diagram | Use It For |
| --- | --- |
| [Value Flow](value-flow.svg) | Explaining why the OS exists and what improves after adoption. |
| [OS Lifecycle](os-lifecycle.svg) | Showing the core intake-to-next-action loop. |
| [Data Flow](data-flow.svg) | Showing source package, installed OS, control plane, work repos, memory, and future active state boundaries. |
| [Workflow And Automation Lifecycle](workflow-automation-lifecycle.svg) | Explaining how workflows, automations, approvals, and run logs relate. |
| [Storage Boundaries](storage-boundaries.svg) | Explaining what filesystem, Notion, database, and memory should own. |

## Authoring Rules

- Keep diagrams hand-authored as SVG unless there is a strong reason to use PNG.
- Keep text generic and public-safe.
- Do not embed secrets, private workspace names, private channel names, or private project names.
- Keep diagrams readable in GitHub, Notion exports, and local Markdown previews.
- If a diagram changes an operating concept, update the matching documentation page in the same change.
