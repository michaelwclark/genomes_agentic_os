# Manual cold recovery for a standalone Fabric

This runbook restores a complete daily recovery set to a stopped target and performs one explicit authority transfer. It is a manual recovery path. The ordinary standalone promotion and failback operations retain their refusal behavior.

The operational target is at most one day of lost changes and restoration within a few hours. Record the actual recovery point and elapsed time during an isolated drill before adopting those numbers as a service commitment. Keep the old host externally fenced until it has been rebuilt as a nonauthoritative target.

## Clone and prepare the tools

Clone the owning `genomes_agentic_os` repository and select the reviewed release tag or exact commit. Follow [the release contract](../release-contract.md) and [the Execution Fabric guide](../13-feature-guides/18-execution-fabric.md). Use the deployment instructions in `deploy/execution-fabric/README.md` from that same reviewed checkout; a source build is not evidence of an installed release.

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

Use the reviewed complete-backup recovery procedure (`docs/operations/execution-fabric-backup-recovery.md` in the backup-enabled release) to select an exact encrypted snapshot, retrieve the decryption key independently and restore all required components into a private empty isolated target. If the selected checkout lacks that procedure, stop and select a reviewed release containing both complete-backup and cold-recovery capabilities before continuing. Verify actual restored bytes and logical PostgreSQL/witness/object/OS receipt linkage. Validate required PostgreSQL roles/extensions and architecture compatibility. A tar listing, file magic, sidecar checksum or per-store backup check does not establish a whole-system restore.

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

`status` returns the immutable historical journal. It does not validate current
authority. Repeating `accept`, `apply` or `resume` for an accepted journal must
still have the unchanged unexpired signed authorization, the exact current
selected anchor and actual native PostgreSQL/witness readbacks. The native
actor verifies the current recovery generation, epoch, host, phase, cluster,
policy and selected witness snapshot/bootstrap/retained receipt before returning
the identical durable acceptance receipt. Drift, a missing actor/store or expired
authorization refuses without replacing history, receipt or anchor bytes.
Historical status remains available for diagnosis; it never grants work release.

When the restored source execution policy A differs from reviewed target policy
B, include the optional closed `policyTransition` in the signed plan before
preparation and approval. It contains `expectedSourceFingerprint` for the actual
restored source, `candidateExecutionPolicyFile` for the canonical existing target
file, and `candidateExecutionPolicySha256` for its exact reviewed bytes. The
native control plane loads that file with its existing `PolicyManager`, checks
its operational applied fingerprint against `candidateConfigDigest`, and checks
its file identity and bytes again before commit. The original PostgreSQL and
witness source fingerprints must still equal A. After the witness commits B,
the already held PostgreSQL cold commit writes B in the same transaction as the
target epoch and leader. Original task associations, approvals and quarantine
history keep their original A bindings. Ordinary policy reload is not part of
this transfer.

Omitting `policyTransition` preserves legacy plan hashes and permits an unchanged
execution policy. A differing source policy without the signed descriptor stays
held. A missing, changed, unsafe or unqualified target file also stays held;
never prebind the restored ledger to B or rewrite original associations to make
validation pass.

## Reconcile before releasing work

Restored queued/running tasks and undelivered effects enter quarantine. Identify work after the backup cutoff, in-flight external actions, provider idempotency keys and actual delivery receipts. An older snapshot cannot prove that those effects did not already happen.

Reconcile the separate personal fallback queue through its existing owner workflow. It is not the shared PostgreSQL ledger. Clearing its latch does not authorize a shared transfer, and a cold transfer does not clear the latch.

Run one exactly approved harmless canary under the new current authority and retain its semantic terminal receipt. It must create no customer/provider effect. Acceptance requires this canary and current epoch/hold readback. Acceptance retains quarantine; it does not resume restored tasks or effects. Existing held provider scopes and sealed reviews remain held.

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

## Inspect and record an individual quarantine disposition

The optional `selectiveDisposition` policy defaults to disabled. This version
supports signed inspection, an immutable decision to keep an item held, and
owner-approved **metadata-only task cancellation**. Cancellation leaves the
task and every effect, alarm and artifact quarantined. It never cancels a
provider request, delivers an effect, clears an alarm, releases an artifact or
requeues work. Ordinary administrative requeue, effect replay and queue drain
also refuse quarantined items. Keep all provider/runtime holds in place.

Positive requeue and provider outcome verification are unavailable. The only
qualified inert route is the single `fabric.cold_canary` created by the cold
protocol, with one attempt. Ordinary admission refuses that type, and acceptance
requires its success. A local provider label or `read_only` task class does not
establish that other work has no effects. Do not create substitute database rows
or provide a generic success receipt to manufacture eligibility.

