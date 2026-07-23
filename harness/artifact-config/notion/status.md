---
schema_version: 1
provider: notion
artifact_type: status
mode: compose
format: {renderer: notion_enhanced_markdown, callouts: true, status_table: true, toggles: true}
approval: {write: explicit}
readback: [workspace, parent_page, page_id, title, rendered_sections]
---

# Notion Status Addendum

Use an outcome/health callout, a compact state table, and a two-column split for
delivered versus next. Put receipts and detailed evidence in toggles.
