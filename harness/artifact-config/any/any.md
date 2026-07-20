---
schema_version: 1
provider: any
artifact_type: any
mode: compose
destination:
  resolver: configured_target
required_sections: []
required_evidence:
  - source identity
  - evidence timestamp
optional_sections:
  - Facts
  - Evidence
  - Inference
  - Recommendations
  - Evidence Gaps
  - Confidence
prohibited_content: []
format:
  renderer: markdown
approval:
  draft: none
  write: explicit
validation:
  - required_sections_present
  - facts_distinct_from_inference
  - audience_safe
readback:
  - target_identity
  - rendered_content_hash
safety:
  sanitize_external_output: true
  verify_target: true
  readback_required: true
  block_secrets: true
  block_local_paths: true
  block_private_links: true
---

# Universal Artifact Standard

Lead with the outcome the intended reader needs. Preserve source facts,
timestamps, environment/tenant/version context when relevant, and the limits of
the available evidence. Keep facts, inference, recommendations, and unanswered
questions visibly distinct.

Use concrete, skimmable headings and compact lists. Do not expose local paths,
private workspace links, secrets, raw customer data, harness internals, or
unbounded logs in an external artifact. A successful write is not complete
until the intended target and rendered result are read back.
