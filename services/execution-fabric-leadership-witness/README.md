# Execution Fabric Leadership Witness

This service is the independent arbiter for Execution Fabric leadership. It is
deliberately deployable outside both `genomesbox` and `bigmac`. DynamoDB is the
durable state and audit plane; conditional transactions prevent stale
promotions, split-brain leadership, epoch rollback, and failback-plan reuse.

## Safety guarantees

- Status uses the read-only bearer token in `WITNESS_READER_TOKEN_FILE`.
  Candidate reports use the exact host-scoped token from
  `WITNESS_CANDIDATE_TOKENS_FILE`. Promotion, failback, and audit use the
  operator token in `WITNESS_ADMIN_TOKEN_FILE`. Health, readiness, and OpenAPI
  remain available to orchestrators without credentials.
- Reader, candidate, admin, and Ed25519 signing credentials are distinct and
  file-backed. The private signing key exists only in the independent witness.
  Control planes and gateways receive only the public key.
- Promotion requires the expected leader and epoch, expiry of the current
  leader's full proof-lease window, and a fresh, healthy candidate inside the
  configured replica-lag and config-digest bounds. A negative health report
  raises an alarm but cannot revoke a still-valid leader proof.
- Each leadership transfer increments the epoch exactly once and returns an
  identity-bound, asymmetrically signed fence receipt. Only the digest is
  persisted with witness state.
- Failback is manual. A safe plan returns a short-lived, one-use token. Commit
  requires a separately recorded operator approval bound to the SHA-256 of that
  token, rejects stale approvals, and atomically consumes the plan.
- Candidate observations, rejected plans, plans, promotions, and failbacks are
  retained as immutable audit items. DynamoDB point-in-time recovery and table
  retention are enabled by the deployment template.

## API

| Method | Route | Credential | Purpose |
| --- | --- | --- | --- |
| `GET` | `/healthz` | Process liveness; no dependency claim |
| `GET` | `/readyz` | DynamoDB state readiness |
| `GET` | `/openapi.json` | Versioned contract |
| `GET` | `/api/v1/admin/leadership/status` | Reader | Leader, epoch, candidate eligibility, promotion gate |
| `PUT` | `/api/v1/admin/leadership/candidates/{candidate}` | Matching candidate | Measured PostgreSQL recovery, timeline, LSN, lag, and config observation |
| `POST` | `/api/v1/admin/leadership/promote` | Admin | Conditional monotonic promotion |
| `POST` | `/api/v1/admin/leadership/failback-plan` | Admin | Short-lived manual plan |
| `POST` | `/api/v1/admin/leadership/failback-commit` | Admin | Approval-bound, one-use failback |
| `GET` | `/api/v1/admin/leadership/audit` | Admin | Durable audit history |

All state-changing receipts use
`apiVersion: execution-fabric-leadership/v1`.
Every status response also carries a short-lived signed leadership proof.
Consumers verify the cluster, leader, epoch, receipt ID, expiry, and Ed25519
signature before admitting work or routing a worker request.

## Development

```bash
npm ci
npm run typecheck
npm test
npm run build
npm audit --audit-level=moderate
```

Unit and HTTP tests use the deterministic in-memory store. The production
adapter uses DynamoDB strongly consistent reads and conditional transactions.
The AWS deployment template and activation runbook live under
`deploy/execution-fabric/witness/`.

## Activation boundary

Source availability is not activation. An operator must deploy the digest-
pinned image into an AWS account/region independent from the two execution
hosts, provision the two secret values, restrict the HTTPS endpoint, report
both candidates, read back DynamoDB point-in-time recovery, and complete a
fenced drill. No AWS account ID, secret value, or default production account is
embedded here. Promotion eligibility requires a fresh report from an actual
PostgreSQL standby (`inRecovery=true`) on the expected timeline with measured
receive/replay LSN lag inside the configured bound.
