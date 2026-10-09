from __future__ import annotations

import argparse
import base64
from contextlib import closing
from datetime import datetime, timedelta, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import tarfile
from types import SimpleNamespace

from jsonschema import Draft202012Validator
import pytest

from genomes_agentic_os import execution_fabric_recovery as r
from genomes_agentic_os.cli import runtime_recovery
from genomes_agentic_os.cli import main


SOURCE = Path(__file__).resolve().parents[1]
PG_SOURCE = {"schemaVersion": "execution-fabric-postgres-source/v1", "systemId": "7432345656789123456",
             "database": "execution_fabric", "databaseOid": "16384", "majorVersion": 17, "serverVersionNum": 170006}


def write(path: Path, value) -> Path:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.write_bytes(value if isinstance(value, bytes) else json.dumps(value).encode())
    path.chmod(0o600)
    return path


def custody_fixture(identity: str, verified: str, *, repository_id: str = "e" * 64) -> dict:
    """Bound native-contract fixture; never qualifies an operational repository."""
    set_id = "fixture-" + identity[-12:]
    native = {"snapshotId": identity, "sourceRoot": "/isolated/fixture-source",
              "tags": ["rubicon-recovery:" + set_id], "createdAt": verified}
    return {"status": "encrypted_bytes_verified", "repositoryId": repository_id,
            "snapshotId": identity, "manifestSha256": "a" * 64, "verifiedAt": verified,
            "recoverySetId": set_id, "sourceRoot": native["sourceRoot"],
            "sourceTag": native["tags"][0], "nativeSnapshot": native,
            "snapshotMetadataSha256": r._digest(native)}


def catalog_row(custody: dict) -> dict:
    native = custody["nativeSnapshot"]
    return {"id": native["snapshotId"], "paths": [native["sourceRoot"]],
            "tags": native["tags"], "time": native["createdAt"]}


@pytest.fixture
def capture(tmp_path: Path):
    source = tmp_path / "authorities"
    sources = {name: [] for name in r.COMPONENTS}
    metadata = {}

    def add(component, name, value, kind="file"):
        path = write(source / component / name, value)
        sources[component].append({
            "kind": kind, "source": str(path),
            "path": component + "/" + name, "sourceBinding": "cluster-rubicon:owner-task:" + component,
        })
        return path

    dump = add("postgres", "ledger.dump", b"PGDMP-test-private-ledger")
    sidecar = add("postgres", "restore.json", {
        "schemaVersion": "execution-fabric-postgres-restore-manifest/v1", "runId": "backup-unit",
        "backupSha256": r.sha256(dump), "backupBytes": dump.stat().st_size,
        "restoreDatabaseCreated": True, "restoreCompleted": True,
        "readbackCompleted": True, "restoreDatabaseDropped": True,
        "readbackManifestSha256": "4" * 64,
        "sourceIdentityVerified": True, "sourceIdentityBefore": PG_SOURCE, "sourceIdentityAfter": PG_SOURCE,
    })
    add("postgres", "health.json", {
        "schemaVersion": "execution-fabric-backup-health/v1", "status": "passed",
        "runId": "backup-unit", "backupSha256": r.sha256(dump),
        "restoreManifest": {"sha256": r.sha256(sidecar)},
        "sourceIdentityVerified": True, "sourceIdentity": PG_SOURCE,
    })
    metadata["postgres"] = {"dump": "postgres/ledger.dump", "receipt": "postgres/health.json",
                            "restoreManifest": "postgres/restore.json",
                            **{name: PG_SOURCE[name] for name in ("systemId", "database", "databaseOid", "majorVersion")}}

    snapshot = {"schemaVersion": "execution-fabric-witness-store/v2",
                "state": {"clusterId": "rubicon", "currentLeader": "genomesbox", "fabricEpoch": 7},
                "promotions": [{"receiptId": "promote-preserve-history"}],
                "candidates": [], "plans": [], "configRotations": [],
                "configRotationAborts": [], "configRotationPreparations": [],
                "audit": [{"auditId": "audit-1", "occurredAt": "2026-10-09T01:00:00Z"}]}
    database = source / "witness" / "witness.db"
    database.parent.mkdir(parents=True)
    with closing(sqlite3.connect(database)) as db, db:
        db.executescript(
            "CREATE TABLE witness_snapshot(cluster_id TEXT,version INTEGER,payload TEXT);"
            "CREATE TABLE witness_audit(cluster_id TEXT,payload TEXT);"
            "CREATE TABLE witness_process_lease(cluster_id TEXT,owner_token TEXT);"
        )
        db.execute("INSERT INTO witness_snapshot VALUES (?,?,?)", ("rubicon", 12, json.dumps(snapshot)))
        db.execute("INSERT INTO witness_audit VALUES (?,?)", ("rubicon", json.dumps(snapshot["audit"][0])))
        db.execute("INSERT INTO witness_process_lease VALUES (?,?)", ("rubicon", "lease-must-not-change"))
    sources["witness"].append({"kind": "sqlite", "source": str(database),
                              "path": "witness/witness.db", "sourceBinding": "witness:original-authority"})
    add("witness", "witness.db.backup", database.read_bytes())
    original_database = "/original/runtime/witness/witness.db"
    add("witness", "witness.db.initialized", {
        "schemaVersion": "execution-fabric-witness-bootstrap/v1", "clusterId": "rubicon",
        "initializedAt": "2026-01-01T01:00:00Z", "database": original_database,
        "backup": original_database + ".backup",
    })
    add("witness", "standalone-witness.bootstrap-complete",
        b"cluster=rubicon initialized=2026-01-01T01:00:00Z\n")
    der = bytes.fromhex("302a300506032b6570032100") + bytes(range(32))
    pem = b"-----BEGIN PUBLIC KEY-----\n" + base64.b64encode(der) + b"\n-----END PUBLIC KEY-----\n"
    key = add("witness", "signing.pem", pem)
    metadata["witness"] = {
        "database": "witness/witness.db", "sentinel": "witness/witness.db.initialized",
        "backup": "witness/witness.db.backup", "hostMarker": "witness/standalone-witness.bootstrap-complete",
        "clusterId": "rubicon", "version": 12, "leader": "genomesbox", "epoch": 7,
        "auditTailSha256": r._digest(snapshot["audit"]), "originalDatabasePath": original_database,
        "originalBackupPath": original_database + ".backup", "signingPublicKey": "witness/signing.pem",
        "signingPublicKeySha256": r.signing_public_key_sha256(key),
    }

    for component, schema, payload_name in (
        ("artifactStore", "execution-fabric-recovery-artifacts/v1", "object-version-1"),
        ("workerSpools", "execution-fabric-recovery-spools/v1", "quarantine/pending-payload"),
        ("immutableReceipts", "execution-fabric-recovery-receipts/v1", "owner-task-receipt"),
    ):
        payload = add(component, payload_name, b"private-object-or-receipt-content")
        reference = {"relativePath": component + "/" + payload_name, "sha256": r.sha256(payload),
                     "bytes": payload.stat().st_size, "ownerBinding": "owner-context-immutable"}
        if component == "artifactStore":
            reference.update({"artifactId": "artifact-1", "objectKey": "objects/key", "versionId": "version-1"})
        add(component, "inventory.json", {"schemaVersion": schema, "references": [reference]})
        metadata[component] = {"inventory": component + "/inventory.json"}

    os_db = source / "osAuthorities" / "canonical.db"
    os_db.parent.mkdir()
    live_os = sqlite3.connect(os_db)
    live_os.execute("PRAGMA journal_mode=WAL")
    live_os.execute("CREATE TABLE tasks(task_id TEXT,owner_context TEXT)")
    live_os.execute("INSERT INTO tasks VALUES ('AGE-250','immutable-owner')")
    live_os.commit()
    sources["osAuthorities"].append({"kind": "sqlite", "source": str(os_db),
                                    "path": "osAuthorities/canonical.db",
                                    "sourceBinding": "harness-control-plane:canonical"})
    metadata["osAuthorities"] = {"snapshot": "osAuthorities/canonical.db",
                                 "authorityId": "harness/shared_factory/00-control-plane/state.db"}
    for component, names in {
        "configuration": ("runtimeEnv", "hosts", "fabricPolicy", "installerState"),
        "releaseAssets": ("imageLock", "releaseManifest"),
        "sourceRecovery": ("bundle", "dirtyPatch"),
        "credentialEscrow": ("secretsBundle", "custodyMetadata"),
    }.items():
        metadata[component] = {"authorities": {}}
        for name in names:
            value = b"unit-private-bytes-" + name.encode()
            if name == "custodyMetadata":
                value = {"schemaVersion": "execution-fabric-recovery-key-custody/v1",
                         "custodianIdentity": "bigmac-custodian",
                         "recoveryKeyRef": "offline-recovery-key-custody",
                         "testedAt": "2026-10-09T01:00:00Z"}
            add(component, name, value)
            metadata[component]["authorities"][name] = component + "/" + name
    proof_file = write(tmp_path / "readback.json", {"status": "verified", "maintenanceRunId": "maint-unit"})
    plan = {
        "schemaVersion": "execution-fabric-recovery-capture/v1", "recoverySetId": "daily-unit",
        "sourceRelease": "v0.9.0+unit-source", "sourceHost": "genomesbox",
        "imageLockSha256": r.sha256(source / "releaseAssets" / "imageLock"),
        "policySha256": "d" * 64, "commonWatermark": "watermark-7",
        "components": sources, "componentMetadata": metadata,
    }
    proof = {
        "schemaVersion": "execution-fabric-recovery-quiescence/v1", "status": "verified",
        "sourceHost": "genomesbox", "policySha256": "d" * 64,
        "commonWatermark": "watermark-7", "maintenanceRunId": "maint-unit",
        "beforeWatermarks": {"ledger": 7, "witness": 12}, "afterWatermarks": {"ledger": 7, "witness": 12},
        "heldRoleIdentities": {"admission": "held-original-role", "writers": "held-owner"},
        "verifiedAt": datetime.now(timezone.utc).isoformat(),
        "verificationReceipts": [{"path": str(proof_file), "sha256": r.sha256(proof_file)}],
    }
    try:
        yield write(tmp_path / "plan.json", plan), write(tmp_path / "maintenance.json", proof), source
    finally:
        live_os.close()


