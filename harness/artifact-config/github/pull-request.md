---
schema_version: 1
provider: github
artifact_type: pull-request
mode: compose
required_sections:
  - Description of the Feature or Problem
  - Description of the Change
  - Associated Work
  - Test Evidence
  - Risk
format:
  renderer: github_markdown
approval:
  write: explicit
readback:
  - pull_request_number
  - head_sha
  - base_branch
  - rendered_body
---

# GitHub Pull Request Addendum

Verify base branch and head SHA. Use checkboxes only for actual author actions;
do not pre-check evidence that was not performed. Call out migrations, feature
flags, tenant/config interaction, operational rollout, and rollback when
relevant.
