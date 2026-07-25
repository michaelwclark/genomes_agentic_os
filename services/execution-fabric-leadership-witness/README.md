# Execution Fabric Leadership Witness

This service is the independent arbiter for Execution Fabric leadership. Its
canonical runtime is a digest-pinned OCI image on a declared host outside both
leadership candidates. The default durable store is local SQLite in a mounted
volume. The release artifact contains no cloud-provider runtime or deployment
adapter.

Two candidate hosts cannot safely decide which one should lead after a
partition. If no independent witness host exists, configure
`WITNESS_MODE=manual_fail_closed`: no witness starts, automatic promotion stays
disabled, and the topology makes no split-brain-safety claim.

## Safety guarantees

- The service binds to the exact `WITNESS_TAILSCALE_IP`; there is no wildcard
  bind default. The portable runner uses the host network and verifies the
  address belongs to the declared witness host before activation.
- `WITNESS_HOST_ID` must differ from every candidate identity. Candidate-token
  configuration must name at least two unique candidates and exclude the
  witness host.
- Status uses the read-only bearer token in `WITNESS_READER_TOKEN_FILE`.
  Candidate reports use the exact host-scoped token from
  `WITNESS_CANDIDATE_TOKENS_FILE`. Promotion, failback, and audit use the
  operator token in `WITNESS_ADMIN_TOKEN_FILE`.
- Reader, candidate, admin, and Ed25519 signing credentials are distinct and
  file-backed. The private signing key exists only in the independent witness;
  control planes and gateways receive only the public key.
- Promotion requires the expected leader and epoch, expiry of the current
  leader's complete proof-lease window, and a fresh healthy candidate inside
  the configured replica-lag, timeline, WAL, and config-digest bounds.
- Each transfer uses a caller-owned `promotionId`, increments the epoch exactly
  once, and atomically stores an identity-bound signed fence receipt. Exact
  replays and receipt lookup recover a lost API response without a second CAS.
- Failback is always manual. Its short-lived one-use plan is bound to a
  separately recorded operator approval and consumed atomically.
- Policy rotation is prepare/commit and fail-closed. A fresh, healthy,
  non-leader streaming candidate must prove the candidate digest was replayed
  from PostgreSQL on the prepared timeline and upstream system.
- SQLite mutations commit the complete state and immutable audit stream under
  `BEGIN IMMEDIATE`, WAL, and `synchronous=FULL` before an API mutation returns.
  The numeric container identity alone can access the mounted state and copied
  secrets. A renewable storage lease fences duplicate or paused processes.
- First startup requires `WITNESS_BOOTSTRAP_ONCE=true`. Initialization writes a
  cluster-bound sentinel and verified recovery backup. A missing database,
  sentinel, backup, corrupt file, or stale local version fails readiness closed.

## Storage

The provider-neutral default is:

```text
WITNESS_STATE_FILE=/var/lib/execution-fabric-witness/witness.sqlite3
WITNESS_BOOTSTRAP_ONCE=true
```

Mount `/var/lib/execution-fabric-witness` on durable host storage and back up
the database, `.initialized` sentinel, and `.backup` recovery copy as one
authority set. Restore never becomes authoritative merely
because a file exists: verify the last leader, epoch, audit tail, candidate
configuration, public key, and drill receipt before reconnecting candidates.

## API

| Method | Route | Credential | Purpose |
| --- | --- | --- | --- |
| `GET` | `/healthz` | none | Process liveness only |
| `GET` | `/readyz` | none | Durable-store readback readiness |
| `GET` | `/openapi.json` | none | Versioned contract |
| `GET` | `/api/v1/admin/leadership/status` | Reader | Leader, epoch, candidates, promotion gate |
| `PUT` | `/api/v1/admin/leadership/candidates/{candidate}` | Matching candidate | Measured replication and config observation |
| `POST` | `/api/v1/admin/leadership/promote` | Admin | Idempotent conditional promotion |
| `GET` | `/api/v1/admin/leadership/promotions/{promotionId}` | Admin | Crash/retry receipt lookup |
| `POST` | `/api/v1/admin/leadership/config-digest-rotations/prepare` | Admin | Prepare fenced policy rotation |
| `POST` | `/api/v1/admin/leadership/config-digest-rotations/commit` | Admin | Commit from causal standby proof |
| `POST` | `/api/v1/admin/leadership/config-digest-rotations/abort` | Admin | Resolve expired pre-database preparation |
| `POST` | `/api/v1/admin/leadership/failback-plan` | Admin | Create short-lived manual plan |
| `POST` | `/api/v1/admin/leadership/failback-commit` | Admin | Consume approval-bound failback |
| `GET` | `/api/v1/admin/leadership/audit` | Admin | Durable audit history |

All state-changing receipts use
`apiVersion: execution-fabric-leadership/v1`. Status responses carry a
short-lived signed leadership proof. Consumers verify cluster, leader, epoch,
receipt ID, expiry, policy digest, and Ed25519 signature before admitting work.

## Development

```bash
npm ci
npm run typecheck
npm test
npm run build
npm audit --audit-level=moderate
```

The portable installer, preflight, health monitor, alert path, and operations
runbook live under `deploy/execution-fabric/witness/`.
