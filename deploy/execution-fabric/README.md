# Execution Fabric deployment

This directory is the portable deployment surface for the Agentic OS Execution
Fabric. It keeps deployment mechanics separate from the generic control-plane
service and from the one editable instance policy at
`harness/config/execution-fabric.yml`.

The full replicated topology is:

- `genomesbox`: PostgreSQL primary, Valkey delivery index, MinIO artifact store,
  API, durable health observer, deterministic healer, and active gateway.
- `bigmac`: streaming PostgreSQL standby, empty/reconstructable Valkey, local
  artifact spool, observer, watchdog, and a stopped emergency control plane.
- Kubernetes workers: the compatibility path `helm/los-agents` contains the
  generic GAOS worker chart only. LOSMON environment/Jira handlers remain in a
  separate LOS domain image and deployment.

Every image reference is supplied by the generated
`execution-fabric-image-lock.json` and must use an immutable `@sha256:` digest.
Compose refuses to start when an image variable is missing. The reviewed
third-party source tags live only in `release-image-sources.json`; release CI
resolves each one to a Linux AMD64/ARM64 index digest and the release builder
rejects missing, mutable, or repository-substituted references. Runtime config
uses only the seven exact digest references in the lock.

The released JSON lock is the only authored image-lock format. Materialize its
deterministic seven-variable runtime projection with:

```bash
installers/execution-fabric/bin/materialize-image-lock.sh \
  execution-fabric-image-lock.json > images.lock.env
```

The materializer rejects missing, extra, mutable, or all-zero references. It
covers the control plane, leadership witness, worker, PostgreSQL, Valkey,
MinIO, and MinIO client. Do not maintain a second hand-written env lock.

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

Installed Compose mounts the editable policy and its managed schema from the
absolute `FABRIC_OS_ROOT` paths. Release-relative `../../harness` paths are not
valid after immutable deployment assets move under `/opt` or the macOS
Application Support directory.

## Personal standalone primary authority

A personal installation may run the shared queue normally on genomesbox
without pretending the co-located witness is an independent failure domain.
This is an explicit non-HA authority mode:

- canonical `execution_fabric.standalone_primary` must be enabled and name the
  exact `genomesbox` host ID;
- `FABRIC_WITNESS_MODE=standalone_primary` starts the digest-pinned witness
  profile on genomesbox, with one host-scoped candidate credential;
- each signed proof is renewable and expires after 90 seconds by default;
- PostgreSQL must be a local primary with `synchronous_commit=local` or `on`,
  no synchronous standby target, `fsync=on`, `full_page_writes=on`, and
  `archive_mode=on`;
- task, effect, and scheduler mutations operate normally while that exact
  proof and durability measurement remain valid;
- promotion, failback, automatic failover, and any bigmac shared-ledger
  authority are disabled.

The host preflight compares `FABRIC_POLICY_FINGERPRINT` with the canonical
policy readback before starting anything. The co-located witness uses a
distinct logical service identity and durable SQLite state, but its placement
does not make it quorum. If genomesbox is lost, shared work waits there and
bigmac follows the separate personal fallback contract below.

Keep `FABRIC_STANDALONE_WITNESS_BOOTSTRAP_ONCE=false`. On first activation the
Linux runner alone grants that capability for one bounded witness start, waits
for `/readyz`, verifies the SQLite database and bootstrap sentinel, writes
`standalone-witness.bootstrap-complete` outside the witness state directory,
and immediately recreates the witness with bootstrap disabled. Later starts
fail closed if that marker exists but either durable file is missing. The
primary profile starts only after witness readiness, preventing candidate and
proof consumers from racing initial authority.

The normal `rotate-policy.sh` command is the governed standalone maintenance
path. Preparation requires the exact healthy local primary to report the
current and staged digests. PostgreSQL commits the candidate fingerprint, and
ordinary mutations remain fenced while the witness still holds the old digest.
Commit requires a fresh local applied-digest report, advances witness state
without changing leader or epoch, and restores short-lived authority.
`--resume` completes or safely aborts interrupted maintenance from fresh local
evidence. This is neither promotion nor failover.

The cross-host artifact-replication timer is intentionally disabled in this
mode. Primary, scheduler, observer, backup, and candidate-reporter health units
remain active; an HA-only replication check would otherwise report the
intentionally absent standby forever.

## Personal fallback activation

The full standby profile remains available for consensus-grade failover, but it
is not required for a personal harness. With
`transport.mode: remote_with_local_fallback`, genomesbox runs the shared
control plane and bigmac retains its existing local SQLite queue as a separate
continuity plane. Install the release normally, set `FABRIC_OS_ROOT` and the
absolute `FABRIC_AGENTIC_OS_CLI` path in bigmac's protected `runtime.env`, then
activate the lightweight personal client plane:

```bash
~/Library/Application\ Support/GenomesAgenticOS/execution-fabric/current/installers/activate-macos.sh \
  --apply --personal-fallback
```

The client plane runs three independent launchd jobs: the scoped remote worker,
the scoped alarm dispatcher, and the fallback watchdog. A dedicated preflight
validates their exact canonical worker identity and capacity, shipped routes,
distinct local token files, notifier, and signed-leader gateway without
requiring the standby datastore profile or copying server-side credential maps
to bigmac. The host worker reads the installed OS root without rewriting its
policy or host registries, routes every remote claim through the signed gateway,
and must claim the canonical two-wide `pr_reviews` capacity rather than quietly
starting with one slot.

