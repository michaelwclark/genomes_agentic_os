---
schema_version: 1
provider: filesystem
artifact_type: any
mode: compose
destination:
  resolver: routed_artifact_folder
format:
  renderer: markdown
approval:
  write: none
safety:
  verify_target: true
  readback_required: true
readback:
  - relative_target
  - content_hash
---

# Filesystem Standard

Write to the routed work-item, run, project, workflow, or program artifact
folder. Use stable names and relative references in portable receipts. Never
overwrite unrelated user content; atomic writes and content-hash readback are
required.
