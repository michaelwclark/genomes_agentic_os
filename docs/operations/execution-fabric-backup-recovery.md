# Complete Rubicon recovery sets

The daily PostgreSQL backup continues when complete recovery sets are disabled.
The new wrapper preserves its disposable database restore and readback checks.
A complete recovery set additionally captures every required authority and verifies
an exact encrypted restic snapshot on the custodian. Success receipts distinguish
local capture, encrypted byte readback, actual application restore, authority
transfer, installation, release and customer acceptance.

## Daily recovery and custody

The target is an encrypted recovery set every day and a cold manual restore on
BigMac within a few hours. Measure the recovery time in a real arm64 drill before
claiming it is met. Retain 14 daily, 4 weekly and 3 monthly verified sets, the latest
good set, and every explicitly pinned drill snapshot.

The primary must not hold the custodian repository password or credentials able
to delete its backup history. Keep a separately recoverable decryption key under
approved offline custody. Record custodians, key references, tested dates and
permissions without key values. Encryption does not establish independent deletion
protection or offsite coverage. Existing Mongo backups and Rubicon recovery sets
require separate successful snapshot receipts.

Ordinary capture and collection never delete backup history. Retention apply requires a fresh
custodian approval bound to the exact retention plan, repository and drill pins
plus independent deletion-protection evidence. It forgets only named full snapshot
IDs and never prunes. Collection removes only its own generated temporary
readback. Explicit plaintext staging/readback directories remain private and need
the approved custodian cleanup procedure.

## Capture contract

A private execution-fabric-recovery-capture/v1 JSON plan binds recoverySetId,
sourceHost, exact sourceRelease, actual imageLockSha256, policySha256 and
commonWatermark. Its components object has exactly these ten names, each with
nonempty byte sources. Each source has exactly kind (file, tree or sqlite),
absolute source, component-prefixed relative path, and immutable owner/context
sourceBinding. Symlinks, special files, traversal, overlapping destinations and
source/target overlap fail closed.

| Component | Required componentMetadata |
| --- | --- |
| postgres | dump, receipt, restoreManifest relative paths; original systemId and integer majorVersion. Actual dump bytes match the real restore-health sidecars and run identity. |
| witness | database, sentinel, backup, hostMarker, clusterId, version, leader, epoch, auditTailSha256, originalDatabasePath, originalBackupPath, signingPublicKey, signingPublicKeySha256. |
| artifactStore | inventory with every available artifact payload, original object key and object version. Preserve versioned MinIO exports and metadata. |
| workerSpools | inventory covering all pending and quarantined receipts and payloads with original owner bindings. |
| osAuthorities | Actual canonical SQLite snapshot and authorityId. Include task, approval, effect, event and room authorities used by the installation. Placeholder databases do not qualify. |
| immutableReceipts | inventory covering immutable run, review, gate, acceptance and continuity receipts with owner/context bindings. |
| configuration | authorities mapping runtimeEnv, hosts, fabricPolicy and installerState to captured private paths. |
| releaseAssets | authorities.imageLock and authorities.releaseManifest. Actual image-lock bytes match the top-level digest. |
| sourceRecovery | authorities.bundle and authorities.dirtyPatch preserving exact release source and uncommitted state. |
| credentialEscrow | authorities.secretsBundle and authorities.custodyMetadata with approved decryption/signing key custody. |

Each reference inventory has exactly schemaVersion and references. Schemas are
execution-fabric-recovery-artifacts/v1, execution-fabric-recovery-spools/v1 and
execution-fabric-recovery-receipts/v1. Every reference has relativePath, actual
sha256, integer bytes and ownerBinding. Artifact references also have artifactId,
objectKey and versionId. Every payload must be represented once. Empty references
are permitted only when the component contains its inventory alone and the actual
maintenance readback establishes that no payload exists.

Key-custody metadata uses execution-fabric-recovery-key-custody/v1 and includes
custodianIdentity, recoveryKeyRef and testedAt, all non-secret references.
Custody claims still require a real decryption/signing recovery drill.

SQLite capture uses the read-only backup API, preserves committed WAL rows, and
checks integrity. Witness capture never invokes the store constructor, claims a
lease, changes an epoch, bootstraps an empty store or rewrites history. Verification
compares original and backup database snapshots, cluster/version/leader/epoch,
relational audit and history. Original initialized sentinel absolute bindings and
standalone host marker remain untouched. Witness signing public key identity is
SHA256 of canonical Ed25519 SPKI DER, independent of PEM whitespace; the inventory
separately hashes original file bytes. Relocation belongs to cold restoration.

The manifest schema is schemas/execution-fabric-recovery-set.schema.json.
Manifest inventories are private and contain path/owner metadata. Public CLI
results contain safe identities, counts and digests.

## Consistent source preparation

