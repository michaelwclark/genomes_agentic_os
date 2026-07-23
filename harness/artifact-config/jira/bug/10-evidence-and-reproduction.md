---
schema_version: 1
provider: jira
artifact_type: bug
mode: compose
required_evidence: [environment, affected version, observed evidence]
validation: [reproduction_is_deterministic_or_gap_is_explicit, evidence_is_sanitized]
---

# Bug Evidence Module

Pin environment and running version. State minimal reproduction, actual/expected
behavior, frequency, blast radius, and evidence limitations. Link the Detective
receipt when causal analysis exists; do not promote hypotheses to facts.