def prepared(capture, tmp_path):
    plan, maintenance, source = capture
    target = tmp_path / "set"
    receipt = r.prepare_recovery_set(plan, maintenance, target, apply=True)
    return target, receipt


def test_capture_has_real_wal_rows_private_bytes_and_closed_manifest(capture, tmp_path):
    assert Path(str(capture[2] / "osAuthorities/canonical.db") + "-wal").stat().st_size > 0
    target, receipt = prepared(capture, tmp_path)
    assert receipt["status"] == "local_capture_complete" and not receipt["offhostCustodyVerified"]
    with closing(sqlite3.connect(target / "osAuthorities/canonical.db")) as db, db:
        assert db.execute("SELECT * FROM tasks").fetchall() == [("AGE-250", "immutable-owner")]
    with closing(sqlite3.connect(capture[2] / "witness/witness.db")) as db, db:
        assert db.execute("SELECT owner_token FROM witness_process_lease").fetchone() == ("lease-must-not-change",)
    manifest = json.loads((target / "manifest.json").read_text())
    schema = json.loads((SOURCE / "schemas/execution-fabric-recovery-set.schema.json").read_text())
    Draft202012Validator(schema).validate(manifest)
    assert json.loads((target / "witness/witness.db.initialized").read_text())["database"].startswith("/original/")
    assert all((target / entry["relativePath"]).stat().st_mode & 0o077 == 0 for entry in manifest["files"])
    assert "unit-private-bytes" not in json.dumps(receipt)


def multi_root_maintenance(capture, tmp_path):
    proof = json.loads(capture[1].read_text())
    proof["schemaVersion"] = "execution-fabric-recovery-quiescence/v2"
    hold = write(tmp_path / "held-admission.json", {"status": "isolated-fixture-only", "owner": "maint-unit"})
    proof["verificationReceipts"].append({"path": str(hold), "sha256": r.sha256(hold)})
    identities = {}
    for role in sorted(r.RECOVERY_ROLES):
        identities[role] = []
        for index in range(2 if role == "workers" else 1):
            qualification = write(tmp_path / (role + str(index) + "-qualified.json"),
                                  {"status": "isolated-fixture-only", "role": role, "index": index})
            proof["verificationReceipts"].append({"path": str(qualification), "sha256": r.sha256(qualification)})
            identities[role].append({"root": "/original/" + role + str(index),
                "maintenanceRunId": proof["maintenanceRunId"],
                "qualificationReceiptSha256": r.sha256(qualification), "admissionReceiptSha256": r.sha256(hold)})
    proof["heldRoleIdentities"] = identities
    write(capture[1], proof)
    return proof


def test_capture_preserves_all_multi_root_roles_without_requiring_original_roots(capture, tmp_path):
    proof = multi_root_maintenance(capture, tmp_path)
    validated_bytes = capture[1].read_bytes()
    target, _ = prepared(capture, tmp_path)
    manifest = json.loads((target / "manifest.json").read_text())
    assert manifest["captureWindow"]["maintenanceReceiptSha256"] == hashlib.sha256(validated_bytes).hexdigest()
    assert manifest["captureWindow"]["heldRoleIdentities"] == proof["heldRoleIdentities"]
    assert len(manifest["captureWindow"]["heldRoleIdentities"]["workers"]) == 2
    schema = json.loads((SOURCE / "schemas/execution-fabric-recovery-set.schema.json").read_text())
    Draft202012Validator(schema).validate(manifest)
    assert r.verify_recovery_set(target)["manifestSha256"] == r.sha256(target / "manifest.json")


@pytest.mark.parametrize("change", ["missing-role", "empty-list", "duplicate-root", "relative-root",
                                   "foreign-hold", "open-identity", "unbound-qualification", "unbound-admission", "open-proof"])
def test_v2_capture_refuses_incomplete_or_unbound_multi_root_identity_before_output(capture, tmp_path, change):
    proof = multi_root_maintenance(capture, tmp_path)
    identities = proof["heldRoleIdentities"]
    binding = identities["workers"][0]
    if change == "missing-role":
        identities.pop("api")
    elif change == "empty-list":
        identities["workers"] = []
    elif change == "duplicate-root":
        identities["workers"].append(dict(binding))
    elif change == "relative-root":
        binding["root"] = "guessed-root"
    elif change == "foreign-hold":
        binding["maintenanceRunId"] = "foreign-owner"
    elif change == "open-identity":
        binding["guessedHost"] = "foreign-host"
    elif change == "unbound-qualification":
        binding["qualificationReceiptSha256"] = "e" * 64
    elif change == "open-proof":
        proof["guessedParticipants"] = ["unqualified"]
    else:
        binding["admissionReceiptSha256"] = "f" * 64
    write(capture[1], proof)
    target = tmp_path / "refused-set"
    with pytest.raises(r.RecoverySetError, match="identity|identities|root|complete|proof"):
        r.prepare_recovery_set(capture[0], capture[1], target, apply=True)
    assert not target.exists()


