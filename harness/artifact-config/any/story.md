---
schema_version: 1
provider: any
artifact_type: story
mode: compose
required_sections:
  - User Outcome
  - Scope
  - Acceptance Criteria
  - Non-Goals
format:
  renderer: markdown
approval:
  write: explicit
validation:
  - outcome_is_user_or_operator_visible
  - acceptance_criteria_are_testable
---

# Good Story Contract

Frame the valuable outcome, not a preselected implementation. Bound the actors,
workflow, state changes, integrations, data/permission behavior, failure
handling, observability, and explicit non-goals. Acceptance criteria should let
product, engineering, and QA agree whether the outcome exists.
