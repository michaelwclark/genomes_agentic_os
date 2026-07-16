# Operator Resource Query

Use `agentic-os operator-resource` when an operator surface needs typed,
read-only Program or Automation state from an installed Agentic OS root.

```bash
agentic-os operator-resource query program --root <os-root>
agentic-os operator-resource get program <exact-resource-id> --root <os-root>
agentic-os operator-resource query automation --root <os-root>
agentic-os operator-resource get automation <exact-resource-id> --root <os-root>
```

The command emits `operator-resource-query/v1` JSON. It reads canonical local
definitions, instances, configuration, schedules, queue receipts, and logs. It
never mutates files, probes remote hosts, dispatches work, or resolves a display
name as an identity.

Program joins require an exact `definition_id`. Automation health is durable
evidence plus freshness, not a host or process liveness claim. Inspect
`diagnostics` and `summary.partial` before presenting a result as complete.
