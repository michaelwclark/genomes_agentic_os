---
schema_version: 1
provider: jira
artifact_type: task
mode: compose
required_sections:
  - Scope
  - Acceptance Criteria
format:
  renderer: jira_adf
approval:
  write: explicit
---

# Jira Task Addendum

Use tasks for bounded technical, operational, or documentation work. If the
work changes user-visible behavior, use a story or bug and make this a child.
