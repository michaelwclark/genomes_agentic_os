---
schema_version: 1
provider: github
artifact_type: release
mode: compose
format: {renderer: github_markdown}
approval: {write: explicit}
readback: [repository, tag, release_id, target_commit, published_state]
---

# GitHub Release Addendum

Verify tag/target commit and attached artifacts. Keep user-impacting changes,
compatibility, rollout, and known issues above implementation details.
