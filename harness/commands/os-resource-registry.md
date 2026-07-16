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

Agentic OS registry authoring refreshes the snapshot after a successful apply.
Operator surfaces should invalidate and refresh after other governed authoring
or publishing operations. Manual filesystem edits require an explicit refresh.
The snapshot is derived state: source definitions and scoped registries remain
the authoring authorities.
