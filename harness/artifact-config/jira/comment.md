---
schema_version: 1
provider: jira
artifact_type: comment
mode: compose
required_sections: []
format:
  renderer: jira_adf
approval:
  write: explicit
readback:
  - comment_id
  - rendered_comment
---

# Jira Comment Addendum

Use a short opening sentence, then only the evidence and next action that
changed. For closeout, name validation, PR/merge/deploy state, remaining risk,
and owner. Avoid private workspace links and local receipt paths.
