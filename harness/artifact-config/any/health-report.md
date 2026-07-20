---
schema_version: 1
provider: any
artifact_type: health-report
mode: compose
required_sections: [Overall Health, Scope, Signals, Degradations, Evidence, Recommended Actions]
format: {renderer: markdown}
approval: {write: explicit}
---

# Good Health Report

Use explicit green/amber/red criteria, fresh evidence, and bounded remediation.
Call unknown health unknown rather than inferring green from missing alerts.