def test_verified_manifest_refuses_open_or_missing_v2_role_bindings(capture, tmp_path):
    multi_root_maintenance(capture, tmp_path)
    target, _ = prepared(capture, tmp_path)
    manifest = json.loads((target / "manifest.json").read_text())
    manifest["captureWindow"]["heldRoleIdentities"]["workers"] = []
    write(target / "manifest.json", manifest)
    with pytest.raises(r.RecoverySetError, match="identity list"):
        r.verify_recovery_set(target)
    schema = json.loads((SOURCE / "schemas/execution-fabric-recovery-set.schema.json").read_text())
    assert list(Draft202012Validator(schema).iter_errors(manifest))


def test_v2_role_proof_cannot_change_during_capture(capture, tmp_path, monkeypatch):
    proof = multi_root_maintenance(capture, tmp_path)
    original = r._copy_source
    def change_once(*args):
        original(*args)
        proof["verifiedAt"] = datetime.now(timezone.utc).isoformat()
        write(capture[1], proof)
    monkeypatch.setattr(r, "_copy_source", change_once)
    target = tmp_path / "changed-maintenance"
    with pytest.raises(r.RecoverySetError, match="proof changed"):
        r.prepare_recovery_set(capture[0], capture[1], target, apply=True)
    assert not (target / "manifest.json").exists()


@pytest.mark.parametrize("version", ["v1", "v2"])
@pytest.mark.parametrize("change", ["sourceHost", "maintenanceRunId", "commonWatermark", "equivalent-json", "symlink"])
def test_inventory_seam_cannot_bind_replaced_or_equivalent_proof_bytes(capture, tmp_path, monkeypatch, version, change):
    if version == "v2":
        multi_root_maintenance(capture, tmp_path)
    original_bytes = capture[1].read_bytes()
    original_proof = json.loads(original_bytes)
    original_inventory = r._inventory
    previous = write(tmp_path / "last-good.json", {"recoverySetId": "original-last-good"})
    previous_bytes = previous.read_bytes()
    authorities = [capture[2] / "witness/witness.db", capture[2] / "witness/witness.db.initialized",
                   capture[2] / "osAuthorities/canonical.db"]
    authority_hashes = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in authorities}
    def inventory_then_replace(*args):
        result = original_inventory(*args)
        if change == "equivalent-json":
            replacement = json.dumps(original_proof, separators=(",", ":")).encode() + b" \n"
            assert replacement != original_bytes and json.loads(replacement) == original_proof
            capture[1].write_bytes(replacement)
        elif change == "symlink":
            destination = tmp_path / "replacement-proof.json"
            destination.write_bytes(original_bytes)
            capture[1].unlink()
            capture[1].symlink_to(destination)
        else:
            replacement = dict(original_proof)
            replacement[change] = "foreign-owner-context"
            write(capture[1], replacement)
        return result
    monkeypatch.setattr(r, "_inventory", inventory_then_replace)
    target = tmp_path / "refused-inventory-replacement"
    with pytest.raises(r.RecoverySetError, match="proof changed|proof is unavailable or unsafe"):
        r.prepare_recovery_set(capture[0], capture[1], target, apply=True)
    assert not (target / "manifest.json").exists() and not (target / "capture.receipt.json").exists()
    assert json.loads((target / "failed.receipt.json").read_text())["status"] == "incomplete"
    assert previous.read_bytes() == previous_bytes
    assert {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in authorities} == authority_hashes


@pytest.mark.parametrize("boundary", ["verification", "success-receipt"])
def test_final_result_refuses_proof_rewrite_and_removes_only_owned_success_artifacts(capture, tmp_path, monkeypatch, boundary):
    proof = multi_root_maintenance(capture, tmp_path)
    original_bytes = capture[1].read_bytes()
    def replace():
        replacement = json.dumps(proof, separators=(",", ":")).encode() + b" \n"
        assert replacement != original_bytes
        capture[1].write_bytes(replacement)
    if boundary == "verification":
        original = r._verify_postgres
        def verify_then_replace(*args):
            original(*args)
            replace()
        monkeypatch.setattr(r, "_verify_postgres", verify_then_replace)
    else:
        original = r._write
        def write_then_replace(path, value):
            original(path, value)
            if path.name == "capture.receipt.json":
                replace()
        monkeypatch.setattr(r, "_write", write_then_replace)
    target = tmp_path / "refused-final-rewrite"
    with pytest.raises(r.RecoverySetError, match="proof changed"):
        r.prepare_recovery_set(capture[0], capture[1], target, apply=True)
    assert not (target / "manifest.json").exists() and not (target / "capture.receipt.json").exists()
    assert json.loads((target / "failed.receipt.json").read_text())["status"] == "incomplete"


def test_manifest_digest_never_rereads_mutable_proof_through_generic_hasher(capture, tmp_path, monkeypatch):
    multi_root_maintenance(capture, tmp_path)
    expected = hashlib.sha256(capture[1].read_bytes()).hexdigest()
    original = r.sha256
    def reject_mutable_proof_hash(path):
        if Path(path) == capture[1]:
            pytest.fail("manifest digest reread the mutable proof instead of validated bytes")
        return original(path)
    monkeypatch.setattr(r, "sha256", reject_mutable_proof_hash)
    target, _ = prepared(capture, tmp_path)
    assert json.loads((target / "manifest.json").read_text())["captureWindow"]["maintenanceReceiptSha256"] == expected


@pytest.mark.parametrize("unsafe", ["symlink", "fifo", "oversized", "invalid-json", "nonobject"])
def test_capture_requires_bounded_nofollow_regular_proof_before_output(capture, tmp_path, unsafe):
    receipt = tmp_path / "unsafe-proof"
    if unsafe == "symlink":
        receipt.symlink_to(capture[1])
    elif unsafe == "fifo":
        os.mkfifo(receipt, 0o600)
    elif unsafe == "oversized":
        receipt.write_bytes(b" " * (4 * 1024 * 1024 + 1))
    elif unsafe == "invalid-json":
        receipt.write_bytes(b"\xff")
    else:
        receipt.write_bytes(b"[]")
    target = tmp_path / "refused-unsafe-proof"
    with pytest.raises(r.RecoverySetError, match="maintenance proof"):
        r.prepare_recovery_set(capture[0], receipt, target, apply=True)
    assert not target.exists()


@pytest.mark.parametrize("component", r.COMPONENTS)
def test_missing_any_authority_component_holds_capture(capture, tmp_path, component):
    plan = json.loads(capture[0].read_text())
    del plan["components"][component]
    write(capture[0], plan)
    with pytest.raises(r.RecoverySetError, match="components"):
        r.prepare_recovery_set(capture[0], capture[1], tmp_path / "set", apply=True)
    assert not (tmp_path / "set").exists()


