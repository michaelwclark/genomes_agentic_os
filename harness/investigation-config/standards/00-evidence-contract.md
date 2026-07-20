---
schema_version: 1
id: evidence-contract
kind: standard
title: Evidence contract
priority: 0
requirements:
  facts_before_inference: true
  competing_hypotheses: true
  disconfirming_evidence: true
  explicit_unknowns: true
  confidence_required: true
---

# Evidence contract

Preserve the original signal before interpreting it. Label observations as
facts only when a source supports them. Keep inference, hypothesis, and causal
claim distinct. Seek evidence that could disprove the leading explanation and
record contradictions instead of smoothing them over. A bounded, low-
confidence conclusion with explicit gaps is better than unsupported certainty.
