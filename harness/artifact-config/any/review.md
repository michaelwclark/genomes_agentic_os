---
schema_version: 1
provider: any
artifact_type: review
mode: compose
required_sections: [Decision, Findings, Evidence, Validation, Residual Risk]
format: {renderer: markdown}
approval: {write: explicit}
validation: [findings_are_actionable, severity_matches_impact]
---

# Good Review

Lead with approve, request changes, or blocked. Findings identify affected
behavior, concrete evidence, impact, and the smallest safe correction. Separate
blockers from non-blocking suggestions and record what was actually validated.
