---
schema_version: 1
provider: any
artifact_type: qa-failure
mode: compose
required_sections:
  - Failed Scenario
  - Observed Behavior
  - Expected Behavior
  - Environment
  - Evidence
format:
  renderer: markdown
approval:
  write: explicit
---

# Good QA Failure Contract

Record the exact scenario, data class, environment and deployed version,
expected/observed results, reproducibility, evidence, and whether the failure
appears to be product code, configuration/rules, test data, test automation, or
environment infrastructure. Preserve uncertainty until investigated.
