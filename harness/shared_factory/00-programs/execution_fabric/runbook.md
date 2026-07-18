# Execution Fabric Runbook

1. Confirm the installed definition reports `enabled = false` and
   `runtime.queue_mode = "filesystem"`.
2. Inspect the existing run queue through the runtime operator surface.
3. Before activation, validate backend readiness, named-queue routing, worker
   limits, provider limits, lease recovery, dead letters, and rollback.
4. Change mode only through the future guarded configuration command; never
   edit live queue state to simulate activation.
5. Refresh the resource registry and validate the installed root after changes.

Rollback returns the selector to `filesystem`; it does not discard in-flight or
historical records without a separately approved migration plan.
