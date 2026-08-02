---
schema_version: 1
provider: any
artifact_type: pull-request
mode: compose
required_sections:
  - Linked Work
  - Summary
  - Change Scope
  - Safety, Compatibility, and Rollout
  - Validation
  - Reviewer Focus
validation:
  - linked_work_has_tracker_hyperlink
format:
  renderer: markdown
approval:
  write: explicit
---

# Universal Pull Request Contract

Start every PR with a `## Linked Work` section containing at least one visible
Markdown hyperlink to its source tracker work item. Resolve the tracker from
the supplied work item: Jira keys use their Jira browse URL, Linear issue
identifiers use their Linear issue URL, and GitHub-backed work uses its issue
URL. A bare ticket key, a plain URL, a placeholder, or an unrelated GitHub PR
link is not sufficient.

Explain the outcome, the bounded implementation scope, safety and compatibility
implications, exact validation evidence, and the decisions reviewers should
inspect. Keep generated/internal receipts out of team-visible text.
