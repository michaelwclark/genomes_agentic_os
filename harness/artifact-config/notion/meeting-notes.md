---
schema_version: 1
provider: notion
artifact_type: meeting-notes
mode: compose
format: {renderer: notion_enhanced_markdown, callouts: true, action_table: true, toggles: true}
approval: {write: explicit}
readback: [workspace, parent_page, page_id, title, rendered_sections]
---

# Notion Meeting Notes Addendum

Put decisions and action table before discussion. Collapse transcript-like
detail and omit unnecessary personal/sensitive content.