@pytest.mark.parametrize("change", ["epoch", "version", "path", "marker", "audit", "key"])
def test_witness_history_and_original_bindings_must_match(capture, tmp_path, change):
    plan = json.loads(capture[0].read_text())
    witness = plan["componentMetadata"]["witness"]
    if change in ("epoch", "version"):
        witness[change] += 1
    elif change == "path":
        witness["originalDatabasePath"] = "/invented/empty-history.db"
    elif change == "marker":
        write(capture[2] / "witness/standalone-witness.bootstrap-complete", b"cluster=foreign initialized=now\n")
    elif change == "audit":
        with closing(sqlite3.connect(capture[2] / "witness/witness.db")) as db, db:
            db.execute("DELETE FROM witness_audit")
    elif change == "key":
        witness["signingPublicKeySha256"] = "e" * 64
    write(capture[0], plan)
    with pytest.raises(r.RecoverySetError, match="witness"):
        r.prepare_recovery_set(capture[0], capture[1], tmp_path / "set", apply=True)
    assert json.loads((tmp_path / "set/failed.receipt.json").read_text())["status"] == "incomplete"


@pytest.mark.parametrize("change", ["dump", "foreign_run", "unrestored"])
def test_pg_actual_dump_and_restore_provenance_are_required(capture, tmp_path, change):
    if change == "dump":
        write(capture[2] / "postgres/ledger.dump", b"tampered-ledger")
    else:
        sidecar = json.loads((capture[2] / "postgres/restore.json").read_text())
        sidecar["runId" if change == "foreign_run" else "restoreCompleted"] = "foreign" if change == "foreign_run" else False
        sidecar_path = write(capture[2] / "postgres/restore.json", sidecar)
        health = json.loads((capture[2] / "postgres/health.json").read_text())
        health["restoreManifest"]["sha256"] = r.sha256(sidecar_path)
        write(capture[2] / "postgres/health.json", health)
    with pytest.raises(r.RecoverySetError, match="PostgreSQL"):
        r.prepare_recovery_set(capture[0], capture[1], tmp_path / "set", apply=True)


@pytest.mark.parametrize("field", ["systemId", "database", "databaseOid", "majorVersion"])
def test_pg_declared_source_must_match_actual_native_sidecar(capture, tmp_path, field):
    plan = json.loads(capture[0].read_text())
    plan["componentMetadata"]["postgres"][field] = 16 if field == "majorVersion" else "99999"
    write(capture[0], plan)
    with pytest.raises(r.RecoverySetError, match="differs from native source"):
        r.prepare_recovery_set(capture[0], capture[1], tmp_path / "set", apply=True)


def test_pg_native_before_after_source_cannot_differ(capture, tmp_path):
    sidecar = json.loads((capture[2] / "postgres/restore.json").read_text())
    sidecar["sourceIdentityAfter"]["database"] = "foreign_database"
    path = write(capture[2] / "postgres/restore.json", sidecar)
    health = json.loads((capture[2] / "postgres/health.json").read_text())
    health["restoreManifest"]["sha256"] = r.sha256(path)
    write(capture[2] / "postgres/health.json", health)
    with pytest.raises(r.RecoverySetError, match="before/after provenance"):
        r.prepare_recovery_set(capture[0], capture[1], tmp_path / "set", apply=True)


@pytest.mark.parametrize("component", ["artifactStore", "workerSpools", "immutableReceipts"])
def test_reference_closure_checks_actual_object_spool_and_receipt_payload(capture, tmp_path, component):
    inventory = json.loads((capture[2] / component / "inventory.json").read_text())
    inventory["references"] = []
    write(capture[2] / component / "inventory.json", inventory)
    with pytest.raises(r.RecoverySetError, match="inventory omits"):
        r.prepare_recovery_set(capture[0], capture[1], tmp_path / "set", apply=True)


def test_capture_refuses_changed_watermark_without_publishing(capture, tmp_path):
    proof = json.loads(capture[1].read_text())
    proof["afterWatermarks"]["ledger"] += 1
    write(capture[1], proof)
    with pytest.raises(r.RecoverySetError, match="quiescence"):
        r.prepare_recovery_set(capture[0], capture[1], tmp_path / "set", apply=True)
    assert not (tmp_path / "set").exists()


@pytest.mark.parametrize("bad_path", ["../escape", "/absolute", "witness/../escape", "witness//duplicate"])
def test_path_contract_rejects_traversal(capture, tmp_path, bad_path):
    plan = json.loads(capture[0].read_text())
    plan["components"]["witness"][0]["path"] = bad_path
    write(capture[0], plan)
    with pytest.raises(r.RecoverySetError):
        r.prepare_recovery_set(capture[0], capture[1], tmp_path / "set", apply=True)


def test_unmanifested_secret_file_and_symlink_are_rejected(capture, tmp_path):
    target, _ = prepared(capture, tmp_path)
    extra = write(target / "manifest-copy-private", b"never-display")
    with pytest.raises(r.RecoverySetError, match="unmanifested"):
        r.verify_recovery_set(target)
    extra.unlink()
    (target / "secret-link").symlink_to(capture[2])
    with pytest.raises(r.RecoverySetError, match="special"):
        r.verify_recovery_set(target)


def test_interrupted_capture_does_not_replace_last_successful_root(capture, tmp_path, monkeypatch):
    original, _ = prepared(capture, tmp_path)
    digest = r.sha256(original / "manifest.json")
    def interrupted(*args):
        raise OSError("injected-private-payload-must-not-be-logged")
    monkeypatch.setattr(r, "_copy_source", interrupted)
    with pytest.raises(OSError):
        r.prepare_recovery_set(capture[0], capture[1], tmp_path / "interrupted", apply=True)
    assert r.sha256(original / "manifest.json") == digest
    assert json.loads((tmp_path / "interrupted/failed.receipt.json").read_text())["status"] == "incomplete"


def test_dry_run_never_reads_password_or_invokes_actor(capture, tmp_path):
    target, _ = prepared(capture, tmp_path)
    def forbidden(*args, **kwargs):
        pytest.fail("dry run invoked native actor")
    result = r.collect_recovery_set(target, str(tmp_path / "missing"), tmp_path / "absent-password",
                                    "daily-unit", runner=forbidden)
    assert result["status"] == "would_encrypt"
    assert r.restore_recovery_set_isolated("absent", "absent", "a" * 64, tmp_path / "restore",
                                          runner=forbidden)["status"] == "planned"
    assert not (tmp_path / "restore").exists()


def test_daily_collection_refuses_stale_set_but_byte_restore_remains_available(capture, tmp_path):
    target, _ = prepared(capture, tmp_path)
    manifest = json.loads((target / "manifest.json").read_text())
    manifest["capturedAt"] = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    write(target / "manifest.json", manifest)
    receipt = json.loads((target / "capture.receipt.json").read_text())
    receipt["manifestSha256"] = r.sha256(target / "manifest.json")
    write(target / "capture.receipt.json", receipt)
    assert r.verify_recovery_set(target)["status"] == "bytes_verified"
    with pytest.raises(r.RecoverySetError, match="stale"):
        r.collect_recovery_set(target, "not-read", "not-read", "daily-unit")


def test_native_command_failure_does_not_disclose_private_output():
    with pytest.raises(r.RecoverySetError) as error:
        r.native_command(["sh", "-c", "printf 'secret-key-content' >&2; exit 1"])
    assert "secret-key-content" not in str(error.value)


