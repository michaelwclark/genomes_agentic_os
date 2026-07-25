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

The protected secret directory must also contain `minio-root-user` and
`minio-root-password`, or equivalent scoped object-store credentials when the
endpoint is external. They are mounted only into the control-plane roles and
MinIO bootstrap; workers never receive them. Artifact lifecycle, retention,
replication, and recovery validation are separate from installer activation.

After both MinIO sites are installed, run
`bin/reconcile-artifact-replication.sh` once and retain its receipt. Both host
service managers then execute `bin/artifact-replication-health.sh` every minute.
Promotion and manual failback call
`bin/validate-artifact-replication-receipt.sh`; neither can proceed on a stale
or one-way result. A former leader must be resynchronized and pass a new
bidirectional canary before it is accepted as the standby again.
