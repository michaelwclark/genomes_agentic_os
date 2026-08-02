# Execution Fabric Control Plane

Portable, generic task coordination for Genomes Agentic OS. PostgreSQL is the
canonical ledger. BullMQ on Valkey is a reconstructable delivery index and
wakeup path. Workers may run on any authorized host and use the versioned HTTP
contract; they do not require a shared filesystem.

This package deliberately contains no project, Jira, LOS, deployment-
environment, or agent-skill types. Those belong in producers and workers.

## Guarantees

- Idempotent admission by `(namespace, idempotencyKey)`. Reusing a key with a
  different request is rejected; a same-request duplicate returns durable task
  truth and never republishes delivery.
- Durable task, run, attempt, event, worker, and external-effect-outbox rows in
  PostgreSQL.
- Attempts are immutable terminal history: each records its worker session,
  lease duration/expiry, timing, result or error; run snapshots expose that
  attempt history and any associated external-effect provider receipt.
- Atomic claims using `FOR UPDATE SKIP LOCKED`.
- Per-worker concurrency limits and capability-aware assignment.
- Worker registration leases, task attempt leases, lease tokens, and monotonic
  fabric epochs fence late or split-brain completion.
- Deterministic expired-lease reconciliation. Work is requeued only inside its
  retry budget; exhausted work is dead-lettered.
- BullMQ jobs contain only task identifiers and can be rebuilt from queued
  PostgreSQL rows.
- Completion and external effects commit in one database transaction. Effect
  keys are globally unique so a separate effect executor can be idempotent.
- API serving, health observation, deterministic healing, and Agentic OS alarm
  delivery are separate roles. None of them is hidden inside a request-serving
  process loop.
- Health findings, alarm intents, repair receipts, and operator actions are
  versioned PostgreSQL records. Automatic repairs are allow-listed, fenced,
  idempotent, cooldown-limited, budgeted, and verified before and after.
- Effect projection has bounded attempts, exponential backoff, expired-claim
  recovery, dead-letter state, and explicit replay. A consumer must declare
  the effect types it owns before it can claim anything.
- Clean SIGINT/SIGTERM shutdown and bounded long polling.

The transport is at-least-once. Every worker operation and external effect must
therefore be idempotent. A successful HTTP response is not authorization to
repeat an effect under a new key.

## Configuration

Queue, pool, admission, concurrency, capability, lease, and retry policy has
exactly one mutable source:
`harness/config/execution-fabric.yml`. It is validated with the shipped
`schemas/execution-fabric.schema.json` contract. Compose mounts both files
read-only. `FABRIC_` environment variables are reserved for host bindings,
dependency endpoints, secret-file references, and process tuning; they do not
override queue policy.

Required:

| Variable | Meaning |
| --- | --- |
| `FABRIC_HOST_ID` | Stable identity of the control-plane host |
| `FABRIC_DATABASE_URL` | PostgreSQL connection URL |
| `FABRIC_VALKEY_URL` | Valkey/Redis-compatible connection URL |
| `FABRIC_API_TOKEN_FILE` | File containing the worker/producer/metrics bearer token |
| `FABRIC_ADMIN_TOKEN_FILE` | File containing the separate operator bearer token |
| `FABRIC_POLICY_CONFIG_FILE` | Read-only canonical instance policy path |
| `FABRIC_POLICY_SCHEMA_FILE` | Read-only shipped schema path used in provenance |
| `FABRIC_CLUSTER_ID` | Witness cluster identity |
| `FABRIC_LEADERSHIP_API_BASE` | Independent witness HTTPS base |
| `FABRIC_LEADERSHIP_TOKEN_FILE` | File containing the read-only witness status token |
| `FABRIC_LEADERSHIP_CANDIDATE_TOKEN_FILE` | File containing this host's unique witness candidate token |
| `FABRIC_CANDIDATE_REPORT_INTERVAL_SECONDS` | Bounded local PostgreSQL candidate report interval |
| `FABRIC_CANDIDATE_HEARTBEAT_MAX_AGE_SECONDS` | Maximum successful candidate heartbeat age |
| `FABRIC_RELIABILITY_SOURCE_TOKENS_FILE` | JSON object mapping each external observation source to a unique token |
| `FABRIC_LEADERSHIP_PUBLIC_KEY_FILE` | File containing the pinned Ed25519 public key |

Important optional settings:

