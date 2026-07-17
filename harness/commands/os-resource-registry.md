# First-Class Resource Registry

Use the materialized top-level registry for fast operator and GUI discovery of
Automations, Programs, Workflows, Rules, Reports, Skills, and Commands.

```bash
agentic-os resource-registry query --ensure --root <os-root>
agentic-os resource-registry query --kind workflow --domain los --root <os-root>
agentic-os resource-registry refresh --root <os-root>
```

`query` reads only
`harness/registries/first-class-resources.json`; it never scans domains or
projects. `--ensure` performs a refresh only when the snapshot is missing.
`refresh` is the governed reconciliation boundary: it discovers registered and
filesystem-backed resources across system, domain, and project scopes, joins
the richer Program and Automation projections, and replaces the snapshot
atomically.

The snapshot reports exact diagnostic totals (`diagnostics`, `info`,
`warnings`, `errors`, and `by_diagnostic_code`) and marks `partial` only when a
warning or error exists. Diagnostics include stable repair metadata so operator
surfaces can explain the affected resource, path, repair class, and next action.
Health is intentionally limited to `not_applicable`, `unobserved`, `disabled`,
`healthy`, `degraded`, and `unhealthy`, with an evidence basis and explicit
liveness-observed flag; static rules, skills, commands, reports, and workflow
documents are `not_applicable`, not artificially healthy.

Agentic OS registry authoring refreshes the snapshot after a successful apply.
Operator surfaces should invalidate and refresh after other governed authoring
or publishing operations. Manual filesystem edits require an explicit refresh.
The snapshot is derived state: source definitions and scoped registries remain
the authoring authorities.
