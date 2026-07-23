---
schema_version: 1
provider: jira
artifact_type: subtask
mode: compose
format: {renderer: jira_adf, task_lists: native}
approval: {write: explicit}
readback: [issue_key, parent_key, rendered_description]
---

# Jira Subtask Addendum

Verify the parent key and configured subtask issue type. Keep acceptance
criteria native and independently testable.
