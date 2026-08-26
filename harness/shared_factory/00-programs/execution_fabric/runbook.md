# Execution Fabric Runbook

1. Run `agentic-os runtime config show --root <root> --json`, then
   `agentic-os runtime config status --root <root> --json`. Record the
   effective source/fingerprint and confirm `runtime.queue_mode = "filesystem"`
   unless a reviewed activation receipt says otherwise.
2. Inspect the existing run queue through the runtime operator surface.
3. Before activation, validate backend readiness, named-queue routing, worker
   limits, provider limits, lease recovery, dead letters, and rollback.
4. Run `agentic-os runtime config validate --root <root>`, followed by
   `agentic-os runtime queue-mode plan execution_fabric --root <root>`.
5. Activate only with `agentic-os runtime queue-mode apply execution_fabric --root <root> --apply`.
   After local/degraded configuration edits, preview then apply
   `agentic-os runtime config reconcile --root <root> [--apply]`. For remote
   policy, validate, record the fingerprint, then use
   `runtime config reload --expected-fingerprint <sha256> [--apply]`. Preserve
   the observer pre-read and server reload receipt; both current and candidate
   fingerprints are fenced before activation.
6. Verify the `codex`, `claude`, `pr_reviews`, `los_environment`,
   `los_fullsail`, and `non_llm` queues and their worker pools in
   `agentic-os runtime snapshot --root <root>` and Command Center. Use
   `--queue codex --status queued`, `--json`, or `--output <receipt.json>` for
   focused and durable evidence.
7. Run one supervisor tick with representative Codex, Claude, non-LLM,
   quiet-run, and registered-watcher work. Confirm no more than five background
   leases run, provider caps hold, and the interactive reserve remains one.
8. Confirm `queue_worker_health_report` is enabled and its latest receipt shows
   remediation and notification results when an unhealthy fixture is injected.
9. Run `agentic-os runtime config diff`, refresh the resource registry, and
   validate the installed root after changes.

For remote mode, also run `agentic-os runtime status --root <root> --json` and
verify that API, observer, healer, effect DLQ, repair-receipt, and alarm-backlog
state is projected through the existing effects/healing/alarms fields. Confirm
the API role has no reconciliation loop, the observer cannot repair, and the
healer cannot send notifications. Test one filtered effect claim, repeated
projection failures to DLQ, explicit replay, an expired claim recovery, a
stale-epoch rejection, and a bigmac alarm-dispatch receipt.

For every representative task, open its task detail and prove that
`run-report.json` is `available` with an `s3://` URI, exact SHA-256, size,
content type, task ID, and attempt ID. Confirm the worker's local artifact spool
is empty after recovery. Inject object-store unavailability once: queue
execution must retain the local report, the observer must open an
`object_store_unavailable` finding and alarm intent, and publication must
recover without copying any object credential onto the worker.

Before enabling promotion, run
`installers/execution-fabric/bin/reconcile-artifact-replication.sh`, then
`artifact-replication-health.sh`. Read back the durable receipt and verify both
canary directions are within `FABRIC_ARTIFACT_REPLICATION_MAX_LAG_SECONDS`.
Promotion and failback deliberately reject receipts older than
`FABRIC_ARTIFACT_REPLICATION_RECEIPT_MAX_AGE_SECONDS`. After either host is
rebuilt, reconcile/resync replication and obtain a new receipt before declaring
that host standby-ready.

Hard-primary-loss takeover additionally requires
`validate-backup-health-receipt.sh` to prove a fresh restore-manifest-verified
backup. Degraded authority must be enabled independently in witness runtime,
host runtime, and canonical `execution_fabric.degraded_primary` policy. Inspect
`degraded-primary.receipt.json`, the leadership snapshot's `authorityMode` and
`degradedUntil`, and the sticky `execution-fabric-degraded-primary` alert. The
scheduler and any task/effect absent from the canonical allowlists remain
fenced. Treat expiry as a mutation-plane stop, not an alert-only deadline.

Verify each server-side worker bootstrap map entry has a unique `bootstrapId`,
token, and worker ID and exactly matches its configured host, pool, queue set,
capability set, and concurrency. Test one valid registration and one peer
impersonation rejection. After initial bootstrap, promotion, or failback, read
the leadership snapshot's `durability` block and the
`postgres-durability.receipt.json`; do not declare the mutation plane active
unless both prove either (a) `remote_apply` with one streaming synchronous
standby or (b) a still-valid signed degraded authority plus local PostgreSQL
`on`/`fsync`/`full_page_writes`/WAL-archive proof. Only case (a) is normal.

Manual failback is:

1. `failback.sh --prepare`
2. `failback.sh --reseed --preparation-file <reseed-authorization.json>`
3. `failback.sh --plan --preparation-file <reseed-authorization.json>`
4. `failback.sh --approve --operator <identity>`
5. `failback.sh --apply --approval-file <approval.json>`

Preserve every phase receipt. A preparation authorizes only target reseed; a
transfer plan is created only after measured target eligibility.

Rollback returns the selector to `filesystem`; it does not discard in-flight or
historical records without a separately approved migration plan.
