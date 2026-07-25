# Execution Fabric deployment

This directory is the portable deployment surface for the Agentic OS Execution
Fabric. It keeps deployment mechanics separate from the generic control-plane
service and from the one editable instance policy at
`harness/config/execution-fabric.yml`.

The production topology is:

- `genomesbox`: PostgreSQL primary, Valkey delivery index, MinIO artifact store,
  API, durable health observer, deterministic healer, and active gateway.
- `bigmac`: streaming PostgreSQL standby, empty/reconstructable Valkey, local
  artifact spool, observer, watchdog, and a stopped emergency control plane.
- Kubernetes workers: the compatibility path `helm/los-agents` contains the
  generic GAOS worker chart only. LOSMON environment/Jira handlers remain in a
  separate LOS domain image and deployment.

Every image reference is supplied by a generated image lock and must use an
immutable `@sha256:` digest. Compose refuses to start when an image variable is
missing. The source package deliberately does not invent release digests.

## Canonical configuration

Do not add host-specific queue-policy files here. Runtime installation consumes:

| Concern | Canonical source |
| --- | --- |
| queues, pools, admission, leases, retries | `harness/config/execution-fabric.yml` |
| host identity | `config/hosts.yml` or `harness/config/hosts.yml` |
| cross-host routing | `harness/registries/hosts-routing.yml` |
| alarm policy and destinations | `harness/registries/alerts.yml` |
| deployment-only environment | `/etc/genomes-agentic-os/execution-fabric/runtime.env` on Linux; `~/Library/Application Support/GenomesAgenticOS/execution-fabric/runtime.env` on macOS |
| runtime secrets | an operator-provisioned `secrets/` directory beside the runtime environment; never this repository |

The deployment environment selects endpoints, immutable images, storage, and
role. It does not redefine queues or alerts.

## Independent service roles

The shipped image has three explicit entrypoints:

| Role | Command | Responsibility |
| --- | --- | --- |
| API | `node dist/src/main.js` | admission, worker/effect protocol, snapshots, and authenticated operator APIs |
| observer | `node dist/src/observer-main.js` | read health state and persist/revise findings plus alarm intents |
| healer | `node dist/src/healer-main.js` | consume allow-listed findings and store bounded before/after repair receipts |

Compose runs these as `control-plane`, `observer`, and `healer` containers over
one PostgreSQL ledger. systemd and launchd include named role entries as well.
The API contains no automatic reconciliation loop. The alarm dispatcher is
also separate: bigmac launchd runs `dispatch-alarms.sh`, which leases durable
alarm intents and calls the canonical Agentic OS notifier.

## Network boundary

Published ports are bound to the explicit `FABRIC_TAILSCALE_IP`. PostgreSQL and
the control plane are not published on `0.0.0.0`. Internal container traffic
uses the private Compose network. Host firewalls and Tailscale ACLs must still
restrict the approved hosts.

| Port | Purpose |
| ---: | --- |
| 3180 | control-plane API, snapshots, metrics |
| 35432 (configurable) | PostgreSQL replication; host port is `FABRIC_POSTGRES_REPLICATION_PORT`, container port remains 5432 |
| 3190 | MinIO API |
| 3191 | MinIO console |

Valkey is never published. Its contents are a reconstructable delivery index,
not recovery truth.

MinIO stores portable worker run reports, not queue truth. `minio-init` creates
the configured `FABRIC_ARTIFACT_BUCKET` and installs the
`FABRIC_ARTIFACT_RETENTION_DAYS` lifecycle. The API holds MinIO credentials in
Docker secrets and gives workers only short-lived task/attempt uploads. Monitor
`GET /api/v1/snapshots/artifacts`; the observer raises
`object_store_unavailable` and `artifact_upload_failure` findings independently
from queue healing.

The observer has a deliberately smaller runtime contract than the API. It
receives PostgreSQL access, canonical policy files, cluster identity, and a
dedicated, configured-bucket-scoped read-only MinIO identity stored as
`artifact-observer-access-key`/`artifact-observer-secret-key`. It does not
receive Valkey, submitter, worker-bootstrap, administrator, effect-consumer,
alarm-dispatcher, reliability-source, or witness credentials, and it has no
egress network. Each persistence transaction locks and rechecks the active
PostgreSQL leader, epoch, and wall-clock lease immediately before commit, so a
former leader cannot create, resolve, or cancel health state after takeover.

