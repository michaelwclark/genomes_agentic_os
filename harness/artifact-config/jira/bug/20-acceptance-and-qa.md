---
schema_version: 1
provider: jira
artifact_type: bug
mode: compose
optional_sections: [Regression Risk, QA Matrix, Technical Notes]
validation: [acceptance_reverses_the_observed_failure, regression_scope_is_named]
---

# Bug Acceptance Module

Acceptance criteria prove the user-visible correction and retained behavior.
Include tenant/environment/data variants only when evidence says they matter.
