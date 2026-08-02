# Execution Fabric installers

These installers place immutable deployment assets outside the Agentic OS root:

- Linux releases: `/opt/genomes-agentic-os/execution-fabric/releases/<version>`
- Linux runtime config: `/etc/genomes-agentic-os/execution-fabric`
- macOS releases: `~/Library/Application Support/GenomesAgenticOS/execution-fabric/releases/<version>`
- macOS runtime config/state: `~/Library/Application Support/GenomesAgenticOS/execution-fabric`

They do not copy secrets, do not rewrite
`harness/config/execution-fabric.yml`, and do not enable promotion. The
operator provisions `runtime.env`, the referenced secret files, and an image
lock with immutable digests.

Release artifacts publish one canonical `execution-fabric-image-lock.json`.
Use `bin/materialize-image-lock.sh LOCK.json` to produce its shell-safe,
deterministic env projection. The helper validates exactly seven digest-pinned
images, including leadership witness and worker. `build-emergency-bundle.sh`
accepts that JSON directly and includes both it and the derived env form; bundle
validation regenerates the projection and rejects drift.

## Personal standalone genomesbox primary

Set `FABRIC_WITNESS_MODE=standalone_primary` only on the configured Linux
primary. The canonical policy must independently opt in the exact host through
`execution_fabric.standalone_primary.enabled` and `.host_id`. Preflight reads
that policy through the installed Agentic OS CLI, matches its SHA-256
fingerprint to `FABRIC_POLICY_FINGERPRINT`, verifies the singleton candidate
credential, requires a digest-pinned witness image, and rejects automatic
failover or promotion.

The Linux primary runner adds the `standalone-primary` Compose profile in this
mode. The signed witness is co-located on genomesbox, renewable, and
short-lived; it is not an independent witness or quorum. The control plane
accepts normal task, effect, and scheduler mutations only while PostgreSQL
directly proves local durable-primary settings. Bigmac never starts a promoted
shared ledger under this mode and continues through its separate local
personal-fallback latch.

Leave `FABRIC_STANDALONE_WITNESS_BOOTSTRAP_ONCE=false` in `runtime.env`. The
runner supplies it only to the first witness container, waits for readiness,
records a host-side completion marker, and recreates the container without the
capability before starting the primary profile. A completion marker with a
missing SQLite database or bootstrap sentinel blocks activation and requires a
restore; it never silently creates replacement authority state.

Policy changes use `bin/rotate-policy.sh` on genomesbox. Standalone mode runs a
fail-closed local maintenance transaction: prepare, database reload, candidate
readback, witness commit, and active-state readback. `--resume` resolves an
interrupted transaction. Promotion and failback remain unavailable. Activation
also leaves the HA-only artifact-replication timer disabled while retaining the
primary, scheduler, observer, backup, and candidate-reporter health units.

On bigmac, `activate-macos.sh --apply --personal-fallback` is the complete
personal client-plane activation, not a standby activation. Its dedicated
preflight verifies the canonical `remote_with_local_fallback` policy, exact
host/worker/pool/queue/capability/concurrency binding, shipped worker routes,
distinct scoped worker and alarm-dispatcher token files, the canonical desktop
notifier, and a currently routable signed-leader gateway. Only after that whole
set passes does launchd start the host worker, alarm dispatcher, and fallback
watchdog. It does not start or require standby PostgreSQL, Valkey, MinIO,
promotion/failback roles, or local copies of server-side credential maps.

The packaged host worker uses `installed_host` root mode. It reads bigmac's
existing Agentic OS policy and registries and never runs the disposable OCI
bootstrap that materializes pod-local config. The control plane remains the
authority that verifies the scoped bootstrap credential against the exact
durable worker registration; bigmac holds only its one worker token and one
separate alarm-dispatcher token. The current `pr_reviewers` policy requires the
host worker to claim both review slots, and its runtime endpoint is the signed
gateway rather than the primary API address used by the fallback probe.

## Independent witness installer

The provider-neutral witness uses its own focused installer and canonical
operator environment:

