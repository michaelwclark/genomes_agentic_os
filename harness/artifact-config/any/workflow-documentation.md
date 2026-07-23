---
schema_version: 1
provider: any
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
  renderer: markdown
approval:
  write: explicit
---

# Good Workflow Documentation Contract

Explain the workflow from the operator's perspective, then show inputs,
outputs, states/flow, decision gates, failure/retry/pause/resume behavior,
manual command and chat skill, receipts, and handoffs. Include a readable visual
for any multi-step or branching workflow.