Manual capture accepts a private, current
execution-fabric-recovery-quiescence/v1 receipt with status=verified, matching
sourceHost, policySha256, commonWatermark, maintenanceRunId, beforeWatermarks,
afterWatermarks, nonempty heldRoleIdentities, verifiedAt and byte-bound
verificationReceipts (path, sha256). Before and after watermarks must agree.
The proof expires after ten minutes and is rechecked after copying.

A schedule or a hand-authored assertion does not establish live quiescence.
The daily coordinator requires the released producer-admission/v1 protocol and
independent qualification of api, scheduler, workers, artifactWriters, witness and
osWriters. It refuses before holds, output creation and native actors when any
participant is missing, its original root/review scope differs, or qualified
installed module, exporter, PG actor/helper/validator or native Node bytes differ.
It never imports another development worktree or substitutes queue cancellation
for a reversible hold.

The canonical daily_plan_file must equal the explicit --daily-plan argument.
The private execution-fabric-recovery-daily/v1 input binds sourceHost,
sourceRelease, imageLockSha256, policySha256, qualificationFile, captureTemplate,
exportPlan, stagingRoot, releaseRoot, backupHealthReceipt, backupDirectory and an
absolute node executable. Its schema is schemas/execution-fabric-recovery-daily.schema.json.
The wrapper uses this coordinator only when complete sets are enabled.

Daily qualification uses execution-fabric-recovery-daily-qualification/v1,
status=qualified, matching source identities, allWritersParticipate=true,
qualifiedAt, an explicit independently approved validUntil, admissionModuleSha256,
exportMainSha256, exportModuleSha256, backupHealthSha256, backupLibSha256,
backupReceiptValidatorSha256, nodeSha256 and participants. Every participant has
role, absolute canonical root, exact reviewRoots, qualificationReceipt and
qualificationSha256. Actual receipt bytes use
execution-fabric-recovery-participant-qualification/v1 and bind qualified status,
role/root/reviewRoots/sourceRelease/protocol, allWriterEntryPointsParticipate=true,
the admission module digest and independent qualification lifetime. The daily job
cannot qualify or extend its own admission. Every run still proves current drain,
retained barriers, original definitions and actual before/after watermarks.

Each run creates a fresh timestamp/UUID set and holds only its own declared
producer overlay. It runs the fixed released PG backup-health actor, reads fresh
actual restore proof, exports every MinIO version and delete-marker metadata,
captures SQLite authorities, compares post-capture watermarks, and invokes the
supported exact original-state restore/readback while retaining barriers. Actual
holding receipts are copied before their supported writer advances them. These,
qualification inputs, original capture template, export receipts, final watermarks
and restoration readbacks are included in the new set's immutable receipt
inventory. Existing history remains untouched.

The read-only export plan uses execution-fabric-recovery-export-plan/v1 with
sourceHost, endpoint, bucket, region, credentialFile, readOnlyDatabaseRole,
ownerBinding, maxVersions and maxBytes. Its private credential reference holds
accessKeyId, secretAccessKey and databaseUrl. Use a qualified non-elevated PG
read-only role and object permissions for ListBucketVersions, GetBucketVersioning,
GetObjectVersion and GetObjectVersionTagging. No Put/Delete/versioning enable
operation is performed. Payloads, object metadata/tags, original keys/version IDs,
delete markers and actual available ledger references are byte verified.

Only a fully verified set whose original admission readback restored is moved to
sets/<fresh-id> and atomically selected in current-success.json. Failures preserve
the prior successful pointer and leave a private attempt failure receipt. A
remaining definition change keeps the affected hold unresolved and requires its
supported owner recovery. Template inputs for spools, immutable history, source
bundle/dirty patch and escrow must be maintained by qualified canonical owners;
missing or inconsistent component inventories fail closure. The source coordinator
does not manufacture custody or released writer qualification.

    agentic-os runtime recovery-set daily --root "$OS_ROOT" \
      --daily-plan "$CANONICAL_DAILY_PLAN" --apply --json

    agentic-os runtime recovery-set plan --root "$OS_ROOT" \
      --capture-plan "$CAPTURE_PLAN" --json

    agentic-os runtime recovery-set prepare --root "$OS_ROOT" \
      --capture-plan "$CAPTURE_PLAN" --maintenance-receipt "$MAINTENANCE_PROOF" \
      --output "$NEW_SET_DIR" --apply --json

## BigMac collection

Explicitly enable canonical execution_fabric.recovery_sets.enabled, bind
primary_host_id and custodian_host_id, and declare remote_staging_root. Register
both hosts in canonical identity and routing registries. The collector runs under
the custodian's exact stable host identity. Apply binds repository, password-file
and automated local staging references to their canonical configured paths.
Install native restic and initialize
the protected custodian-local repository separately. Missing tools, credentials
or permissions stop without an alternate transport or API fallback.

