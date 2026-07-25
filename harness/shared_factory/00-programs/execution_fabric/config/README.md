# Execution Fabric configuration ownership

This program directory contains no editable queue or worker-pool catalog.
`harness/config/execution-fabric.yml` is the only mutable instance policy and
owns task routes, named queues, worker pools, admission, scheduling, leases,
and retries.

The program's `schemas/` directory contains compatibility contracts only.
Installed package schemas are upgraded under `harness/schemas/` through the
package checksum manifest. Use:

```text
agentic-os runtime config show
agentic-os runtime config status
agentic-os runtime config diff
agentic-os runtime config validate
```

Use guarded `runtime config reconcile` for local/degraded SQLite and guarded
`runtime config reload` for the remote control plane. Do not add a second
`queues.yml`, `worker-pools.yml`, host registry, or alert registry here.
