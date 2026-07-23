---
schema_version: 1
provider: jira
artifact_type: bug
mode: compose
required_sections:
  - Observed Behavior
  - Expected Behavior
  - Reproduction
  - Impact
  - Acceptance Criteria
format:
  renderer: jira_adf
approval:
  write: explicit
validation:
  - gherkin_when_it_clarifies_acceptance
---

# Jira Bug Addendum

Keep the summary symptom-first and searchable. Use a compact environment/
tenant/version table when scope varies. Put stack traces and raw logs in
attachments or evidence links, not the description. Use Gherkin only when it
makes conditional behavior more precise.