| Variable | Default | Meaning |
| --- | ---: | --- |
| `FABRIC_PORT` | `3180` | HTTP port |
| `FABRIC_QUEUE_PREFIX` | `agentic-os:fabric` | BullMQ key/queue namespace |
| `FABRIC_LEASE_SECONDS` | `120` | Attempt lease |
| `FABRIC_WORKER_TTL_SECONDS` | `45` | Worker registration lease |
| `FABRIC_LONG_POLL_MS` | `15000` | Claim long-poll ceiling |
| `FABRIC_OBSERVER_INTERVAL_MS` | `15000` | Durable finding evaluation cadence |
| `FABRIC_HEALER_INTERVAL_MS` | `15000` | Allow-listed deterministic repair cadence |
| `FABRIC_HEALER_COOLDOWN_SECONDS` | `60` | Minimum repeat-repair cooldown |
| `FABRIC_HEALER_MAX_REPAIRS_PER_HOUR` | `30` | Per-action hourly repair budget |
| `FABRIC_HEALER_ALLOW_ACTIONS` | three deterministic recovery actions | Comma-separated subset of `reconcile_expired_attempts`, `reconstruct_delivery`, and `recover_effect_claim`; unknown actions fail startup |
Secrets are accepted by file reference, never by a committed config value.
Both tokens must contain at least 32 non-whitespace characters and must differ;
startup fails closed otherwise. The API token is accepted only by ordinary
`/api/v1/**` routes and `/metrics`. The admin token is accepted only by
`/api/v1/admin/**`. Health, readiness, and OpenAPI remain unauthenticated for
orchestration and contract discovery.

The service exposes the applied SHA-256 fingerprint and its exact source.
Every admission, worker registration, and claim rechecks the on-disk policy.
An invalid edit or unapplied drift closes those mutation paths. Reload is
explicit through `POST /api/v1/admin/config/reload`; changing a database-wide
fingerprint requires all queued/running work and live workers to be drained.
PostgreSQL stores the active fingerprint, so replicas with different policy
cannot independently admit or claim work.

## Local development

Node 22, PostgreSQL 16+, and Valkey 7.2+ are expected.

```bash
npm ci
cp .env.example .env
npm run migrate
npm run typecheck
npm test
npm run start:api
npm run start:observer
npm run start:healer
```

Those three commands are independent long-running roles over one PostgreSQL
truth plane. The API role never starts the observer or healer loop. Alarm
delivery is a fourth, host-local Agentic OS path:
`installers/execution-fabric/bin/dispatch-alarms.sh`.

Run the opt-in dependency-backed test only against disposable services:

```bash
FABRIC_INTEGRATION_TESTS=1 \
FABRIC_TEST_DATABASE_URL=postgresql://... \
FABRIC_TEST_VALKEY_URL=redis://... \
npm run test:integration
```

## Worker protocol

1. `POST /api/v1/workers/register` with stable worker/host IDs, accepted queues,
   capabilities, and maximum concurrency.
2. Heartbeat before the returned worker lease expires. Include active attempt
   IDs so their leases renew with the worker.
3. `POST /api/v1/assignments/claim`. A `204` means capacity/work is unavailable;
   it is not an error.
4. Execute the task idempotently.
5. Complete or fail with the exact `workerId`, `leaseToken`, and `fabricEpoch`
   from the assignment. A `409 fenced` means the result is stale and must not
   produce effects.

Task completion may stage external effect intents:

```json
{
  "workerId": "worker-a",
  "leaseToken": "00000000-0000-0000-0000-000000000000",
  "fabricEpoch": 7,
  "result": {"summary": "done"},
  "effects": [{
    "effectKey": "notification:task-id:completed",
    "effectType": "notification.send",
    "payload": {"channel": "operator"},
    "maxAttempts": 5,
    "baseBackoffSeconds": 60
  }]
}
```

The effect executor is intentionally separate from task execution. It claims
with `POST /api/v1/effects/claim` and a non-empty `effectTypes` allow-list. A
consumer may never claim globally and skip effects it does not own, because
that would poison unrelated leases. It performs the effect idempotently using
`effectKey` and submits provider readback to
`POST /api/v1/effects/{effectId}/deliver`. Failed delivery is returned through
the sibling `/fail` route. PostgreSQL increments `attemptCount`, applies the
larger of the caller delay and bounded exponential backoff, and moves the
effect to `dead_lettered` at `maxAttempts`.

Every worker, producer, effect executor, snapshot client, and metrics scraper
must send `Authorization: Bearer <FABRIC_API_TOKEN_FILE contents>`. It must not
reuse the admin token.

## Monitoring

- `GET /healthz`: process liveness only.
- `GET /readyz`: PostgreSQL and Valkey readiness.
- `GET /metrics`: API-token-protected Prometheus/OpenMetrics counters, latency, queue depth,
  running count, worker count, plus Node process metrics.
- `GET /api/v1/snapshots/queues`: canonical depth and oldest queued age.
- `GET /api/v1/snapshots/workers`: live/offline workers, host, capacity, and
  running count.
- `GET /api/v1/snapshots/runs?limit=200`: bounded recent run/task sample.
- `GET /api/v1/snapshots/reliability`: durable finding, alarm, and repair
  lifecycle counts plus last observer/healer timestamps.
