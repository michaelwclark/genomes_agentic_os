---
schema_version: 1
provider: confluence
artifact_type: meeting-notes
mode: compose
format: {renderer: confluence_markdown, decision_panel: true, action_table: true}
approval: {write: explicit}
readback: [space, parent_page, page_id, title, rendered_sections]
---

# Confluence Meeting Notes Addendum

Place decisions/actions first and link owners. Keep discussion compressed and
avoid publishing sensitive transcript detail.
