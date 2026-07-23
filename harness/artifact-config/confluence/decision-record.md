---
schema_version: 1
provider: confluence
artifact_type: decision-record
mode: compose
format: {renderer: confluence_markdown, decision_panel: true, comparison_table: true}
approval: {write: explicit}
readback: [space, parent_page, page_id, title, rendered_sections]
---

# Confluence Decision Addendum

Use a decision/status panel and concise options/consequences table. Link the
affected design and delivery work.
