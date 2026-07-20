---
schema_version: 1
provider: notion
artifact_type: any
mode: compose
destination:
  resolver: verified_genomes_notion_parent
format:
  renderer: notion_enhanced_markdown
  table_of_contents: true
  visual_hierarchy: rich
approval:
  write: explicit
validation:
  - genomes_notion_identity_verified
  - scannable_visual_hierarchy
readback:
  - page_id
  - parent_id
  - rendered_page
---

# Notion Standard

Create a useful page, not a Markdown dump. Start with a one-screen executive
summary or callout, add a table of contents for long pages, use columns/tables/
toggles/callouts where they clarify relationships, and break large programs
into navigable child pages. Use diagrams or images for multi-step flows. Verify
the parent is Genome's Notion before writing and fetch the page after creation.