```sh
installers/execution-fabric/install-witness.sh \
  --apply --source-root /path/to/genomes_agentic_os --release <release>
installers/execution-fabric/activate-witness.sh --apply
```

Installation copies only immutable deployment assets and remains inert.
Activation preflights the exact Tailscale bind IP, digest-pinned OCI image,
independent host identity, candidate-scoped credentials, and durable state
mount before Docker or Podman starts anything. It also installs and enables the
systemd health-monitor timer; the released witness has no cloud-provider
runtime or deployment adapter.

When no independent third host is configured, set
`WITNESS_MODE=manual_fail_closed`. The activator starts no witness and requires
automatic failover and promotion to remain disabled. Two execution candidates
do not become a safe quorum by agreeing with themselves.

Keep datastore credentials out of `runtime.env`. Both hosts require protected
`secrets/postgres-password`, `secrets/valkey-app-password`, and
`secrets/valkey-health-password` files containing URL-safe tokens of at least
32 characters. The standby PostgreSQL password must equal the primary value
because physical replication copies the role verifier. Compose mounts these
files and constructs application URLs inside the container process; rendered
configuration contains only `/run/secrets/...` paths. Valkey's ACL is generated
on container tmpfs rather than stored as a plaintext operator file.

`runtime.env` uses `FABRIC_POSTGRES_REPLICATION_PORT=35432` by default on both
hosts. This is the Tailscale-bound host port, not PostgreSQL's internal
container port. Keep the replication pgpass entry aligned when overriding it.
Replication slots follow the target role: `genomesbox_fabric` feeds the
configured primary host while it is being rebuilt as a failback target, and
`bigmac_fabric` feeds the configured standby host. Failback creates the former
before the primary-host base backup; receipt activation creates the latter
before rebuilding the standby. Reseed resolves the same names through the
shared installer contract instead of carrying separate literals.

`install-linux.sh` installs systemd units for the genomesbox primary plus
observer, watchdog, and backup timers. `install-macos.sh` installs launchd
definitions for the bigmac warm standby, worker, observer, and watchdog.

The Linux backup timer invokes `bin/backup-health.sh`, which accepts only the
canonical `${FABRIC_RUNTIME_STATE_DIR}/backup-health.json` destination and
validates the newly generated run ID. The underlying backup is not healthy
until it has been restored into an isolated disposable database, queried, and
removed; the validator also verifies the hash-bound restore-manifest sidecar.

Both installers are inert without `--apply`. Service activation is a separate,
explicit operation:

```sh
# Linux, after runtime.env and every referenced secret/config file are ready.
sudo /opt/genomes-agentic-os/execution-fabric/current/installers/activate-linux.sh --apply

# macOS, after runtime.env and every referenced secret/config file are ready.
"$HOME/Library/Application Support/GenomesAgenticOS/execution-fabric/current/installers/activate-macos.sh" --apply
```

The activators run the complete `bin/preflight.sh` role check before the first
`systemctl` or `launchctl` mutation. A failed preflight starts nothing.
Successful activation is idempotent: systemd starts already-active units
without restarting them, and the macOS activator skips labels already loaded in
the user launchd domain.

`install-*.sh --enable` remains an explicit install-and-activate convenience
and delegates to the same activator. Re-running the installer for the same
current release does not copy the release again or exit 73; adding `--enable`
activates that inert release. It still refuses an incomplete release or a
previous release that is installed but is not the selected `current` release,
so an installer rerun cannot become an accidental rollback.

The host worker has a package-owned executable at
`current/installers/bin/python-worker.sh`. `bin/worker.sh` selects it by default
and points it at the stable signed-leader gateway. The executable launches the
shipped `genomes_agentic_os.execution_fabric_worker` module, so an operator no
longer needs to create an untracked wrapper. Set `FABRIC_WORKER_PYTHON` when the
package lives in a dedicated virtual environment; it may be an absolute path or
an executable name. `FABRIC_WORKER_EXECUTABLE` remains an explicit advanced
override for another governed worker implementation of the public `/api/v1`
register, heartbeat, claim, complete, and fail protocol. Standby preflight
verifies that the default Python module is importable before launchd is touched.

