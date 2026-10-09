# Manual cold recovery for a standalone Fabric

This runbook restores a complete daily recovery set to a stopped target and performs one explicit authority transfer. It is a manual recovery path. The ordinary standalone promotion and failback operations retain their refusal behavior.

The operational target is at most one day of lost changes and restoration within a few hours. Record the actual recovery point and elapsed time during an isolated drill before adopting those numbers as a service commitment. Keep the old host externally fenced until it has been rebuilt as a nonauthoritative target.

## Clone and prepare the tools

Clone the owning `genomes_agentic_os` repository and select the reviewed release tag or exact commit. Follow [the release contract](../release-contract.md) and [deployment instructions](../../deploy/execution-fabric/README.md); a source build is not evidence of an installed release.

Install the supported Python CLI and locked Node dependencies, then build the two services:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e .
npm --prefix services/execution-fabric-control-plane ci
npm --prefix services/execution-fabric-control-plane run build
npm --prefix services/execution-fabric-leadership-witness ci
npm --prefix services/execution-fabric-leadership-witness run build
.venv/bin/agentic-os runtime cold-recovery --help
```

Use a qualified Node/runtime build on the recovery host. The two fixed entrypoints are `services/execution-fabric-control-plane/dist/src/cold-recovery-main.js` and `services/execution-fabric-leadership-witness/dist/src/cold-recovery-main.js`. Record their actual SHA-256 digests in the reviewed cold policy. Preserve the locked dependencies and complete release/image/source receipt; an entrypoint hash alone does not establish the provenance of its imports or installed image.

The separate JSON policy template is `harness/config/execution-fabric-cold-recovery.json`. It is disabled and contains no private credentials. Configure the exact cluster and allowed hosts, independent recovery/fence public keys, approval lifetime and qualified actor digests. Keep private signing keys, the target PostgreSQL URL file and the recovery repository password in private operator custody outside Git. Do not copy primary role credentials to the restored target unchanged.

Signature verification requires local OpenSSL with Ed25519
`pkeyutl -verify -rawin` support. Use Ed25519 PEM public keys and base64-encoded
64-byte signatures over the exact payload bytes returned by
`genomes_agentic_os.cold_recovery.canonical(payload)`. Preserve canonical
integer and field bindings; signing a pretty-printed JSON file produces
different bytes. Keep recovery and external-fence signing identities in their
separate approved custody, and qualify the local verifier with the isolated test
before an outage. Missing tools or invalid signatures refuse recovery.

## Establish independent authority before restoring

A restored witness snapshot cannot certify its own freshness. Maintain the operator recovery anchor outside the recovery set and independently recover its latest accepted generation, epoch and signing identity. A missing anchor refuses recovery. Initial provisioning requires a signed external baseline and separate authority proof; it cannot use an assumed epoch zero or delete an initialized marker to bootstrap.

Obtain and verify the external fence for the original writer. Suitable evidence must establish that the old host cannot write to shared stores or external effects and remains fenced independently of its restored disk or local witness. A failed health probe or inability to reach the host is insufficient. Bind the exact old/target host, cluster, recovery set, freshness baseline, operator and expiry into the closed signed request.

If the old host is still reachable, stop and hold the selected producer/runtime roles through the supported admission workflow and take a new complete consistent backup before a planned transfer. If it failed, use the newest independently byte-verified complete set and record the lost interval. Preserve the original state and every immutable receipt.

## Restore into a held target

Use [complete backup recovery](../operations/execution-fabric-backup-recovery.md) to select an exact encrypted snapshot, retrieve the decryption key independently and restore all required components into a private empty isolated target. Verify actual restored bytes and logical PostgreSQL/witness/object/OS receipt linkage. Validate required PostgreSQL roles/extensions and architecture compatibility. A tar listing, file magic, sidecar checksum or per-store backup check does not establish a whole-system restore.

Keep API mutation, workers, schedulers, healer and external effect publishers stopped or durably held. Do not invoke existing HA leadership activation: it can requeue/refence old attempts and effects. Do not reseed or overwrite an authoritative host to simplify a drill.

The dedicated protocol relocates the witness through supported store logic, preserving original absolute database/backup path bindings and initialized/bootstrap markers in an immutable relocation receipt. Rotate authority and role identities, advance one generation/epoch and reject stale writer/worker/effect proofs.

## Plan, approve and apply exactly once

Construct request JSON against `schemas/execution-fabric-cold-recovery.schema.json`. A request binds the actual complete-set manifest, policy hash, source/target host, independent fence, anchor and signatures. Do not replace those fields with self-asserted success flags.

Each CLI operation requires explicit references:

```sh
agentic-os runtime cold-recovery prepare \
  --request /private/operator/recovery-request.json \
  --policy /private/operator/cold-policy.json \
  --anchor /private/operator/recovery-anchor.json \
  --journal-dir /private/operator/recovery-journal \
  --service-root /reviewed/source/services \
  --database-url-file /private/operator/target-database-url \
  --json
