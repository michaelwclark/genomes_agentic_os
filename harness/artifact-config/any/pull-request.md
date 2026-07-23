---
schema_version: 1
provider: any
artifact_type: pull-request
mode: compose
required_sections:
  - Description of the Feature or Problem
  - Description of the Change
  - Associated Work
  - Test Evidence
  - Risk
format:
  renderer: markdown
approval:
  write: explicit
---

# Good Pull Request Contract

Explain why the behavior was wrong or missing, what invariant the change now
enforces, why this code seam owns it, how it was tested, and the operational or
compatibility risk. Link the source work item and keep generated/internal
receipts out of team-visible text.
