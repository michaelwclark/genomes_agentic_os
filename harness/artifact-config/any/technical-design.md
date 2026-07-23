---
schema_version: 1
provider: any
artifact_type: technical-design
mode: compose
required_sections: [Problem, Context and Constraints, Proposed Design, Data and Interfaces, Failure Handling, Security and Privacy, Alternatives, Validation and Rollout]
format: {renderer: markdown}
approval: {write: explicit}
validation: [interfaces_are_explicit, failure_paths_are_designed]
---

# Good Technical Design

Explain the behavior and boundaries another engineer must reason about. Cover
data ownership, interfaces, invariants, failure/recovery, observability,
security, rollout, and rejected alternatives—not a file-by-file forecast.
