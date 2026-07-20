---
schema_version: 1
provider: notion
artifact_type: incident-report
mode: compose
format: {renderer: notion_enhanced_markdown, severity_callout: true, timeline_table: true, action_table: true}
approval: {write: explicit}
readback: [workspace, parent_page, page_id, title, rendered_sections]
---

# Notion Incident Addendum

Show severity/current status, impact, mitigation, and next update first. Use a
timestamped timeline and owned action table; keep hypotheses visibly labeled.
