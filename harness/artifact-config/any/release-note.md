---
schema_version: 1
provider: any
artifact_type: release-note
mode: compose
required_sections:
  - Summary
  - Changes
  - Upgrade or Rollout Notes
format:
  renderer: markdown
approval:
  write: explicit
---

# Good Release Note Contract

Describe user/operator impact, compatibility, migrations or rollout steps,
risk, verification, and known limitations. Use released versions and verified
links; do not infer deployment from a merged branch.
