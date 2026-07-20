---
schema_version: 1
provider: any
artifact_type: incident-report
mode: compose
required_sections: [Status and Severity, Impact, Timeline, Detection, Mitigation, Current Risk, Owners and Next Update]
format: {renderer: markdown}
approval: {write: explicit}
validation: [timestamps_are_explicit, facts_and_hypotheses_are_separate]
---

# Good Incident Report

Prioritize current impact, mitigation, and next update. During an incident,
label hypotheses and unknowns; reserve causal certainty for the subsequent RCA.
