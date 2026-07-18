# Execution Fabric Runbook

1. Confirm the installed definition reports `enabled = false` and
   `runtime.queue_mode = "filesystem"`.
2. Inspect the existing run queue through the runtime operator surface.
3. Before activation, validate backend readiness, named-queue routing, worker
   limits, provider limits, lease recovery, dead letters, and rollback.
4. Run `agentic-os runtime queue-mode plan execution_fabric --root <root>`.
5. Activate only with `agentic-os runtime queue-mode apply execution_fabric --root <root> --apply`.
6. Verify the `codex`, `claude`, and `non_llm` queues and worker pools in
   `agentic-os runtime queue-mode status --root <root>` and Command Center.
7. Run one supervisor tick with representative Codex, Claude, non-LLM,
   quiet-run, and registered-watcher work. Confirm no more than five background
   leases run, provider caps hold, and the interactive reserve remains one.
8. Confirm `queue_worker_health_report` is enabled and its latest receipt shows
   remediation and notification results when an unhealthy fixture is injected.
9. Refresh the resource registry and validate the installed root after changes.

Rollback returns the selector to `filesystem`; it does not discard in-flight or
historical records without a separately approved migration plan.