def test_encryption_exact_snapshot_is_restored_and_bytes_verified(capture, tmp_path):
    target, original = prepared(capture, tmp_path)
    repo = tmp_path / "repository"
    repo.mkdir(mode=0o700)
    password = write(tmp_path / "repository-password", b"fixture-secret-key")
    seen = []
    def native_fixture(argv, **kwargs):
        seen.append(argv)
        if "cat" in argv:
            return subprocess.CompletedProcess(argv, 0, json.dumps({"id": "e" * 64}).encode())
        if "snapshots" in argv:
            return subprocess.CompletedProcess(argv, 0, json.dumps([{"id": "a" * 64,
                "paths": [str(target)], "tags": ["rubicon-recovery:daily-unit"],
                "time": datetime.now(timezone.utc).isoformat()}]).encode())
        if "backup" in argv:
            return subprocess.CompletedProcess(argv, 0, b'{"message_type":"summary","snapshot_id":"' + b"a" * 64 + b'"}\n')
        assert argv[argv.index("restore") + 1] == "a" * 64
        restored = Path(argv[argv.index("--target") + 1]) / str(target).lstrip("/")
        shutil.copytree(target, restored)
        return subprocess.CompletedProcess(argv, 0, b"")
    receipt = r.collect_recovery_set(target, str(repo), password, "daily-unit",
                                     apply=True, runner=native_fixture)
    assert receipt["snapshotId"] == "a" * 64
    assert receipt["manifestSha256"] == original["manifestSha256"]
    assert receipt["applicationRestoreQualification"] == "required"
    assert not receipt["authorityTransferAuthorized"]
    assert "fixture-secret-key" not in json.dumps(receipt) + json.dumps(seen)


def test_transport_is_fixed_to_registered_host_and_declared_root(capture, tmp_path):
    target, _ = prepared(capture, tmp_path)
    calls = []
    def ssh_fixture(argv, *, stdout, **kwargs):
        calls.append(argv)
        with tarfile.open(fileobj=stdout, mode="w") as archive:
            archive.add(target, arcname=".")
        return subprocess.CompletedProcess(argv, 0, b"")
    output = tmp_path / "pulled"
    receipt = r.pull_recovery_set("genomesbox", "/declared/sets/daily-unit", output,
                                 registered_hosts={"genomesbox": {"ssh_alias": "genomesbox"}},
                                 source_root="/declared/sets", apply=True, runner=ssh_fixture)
    assert receipt["status"] == "bytes_verified"
    assert calls[0][-1] == "tar -C /declared/sets/daily-unit -cf - ."
    for host, remote in (("foreign", "/declared/sets/set"), ("genomesbox", "/other/root/set"),
                         ("genomesbox", "/declared/sets/$(inject)")):
        with pytest.raises(r.RecoverySetError):
            r.pull_recovery_set(host, remote, tmp_path / "never-created",
                                registered_hosts={"genomesbox": {}}, source_root="/declared/sets",
                                apply=True, runner=ssh_fixture)
    assert len(calls) == 1


def test_current_selector_binds_fixed_pointer_and_destination_bytes_before_encryption(capture, tmp_path, monkeypatch):
    target, verified = prepared(capture, tmp_path)
    current = {"schemaVersion": "execution-fabric-recovery-current/v1", "status": "complete",
               "sourceHost": "genomesbox", "recoverySetId": "daily-unit", "relativePath": "sets/daily-unit",
               "manifestSha256": verified["manifestSha256"],
               "capturedAt": json.loads((target / "manifest.json").read_text())["capturedAt"],
               "restorationVerified": True, "authorityTransferAuthorized": False}
    calls = []
    encrypted = []
    def ssh_fixture(argv, **kwargs):
        calls.append(argv)
        if argv[-1].startswith("cat -- "):
            return subprocess.CompletedProcess(argv, 0, json.dumps(current).encode())
        with tarfile.open(fileobj=kwargs["stdout"], mode="w") as archive:
            archive.add(target, arcname=".")
        return subprocess.CompletedProcess(argv, 0, b"")
    def custody_fixture(source, repository, password, set_id, **kwargs):
        encrypted.append((source, set_id))
        assert r.verify_recovery_set(source)["manifestSha256"] == verified["manifestSha256"]
        return {"status": "encrypted_bytes_verified"}
    monkeypatch.setattr(r, "collect_recovery_set", custody_fixture)
    result = r.collect_current_recovery_set("genomesbox", tmp_path / "pulls", "not-read", "not-read",
        source_root="/declared staging", registered_hosts={"genomesbox": {"ssh_alias": "approved-box"}},
        apply=True, runner=ssh_fixture)
    assert result["status"] == "encrypted_bytes_verified" and len(encrypted) == 1
    assert calls[0][-1] == "cat -- '/declared staging/current-success.json'"
    assert calls[1][-1] == "tar -C '/declared staging/sets/daily-unit' -cf - ."
    assert all(call[-2] == "approved-box" for call in calls)
    current["manifestSha256"] = "f" * 64
    with pytest.raises(r.RecoverySetError, match="identity differs"):
        r.collect_current_recovery_set("genomesbox", tmp_path / "other-pulls", "not-read", "not-read",
            source_root="/declared staging", registered_hosts={"genomesbox": {}}, apply=True, runner=ssh_fixture)
    assert len(encrypted) == 1


@pytest.mark.parametrize("change", ["relativePath", "restorationVerified", "authorityTransferAuthorized"])
def test_current_selector_refuses_incomplete_or_unsafe_reference_without_pull(tmp_path, change):
    current = {"schemaVersion": "execution-fabric-recovery-current/v1", "status": "complete",
               "sourceHost": "genomesbox", "recoverySetId": "daily-unit", "relativePath": "sets/daily-unit",
               "manifestSha256": "a" * 64, "capturedAt": datetime.now(timezone.utc).isoformat(),
               "restorationVerified": True, "authorityTransferAuthorized": False}
    current[change] = "../escape" if change == "relativePath" else not current[change]
    calls = []
    def ssh_fixture(argv, **kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, json.dumps(current).encode())
    with pytest.raises(r.RecoverySetError, match="original-state restoration"):
        r.collect_current_recovery_set("genomesbox", tmp_path / "never-created", "not-read", "not-read",
            source_root="/declared", registered_hosts={"genomesbox": {}}, apply=True, runner=ssh_fixture)
    assert len(calls) == 1 and not (tmp_path / "never-created").exists()


def test_capture_receipt_cannot_claim_another_manifest(capture, tmp_path):
    target, _ = prepared(capture, tmp_path)
    receipt = json.loads((target / "capture.receipt.json").read_text())
    receipt["manifestSha256"] = "f" * 64
    write(target / "capture.receipt.json", receipt)
    with pytest.raises(r.RecoverySetError, match="capture receipt"):
        r.verify_recovery_set(target)


@pytest.mark.parametrize("paths,identity", [(["/original/set"], "b" * 64),
    (["/original/set", "/foreign/set"], "a" * 64), (["/../escape"], "a" * 64)])
def test_restore_refuses_foreign_or_ambiguous_native_snapshot_identity_before_output(tmp_path, paths, identity):
    repo = tmp_path / "protected-repository"
    repo.mkdir(mode=0o700)
    password = write(tmp_path / "protected-key", b"fixture-only")
    calls = []
    def fixture_native(argv):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, json.dumps([{"id": identity, "paths": paths}]).encode())
    with pytest.raises(r.RecoverySetError, match="source identity|unsafe relative"):
        r.restore_recovery_set_isolated(str(repo), password, "a" * 64, tmp_path / "never-created",
            apply=True, runner=fixture_native)
    assert len(calls) == 1 and calls[0][-2:] == ["snapshots", "a" * 64]
    assert not (tmp_path / "never-created").exists()


