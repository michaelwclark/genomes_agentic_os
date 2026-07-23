---
schema_version: 1
provider: notion
artifact_type: decision-record
mode: compose
format: {renderer: notion_enhanced_markdown, decision_callout: true, comparison_table: true}
approval: {write: explicit}
readback: [workspace, parent_page, page_id, title, rendered_sections]
---

# Notion Decision Addendum

Use a decision/status callout and option comparison table. Link affected
systems/work only after verifying the target workspace and visibility.
