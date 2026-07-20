---
schema_version: 1
provider: jira
artifact_type: spike
mode: compose
format: {renderer: jira_adf, task_lists: native}
approval: {write: explicit}
readback: [issue_key, issue_type, rendered_description]
---

# Jira Spike Addendum

Use the configured Spike issue type when present; otherwise require an explicit
mapped task type and retain the spike identity in the title/labels.