def test_tar_link_escape_never_extracts(capture, tmp_path):
    def ssh_fixture(argv, *, stdout, **kwargs):
        with tarfile.open(fileobj=stdout, mode="w") as archive:
            link = tarfile.TarInfo("witness/linked")
            link.type = tarfile.SYMTYPE
            link.linkname = "/outside/private"
            archive.addfile(link)
        return subprocess.CompletedProcess(argv, 0, b"")
    with pytest.raises(r.RecoverySetError, match="unsafe link"):
        r.pull_recovery_set("genomesbox", "/declared/sets/id", tmp_path / "unsafe",
                            registered_hosts={"genomesbox": {}}, source_root="/declared/sets",
                            apply=True, runner=ssh_fixture)


def test_retention_preserves_last_good_and_drill_pin(tmp_path):
    receipts = tmp_path / "receipts"
    now = datetime.now(timezone.utc)
    for number in range(20):
        write(receipts / f"{number}.json", custody_fixture(f"{number:064x}",
              (now - timedelta(days=number)).isoformat()))
    pin = f"{19:064x}"
    plan = r.plan_retention(receipts, keep=2, weekly=0, monthly=0, pinned=(pin,))
    assert f"{0:064x}" in plan["retained"] and pin in plan["retained"]
    assert pin not in plan["remove"] and plan["prune"] is False
    with pytest.raises(r.RecoverySetError):
        r.plan_retention(receipts, keep=0)


def test_retention_apply_requires_exact_approved_plan_and_forgets_only_named_ids(tmp_path):
    receipts = tmp_path / "custody"
    now = datetime.now(timezone.utc)
    catalog = {}
    for index in range(3):
        custody = custody_fixture(f"{index:064x}", (now - timedelta(days=index)).isoformat())
        write(receipts / (str(index) + ".json"), custody)
        catalog[custody["snapshotId"]] = catalog_row(custody)
    unknown = "d" * 64
    catalog[unknown] = {"id": unknown, "paths": ["/unreceipted/fixture"], "tags": [], "time": now.isoformat()}
    repository = tmp_path / "protected-repository"
    repository.mkdir(mode=0o700)
    password = write(tmp_path / "private-key", b"private-fixture-key")
    copy_receipt = write(tmp_path / "independent-copy.json", {"status": "verified", "fixtureOnly": True})
    plan = r.plan_retention(receipts, keep=1, weekly=0, monthly=0, pinned=(f"{2:064x}",))
    approval = {"schemaVersion": "execution-fabric-recovery-retention-approval/v1", "status": "verified",
        "planSha256": plan["planSha256"], "repository": str(repository), "repositoryId": "e" * 64,
        "drillPinnedSnapshots": [f"{2:064x}"],
        "custodianIdentity": "independent-fixture-custodian", "independentDeletionProtectionVerified": True,
        "verifiedAt": now.isoformat(), "verificationReceipts": [{"path": str(copy_receipt), "sha256": r.sha256(copy_receipt)}]}
    approval_file = write(tmp_path / "approval.json", approval)
    calls = []
    def fixture_native(argv):
        calls.append(argv)
        if "cat" in argv:
            return subprocess.CompletedProcess(argv, 0, json.dumps({"id": "e" * 64}).encode())
        if "snapshots" in argv:
            return subprocess.CompletedProcess(argv, 0, json.dumps(list(catalog.values())).encode())
        assert "forget" in argv
        for identity in argv[argv.index("forget") + 1:]:
            del catalog[identity]
        return subprocess.CompletedProcess(argv, 0, b"")
    result = r.apply_retention(receipts, str(repository), password, approval_file, keep=1, weekly=0, monthly=0,
        pinned=(f"{2:064x}",), apply=True, runner=fixture_native)
    assert result["status"] == "forgot_exact_snapshots" and result["prune"] is False
    forget = [call for call in calls if "forget" in call]
    assert len(forget) == 1 and forget[0][-2:] == ["forget", f"{1:064x}"]
    assert not any("prune" in call for call in calls)
    assert result["retainedReadbackVerified"] and unknown in result["preservedUnknownSnapshots"]
    assert set(catalog) == {f"{0:064x}", f"{2:064x}", unknown}
    approval["planSha256"] = "f" * 64
    write(approval_file, approval)
    with pytest.raises(r.RecoverySetError, match="custodian retention approval"):
        r.apply_retention(receipts, str(repository), password, approval_file, keep=1, weekly=0, monthly=0,
            pinned=(f"{2:064x}",), apply=True, runner=fixture_native)
    assert len([call for call in calls if "forget" in call]) == 1


@pytest.mark.parametrize("change", ["foreign_repository", "missing_last_good", "missing_pin", "source_root", "catalog_changed"])
def test_retention_native_preflight_refuses_provenance_or_survivor_gaps_before_forget(tmp_path, change):
    now = datetime.now(timezone.utc)
    receipts = tmp_path / "custody"
    rows = {}
    for index in range(3):
        custody = custody_fixture(f"{index:064x}", (now - timedelta(days=index)).isoformat())
        write(receipts / (str(index) + ".json"), custody)
        rows[custody["snapshotId"]] = catalog_row(custody)
    repo = tmp_path / "repo"
    repo.mkdir(mode=0o700)
    password = write(tmp_path / "key", b"fixture-only")
    evidence = write(tmp_path / "independent-copy.json", {"fixtureOnly": True, "status": "verified"})
    plan = r.plan_retention(receipts, keep=1, weekly=0, monthly=0, pinned=(f"{2:064x}",))
    approval = write(tmp_path / "approval.json", {
        "schemaVersion": "execution-fabric-recovery-retention-approval/v1", "status": "verified",
        "repository": str(repo), "repositoryId": "e" * 64, "planSha256": plan["planSha256"],
        "drillPinnedSnapshots": [f"{2:064x}"], "custodianIdentity": "fixture-custodian",
        "independentDeletionProtectionVerified": True, "verifiedAt": now.isoformat(),
        "verificationReceipts": [{"path": str(evidence), "sha256": r.sha256(evidence)}]})
    if change == "missing_last_good":
        del rows[f"{0:064x}"]
    elif change == "missing_pin":
        del rows[f"{2:064x}"]
    elif change == "source_root":
        rows[f"{0:064x}"]["paths"] = ["/foreign/source"]
    calls, reads = [], 0
    def fixture_native(argv):
        nonlocal reads
        calls.append(argv)
        if "cat" in argv:
            return subprocess.CompletedProcess(argv, 0, json.dumps({"id": ("d" if change == "foreign_repository" else "e") * 64}).encode())
        assert "snapshots" in argv, "refusal must occur before any forget"
        reads += 1
        value = list(rows.values())
        if change == "catalog_changed" and reads > 1:
            value += [{"id": "b" * 64, "paths": ["/unknown"], "tags": [], "time": now.isoformat()}]
        return subprocess.CompletedProcess(argv, 0, json.dumps(value).encode())
    with pytest.raises(r.RecoverySetError):
        r.apply_retention(receipts, str(repo), password, approval, keep=1, weekly=0, monthly=0,
            pinned=(f"{2:064x}",), apply=True, runner=fixture_native)
    assert not any("forget" in call or "prune" in call for call in calls)