Retention is deletion policy, not backup. Run
`reconcile-artifact-replication.sh` after both sites are reachable. It enables
bucket versioning and MinIO server-side replication in both directions,
including existing objects, deletes, delete markers, and metadata. Only the
witness leader writes, so the topology behaves as one active writer while
remaining safe when promotion changes the writer.

The per-host timer runs `artifact-replication-health.sh`: it captures MinIO
replication status, writes canaries through primary→standby and
standby→primary, measures their visible lag, and atomically records
`artifact-replication-health.json`. Promotion and failback reject a failed,
one-directional, or stale receipt. During an outage the last pre-outage receipt
is the RPO evidence; after failback, reconcile/resync backlog and obtain a new
two-direction canary receipt before restoring normal standby status.

The replication host port deliberately defaults to `35432`, because genomesbox
may already run a host PostgreSQL listener on `0.0.0.0:5432`. Set the same
`FABRIC_POSTGRES_REPLICATION_PORT` value in both hosts' canonical
`runtime.env`; bigmac uses it for `pg_basebackup` and for its own standby bind.
Container-to-container database URLs still use port `5432`. The operator-owned
`postgres-replication-pgpass` entry must name the genomesbox Tailscale address
and this configured host port.

## Profiles

```bash
# genomesbox
docker compose \
  -f compose.genomesbox.yml \
  --profile primary up -d

# bigmac warm data plane only
docker compose \
  -f compose.bigmac.yml \
  --profile standby up -d
```

The `promoted` profile on bigmac is intentionally not started by Compose or
launchd. `installers/execution-fabric/bin/promote.sh` must receive a successful
receipt from the versioned leadership API before it may promote PostgreSQL or
start the emergency control plane.

Both host profiles include the commandless `candidate-reporter` service. It
queries its local PostgreSQL instance for recovery state, timeline, receive and
replay LSNs, monotonic absolute WAL positions, upstream system identifier, WAL
receiver state/last-message time, byte lag, and database clock; fingerprints the mounted canonical
`harness/config/execution-fabric.yml`; and publishes only through that host's
candidate-scoped witness credential. Its bounded loop defaults to 30 seconds.
The Compose health check and the independent host
`candidate-reporter-health.sh` monitor require a successful heartbeat no older
than 75 seconds. The host monitor writes
`candidate-reporter-health.json` and raises the canonical
`runtime.execution_fabric.health` alert if the container, contract, mode, or
freshness fails.

The witness stores the last accepted active-leader WAL position as the upstream
baseline. A standby is ineligible when that baseline is missing or stale, its
receiver is disconnected/non-streaming, its upstream system ID differs, or its
replay position trails the leader baseline by more than the configured byte
limit. A zero local receive/replay gap is not proof of upstream currency.
Production PostgreSQL starts with `synchronous_commit=local` and no named
synchronous standby so initial bootstrap and promotion cannot deadlock before a
replica exists. The application mutation plane remains fenced in that state.
`enable-postgres-durable-primary.sh` first proves one streaming synchronous
standby, then enables and reads back `synchronous_commit=remote_apply`. Only
that measured state admits unrestricted mutations. For hard primary loss, an
operator can explicitly enable the two matching fail-closed controls
`WITNESS_ALLOW_DEGRADED_PRIMARY` and `FABRIC_ALLOW_DEGRADED_PRIMARY`.
Promotion then also requires fresh emergency-bundle, bidirectional artifact,
restore-verified backup, exact upstream WAL/RPO, and witness-lease evidence.
The signed witness token carries `authorityMode=degraded_primary` and a bounded
`degradedUntil`; PostgreSQL must prove `synchronous_commit=on`, `fsync=on`,
`full_page_writes=on`, and `archive_mode=on`. Canonical
`execution_fabric.degraded_primary` task/effect allowlists constrain work, and
the scheduler role remains supervised but its own authority check admits no
occurrence unless `degraded_primary.allow_scheduler` is enabled. The
independent sticky critical alert remains active until a standby is reseeded
and `remote_apply` is read back.

