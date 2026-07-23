---
schema_version: 1
provider: any
artifact_type: dashboard
mode: compose
required_sections: [Purpose, Current Health, Key Measures, Exceptions, Trends, Actions]
format: {renderer: markdown}
approval: {write: explicit}
validation: [measures_have_timestamp_and_source, status_thresholds_are_defined]
---

# Good Dashboard

Show health and exceptions before detail. Every measure needs a source,
timestamp, definition, and threshold. Prefer a small set of consequential
signals over activity counts.
