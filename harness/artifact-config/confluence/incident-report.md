---
schema_version: 1
provider: confluence
artifact_type: incident-report
mode: compose
format: {renderer: confluence_markdown, status_panel: true, timeline_table: true, action_table: true}
approval: {write: explicit}
readback: [space, parent_page, page_id, title, rendered_sections]
---

# Confluence Incident Addendum

Lead with severity/current state and impact. Use timestamped timeline and owned
action tables; link the subsequent RCA when causal analysis is complete.
