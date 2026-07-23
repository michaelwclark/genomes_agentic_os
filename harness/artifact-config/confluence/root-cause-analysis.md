---
schema_version: 1
provider: confluence
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
  renderer: confluence_markdown
approval:
  write: explicit
---

# Confluence RCA Addendum

Use the established incident/RCA parent and labels. Link prior related RCAs and
follow-up tickets, but keep the current causal chain and corrective actions
self-contained enough to remain useful when external links age.