Observer, effect-consumer, alarm-dispatcher, reliability-source, worker,
submitter, and admin credentials are separate. `fabric-api-token` is GET-only.
The server-side worker bootstrap file is a JSON identity map keyed by stable
`bootstrapId`; each entry binds one unique token to the exact worker ID, host,
pool, queue set, capability set, and concurrency. A worker credential cannot
register a peer identity. Registration returns a short-lived session token for
heartbeat, claims, attempt completion, and artifact recovery.
Effect consumer JSON entries bind `{token, source, effectTypes}` to their map
key (consumer ID); alarm dispatcher entries bind `{token, source}`. Every token
must be globally unique. Claim delivery/failure calls then use the short-lived
claim token, not the static claim credential.

The reporter remains running across a promotion. A standby heartbeat requires
`pg_is_in_recovery()=true`; immediately after promotion the promotion script
restarts the reporter and requires a fresh `active` heartbeat with
`pg_is_in_recovery()=false`. Thus an active bigmac cannot continue presenting
stale standby eligibility. The same transition is required during manual
failback activation.

## Recovery contract

1. The bigmac watchdog checks the primary readiness endpoint using multiple
   consecutive probes and records a local incident receipt.
2. It sends a local Agentic OS alert through the canonical alert registry. The
   alert path does not depend on genomesbox: the bigmac watchdog detects failed
   genomesbox readiness probes, invokes
   `~/agentic_os/harness/bin/agentic-os-notify` with source
   `runtime.execution_fabric.health` and level `critical`, and the existing
   `harness/registries/alerts.yml` policy delivers the desktop toast and durable
   alert history on bigmac. No deployment-specific alert registry exists.
3. If automatic promotion is enabled, the watchdog invokes the promotion
   command. Promotion validates the emergency bundle, a fresh local standby
   candidate-health receipt, replica lag, witness lease, expected leader, and
   current epoch through `/api/v1`. The signed promotion request's incident
   digest binds both the outage receipt and candidate-health receipt.
4. Only an Ed25519-verified API receipt whose cluster, leader, epoch, receipt
   ID, expiry, and current witness readback all match authorizes PostgreSQL
   promotion and the `promoted` Compose profile.
5. Promotion proves the new primary role and starts API, observer, healer, and
   scheduler under the signed degraded-primary envelope. The scheduler remains
   supervised but admits occurrences only when the canonical degraded-primary
   policy explicitly allows them. A durable `degraded-primary.receipt.json`
   and repeated independent critical alert make the lost redundancy
   unmissable. When the former primary is reseeded and streaming
   synchronously, the failback path restores `remote_apply`, reads it back, and
   explicitly starts the scheduler so a prior standby-side supervisor exit
   cannot leave scheduled work dormant.
6. The control plane transactionally installs the new epoch before readiness.
   Old workers, attempts, effects, and a restarted former primary are rejected
   by witness, database-leader, epoch, and lease-token fencing.
7. Failback is always manual and two phase. A state-bound preparation token
   first authorizes only standby reseed. After the rebuilt target reports fresh
   eligibility, the operator requests a short-lived transfer plan, approves its
   exact hash, and applies the epoch transfer through the versioned API.

Policy rotation is a fenced, resumable two-authority operation, not a raw API
call. `installers/execution-fabric/bin/rotate-policy.sh` first requires fresh
candidate reports from both configured hosts for both the applied database
digest and reviewed staged digest, then creates a signed, expiring preparation
in the witness. The control-plane API refuses an unprepared reload. The current
leased leader transactionally records that digest in PostgreSQL, then consumes
the witness preparation only after a fresh, healthy, non-leader streaming
standby proves it replayed that change on the prepared timeline and upstream
system. The commit remains bound to the exact old digest, leader, and epoch.
Every signed authority proof binds the digest, making the bounded handoff
fail-closed. The rotation is idempotent and discoverable from the witness, so
the standby promotion path can finish a database-committed rotation after the
old leader disappears. Unconsumed preparations stay visible after token expiry:
an expired token cannot authorize a new database reload, but fresh
standby-applied evidence can recover and commit an already replicated change.
If an expired preparation never reached PostgreSQL, fresh standby evidence of
the old digest can conditionally abort it before promotion. Its observation,
lag, and receiver timestamps must all be strictly post-expiry. The witness
allows only one unresolved preparation per cluster.
Scheduler, healer, and observer processes compare their disk candidate with
the durable fingerprint on each tick and adopt only an exact match. Startup
can initialize an empty fingerprint or accept an identical one; it can never
replace an existing authority outside this explicit rotation protocol.
Unapproved edits remain fail-closed and observable as config drift. The final
receipt proves PostgreSQL, witness, local policy, and renewed active leadership
all agree, so an approved `allow_scheduler` change does not depend on a
coincidental process or host-manager restart.

