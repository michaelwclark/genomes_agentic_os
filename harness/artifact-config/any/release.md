---
schema_version: 1
provider: any
artifact_type: release
mode: compose
required_sections: [Release Identity, Included Changes, Compatibility, Validation, Rollout, Rollback, Known Risks]
format: {renderer: markdown}
approval: {write: explicit}
validation: [release_identity_is_verified, rollback_is_actionable]
---

# Good Release

Pin the exact tag, commit, artifacts, and target. Explain compatibility,
validation, rollout sequence, rollback condition, and known risk without
repeating every implementation detail.
