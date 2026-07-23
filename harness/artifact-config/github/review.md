---
schema_version: 1
provider: github
artifact_type: review
mode: compose
format: {renderer: github_markdown}
approval: {write: explicit}
readback: [repository, pull_request, review_id, review_state, rendered_body]
---

# GitHub Review Addendum

Use request-changes only for blocker-grade correctness, security, data, or
contract failures. Inline comments stay tightly scoped; the summary records the
decision, validation, and residual risk.
