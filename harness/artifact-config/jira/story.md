---
schema_version: 1
provider: jira
artifact_type: story
mode: compose
required_sections:
  - User Outcome
  - Scope
  - Acceptance Criteria
  - Non-Goals
format:
  renderer: jira_adf
approval:
  write: explicit
---

# Jira Story Addendum

Write the summary as a capability/outcome, not “implement X.” Make acceptance
criteria independently checkable and include permissions, errors, analytics,
and compatibility only when material. Link investigation and design evidence;
do not copy entire documents into the issue.
