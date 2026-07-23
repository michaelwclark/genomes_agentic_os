---
schema_version: 1
provider: any
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
  renderer: markdown
approval:
  write: explicit
validation:
  - workstreams_have_coherent_boundaries
  - completion_is_measurable
---

# Good Epic Contract

Define one coherent outcome that needs multiple independently deliverable work
items. Explain why the current state is insufficient, what is in and out, the
dependency/sequence model, rollout and operational implications, and the
evidence that closes the epic. Do not use an epic as an unbounded bucket.