The watchdog probes once per minute, latches after the configured sustained
failure threshold, and sends critical alerts through the canonical Agentic OS
notification route. It does not start PostgreSQL, Valkey, MinIO, or a second
shared control plane on bigmac. The remote worker and alarm dispatcher naturally
stop receiving shared work while the gateway is unavailable; bigmac's existing
local runtime continues under the fallback latch. This keeps the fallback small and predictable:
local bigmac automations continue, while genomesbox-owned queued work waits for
genomesbox to return. Failback is always an explicit, readiness-gated CLI
operation.

## Datastore credential boundary

`runtime.env` must not contain `FABRIC_DATABASE_URL`, `FABRIC_VALKEY_URL`, or
either datastore password. Provision the same `postgres-password` and
`valkey-app-password` files in each host's protected `secrets/` directory; also
provision a distinct `valkey-health-password`. Each value must be one URL-safe
token of at least 32 characters (`A-Z`, `a-z`, `0-9`, `.`, `_`, `~`, or `-`).

Compose mounts these files only into roles that need them.
`datastore-env-entrypoint.sh` constructs the PostgreSQL and Redis-compatible
URLs inside each application process immediately before `exec`; secret values
do not appear in `runtime.env` or rendered Compose configuration.
`valkey-acl-entrypoint.sh` builds a mode-0600 ACL on tmpfs, disables the
default user, and starts Valkey without placing a password in its command line.
The standby uses the same PostgreSQL password as the primary because physical
replication copies the role verifier.

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
3. In the full replicated topology, if automatic promotion is enabled, the watchdog invokes the promotion
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
Compose mounts only the policy `config/` and `schemas/` directories as a
least-privilege read-only bundle, rather than mounting the whole harness or a
single-file bind whose inode can remain pinned after replacement. After the
database reload, rotation force-recreates the API, observer, healer, and
scheduler cohort and reads back each role's exact approved and applied
fingerprint before witness commit. A second readback after commit requires a
fresh successful tick from every role. Any mismatch leaves authority fenced
and no successful rotation receipt is written. Unapproved edits remain
fail-closed and observable as config drift.
For a host statically configured as `standby`, recovery reads the actual
promoted cohort: zero running policy roles may defer until promotion, all four
running roles are treated as active, and a partial cohort fails closed.

The versioned `/api/v1/admin/leadership/*` contract is implemented by the
deployable service in
`services/execution-fabric-leadership-witness`. Its canonical provider-neutral
deployment for full HA uses a singleton SQLite authority on a third host and has no
cloud-provider deployment dependency. Personal `standalone_primary` instead
runs that signed authority co-located on genomesbox and disables every
leadership transfer. Each mutation
commits under `BEGIN IMMEDIATE`, WAL, and `synchronous=FULL` before returning.
It advances a monotonic epoch, returns an identity-bound fence receipt, checks fresh
health/replica-lag/config evidence, reject stale expected-leader/epoch
requests, and preserve durable audit records. A two-host ping check is not a
witness, and two candidates are not a quorum.

Every worker is configured with its host's stable gateway on port 3181. The
gateway routes to genomesbox or bigmac only from a short-lived, signed witness
proof. It does not infer leadership from one failed health check, and it stops
routing when a cached proof expires. Promotion and manual failback therefore
do not require editing worker configuration.

The portable OCI manifest, installer, Tailscale-only bind preflight, monitor,
and activation runbook are under `witness/`. Source availability does not
activate the witness. Full HA requires a real independent host, immutable
image, network policy, protected secrets, durable state, candidate reporters,
alarms, and a successful failover/failback drill remain full-HA operator prerequisites.
A personal installation may
instead select `standalone_primary`, which starts the signed witness alongside
genomesbox but never authorizes promotion or failback. Select
`manual_fail_closed` when neither authority is intended; no witness starts and
automatic promotion must remain disabled.

Additional activation prerequisites are deliberately explicit:

- the release pipeline must publish the control-plane, leadership-witness, and
  worker images, resolve the reviewed PostgreSQL, Valkey, MinIO, and MinIO
  client multi-arch indexes, and generate one digest-only image lock containing
  all seven;
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

- the canonical immutable JSON image lock and its deterministic env
  materialization;
- Compose, systemd, launchd, and Helm deployment assets;
- the four canonical instance configuration files;
- promotion, failback, drill, observer, and watchdog commands;
- release identity and validation receipts.

Secrets are never copied. Build output is written outside the source tree. Run
the validator after every release/config change and before every drill.
The builder accepts the published JSON lock as `--image-lock`; validation
regenerates `images.lock.env` and requires an exact byte match.

## Readiness and drills

- Dependency and API containers have readiness health checks. Observer,
  healer, and scheduler health checks read their durable role receipt instead
  of testing only process existence. Status exposes each role's approved and
  applied fingerprint, instance ID, last successful tick, last error, and
  consecutive failure count. Startup grace is bounded to 90 seconds by
  default, and restart attempts preserve failure history, so a never-ticking
  or crash-looping role becomes unhealthy instead of remaining startup-green.
  Status evaluates only the active host; replicated historical rows from the
  other host remain durable without producing false local alarms.
- The backup timer calls `installers/bin/backup-health.sh`. Each run writes a
  custom-format dump, restores it into a uniquely named disposable database,
  queries restored catalog objects and every restored table, removes that
  database, and only then atomically publishes
  `execution-fabric-backup-health/v1`. The receipt binds the backup SHA-256 to
  a hashed `execution-fabric-postgres-restore-manifest/v1` sidecar. A dump-list
  check alone is never accepted as restore evidence. Configure
  `FABRIC_BACKUP_HEALTH_RECEIPT_FILE` as
  `${FABRIC_RUNTIME_STATE_DIR}/backup-health.json`.
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
