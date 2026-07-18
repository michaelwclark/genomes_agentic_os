# Execution Fabric Rules

- Ship inactive: `enabled = false`.
- Preserve compatibility: `runtime.queue_mode = "filesystem"` until explicit activation.
- Never infer activation from the presence of this directory.
- Route all managed producers through one selected queue mode; do not dual-write silently.
- Keep mutable queue, lease, attempt, worker, and heartbeat data outside this definition.
- Require bounded concurrency, idempotency, leases, backpressure, and dead-letter behavior before enabling the managed mode.
- Preserve operator-modified installed configuration during source-package updates.
