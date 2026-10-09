# Held Fabric restoration tools

Use these tools to preserve and inspect recovery evidence and to prepare an inert release candidate. Their receipts separate source validation, recovered data authority, installation, activation and customer acceptance.

The tools use Python's standard library. They do not invoke the product CLI, source Env/config, query databases, invoke Docker/systemd, provision credentials, execute an archived helper or contact a provider/model. The inventory never writes files. The staging tool writes six inert files and one receipt to one new directory. Its rollback command verifies and preserves that directory; it removes nothing.

## Clone and pin the tool source

Use a separate clean tools checkout at the exact reviewed revision. Preserve an existing dirty runtime/source checkout.

~~~sh
git clone https://github.com/michaelwclark/genomes_agentic_os.git rubicon-restoration-tools
git -C rubicon-restoration-tools checkout --detach <reviewed-tools-commit>
git -C rubicon-restoration-tools rev-parse HEAD
~~~

Replace the commit placeholder with the source revision accepted by the normal development/review/release workflow. The tools revision and the recovered runtime release revision are separate identities. A clean source checkout does not prove that the installed runtime has that version.

Before an administrator executes a tool, provide a trusted immutable copy and its separately reviewed SHA-256. Python's isolated mode prevents user import configuration. Do not run an unreviewed mutable user file as root or add a new elevation mechanism to overcome a denied action.

## Verify the original held bundle

An accepted held bundle contains exactly eight regular mode-0600 members: held-stage-plan.json, a historical held_staging.py reference, and six payload files. The source tool never executes that historical helper and never extracts the archive.

~~~sh
python3 -I -B installers/execution-fabric/bin/held-staging.py verify \
  --bundle /absolute/path/to/accepted-held-stage.tar.gz \
  --bundle-sha256 <accepted-original-bundle-sha256>

python3 -I -B installers/execution-fabric/bin/held-staging.py plan \
  --bundle /absolute/path/to/accepted-held-stage.tar.gz \
  --bundle-sha256 <accepted-original-bundle-sha256>
~~~

Verify authentic release custody/attestation and obtain the bundle pin through the normal workflow before using the tool. The pin is checked before archive/JSON interpretation. Verification rejects foreign/duplicate members, links, directories/devices, unsafe modes, expanded-size overflow, payload digest/size drift, duplicate JSON keys, any operational effect, and any admitted activation or initialization in HOLD.

The plan's target is an exact child of its existing staging_parent. The six files are HOLD.json, SHA256SUMS, execution-fabric-config-schema.tar.gz, execution-fabric-emergency-bundle.tar.gz, execution-fabric-image-lock.json and execution-fabric-release-manifest.json. Every payload remains inert, including the nested emergency bundle.

Retain original historical compressed bytes. Reserializing or recompressing a candidate creates a different artifact and must receive a new pin; it cannot inherit the original bundle identity. A local verification result does not refresh provider release/attestation truth.

## Inventory recovery custody before bootstrap

The administrator inventory traverses one explicitly admitted absolute directory. Its hard limits are depth 4, 2,000 listed entries and 80 MiB of aggregate payload hashing. Every directory component and file uses no-follow descriptors. Protected credential/config/Env/log/account paths receive metadata only, and protected directories are not entered. Symlinks, special files and nested devices are not traversed.

Eligible recovery archives, SQLite snapshots, dumps and opaque encrypted artifacts receive a SHA-256 within the budget and a fixed binary-magic classification when recognized. Raw header bytes, contents, Env values and decoded configuration are never emitted. An unknown extension remains metadata only. Files changing during hashing receive no digest.

~~~sh
python3 -I -B /trusted/pinned/recovery-inventory.py \
  --expected-script-sha256 <reviewed-inventory-script-sha256> \
  --root /absolute/admitted/recovery-directory \
  --max-depth 4 --max-entries 2000 --max-hash-bytes 83886080 --json
~~~

The trusted copy is an operator prerequisite, not an installation performed by this command. Supply only the emitted JSON to the private recovery task. Do not include configuration, credentials, terminal history, raw database output or logs. Preserve missing/inaccessible/unstable/protected/truncated distinctions. Filename hints identify candidate roles, not datastores.