def test_retention_rejects_mixed_or_legacy_repository_receipts_before_native_actor(tmp_path):
    receipts = tmp_path / "custody"
    now = datetime.now(timezone.utc).isoformat()
    write(receipts / "first.json", custody_fixture("a" * 64, now))
    other = write(receipts / "foreign.json", custody_fixture("b" * 64, now, repository_id="d" * 64))
    with pytest.raises(r.RecoverySetError, match="mix or substitute"):
        r.plan_retention(receipts)
    other.unlink()
    legacy = custody_fixture("b" * 64, now)
    del legacy["repositoryId"]
    write(receipts / "legacy.json", legacy)
    with pytest.raises(r.RecoverySetError, match="digest"):
        r.plan_retention(receipts)


def test_actual_cli_dry_actions_preserve_files_and_do_not_read_keys(capture, tmp_path, capsys, monkeypatch):
    target, _ = prepared(capture, tmp_path)
    settings = {"enabled": False, "primary_host_id": "genomesbox", "custodian_host_id": "bigmac",
                "remote_staging_root": "/declared", "max_age_seconds": 86400}
    monkeypatch.setattr(runtime_recovery, "load_execution_fabric_config", lambda _: SimpleNamespace(
        value={"execution_fabric": {"recovery_sets": settings}}))
    monkeypatch.setattr(runtime_recovery, "load_hosts", lambda _: {"genomesbox": {}})
    before = {p.relative_to(target).as_posix(): r.sha256(p) for p in target.rglob("*") if p.is_file()}
    actions = [
        ["plan", "--capture-plan", str(capture[0])],
        ["prepare", "--capture-plan", str(capture[0]), "--maintenance-receipt", "not-read", "--output", str(tmp_path / "never-created")],
        ["pull", "--source-host", "genomesbox", "--remote-source", "/declared/sets/id", "--output", str(tmp_path / "never-created")],
        ["collect", "--source-dir", str(target), "--set-id", "daily-unit", "--repository", "not-read", "--password-file", "not-read"],
        ["collect-current", "--source-host", "genomesbox", "--local-root", str(tmp_path / "never-created"),
         "--repository", "not-read", "--password-file", "not-read"],
        ["restore-plan", "--repository", "not-read", "--password-file", "not-read", "--snapshot-id", "a" * 64,
         "--target", str(tmp_path / "never-created")],
    ]
    for action in actions:
        assert main(["runtime", "recovery-set", *action, "--json"]) == 0
        result = json.loads(capsys.readouterr().out)
        assert result["status"] in ("planned", "would_encrypt")
        assert not (tmp_path / "never-created").exists()
    assert before == {p.relative_to(target).as_posix(): r.sha256(p) for p in target.rglob("*") if p.is_file()}


