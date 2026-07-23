---
schema_version: 1
provider: any
artifact_type: task
mode: compose
required_sections:
  - Scope
  - Acceptance Criteria
format:
  renderer: markdown
approval:
  write: explicit
---

# Good Task Contract

Name one bounded deliverable, its owner/dependencies, the reason it exists, and
the proof of completion. A task should be independently actionable and should
not hide product behavior that belongs in a story or bug.