All inventory receipts retain authority=unproven, recovery_set_complete=false and bootstrap_allowed=false. The recovery-set owner must bind a consistent accepted PostgreSQL system identity/WAL recovery point, witness leader/epoch/sentinel, object/report hashes and current source/policy/host/owner/context. Even a valid SQLite header and identical snapshot hashes do not establish current PostgreSQL authority. Do not initialize an empty store or promote a leader from inventory evidence.

## Apply only separately admitted inert staging

The caller must obtain exact operational authorization through the existing governed workflow and a separately admitted existing staging parent before application. This tool does not create an authorization system. A pinned parent receipt records that workflow's provenance; parsing an opaque receipt is not an authorization verdict.

~~~sh
python3 -I -B installers/execution-fabric/bin/held-staging.py stage \
  --bundle /absolute/path/to/accepted-held-stage.tar.gz \
  --bundle-sha256 <accepted-original-bundle-sha256> \
  --parent-receipt /absolute/path/to/existing-governed-operation-receipt.json \
  --parent-receipt-sha256 <reviewed-existing-parent-receipt-sha256> \
  --apply
~~~

Application creates only the plan's new mode-0700 target, six mode-0600 payloads and STAGING-RECEIPT.json. It requires a parent owned by the executing principal without group/other write permission. Existing files/directories, broken target links, symlink components, missing parents and foreign parents fail closed. It neither creates the parent nor overwrites an existing target.

The receipt records original bundle/plan/payload pins, target inode/device/owner, the parent custody and existing parent receipt pin. It leaves all 17 operational effects false and activation/bootstrap disallowed. Errors retain every new partial file for reconciliation; there is no automatic cleanup or repair.

Success requires synchronizing each file, the target directory and its parent directory. A parent synchronization failure refuses success and preserves the full or partial new directory for reconciliation; a file left by a failed command is not a successful workflow receipt.

The tool does not update current, write systemd units/runtime.env, reload/enable/start services, pull images, initialize state, open an API, admit a worker or touch queues/schedulers/healers/failback. Omitting --enable from the stock Linux installer is insufficient for inert staging: that installer still writes operational files and reloads systemd.

## Verify rollback without deleting state

Pin the recorded STAGING-RECEIPT.json separately, then request read-only preservation verification:

~~~sh
python3 -I -B installers/execution-fabric/bin/held-staging.py rollback \
  --bundle /absolute/path/to/accepted-held-stage.tar.gz \
  --bundle-sha256 <accepted-original-bundle-sha256> \
  --receipt /absolute/staged/target/STAGING-RECEIPT.json \
  --receipt-sha256 <recorded-staging-receipt-sha256>
~~~

Verification requires the exact target binding, directory identity/mode/owner, closed seven-file set, recorded receipt and six private payload digests. Altered, partial, foreign or symlink state is preserved and refused. Successful verification removes zero files; any cleanup needs a separate admitted procedure.

Verification also requalifies the recorded staging-parent custody and opens the target relative to that parent descriptor. After all file reads it repeats the bounded name check, checks file and directory metadata stability, and reopens the recorded parent namespace. A moved parent/target, concurrent foreign entry or change to an already read file refuses success while preserving every file.

## Continue installation and acceptance

After accepted recovery authority, qualify the target OS/package/container prerequisites and daemon suppression, then use the separately authorized supported operational installer. Provide protected role-specific secret references through ordinary custody. Do not copy secret values into plans or receipts.

AGE-224 activation holds, account-only native Claude qualification and held provider families remain independent gates. Producers/workers/replay need their current admitted authority. Validate installed package version, installed source/assets, configuration composition, service/API behavior, datastore/witness/object authority and applicable customer acceptance separately. These utilities do not satisfy those gates.

## Focused source checks

Run the two standalone utility test modules in the registered source worktree:

~~~sh
python3 -B -m pytest -q -p no:cacheprovider \
  tests/test_fabric_held_staging.py tests/test_fabric_recovery_inventory.py
~~~

The tests use disposable local directories and synthetic candidates. They cover malformed bundles, closed HOLD/effects, digest gates, links/devices, collision/foreign/mode/tamper preservation, partial writes, rollback with zero deletions, metadata limits, sensitive canary suppression and authority remaining unproven. Passing these checks is local source evidence. Normal full source/coverage/review/release gates remain required before installed consumption.