@pytest.mark.parametrize("change", ["repository", "password_file", "local_staging_root"])
def test_actual_cli_cannot_redirect_custodian_inputs_under_enabled_policy(tmp_path, capsys, monkeypatch, change):
    settings = {"enabled": True, "primary_host_id": "genomesbox", "custodian_host_id": "bigmac",
                "repository": str(tmp_path / "repository"), "password_file": str(tmp_path / "password"),
                "local_staging_root": str(tmp_path / "staging")}
    monkeypatch.setattr(runtime_recovery, "load_execution_fabric_config", lambda _: SimpleNamespace(
        value={"execution_fabric": {"recovery_sets": settings}}))
    monkeypatch.setattr(runtime_recovery, "resolve_execution_fabric_host_id", lambda _: "bigmac")
    selected = dict(settings)
    selected[change] = str(tmp_path / "unconfigured-path")
    assert main(["runtime", "recovery-set", "collect-current", "--source-host", "genomesbox",
        "--local-root", selected["local_staging_root"], "--repository", selected["repository"],
        "--password-file", selected["password_file"], "--apply", "--json"]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "held"
    assert not list(tmp_path.iterdir())


def test_cli_failure_has_safe_output_and_never_fake_success(capture, tmp_path, capsys):
    target, _ = prepared(capture, tmp_path)
    write(target / "unexpected", b"secret-content-canary")
    parser = argparse.ArgumentParser()
    runtime_recovery.register(parser.add_subparsers(required=True))
    args = parser.parse_args(["recovery-set", "verify", "--restored-root", str(target), "--json"])
    assert args.handler(args) == 1
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "held" and not result["authorityTransferAuthorized"]
    assert "secret-content-canary" not in json.dumps(result)


def test_registered_runtime_recovery_dispatches_through_actual_cli(capture, tmp_path, capsys):
    target, _ = prepared(capture, tmp_path)
    assert main(["runtime", "recovery-set", "verify", "--restored-root", str(target), "--json"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "bytes_verified" and not result["authorityTransferAuthorized"]


@pytest.mark.skipif(not os.environ.get("RUBICON_NATIVE_RESTIC"), reason="explicit native disposable restic qualification")
def test_native_restic_encrypted_exact_snapshot_roundtrip(capture, tmp_path):
    """Real native encryption and readback of isolated fixture authorities."""
    binary = os.environ["RUBICON_NATIVE_RESTIC"]
    # Canonical immutable history can have its own manifest filename and schema.
    plan = json.loads(capture[0].read_text())
    native_pg = os.environ.get("RUBICON_NATIVE_PG_EVIDENCE")
    native_pg_receipt = None
    if native_pg:
        evidence = Path(native_pg)
        native_pg_receipt = json.loads((evidence / "terminal.json").read_text())
        assert native_pg_receipt["status"] == "postgres_provenance_qualified"
        assert native_pg_receipt["containerTeardownVerified"] and native_pg_receipt["dumpRestoreReadbackVerified"]
        assert native_pg_receipt["nonElevatedReadonlyExportVerified"]
        source = native_pg_receipt["sourceIdentity"]
        for original, destination in (("native-ledger.dump", "ledger.dump"),
                                      ("native-backup-health.json", "health.json"),
                                      ("native-restore-sidecar.json", "restore.json")):
            write(capture[2] / "postgres" / destination, (evidence / original).read_bytes())
        plan["componentMetadata"]["postgres"].update({name: source[name] for name in
            ("systemId", "database", "databaseOid", "majorVersion")})
    nested = write(capture[2] / "immutableReceipts/manifest.json", {"schemaVersion": "historical-receipt/v1",
        "originalOwner": "original-task:review"})
    plan["components"]["immutableReceipts"].append({"kind": "file", "source": str(nested),
        "path": "immutableReceipts/manifest.json", "sourceBinding": "original-task:review"})
    inventory = json.loads((capture[2] / "immutableReceipts/inventory.json").read_text())
    inventory["references"].append({"relativePath": "immutableReceipts/manifest.json", "sha256": r.sha256(nested),
        "bytes": nested.stat().st_size, "ownerBinding": "original-task:review"})
    write(capture[2] / "immutableReceipts/inventory.json", inventory)
    write(capture[0], plan)
    target, captured = prepared(capture, tmp_path)
    repository = tmp_path / "encrypted-repository"
    repository.mkdir(mode=0o700)
    password = write(tmp_path / "offline-custodian-password", os.urandom(32).hex().encode())
    r.native_command([binary, "--repo", str(repository), "--password-file", str(password), "init"])
    custody = r.collect_recovery_set(
        target, str(repository), password, "daily-unit", restic=binary, apply=True,
        verify_target=tmp_path / "encrypted-readback",
    )
    assert custody["status"] == "encrypted_bytes_verified"
    assert custody["manifestSha256"] == captured["manifestSha256"]
    assert len(custody["snapshotId"]) == 64
    restored = r.restore_recovery_set_isolated(
        str(repository), password, custody["snapshotId"], tmp_path / "isolated-drill",
        restic=binary, apply=True,
    )
    assert restored["manifestSha256"] == captured["manifestSha256"]
    assert restored["status"] == "bytes_verified"
    assert not restored["authorityTransferAuthorized"]
    assert restored["applicationRestoreQualification"] == "required"
    assert json.loads((tmp_path / "recovery-receipts/daily-unit.json").read_text()) == custody
    metrics_output = os.environ.get("RUBICON_NATIVE_RESTIC_RECEIPT_DIR")
    if metrics_output:
        destination = Path(metrics_output)
        assert destination.is_absolute() and not destination.exists()
        destination.mkdir(mode=0o700)
        manifest = json.loads((target / "manifest.json").read_text())
        write(destination / "native-roundtrip.json", {
            "schemaVersion": "execution-fabric-native-encrypted-roundtrip-fixture/v1", "fixtureOnly": True,
            "nativeRestic": binary, "repositoryId": custody["repositoryId"], "snapshotId": custody["snapshotId"],
            "manifestSha256": captured["manifestSha256"], "components": sorted(manifest["components"]),
            "fileCount": len(manifest["files"]), "payloadBytes": sum(row["bytes"] for row in manifest["files"]),
            "encryptedReadbackVerified": True, "exactSnapshotIsolatedRestoreVerified": True,
            "nativePostgresProvenanceReceiptSha256": r.sha256(Path(native_pg) / "terminal.json") if native_pg else None,
            "nativePostgresDumpSha256": native_pg_receipt["backupSha256"] if native_pg_receipt else None,
            "nativeMinioQualified": False, "productionRecoveryQualified": False,
            "authorityTransferAuthorized": False, "applicationRestoreQualification": "required",
        })
    # Actual encrypted repository data must not expose a captured plaintext canary.
    for data in (repository / "data").rglob("*"):
        if data.is_file():
            assert b"PGDMP-test-private-ledger" not in data.read_bytes()


@pytest.mark.skipif(not os.environ.get("RUBICON_NATIVE_RESTIC"), reason="explicit native disposable restic catalog qualification")
def test_native_retention_binds_two_repositories_and_preserves_all_catalog_snapshots(capture, tmp_path):
    """Actual native identity/catalog validation; never issues forget or prune."""
    binary = os.environ["RUBICON_NATIVE_RESTIC"]
    source, _ = prepared(capture, tmp_path)
    key = write(tmp_path / "private-custodian-key", os.urandom(32).hex().encode())
    calls = []
    def actual_native(argv, **kwargs):
        calls.append(argv)
        assert "forget" not in argv and "prune" not in argv
        return r.native_command(argv, **kwargs)
    custody = []
    for name in ("first", "second"):
        repo = tmp_path / name / "repository"
        repo.mkdir(mode=0o700, parents=True)
        r.native_command([binary, "--repo", str(repo), "--password-file", str(key), "init"])
        custody.append(r.collect_recovery_set(source, str(repo), key, "daily-unit", restic=binary,
            apply=True, runner=actual_native))
    repo = tmp_path / "first/repository"
    receipts = repo.parent / "recovery-receipts"
    assert custody[0]["repositoryId"] != custody[1]["repositoryId"]
    unknown = write(tmp_path / "unreceipted-private-fixture", b"unreceipted snapshot must survive")
    prefix = [binary, "--repo", str(repo), "--password-file", str(key), "--json"]
    actual_native(prefix + ["backup", str(unknown)])
    catalog_before = r._catalog(prefix, actual_native)
    copy_evidence = write(tmp_path / "independent-copy-fixture.json", {"fixtureOnly": True, "status": "verified"})
    def approve(plan):
        return write(tmp_path / "retention-approval.json", {
            "schemaVersion": "execution-fabric-recovery-retention-approval/v1", "status": "verified",
            "repository": str(repo), "repositoryId": custody[0]["repositoryId"], "planSha256": plan["planSha256"],
            "drillPinnedSnapshots": sorted(set(plan["retained"]) - {plan["lastGood"]}),
            "custodianIdentity": "isolated-fixture-only", "independentDeletionProtectionVerified": True,
            "verifiedAt": datetime.now(timezone.utc).isoformat(),
            "verificationReceipts": [{"path": str(copy_evidence), "sha256": r.sha256(copy_evidence)}]})
    plan = r.plan_retention(receipts)
    result = r.apply_retention(receipts, str(repo), key, approve(plan), restic=binary,
        apply=True, runner=actual_native)
    assert result["forgotSnapshots"] == [] and result["retainedReadbackVerified"]
    assert set(r._catalog(prefix, actual_native)) == set(catalog_before)
    assert len(result["preservedUnknownSnapshots"]) == 1
    write(receipts / "foreign-repository.json", custody[1])
    with pytest.raises(r.RecoverySetError, match="mix or substitute"):
        r.apply_retention(receipts, str(repo), key, tmp_path / "not-read", restic=binary, apply=True, runner=actual_native)
    (receipts / "foreign-repository.json").unlink()
    pin = "f" * 64
    pin_plan = r.plan_retention(receipts, pinned=(pin,))
    with pytest.raises(r.RecoverySetError, match="lacks retained"):
        r.apply_retention(receipts, str(repo), key, approve(pin_plan), pinned=(pin,), restic=binary,
            apply=True, runner=actual_native)
    forged = custody_fixture("a" * 64, datetime.now(timezone.utc).isoformat(),
                             repository_id=custody[0]["repositoryId"])
    write(receipts / "missing-last-good.json", forged)
    missing_plan = r.plan_retention(receipts, keep=1, weekly=0, monthly=0)
    with pytest.raises(r.RecoverySetError, match="lacks retained"):
        r.apply_retention(receipts, str(repo), key, approve(missing_plan), keep=1, weekly=0, monthly=0,
            restic=binary, apply=True, runner=actual_native)
    assert set(r._catalog(prefix, actual_native)) == set(catalog_before)
    metrics_output = os.environ.get("RUBICON_NATIVE_RESTIC_RECEIPT_DIR")
    if metrics_output:
        destination = Path(metrics_output)
        assert destination.is_absolute()
        destination.mkdir(mode=0o700, exist_ok=True)
        write(destination / "native-retention-catalog.json", {
            "schemaVersion": "execution-fabric-native-retention-catalog-fixture/v1", "fixtureOnly": True,
            "repositoryIds": [row["repositoryId"] for row in custody],
            "catalogBefore": sorted(catalog_before), "catalogAfter": sorted(r._catalog(prefix, actual_native)),
            "unknownSnapshotsPreserved": result["preservedUnknownSnapshots"],
            "lastGood": plan["lastGood"], "retainedReadbackVerified": result["retainedReadbackVerified"],
            "actualMixedRepositoryRefused": True, "actualMissingPinnedSnapshotRefused": True,
            "actualMissingLastGoodRefused": True, "nativeForgetInvocations": 0, "nativePruneInvocations": 0,
            "productionRetentionAuthorized": False,
        })
