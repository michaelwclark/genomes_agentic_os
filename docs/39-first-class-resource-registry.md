# First-Class Resource Registry and Tags

The first-class resource registry is the fast local projection used by desktop
and operator surfaces. A normal query reads one atomic JSON snapshot and never
rescans the installed OS tree:

```bash
agentic-os resource-registry query --ensure --root ~/agentic_os
agentic-os resource-registry query --kind automation --domain los --root ~/agentic_os
```

`refresh` is the explicit reconciliation boundary. It discovers source-backed
resources, joins runtime evidence, and atomically replaces
`harness/registries/first-class-resources.json`.

## Custom tags

Operator-defined tags never modify the generated snapshot directly. They live
in the guarded `first-class-resource-tags/v1` overlay and are keyed by the exact
stable resource ID returned by a query.

```bash
agentic-os resource-registry tags add \
  --resource-id skill:harness:registries:skills.yml:review \
  --tag "Needs Review" --root ~/agentic_os
agentic-os resource-registry tags list \
  --resource-id skill:harness:registries:skills.yml:review --root ~/agentic_os
agentic-os resource-registry tags remove \
  --resource-id skill:harness:registries:skills.yml:review \
  --tag needs-review --root ~/agentic_os
```

Tags normalize to lowercase kebab case, deduplicate, and reject unsupported or
path-like input. Add/remove operations serialize through a local file lock,
atomically persist the overlay, refresh the materialized snapshot, and write a
mutation receipt. A resource exposes both its merged `tags` and explicit
`tag_provenance.derived` / `tag_provenance.custom` arrays.

Deleting or hand-editing the generated snapshot is never the tag workflow.
Rollback one tag with the matching `remove` operation; restore a full prior
overlay from normal filesystem backup only when repairing a damaged overlay.
