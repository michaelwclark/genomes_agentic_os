---
schema_version: 1
provider: notion
artifact_type: daily-handoff
mode: compose
format: {renderer: notion_enhanced_markdown, callouts: true, columns: true, task_lists: true}
approval: {write: explicit}
readback: [workspace, parent_page, page_id, title, rendered_sections]
---

# Notion Daily Handoff Addendum

Lead with date/health and decisions needed. Use columns for completed versus
next, a blocker callout, and task items only for real owner actions.