```

The command defaults to a validated dry run. Inspect its exact result, then use `--apply` only for the reviewed operation. `inspect` and `status` are read-only; `prepare`, `approve`, `apply`, `resume`, `canary`, `accept` and `initialize-anchor` require explicit mutation.

Run preparation and operator approval, then apply the same closed transition. Keep the signed artifacts, actor hashes, old/new identities and immutable journal. Cross-store changes are forward-only: interrupted transitions remain held and resume the exact identity through `resume`. Never restore an older anchor or start a second transition to escape a partial operation.

## Reconcile before releasing work

Restored queued/running tasks and undelivered effects enter quarantine. Identify work after the backup cutoff, in-flight external actions, provider idempotency keys and actual delivery receipts. An older snapshot cannot prove that those effects did not already happen.

Reconcile the separate personal fallback queue through its existing owner workflow. It is not the shared PostgreSQL ledger. Clearing its latch does not authorize a shared transfer, and a cold transfer does not clear the latch.

Run one exactly approved harmless canary under the new current authority and retain its semantic terminal receipt. It must create no customer/provider effect. Acceptance requires this canary and current epoch/hold readback. Resume only individually reconciled work through normal owner-bound transitions; existing held provider scopes and sealed reviews remain held.

The shipped canary is `fabric.cold_canary`, using queue and namespace
`fabric_cold_recovery`, pool `fabric_cold_recovery_workers` and handler
`fabric_cold_canary_v1`. The queue and pool default to disabled. Configure only
that lane for the recovery worker, with concurrency one and the local provider;
mixed queues, custom executors and external providers refuse execution. Ordinary
API admission cannot create this task, even when the lane is enabled. The signed
offline recovery operation creates the single approved task.

Its closed payload binds `schema_version`, `recovery_id`, `cluster_id`,
`epoch` and `generation`. The handler returns those bindings with its fixed
`handler` and actual `task_id`. Acceptance compares the actual task and attempt
result with the approved transition and target host. The handler computes in
memory; the dedicated worker does not drain or publish artifact spools. A task
marked completed with a substitute result fails acceptance.

Keep customer/provider lanes held throughout this canary. Restore Claude access
through the authenticated claude.ai subscription on the target host and verify
it separately before admitting provider work. This recovery procedure does not
authorize API keys, injected tokens or retries of sealed or held reviews.

## Validate and record the drill

Retain source/package/image/policy/host identities, actual complete-set and decrypted-byte proofs, independent key retrieval, fence and anchor readbacks, witness/ledger transition receipts, quarantined counts, exact canary terminal result, restored object/receipt linkage and API/worker capability readback.

Measure recovery point, data loss interval, transfer/decrypt/store-restore/validation durations and total elapsed recovery. Repeat on the intended GenomesBox and BigMac architectures using stopped disposable stores. Refuse stale/tampered/missing components, wrong cluster/host/key/path, expired/replayed approvals, anchor rollback, missing external fence and ambiguous effects. A pure unit-test result is distinct from this drill.

The repository also supplies a repeatable isolated PostgreSQL qualification:

```sh
uv sync --locked --extra dev
npm ci --prefix services/execution-fabric-control-plane
npm run build --prefix services/execution-fabric-control-plane
npm ci --prefix services/execution-fabric-leadership-witness
npm run build --prefix services/execution-fabric-leadership-witness
docker pull docker.io/library/postgres@sha256:742f40ea20b9ff2ff31db5458d127452988a2164df9e17441e191f3b72252193
recovery_test_output=$(mktemp -d)
.venv/bin/python tests/scripts/run-fabric-cold-recovery.py \
  --source-root "$PWD" --output-parent "$recovery_test_output"
```

Keep the private output directory until its receipts have been reviewed and
archived. The helper creates a fresh owned child directory and disposable database
and never pulls an alternate image. Exit zero requires actual accepted
`DATABASE-QUALIFICATION.json` and verified removal of the exact owned container
and private credentials, recorded in `RUN-RECEIPT.json`. Missing prerequisites,
protocol failure or uncertain cleanup return nonzero. Preserve these two named
receipts; do not upload private credential files or broad fixture directories.
This test proves the protocol and shipped handler against real stores. Actual
installed API/worker operation, recovered customer data, cross-host fencing,
independent key custody and the measured recovery objective require the separate
operational drill.

## Fail back without reversing history

Take a new complete backup from the accepted active recovery host. Rebuild the original host as a stopped nonauthoritative target. Obtain a new external fence against the current writer and perform a second one-use transfer with a newer generation/epoch and rotated identities. Reconcile the new backup cutoff and repeat the canary/acceptance gate. Keep both histories and journals; never automatically fail back, copy two divergent ledgers together or waive the fence.

## Failure handling

If integrity, authority or external-effect reconciliation fails, keep the target held and preserve the diagnostic journal. Repair the exact missing input or resume the exact forward transition after fresh readback. Do not delete initialized markers, recreate an anchor, reuse old credentials, reset queues, start broad activators or repeatedly retry unchanged denied actors.

The installation inventory and inert staging tools support recovery preparation. They do not grant authority to initialize an empty primary over unknown recovered state.
