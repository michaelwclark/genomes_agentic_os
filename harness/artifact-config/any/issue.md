---
schema_version: 1
provider: any
artifact_type: issue
mode: compose
required_sections:
  - Summary
  - Acceptance Criteria
format:
  renderer: markdown
approval:
  write: explicit
---

# Good Issue Contract

Use an issue when the provider does not require a narrower type. State the
problem or outcome, bounded scope, required evidence, observable completion,
risks, and dependencies. Prefer the narrower bug/story/task contract whenever
the intent is known.
