---
schema_version: 1
provider: notion
artifact_type: program
mode: compose
required_sections:
  - Purpose
  - Outcomes
  - Workflow Map
  - Operating Model
  - Failure Handling
  - Metrics and Receipts
  - Archive Soon
format:
  renderer: notion_enhanced_markdown
  child_pages: required
  flow_images: required
approval:
  write: explicit
---

# Notion Program Addendum

The program home is a visual index, not the whole manual. Give each workflow a
child page and give complex workflow topics their own subpages. Use a minimum
flowchart image per workflow, compact status/ownership tables, callouts for hard
rules, and an explicit Archive Soon page for overlaps and migration status.
