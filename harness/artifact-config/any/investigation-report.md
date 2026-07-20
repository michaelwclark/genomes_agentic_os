---
schema_version: 1
provider: any
artifact_type: investigation-report
mode: compose
required_sections:
  - Signal
  - Scope
  - Facts
  - Hypotheses
  - Conclusion
  - Evidence Gaps
  - Confidence
format:
  renderer: markdown
approval:
  write: explicit
validation:
  - deployed_version_identified_for_environment_scope
  - facts_and_inference_separated
---

# Good Investigation Report Contract

Preserve the original allegation, then show scope, deployed-version authority,
timeline, facts, contradictions, competing hypotheses, disconfirming evidence,
conclusion, confidence, and remaining gaps. “Most likely” is not “confirmed.”
