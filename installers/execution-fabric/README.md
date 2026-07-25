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

`runtime.env` uses `FABRIC_POSTGRES_REPLICATION_PORT=35432` by default on both
hosts. This is the Tailscale-bound host port, not PostgreSQL's internal
container port. Keep the replication pgpass entry aligned when overriding it.

`install-linux.sh` installs systemd units for the genomesbox primary plus
observer, watchdog, and backup timers. `install-macos.sh` installs launchd
definitions for the bigmac warm standby, worker, observer, and watchdog.

Both installers are inert without `--apply`. Service loading is a separate
`--enable` choice so package installation is not mistaken for runtime
activation.

The worker definition executes `FABRIC_WORKER_EXECUTABLE`. No worker binary is
invented by the deployment layer; it must implement the public `/api/v1`
register, heartbeat, claim, complete, and fail protocol.

Control-plane roles require
`FABRIC_WORKER_BOOTSTRAP_CREDENTIALS_FILE`, a protected JSON map keyed by
stable bootstrap ID. Each entry binds one unique token to its exact worker ID,
host ID, pool ID, queue set, capability set, and concurrency. The installed
worker itself receives only its one scoped token file; it never receives the
server-side map.

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
the current leadership lease. Before the witness can commit, a fresh,
non-leader candidate report must prove that a healthy streaming standby has
replayed the PostgreSQL change and observes the candidate digest on the
prepared timeline and upstream system. Only then can the witness consume the
preparation at the exact leader and epoch. Signed leadership proofs carry the
policy digest, so every mutation is immediately fenced during the short
handoff. The command waits for active-authority readback and writes
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
