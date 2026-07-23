---
schema_version: 1
provider: any
artifact_type: subtask
mode: compose
required_sections: [Parent Outcome, Scope, Acceptance Criteria, Dependencies]
format: {renderer: markdown}
approval: {write: explicit}
validation: [independently_assignable, parent_link_is_explicit]
---

# Good Subtask

Describe one independently verifiable slice of its parent. State the parent
outcome, exact boundary, dependencies, deliverable, and acceptance evidence.
Do not copy the parent description or use a subtask as an unbounded catch-all.
