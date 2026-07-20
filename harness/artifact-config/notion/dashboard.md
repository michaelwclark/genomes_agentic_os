---
schema_version: 1
provider: notion
artifact_type: dashboard
mode: compose
format: {renderer: notion_enhanced_markdown, callouts: true, columns: true, metric_tables: true}
approval: {write: explicit}
readback: [workspace, parent_page, page_id, title, rendered_sections]
---

# Notion Dashboard Addendum

Use a health callout, small KPI cards/tables, trends, and exception/action
tables. Every metric displays definition, source, and freshness.