- `GET /api/v1/status`: versioned, single-read operator view of queues,
  workers, runs, effects, alarms, healer state, HA leadership, and effective
  policy source/fingerprint/drift.
- `POST /api/v1/admin/reconcile`: authenticated immediate expiry/delivery
  repair. Normal repair scheduling belongs only to the healer role.
- `POST /api/v1/admin/config/reload`: validate and activate a changed canonical
  policy, or fail closed with a drain-required conflict.
- `POST /api/v1/admin/findings/{findingId}/acknowledge`: acknowledge one
  durable incident without deleting its history.
- `POST /api/v1/admin/effects/{effectId}/replay`: idempotently replay an
  explicit failed/dead-lettered/cancelled effect at the current epoch.
- `POST /api/v1/admin/tasks/{taskId}/cancel` and `/requeue`: fenced,
  receipt-backed task repair.
- `POST /api/v1/admin/queues/{queue}/drain`: cancel only queued work with a
  durable operator receipt.

The observer covers expired attempts, missing BullMQ delivery, dead workers,
queues without live capacity, policy fingerprint drift, expired effect claims,
and effect projection failures. It opens or revises findings and stages
deduplicated alarm intents; it performs no repair and sends no notification.
The healer consumes only `expired_attempts`, `missing_delivery`, and
`expired_effect_claims` findings by default. Dead workers, missing capacity,
config drift, and definitive projection failures remain visible/operator-owned.
The separate bigmac dispatcher claims the alarm outbox and passes it through
the canonical `runtime.execution_fabric.health` Agentic OS notifier policy.

Recommended alarms:

- readiness is non-200 for two consecutive probes;
- no live worker for a required queue;
- oldest queued age exceeds the queue SLO;
- dead-letter count increases;
- reconcile failures or sustained delivery reconstruction;
- worker lease churn or running attempts near expiry;
- PostgreSQL replica lag exceeds the configured failover RPO.

## Recovery and HA

Valkey is not restored as truth. On an empty/replaced Valkey, start the API,
observer, and healer roles. The observer records missing deliveries; the
healer republishes every eligible queued PostgreSQL task using the task UUID as
the BullMQ job ID and stores a verified repair receipt.

The independently deployable provider-neutral witness uses one durable SQLite
authority on a third host to implement conditional leadership arbitration,
candidate evidence, monotonic witness epochs, and Ed25519-signed
promotion/failback receipts. The control plane continuously reports its local
candidate evidence, verifies short-lived signed witness proofs, and self-fences
readiness plus every admission, claim, completion, effect, repair, and
configuration mutation before proof expiry.

A promoted host must supply the signed transfer receipt. Startup verifies the
signature, cluster, leader, epoch, receipt ID, expiry, policy digest, and current
witness readback, then transactionally advances `fabric_state.current_epoch`.
The same transaction fences old attempts/workers, requeues interrupted tasks,
and re-epochs undelivered effects. PostgreSQL also rejects mutations unless its
leader ID and lease match the serving host. A restarted former primary cannot
serve after witness leadership moved.

Workers use the per-host gateway on port 3181. It discovers the current leader
only from the signed witness status, follows promotion without worker config
edits, and uses a cached route only until its signed proof expires. A health
check alone never changes routing or leadership. Failback is always manual,
uses the same signed receipt bootstrap, and enforces a configurable recovery
hold before readiness.

## API compatibility

The public worker and operator API is `/api/v1`. `GET /openapi.json` is the
machine-readable contract. Breaking changes require a new API version; additive
fields may be introduced within v1.

## Portable run artifacts

Workers write their full run report locally first, then register a bounded
artifact against the exact task and attempt. The control plane returns a
short-lived, single-object PUT URL; object-store credentials never leave the
service. Finalization reads the stored object and verifies its actual SHA-256
and size before PostgreSQL marks the artifact available. A claimed digest in
HTTP metadata is not accepted as integrity evidence.

Use `GET /api/v1/tasks/{taskId}` for run detail including artifact metadata,
`GET /api/v1/snapshots/artifacts` for counts and object-store health, and
`GET /api/v1/artifacts/{artifactId}/download` for a short-lived download.
Workers copy failed publications into a durable spool with immutable SHA-256
and size metadata. The manifest holds the opaque `attemptRecoveryToken`, which
is useless without a current registration token for the same durable worker.
Replacement pods with that workload identity request a fresh PUT grant, retry
bounded batches with exponential backoff, and quarantine corrupt or exhausted
records. Spool pending, due, and quarantine counts are merged into worker and
session heartbeat metadata for central monitoring. Never put registration or
lease bearer tokens, MinIO keys, command environment, or arbitrary task
payloads in artifact metadata.
