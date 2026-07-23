---
schema_version: 1
provider: notion
artifact_type: workflow-documentation
mode: compose
required_sections:
  - What It Does
  - When It Runs
  - Inputs and Outputs
  - Flow
  - Failure Handling
  - Manual Run
  - Receipts
format:
  renderer: notion_enhanced_markdown
  flow_images: required
approval:
  write: explicit
---

# Notion Workflow Addendum

Open with an operator callout and a flow image. Put detailed states, commands,
receipts, and failure modes in tables or toggles so the common path stays easy
to scan. Link child pages for provider or domain-specific detail.
