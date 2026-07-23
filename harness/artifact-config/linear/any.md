---
schema_version: 1
provider: linear
artifact_type: any
mode: compose
destination:
  resolver: configured_linear_team
format:
  renderer: linear_markdown
approval:
  write: explicit
validation:
  - team_and_parent_verified
readback:
  - identifier
  - team
  - rendered_description
---

# Linear Standard

Keep the issue compact: outcome/problem, decisive context, acceptance, risks,
and links. Use projects and initiatives for hierarchy instead of duplicating a
large plan in every issue. Verify team, status, project/initiative, cycle,
labels, priority, and assignee after writing.