Daily collection reads the fixed registered source current-success.json, verifies
its complete source/set/digest/original-restoration binding, then pulls that exact
immutable set. Pull permits only a registered SSH alias and a recovery set beneath
the declared remote staging root. Remote commands are fixed quoted cat -- for the
current pointer and tar -C PATH -cf - . for its exact set.
SSH uses batch mode, no forwarding and a bounded connection timeout. Extraction
rejects traversal, links and devices. Destination bytes, source host and authority
closure are verified. Permission refusals stop.

    agentic-os runtime recovery-set pull --root "$OS_ROOT" \
      --source-host genomesbox --remote-source "$PRIMARY_SET_DIR" \
      --output "$NEW_LOCAL_SET_DIR" --apply --json

    agentic-os runtime recovery-set collect --root "$OS_ROOT" \
      --source-dir "$NEW_LOCAL_SET_DIR" --set-id "$EXACT_SET_ID" \
      --repository "$LOCAL_REPOSITORY" --password-file "$CUSTODIAN_PASSWORD_FILE" \
      --verify-target "$NEW_READBACK_DIR" --apply --json

    agentic-os runtime recovery-set collect-current --root "$OS_ROOT" \
      --source-host genomesbox --local-root "$CUSTODIAN_LOCAL_STAGING_ROOT" \
      --repository "$LOCAL_REPOSITORY" --password-file "$CUSTODIAN_PASSWORD_FILE" \
      --apply --json

Collection gives restic a password-file reference, obtains the full immutable
snapshot ID, restores that ID into a new private target, and verifies every
payload and manifest identity. Only then does it publish
execution-fabric-recovery-custody/v1 beside the repository. Successful byte
readback reports applicationRestoreQualification=required and
independentDeletionProtectionVerified=false. A native restic receipt is required
for encryption qualification; fixture runners test code behavior only.

The installed template launchd/com.genomes.agentic-os.execution-fabric.recovery-backup.plist
runs daily at 03:30 local time, with no run-at-load or keep-alive. Ordinary Fabric
activation leaves it unloaded. Load it after explicit configuration and a
supervised successful collection. A loaded schedule does not prove backup success.

| Primary environment | Purpose |
| --- | --- |
| FABRIC_RECOVERY_SETS_ENABLED | 1 enables complete capture; other values preserve PG-only backups. |
| FABRIC_RECOVERY_DAILY_PLAN_FILE | Exact canonical private daily coordinator input. |
| FABRIC_RECOVERY_AGENTIC_OS_CLI | Installed executable, default agentic-os. |

| Collector environment | Purpose |
| --- | --- |
| FABRIC_RECOVERY_SOURCE_HOST | Registered canonical primary identity for fixed current-set selection and pull. |
| FABRIC_RECOVERY_LOCAL_STAGING_ROOT | Canonical private root for fresh local current-set transfers. |
| FABRIC_RECOVERY_REPOSITORY / FABRIC_RECOVERY_PASSWORD_FILE | Independently initialized local repository and protected custodian key-file reference. |
| FABRIC_RECOVERY_RESTIC | Native binary, default restic. |

## Isolated restore and disaster drill

    agentic-os runtime recovery-set restore-plan --root "$OS_ROOT" \
      --repository "$LOCAL_REPOSITORY" --password-file "$CUSTODIAN_PASSWORD_FILE" \
      --snapshot-id "$FULL_SNAPSHOT_ID" --target "$NEW_DRILL_ROOT" --json

    agentic-os runtime recovery-set restore-isolated --root "$OS_ROOT" \
      --repository "$LOCAL_REPOSITORY" --password-file "$CUSTODIAN_PASSWORD_FILE" \
      --snapshot-id "$FULL_SNAPSHOT_ID" --target "$NEW_DRILL_ROOT" --apply --json

This restores and verifies filesystem bytes without changing live services or
authority. Finish application qualification in a fresh isolated namespace:
install the exact release and arm64 image locks; restore PostgreSQL into a
disposable database and read back all schemas/tables/authorities; restore MinIO
keys and versions and verify available object/receipt/pending/quarantine payload
hashes; load canonical OS authorities without replacing owner contexts; prove
signing and decryption custody. Pin the drill snapshot and record elapsed time,
actual package/image compatibility, source/custody identities, application readback
hashes and safety holds.

The closed execution-fabric-cold-restore-input/v1 is admitted only after actual
application restore/readback and custody evidence. It binds manifest/restore
receipt, source release/image lock/watermark, original witness cluster/version/
leader/epoch/audit/path digests, original PostgreSQL system/version and actual
readback, verified artifact references, OS/immutable receipt inventories and
custody receipt. Missing evidence keeps transfer held. Cold restoration separately
records supported witness relocation and authority transfer. Never hand-edit a
sentinel, bootstrap empty authority, use normal HA promotion, replay unaccepted
effects or replace source history to make a drill pass.

Keep backup validation distinct from merge, installed package, actual host runtime,
eligible review/release and customer acceptance receipts.
