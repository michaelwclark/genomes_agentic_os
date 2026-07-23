---
schema_version: 1
provider: notion
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
  renderer: notion_enhanced_markdown
  timeline_table: true
  action_database_or_table: true
approval:
  write: explicit
---

# Notion RCA Addendum

Use a severity/outcome callout, timeline table, causal-chain visual when useful,
and an action table with owner, priority, due state, verification, and linked
work. Put raw evidence in toggles or attachments; keep the causal narrative
readable.
