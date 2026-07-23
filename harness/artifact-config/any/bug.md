---
schema_version: 1
provider: any
artifact_type: bug
mode: compose
required_sections:
  - Observed Behavior
  - Expected Behavior
  - Reproduction
  - Impact
  - Acceptance Criteria
required_evidence:
  - affected version or environment when known
  - first observed timestamp when known
format:
  renderer: markdown
approval:
  write: explicit
validation:
  - reproduction_is_actionable
  - acceptance_criteria_are_observable
---

# Good Bug Contract

Describe the user-visible or system-visible failure without asserting an
unproven cause. Give the smallest deterministic reproduction, affected scope,
severity/impact, evidence, and any tenant/environment/version boundary. Write
acceptance criteria as observable repaired behavior plus important regression
guards. Put hypotheses in analysis, not in the bug title or facts.
