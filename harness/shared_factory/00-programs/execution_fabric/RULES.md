# Execution Fabric Rules

- Ship inactive: `enabled = false`.
- Preserve compatibility: `runtime.queue_mode = "filesystem"` until explicit activation.
- Never infer activation from the presence of this directory.
- Route all managed producers through one selected queue mode; do not dual-write silently.
- Keep mutable queue, lease, attempt, worker, and heartbeat data outside this definition.
- Require bounded concurrency, idempotency, leases, backpressure, and dead-letter behavior before enabling the managed mode.
- Preserve operator-modified installed configuration during source-package updates.
- Treat `harness/config/execution-fabric.yml` as the one editable instance
  configuration for queues, pools, admission limits, leases, and retries.
- Resolve release defaults, instance config, canonical host overlay, then
  invocation overlay. Merge queues and pools by stable `id`; host/invocation
  layers may tighten but never increase safety or capacity limits.
- Validate and fingerprint that file before use. Reconcile it only while
  `execution_fabric` is the selected writer and only inside the shared
  queue-mode mutation guard plus one SQLite transaction.
- Reuse `config/hosts.yml` or `harness/config/hosts.yml` for host identity,
  `harness/registries/hosts-routing.yml` for routing, and
  `harness/registries/alerts.yml` for alert policy. Never create Execution
  Fabric-specific copies of those registries.
- Keep task execution, health observation, deterministic healing, and alarm
  dispatch in independent roles over one durable ledger. The API must not run
  an automatic reconcile loop; the observer must not mutate business state;
  the healer must not deliver notifications.
- Keep scheduling as an independently supervised role. Persist each occurrence
  before admission and require deterministic idempotency plus current leader,
  lease, and epoch fencing for every scheduler mutation.
- Treat worker registrations as immutable sessions and associate each attempt
  with its exact session. Do not overwrite historical session evidence.
- Bind every bootstrap credential to one durable bootstrap ID and its exact
  worker, host, pool, queues, capabilities, and concurrency. Never use one
  global worker-registration bearer or let a credential register a peer.
- Require every effect consumer to claim a non-empty allow-list of effect
  types it owns. Bind its distinct static credential to the exact consumer ID,
  source, and effect-type allow-list. Never claim globally and skip unrelated
  effects.
- Keep the observer credential GET-only. Alarm dispatchers use a separate
  credential bound to dispatcher ID and source. Effect/alarm deliver and fail
  calls use the short-lived claim token, never the static claim credential.
- Promotion and failback require a fresh accepted leader WAL baseline,
  matching PostgreSQL system ID, a streaming/fresh receiver, and a candidate
  replay position inside the configured upstream byte gap. Never infer
  currency from a zero local receive/replay gap.
- Keep PostgreSQL mutation admission fenced until the local database is primary
  and readback proves `remote_apply`, a non-empty synchronous standby target,
  and at least one streaming synchronous standby. Bootstrap may be asynchronous
  only while the application mutation plane remains fenced.
- Split failback into a state-bound standby-reseed authorization followed by a
  fresh eligibility-checked transfer plan. Never require a transfer plan in
  order to create the standby whose eligibility that plan must prove.
- Bound effect attempts and backoff, recover expired claims, dead-letter at the
  configured limit, and replay only through an idempotent, admin-authenticated,
  current-epoch operator receipt.
- Automatic healing is restricted to configured allow-listed actions with
  current-leader/epoch fencing, idempotency, cooldown, hourly budget, and
  persisted before/after verification. Config drift, missing worker capacity,
  and definitive effect failures remain operator-visible unless a separately
  reviewed repair is added.
