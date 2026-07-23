---
schema_version: 1
provider: github
artifact_type: any
mode: compose
destination:
  resolver: configured_repository
format:
  renderer: github_markdown
approval:
  write: explicit
validation:
  - repository_and_target_verified
  - no_local_or_private_workspace_references
readback:
  - number_or_comment_id
  - repository
  - rendered_body
---

# GitHub Standard

Write for the engineering team: behavior, code contract, test/check evidence,
risk, rollout, and linked public/team-visible work. Never expose local paths,
private workspace pages, internal harness terms, credentials, or raw logs.
