---
schema_version: 1
provider: jira
artifact_type: epic
mode: compose
required_sections:
  - Outcome
  - Problem
  - Scope
  - Workstreams
  - Acceptance Criteria
  - Non-Goals
format:
  renderer: jira_adf
approval:
  write: explicit
validation:
  - child_map_and_dependencies_present
---

# Jira Epic Addendum

Use the epic as the outcome and sequencing contract. List child workstreams by
capability, show dependency/rollout order, and define an epic-level closeout
check that cannot be satisfied merely because all children reached Done.
