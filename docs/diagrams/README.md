# Diagrams

Committed diagrams are **PNG** (or hand-authored SVG). The repo stays Mermaid-free at the committed level: handbook diagrams are authored as Mermaid `.mmd` **sources that are gitignored** and rendered to PNG by `docs/architecture/tools/render-diagrams.sh` (which drives the local Chrome). The intended publishing targets include Notion and agent-readable markdown, and PNG/SVG assets preserve consistently across those surfaces.

Handbook page diagrams are named `<page-slug>-<name>.png` and live here alongside the legacy standalone SVGs listed below. Regenerate every PNG after editing any `.mmd` with `bash docs/architecture/tools/render-diagrams.sh`.

## Available Diagrams

| Diagram | Use It For |
| --- | --- |
| [Value Flow](value-flow.svg) | Explaining why the OS exists and what improves after adoption. |
| [OS Lifecycle](os-lifecycle.svg) | Showing the core intake-to-next-action loop. |
| [Data Flow](data-flow.svg) | Showing source package, installed OS, control plane, work repos, memory, and future active state boundaries. |
| [Workflow And Automation Lifecycle](workflow-automation-lifecycle.svg) | Explaining how workflows, automations, approvals, and run logs relate. |
| [Storage Boundaries](storage-boundaries.svg) | Explaining what filesystem, Notion, database, and memory should own. |
| [Cliefnotes System Map](cliefnotes-system-map.svg) | Showing how the Cliefnotes map, rooms, tools, memory, and control-plane concepts map to this OS. |
| [Cliefnotes Workflow Data Flow](cliefnotes-workflow-data-flow.svg) | Showing the source-derived flow from capture through outcome, questions, PRD, plan, dispatch, validation, and feedback. |

## Authoring Rules

- Author handbook diagrams as Mermaid `.mmd` (gitignored) and commit the rendered PNG; legacy standalone diagrams may remain hand-authored SVG.
- Keep text generic and public-safe.
- Do not embed secrets, private workspace names, private channel names, or private project names.
- Keep diagrams readable in GitHub, Notion exports, and local Markdown previews.
- If a diagram changes an operating concept, update the matching documentation page in the same change.
