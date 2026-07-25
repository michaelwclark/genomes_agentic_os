# Leadership witness deployment and operations

## Choose the safety mode

The canonical portable contract has two explicit modes:

- `independent`: start one digest-pinned OCI witness on a declared third host
  outside `genomesbox` and `bigmac`.
- `manual_fail_closed`: start no witness, require
  `FABRIC_AUTO_FAILOVER=false` and `FABRIC_ENABLE_PROMOTION=false`, and make no
  two-node split-brain-safety claim.

A Tailscale ping between two candidate hosts is not a witness. Loss of the
independent authority fences new promotion decisions; it does not let either
candidate vote for itself.

## Provision an independent host

1. Choose a stable witness host ID that is absent from the candidate-token map.
2. Install Docker or Podman and Tailscale. Restrict the witness port to the two
   candidates and operator identities with Tailscale ACLs and the host firewall.
3. Build, scan, sign, and publish the witness image. Record only the immutable
   `image@sha256:...` reference.
4. Create distinct reader and admin bearer-token files, a JSON map containing
   one unique token per candidate, and one Ed25519 PKCS8 private key. Files must
   remain outside the repository and readable only by the witness operator.
   Distribute candidate hosts only their scoped token, the reader token where
   needed, and the public key. Keep the admin token operator-controlled.
5. Copy `witness.env.example` to the canonical operator-owned `witness.env`.
   Set the exact `WITNESS_TAILSCALE_IP`, host and cluster IDs, digest-pinned
   image, state directory, secret paths, initial leader, and reviewed policy
   digest. Set `WITNESS_BOOTSTRAP_ONCE=true` only for the first start; after
   the `.initialized` sentinel and `.backup` exist, return it to `false`.
6. Pull the exact image digest, then install inert assets:

   ```sh
   installers/execution-fabric/install-witness.sh \
     --apply \
     --source-root /path/to/genomes_agentic_os \
     --release <release>
   ```

7. Preflight without mutation:

   ```sh
   WITNESS_ENV_FILE=/etc/genomes-agentic-os/execution-fabric-witness/witness.env \
     /opt/genomes-agentic-os/execution-fabric-witness/current/bin/preflight.sh
   ```

   Preflight proves the bind IP belongs to this Tailscale node, the image is
   digest-pinned and locally installed, the candidate map excludes the witness,
   both candidates have unique scoped tokens, secrets exist, and the portable
   state path is mounted under the canonical container directory.
8. Activate explicitly:

   ```sh
   installers/execution-fabric/activate-witness.sh --apply
   ```

   The OCI runner uses host networking so the process itself binds only to the
   configured Tailscale IP. It drops all capabilities, enables
   `no-new-privileges`, makes the root filesystem read-only, and mounts only
   the numeric-identity state directory and one protected prepared-secrets
   directory. Host secret sources are never made container-readable directly.
9. Run `bin/health.sh`, authenticated `bin/smoke-test.sh`, and
   `bin/monitor.sh`. Read back `/readyz`, the signed status, current container
   digest, state-file durability, and the Agentic OS alert receipt.

## Health and alarms

`bin/monitor.sh` writes the atomic
`execution-fabric-witness-health/v2` receipt to
`WITNESS_RUNTIME_STATE_DIR/health.json`.

- `availability=available` means both liveness and durable readiness passed.
- `automaticPromotionEligible=true` additionally requires a current,
  cluster-bound `execution-fabric-witness-promotion-eligibility/v1` drill
  receipt. Health alone never grants promotion eligibility.
- `critical` disables any promotion assumption and emits the canonical
  `runtime.execution_fabric.health` alert through `agentic-os-notify`.
- `manual_fail_closed` records that no automatic promotion authority exists.

The witness installer installs and enables a 30-second systemd timer for the
monitor. Exercise the notification path with an
operator-approved test. Do not stop the witness merely to make the pager sing.

Container restart policy is a recovery aid, not health proof. Alert on:

- container absence or restart loops;
- `/healthz` or `/readyz` failure;
- stale monitor receipt;
- state-volume capacity or I/O errors;
- candidate-report freshness;
- signing-key or token rotation failure.

## Candidate reporting and promotion

Each candidate reporter derives health from its local PostgreSQL role,
timeline, receive/replay LSNs, absolute WAL positions, receiver state,
last-message time, database clock, and canonical policy digest. Remote ping
health is insufficient. The current leader must publish a fresh upstream WAL
baseline; a disconnected standby can otherwise report zero local lag while
remaining behind.

Promotion requires:

- a fresh signed witness proof;
- expected leader and epoch readback;
- complete expiry of the prior proof lease;
- fresh eligible standby evidence on the same timeline and upstream system;
- fresh backup-restore and bidirectional artifact-replication receipts;
- a valid emergency bundle and successful drill;
- explicit operator enablement of automatic promotion.

The witness advances the epoch and durably records the signed fence receipt
before local PostgreSQL promotion begins. `promote.sh` stores its operation
journal before CAS, looks up the exact `promotionId` after response loss, and
resumes idempotently if PostgreSQL is already primary. A stale request returns
HTTP 409 and must never be retried with guessed values.

## Manual failback

Failback remains the existing four-step guarded flow:

1. `failback.sh --prepare`
2. `failback.sh --reseed --preparation-file PATH`
3. `failback.sh --plan --preparation-file PATH`, then review and
   `failback.sh --approve --operator ID`
4. `failback.sh --apply --approval-file PATH`

The witness atomically consumes the exact approval-bound plan and issues a new
signed epoch. Reused plans, stale approvals, stale timelines, and ambiguous
data volumes fail closed.

## Backup and restore

For the default SQLite adapter, back up with a consistent SQLite backup or
while the witness container is stopped. Preserve the database and WAL as one
recovery unit. Periodically restore into a disposable host, start the same
digest-pinned image on an isolated test IP, and verify:

- schema/readiness;
- leader, epoch, fence digest, and policy digest;
- candidate records and pending one-use plans;
- audit tail and signed public-key continuity.

A restored file is never automatically authoritative. Reconnect candidate
hosts only after incident-command review and an exact signed drill.

## Credential and image rotation

Rotate reader, candidate, admin, and signing credentials independently. Never
rotate the signing key during an unresolved promotion, failback, or policy
rotation. Replace a running immutable image explicitly; the runner refuses to
silently mutate an existing container to a different digest.
