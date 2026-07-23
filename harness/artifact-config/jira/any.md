---
schema_version: 1
provider: jira
artifact_type: any
mode: compose
destination:
  resolver: configured_jira_project
format:
  renderer: jira_adf
  headings: native
  task_lists: native
approval:
  write: explicit
validation:
  - project_and_issue_type_verified
  - jira_native_rendering
readback:
  - issue_key
  - issue_type
  - rendered_description
---

# Jira Standard

Use Jira-native headings, lists, task lists, links, and code/preformatted blocks
when they improve scanning. Verify project, issue type, parent/epic linkage,
components, priority, labels, fix version, assignee, and workflow state rather
than copying assumptions from a draft. After writing, fetch the issue and check
the rendered description and important fields.