Enable the optional policy only through an independently reviewed configuration
change. Bind the original accepted policy digest, exact reviewed source release,
existing canonical SQLite authority path/domain/project and current execution
policy file. The signed accepted receipt, recovery generation/epoch, cluster,
target host and PostgreSQL system identity must remain current. A configured
hash alone does not qualify a policy rotation, backend, package or host.
Apply the reviewed release's additive PostgreSQL migrations through its existing
migration procedure against the exact backed-up, held target before running
these new actors. Retain the nonempty migration-016 to migration-017 preservation
proof and current schema readback. These actors require the generation-keyed
history tables; they refuse an older or unknown schema. Source compilation does
not migrate a restored database or authorize an empty primary bootstrap.

An item needs a genuine original association in the canonical work registry.
Its `executionFabricBinding` metadata must preserve the exact task UUID,
request hash, original queue/namespace/type/provider/configuration fingerprint,
original development policy fingerprint, logical context digest and immutable
context receipt URI/file digest. The actual owner-written work history must
have recorded that same binding with `receipt_ref="fabric-task:<task UUID>"`
before the first quarantine hold. The original effective-policy receipt must
already have an `internal` artifact reference for the same work ID and bytes,
also predating the first hold. Its real context assembler digest is checked;
it is distinct from the receipt file's SHA-256. Missing, retroactively supplied,
specialized unsupported or conflicting associations remain held. This operation
does not write associations or migrate/create an authority database.

Construct a closed signed inspection selector using
`schemas/execution-fabric-cold-disposition.schema.json`'s `inspectionRequest`
definition. Use the independently held recovery signing key and the existing
canonical serializer; include the exact current owner/work/context and a
bounded authorization window. The standard command first checks only static
structure and signature:

```sh
agentic-os runtime cold-recovery inspect-disposition \
  --request /private/operator/item-inspection.json \
  --policy /private/operator/cold-policy.json \
  --anchor /private/operator/recovery-anchor.json \
  --journal-dir /private/operator/recovery-journal \
  --service-root /reviewed/source/services \
  --database-url-file /private/operator/target-database-url \
  --json
```

Add `--apply` to this **inspection** command to obtain actual database and
canonical-authority readback. The native actor owns the SQLite writer barrier
and PostgreSQL locks during the read, then rolls them back without changing
item, event or decision records. Its receipt reports current item/history/
dependency/work digests, the previous disposition digest and bounded dependency
counts. Its bounded `decisionHistory` contains immutable receipt/predecessor/
event references and generations; it verifies the retained events and each
generation's chain without exposing context bodies or provider data.
`routeQualified=false` is explicit: the accepted canary was created after the
first hold and cannot satisfy this required pre-hold association/history.
`requeueAvailable=false` and `providerOutcomeVerifier="unavailable"` remain
explicit. Static dry-run results report that database and canonical authority
have not been validated.

For a hold or cancellation, construct the closed `request` definition from
those actual readbacks. Bind a stable new idempotency key and the current
predecessor. Cancellation additionally requires the real owner's work to have
reached `finished`, `documented` or `archived` through its normal workflow, no
active attempts/runs/claim, and reason `owner_cancelled`. Do not edit old task
attempts, receipts or history to obtain those states.

Use the existing canonical approval producer
`state.control_plane_facts.request_approval` with subject type
`execution_fabric_cold_disposition`, subject ID equal to the task/effect UUID,
the actual owner as requester and the explicit operator as named approver.
Its metadata `requestSha256` is produced by
`cold_quarantine_disposition.approval_binding(payload)`, which excludes only
`approvalSha256` to avoid a circular row hash. The named operator records the
decision with the existing `decide_approval` API before expiry. Hash the actual
approved SQLite row, including its stored metadata JSON string, into
`approvalSha256`, then sign the complete request. There is no new CLI that
implicitly creates or approves this authority; a missing qualified owner/
approval integration is a hold, not an invitation to write raw SQLite rows.

Run `disposition` with the same explicit references, first without `--apply`,
then add `--apply` only for the exact reviewed request. The fixed native actor
holds the existing canonical SQLite writer fence through PostgreSQL commit,
checks the current accepted recovery and loaded/applied execution policy,
preserves all dependency/history bytes, appends one immutable decision and
event, and verifies their readbacks. Unsupported backends and provider verbs
refuse. Each independent item needs its own original association and approval.

Keep the returned private local receipt and actual database receipt. If the
database committed but local publication failed, exact unchanged replay of the
same signed request can retrieve the committed proof and publish only a missing
local receipt. It never overwrites a conflicting receipt. Expired authorization
can retrieve an already committed unchanged proof; it cannot authorize a new
decision. A changed item, dependency, owner, policy, event or successor decision
refuses replay. Fresh decisions need a new key, current predecessor, fresh
readbacks and a new approval. Preserve refused attempts and investigate their
cause; do not retry an unchanged refusal.

Migration `017_cold_quarantine_dispositions` preserves every migration-016 hold
as immutable generation-keyed history. Existing consumers read active-hold
views under their original names. A later recovery/failback records fresh holds
and rejects old generation/epoch proofs. This revision's database constraints
prohibit every quarantine release, including through the disposition journal.
Local fixture qualification of these operations is separate from an installed
release, current host recovery, customer data restoration and provider readiness.

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
