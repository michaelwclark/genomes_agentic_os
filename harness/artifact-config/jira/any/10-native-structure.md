---
schema_version: 1
provider: jira
artifact_type: any
mode: compose
format: {renderer: jira_adf, headings: native, task_lists: native}
validation: [adf_renders_without_markdown_artifacts, project_and_issue_type_verified]
readback: [issue_key, issue_type, rendered_description]
---

# Jira Native Structure

Use Jira-native ADF headings, lists, code blocks, tables, links, and task items.
Read the issue back after create/update and verify semantic structure, not only
the API response.