The versioned `/api/v1/admin/leadership/*` contract is implemented by the
independently deployable service in
`services/execution-fabric-leadership-witness`. It uses DynamoDB conditional
transactions to arbitrate one leader, advance a monotonic epoch, return an
identity-bound fence receipt, check fresh health/replica-lag/config evidence,
reject stale expected-leader/epoch requests, and preserve durable audit
records. A two-host ping check is not a witness.

Every worker is configured with its host's stable gateway on port 3181. The
gateway routes to genomesbox or bigmac only from a short-lived, signed witness
proof. It does not infer leadership from one failed health check, and it stops
routing when a cached proof expires. Promotion and manual failback therefore
do not require editing worker configuration.

The portable AWS deployment template and activation runbook are under
`witness/`. Source availability does not activate the witness. A real
independent AWS stack, HTTPS/network policy, provider-managed secrets,
candidate reporters, alarms, and a successful failover/failback drill remain
operator prerequisites. Automatic promotion stays disabled until those
receipts exist.

Additional activation prerequisites are deliberately explicit:

- the release pipeline must publish the control-plane and worker images and
  generate a real digest-only image lock;
- the worker executable must implement the existing `/api/v1` worker protocol;
- the initial PostgreSQL base backup and replication slot must be verified
  before enabling automatic promotion;
- MinIO replication must be reconciled and a fresh two-direction canary receipt
  must satisfy the configured artifact RPO before promotion is enabled;
- Tailscale ACLs, host firewalls, runtime secret files, and the canonical
  `runtime.execution_fabric.health` alert source must be provisioned and read back;
- a successful drill receipt is required before `FABRIC_ENABLE_PROMOTION=true`.

## Emergency bundle

`emergency-bundle/manifest.yml` is the discoverable, versioned contract. The
builder creates a checksum manifest containing:

- the immutable image lock;
- Compose, systemd, launchd, and Helm deployment assets;
- the four canonical instance configuration files;
- promotion, failback, drill, observer, and watchdog commands;
- release identity and validation receipts.

Secrets are never copied. Build output is written outside the source tree. Run
the validator after every release/config change and before every drill.

## Readiness and drills

- Dependency and API containers have readiness health checks; observer and
  healer liveness/restart state remains independently visible in Compose and
  the host service manager.
- PostgreSQL backups are written to a dedicated volume by the `backup` profile.
- The observer writes bounded snapshots atomically.
- The health observer writes durable, versioned findings and alarm intents.
- The healer enforces allow-list, idempotency, epoch fencing, cooldown, hourly
  budget, and before/after verification.
- The bigmac alarm dispatcher uses its dedicated source/consumer-bound token and the existing
  `runtime.execution_fabric.health` alert registry entry; it is not embedded in
  the observer or healer.
- The watchdog uses a persistent consecutive-failure counter and rate-limited
  local alerts.
- Candidate reporting has its own Compose health check and host-side
  systemd/launchd freshness monitor; it does not depend on primary API
  readiness or the watchdog alarm path.
- `drill.sh` validates assets, probes both hosts, exercises the versioned
  leadership preflight, records the candidate-health receipt digest, and proves
  that a real promotion remains fenced unless explicitly enabled.
- Failback is never automatic. Run `failback.sh --prepare`, pass its receipt to
  `failback.sh --reseed --preparation-file PATH`, then request the eligibility-
  verified transfer with `failback.sh --plan --preparation-file PATH`. Review
  the bounded plan, record a hash-bound approval with
  `failback.sh --approve --operator ID`, then pass the returned artifact to
  `failback.sh --apply --approval-file PATH`. The target is already reseeded
  and measured as a standby before the old mutation plane is fenced and the
  witness advances epoch.
