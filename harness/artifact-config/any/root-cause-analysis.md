---
schema_version: 1
provider: any
artifact_type: root-cause-analysis
mode: compose
required_sections:
  - Summary
  - Impact
  - Timeline
  - Root Cause
  - Contributing Factors
  - Corrective Actions
  - Prevention and Detection
  - Evidence
  - Evidence Gaps
  - Confidence
format:
  renderer: markdown
approval:
  write: explicit
validation:
  - causal_claims_are_evidence_backed
  - actions_have_owner_and_verification
---

# Good RCA Contract

An RCA explains the causal chain, not only the failed component. Distinguish
trigger, root cause, contributing conditions, blast radius, detection/recovery,
and why existing safeguards did not prevent or surface the problem sooner.
Corrective actions need owners, priority, verification, and prevention/detection
coverage. Avoid blame and unsupported certainty.
