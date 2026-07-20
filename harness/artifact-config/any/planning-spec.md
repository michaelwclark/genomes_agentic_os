---
schema_version: 1
provider: any
artifact_type: planning-spec
mode: compose
required_sections:
  - Problem
  - Goals
  - Non-Goals
  - Proposed Behavior
  - Failure Handling
  - Acceptance Criteria
  - Validation
format:
  renderer: markdown
approval:
  write: explicit
---

# Good Planning Spec Contract

Make the problem and operator/customer outcome clear before architecture.
Define boundaries, source-of-truth decisions, behavior/state, security and
failure recovery, compatibility/migration, observability, rollout, measurable
acceptance, and unresolved decisions. Prefer diagrams for non-trivial flow.
