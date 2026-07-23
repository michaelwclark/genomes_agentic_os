---
schema_version: 1
provider: confluence
artifact_type: any
mode: compose
destination:
  resolver: configured_confluence_space
format:
  renderer: confluence_markdown
approval:
  write: explicit
validation:
  - space_and_parent_verified
readback:
  - page_id
  - version
  - rendered_body
---

# Confluence Standard

Write durable team documentation with a clear owner, status, last-verified
date, source links, and audience. Prefer tables for timelines/actions and page
hierarchy for long subjects. Search for an existing canonical page before
creating another; link or update rather than fork knowledge.
