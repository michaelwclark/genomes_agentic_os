---
schema_version: 1
id: investigation-report
kind: output
title: Investigation report
priority: 70
applies_to:
  outputs: [investigation-report]
outputs:
  - normalized signal
  - environment and deployed version
  - facts and source receipts
  - hypotheses and contradictions
  - conclusion, confidence, and gaps
---

# Investigation report output

Produce a compact decision-grade report. Lead with the conclusion, environment,
version, and confidence. Preserve the signal, facts, hypotheses, disconfirming
evidence, gaps, and next owner. Render through the provider/type artifact
contract before any external write.
