---
schema_version: 1
provider: any
artifact_type: test-plan
mode: compose
required_sections: [Quality Risks, Test Matrix, Environments and Data, Scenarios, Regression, Observability, Entry and Exit Criteria]
format: {renderer: markdown}
approval: {write: explicit}
validation: [scenarios_trace_to_risk, environment_and_data_are_reproducible]
---

# Good Test Plan

Start from behavior and risk. Cover positive, negative, boundary, permission,
failure, recovery, compatibility, and regression paths at the cheapest layer
that proves each claim.
