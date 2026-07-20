---
schema_version: 1
provider: github
artifact_type: comment
mode: compose
format: {renderer: github_markdown}
approval: {write: explicit}
readback: [repository, object_id, comment_id, rendered_body]
---

# GitHub Comment Addendum

Be specific to the diff, check, or decision. Link exact evidence and avoid
duplicating status already visible in checks.