Control-plane roles require
`FABRIC_WORKER_BOOTSTRAP_CREDENTIALS_FILE`, a protected JSON map keyed by
stable bootstrap ID. Each entry binds one unique token to its exact worker ID,
host ID, pool ID, queue set, capability set, and concurrency. The installed
worker itself receives only its one scoped token file; it never receives the
server-side map.

The bigmac worker runtime must set `FABRIC_WORKER_ID`,
`FABRIC_WORKER_BOOTSTRAP_ID`, `FABRIC_WORKER_POOL_ID`,
`FABRIC_WORKER_ACCEPTED_QUEUES`, `FABRIC_WORKER_CAPABILITIES`,
`FABRIC_WORKER_MAX_CONCURRENCY`, and
`AGENTIC_OS_EXECUTION_FABRIC_WORKER_TOKEN_FILE`. Standby preflight verifies
that those values and token file exactly match the selected entry in the
server-side bootstrap map before launchd starts the worker.

The protected secret directory must also contain `minio-root-user`,
`minio-root-password`, `artifact-observer-access-key`, and
`artifact-observer-secret-key`, or equivalent scoped object-store credentials
when the endpoint is external. Root credentials are mounted into MinIO
bootstrap and the API/healer roles that mint or reconcile task-scoped artifact
access. The observer receives only its dedicated read-only identity; workers
receive neither identity. Artifact lifecycle, retention, replication, and
recovery validation are separate from installer activation.

After both MinIO sites are installed, run
`bin/reconcile-artifact-replication.sh` once and retain its receipt. Both host
service managers then execute `bin/artifact-replication-health.sh` every minute.
Promotion and manual failback call
`bin/validate-artifact-replication-receipt.sh`; neither can proceed on a stale
or one-way result. A former leader must be resynchronized and pass a new
bidirectional canary before it is accepted as the standby again.

## Fenced policy rotation

Do not call the control-plane config-reload endpoint by itself. Copy the same
reviewed `harness/config/execution-fabric.yml` to both configured hosts, wait
for both candidate reporters to publish its SHA-256 digest, then run this on
the witnessed leader:

```sh
bin/rotate-policy.sh OLD_DIGEST NEW_DIGEST
```

The command first writes a signed, expiring preparation to the independent
witness. Candidate reports keep the currently applied PostgreSQL digest
separate from the staged disk-policy digest, so staging never makes ordinary
promotion eligibility lie. The control plane accepts no reload without that
signed preparation. It then transactionally rotates PostgreSQL while holding
the current leadership lease. `converge-policy-roles.sh --recreate` then
force-recreates the complete API/observer/healer/scheduler cohort and requires
exact per-role candidate-fingerprint readback. Before the witness can commit, a fresh,
non-leader candidate report must prove that a healthy streaming standby has
replayed the PostgreSQL change and observes the candidate digest on the
prepared timeline and upstream system. Only then can the witness consume the
preparation at the exact leader and epoch. Signed leadership proofs carry the
policy digest, so every mutation is immediately fenced during the short
handoff. After witness commit, `converge-policy-roles.sh --verify` requires
healthy fresh ticks from all four roles. The command then writes
`policy-rotation-<uuid>.receipt.json`.

If the process or network fails after the database commit, rerun the identical
command. It reuses the pending rotation ID and resumes the idempotent witness
mutation. Unconsumed preparations remain discoverable after their preparation
token expires; expiry prevents a new PostgreSQL reload, but it does not erase a
database-committed recovery path. Before every takeover, `promote.sh` invokes
`rotate-policy.sh --resume`. If the candidate digest reached synchronously
replicated PostgreSQL, bigmac can publish the required fresh standby evidence
and finish the witness commit even after genomesbox disappears. If an expired
preparation never reached PostgreSQL, the same path uses fresh standby evidence
of the old digest to conditionally abort it before promotion. That observation,
lag measurement, and receiver timestamp must all be strictly newer than the
preparation expiry, closing the database-commit/reporting race. The witness
permits only one unresolved preparation, so recovery cannot become ambiguous.
A different rotation is rejected until the pending operation is resolved; do
not delete that record to bulldoze through a conflict.
