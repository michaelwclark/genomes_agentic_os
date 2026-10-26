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
import stat
import subprocess
import tarfile
from types import SimpleNamespace

from jsonschema import Draft202012Validator
import pytest

from genomes_agentic_os import execution_fabric_recovery as r
from genomes_agentic_os.cli import runtime_recovery
from genomes_agentic_os.cli import main


# Recovery behavior qualification additions use only disposable fixtures. Native
# source-test cases remain opt-in; installed/native measurements are separate.


@pytest.mark.parametrize("refusal", ["short-id", "nonhex-id", "existing", "dangling-symlink", "missing-repository", "symlink-repository"])
def test_isolated_restore_refuses_unsafe_targets_before_key_or_actor(tmp_path, monkeypatch, refusal):
    target = tmp_path / "restore"
    repo = tmp_path / "repository"
    repo.mkdir(mode=0o700)
    snapshot = "a" * 64
    prior = None
    if refusal == "short-id":
        snapshot = "a" * 12
    elif refusal == "nonhex-id":
        snapshot = "x" * 64
    elif refusal == "existing":
        prior = write(target / "original", b"inert original restore target")
    elif refusal == "dangling-symlink":
        target.symlink_to(tmp_path / "absent")
    elif refusal == "missing-repository":
        repo.rmdir()
    else:
        actual = tmp_path / "actual-repository"
        repo.rename(actual)
        repo.symlink_to(actual, target_is_directory=True)
    calls = []
    monkeypatch.setattr(r, "_password", lambda _: pytest.fail("key preflight must not run"))
    with pytest.raises(r.RecoverySetError):
        r.restore_recovery_set_isolated(str(repo), tmp_path / "never-read-key", snapshot, target,
                                        apply=True, runner=lambda argv: calls.append(argv))
    assert not calls
    if prior:
        assert prior.read_bytes() == b"inert original restore target"
    else:
        assert not target.exists()
    assert target.is_symlink() == (refusal == "dangling-symlink")


@pytest.mark.parametrize("outcome", ["os-error", "timeout", "nonzero", "success"])
def test_native_command_classifies_failure_without_private_output_or_fallback(monkeypatch, outcome):
    calls = []
    def process(argv, **kwargs):
        calls.append((argv, kwargs))
        if outcome == "os-error":
            raise OSError("INERT_FIXTURE_PRIVATE_OUTPUT")
        if outcome == "timeout":
            raise subprocess.TimeoutExpired(argv, 1, output=b"INERT_FIXTURE_PRIVATE_OUTPUT")
        return subprocess.CompletedProcess(argv, 1 if outcome == "nonzero" else 0,
                                           b"INERT_FIXTURE_PRIVATE_OUTPUT", b"INERT_FIXTURE_PRIVATE_OUTPUT")
    monkeypatch.setattr(r.subprocess, "run", process)
    if outcome == "success":
        assert r.native_command(["fixture-native-only"], timeout=1).returncode == 0
    else:
        with pytest.raises(r.RecoverySetError) as error:
            r.native_command(["fixture-native-only"], timeout=1)
        assert "INERT_FIXTURE_PRIVATE_OUTPUT" not in str(error.value)
    assert len(calls) == 1 and calls[0][1]["timeout"] == 1


@pytest.mark.parametrize("metadata", [[], [{"id": "a" * 64, "paths": ["relative"]}],
    [{"id": "b" * 64, "paths": ["/source"]}],
    [{"id": "a" * 64, "paths": ["/source", "/foreign"]}],
    [{"id": "a" * 64, "paths": ["/source/../foreign"]}]])
def test_restore_catalog_refusal_does_not_create_target_or_call_restore(tmp_path, metadata):
    repo = tmp_path / "repository"
    repo.mkdir(mode=0o700)
    password = write(tmp_path / "fixture-key", b"inert local fixture key")
    calls = []
    def catalog(argv):
        calls.append(argv)
        assert "snapshots" in argv
        return subprocess.CompletedProcess(argv, 0, json.dumps(metadata).encode())
    target = tmp_path / "new-restore"
    with pytest.raises(r.RecoverySetError, match="snapshot source identity|unsafe relative path"):
        r.restore_recovery_set_isolated(str(repo), password, "a" * 64, target, apply=True, runner=catalog)
    assert len(calls) == 1 and not target.exists()


def _retention_survivor_fixture(tmp_path):
    receipts = tmp_path / "custody"
    repo = tmp_path / "repository"
    repo.mkdir(mode=0o700)
    password = write(tmp_path / "fixture-key", b"inert local fixture key")
    now = datetime.now(timezone.utc)
    rows = {}
    for number in range(1, 4):
        custody = custody_fixture(f"{number:064x}", (now - timedelta(days=number)).isoformat())
        write(receipts / (str(number) + ".json"), custody)
        rows[custody["snapshotId"]] = catalog_row(custody)
    plan = r.plan_retention(receipts, keep=3, weekly=0, monthly=0)
    reference = write(tmp_path / "independent-copy.json", {"status": "isolated custody seam only"})
    proof = {"schemaVersion": "execution-fabric-recovery-retention-approval/v1", "status": "verified",
             "planSha256": plan["planSha256"], "repositoryId": plan["repositoryId"],
             "repository": str(repo), "drillPinnedSnapshots": [], "custodianIdentity": "fixture-custodian",
             "independentDeletionProtectionVerified": True, "verifiedAt": now.isoformat(),
             "verificationReceipts": [{"path": str(reference), "sha256": r.sha256(reference)}]}
    return receipts, repo, password, rows, write(tmp_path / "approval.json", proof), reference


@pytest.mark.parametrize("failure", ["changed-proof", "symlink-proof", "future", "invalid-time"])
def test_retention_refuses_uncertain_approval_before_key_or_native(tmp_path, monkeypatch, failure):
    receipts, repo, password, rows, approval, reference = _retention_survivor_fixture(tmp_path)
    before = {p.name: p.read_bytes() for p in receipts.glob("*.json")}
    proof = json.loads(approval.read_text())
    if failure == "changed-proof":
        write(reference, {"status": "changed independent fixture"})
    elif failure == "symlink-proof":
        actual = reference.with_name("actual-proof.json")
        reference.rename(actual)
        reference.symlink_to(actual)
    else:
        proof["verifiedAt"] = ((datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
                                if failure == "future" else "invalid fixture time")
        write(approval, proof)
    monkeypatch.setattr(r, "_password", lambda _: pytest.fail("refused approval must not access key"))
    calls = []
    with pytest.raises(r.RecoverySetError):
        r.apply_retention(receipts, str(repo), password, approval, keep=3, weekly=0, monthly=0,
                          apply=True, runner=lambda argv: calls.append(argv))
    assert not calls and before == {p.name: p.read_bytes() for p in receipts.glob("*.json")}


@pytest.mark.parametrize("failure", ["missing-survivor", "changed-survivor", "repository-drift"])
def test_retention_failed_survivor_readback_preserves_history_without_forget(tmp_path, failure):
    receipts, repo, password, rows, approval, _ = _retention_survivor_fixture(tmp_path)
    unknown = {"id": "f" * 64, "paths": ["/foreign/fixture"], "tags": [],
               "time": datetime.now(timezone.utc).isoformat()}
    rows[unknown["id"]] = unknown
    before = {p.name: p.read_bytes() for p in receipts.glob("*.json")}
    calls, catalogs = [], 0
    def native(argv):
        nonlocal catalogs
        calls.append(argv)
        assert "forget" not in argv and "prune" not in argv and "unlock" not in argv
        if "cat" in argv:
            identity = "d" * 64 if failure == "repository-drift" and catalogs >= 3 else "e" * 64
            return subprocess.CompletedProcess(argv, 0, json.dumps({"id": identity}).encode())
        assert "snapshots" in argv
        catalogs += 1
        value = [dict(row) for row in rows.values()]
        if catalogs >= 3 and failure == "missing-survivor":
            value = [row for row in value if row["id"] != unknown["id"]]
        elif catalogs >= 3 and failure == "changed-survivor":
            value[-1]["tags"] = ["changed-foreign-fixture"]
        return subprocess.CompletedProcess(argv, 0, json.dumps(value).encode())
    with pytest.raises(r.RecoverySetError, match="survivor readback"):
        r.apply_retention(receipts, str(repo), password, approval, keep=3, weekly=0, monthly=0,
                          apply=True, runner=native)
    assert catalogs == 3 and all("forget" not in argv for argv in calls)
    assert before == {p.name: p.read_bytes() for p in receipts.glob("*.json")}


@pytest.mark.parametrize("failure", ["symlink", "missing", "copied-byte-mismatch"])
def test_capture_source_refusal_preserves_previous_set_and_authority_bytes(capture, tmp_path, monkeypatch, failure):
    plan_file, maintenance, source = capture
    plan = json.loads(plan_file.read_text())
    previous, _ = prepared(capture, tmp_path)
    prior = {p.relative_to(previous).as_posix(): p.read_bytes() for p in previous.rglob("*") if p.is_file()}
    source_item = next(s for values in plan["components"].values() for s in values if s["kind"] == "file")
    original = Path(source_item["source"])
    original_bytes = original.read_bytes()
    if failure == "symlink":
        link = tmp_path / "unbound-source"
        link.symlink_to(original)
        source_item["source"] = str(link)
    elif failure == "missing":
        source_item["source"] = str(tmp_path / "missing-component")
    else:
        copy = shutil.copyfile
        def corrupt_destination(src, dst, **kwargs):
            result = copy(src, dst, **kwargs)
            if Path(src) == original:
                Path(dst).write_bytes(b"changed isolated copied bytes")
            return result
        monkeypatch.setattr(r.shutil, "copyfile", corrupt_destination)
    write(plan_file, plan)
    output = tmp_path / "refused-set"
    source_before = {p.relative_to(source).as_posix(): p.read_bytes()
                     for p in source.rglob("*") if p.is_file() and not p.is_symlink()}
    binding_before = {p: p.read_bytes() for p in (plan_file, maintenance)}
    native_calls = []
    def forbidden_native(*args, **kwargs):
        native_calls.append((args, kwargs))
        pytest.fail("capture refusal must not launch a native/provider actor")
    monkeypatch.setattr(r, "native_command", forbidden_native)
    with pytest.raises(r.RecoverySetError, match="symlink|missing|changed during capture"):
        r.prepare_recovery_set(plan_file, maintenance, output, apply=True)
    assert output.is_dir() and not output.is_symlink()
    failed = output / "failed.receipt.json"
    assert failed.is_file() and not failed.is_symlink()
    assert json.loads(failed.read_text()) == {
        "schemaVersion": "execution-fabric-recovery-failure/v1",
        "recoverySetId": plan["recoverySetId"], "status": "incomplete"}
    assert not (output / "manifest.json").exists()
    assert not (output / "capture.receipt.json").exists()
    with pytest.raises(r.RecoverySetError, match="required JSON input is unavailable"):
        r.verify_recovery_set(output)
    retained = {p.relative_to(output).as_posix() for p in output.rglob("*") if p.is_file()}
    if failure == "copied-byte-mismatch":
        assert retained == {"failed.receipt.json", source_item["path"]}
        assert (output / source_item["path"]).read_bytes() != original_bytes
    else:
        assert retained == {"failed.receipt.json"}
    assert native_calls == []
    assert original.read_bytes() == original_bytes
    assert source_before == {p.relative_to(source).as_posix(): p.read_bytes()
                             for p in source.rglob("*") if p.is_file() and not p.is_symlink()}
    assert binding_before == {p: p.read_bytes() for p in (plan_file, maintenance)}
    assert prior == {p.relative_to(previous).as_posix(): p.read_bytes() for p in previous.rglob("*") if p.is_file()}


@pytest.mark.parametrize("forgery", ["duplicate-inventory", "empty-owner", "witness-path", "signing-key", "os-authority", "public-mode"])
def test_forged_private_set_cannot_qualify_inventory_or_authority_closure(capture, tmp_path, forgery):
    original, _ = prepared(capture, tmp_path)
    before = {p.relative_to(original).as_posix(): p.read_bytes() for p in original.rglob("*") if p.is_file()}
    candidate = tmp_path / "forged-set"
    shutil.copytree(original, candidate)
    manifest_path = candidate / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    if forgery == "duplicate-inventory":
        manifest["files"].append(dict(manifest["files"][0]))
        manifest["fileInventorySha256"] = r._digest(manifest["files"])
    elif forgery == "empty-owner":
        manifest["files"][0]["sourceBinding"] = ""
        manifest["fileInventorySha256"] = r._digest(manifest["files"])
    elif forgery == "witness-path":
        manifest["components"]["witness"]["originalDatabasePath"] = "/foreign/fixture-authority.db"
    elif forgery == "signing-key":
        manifest["components"]["witness"]["signingPublicKeySha256"] = "0" * 64
    elif forgery == "os-authority":
        manifest["components"]["osAuthorities"]["authorityId"] = ""
    else:
        candidate.chmod(0o755)
    write(manifest_path, manifest)
    receipt = json.loads((candidate / "capture.receipt.json").read_text())
    receipt["manifestSha256"] = r.sha256(manifest_path)
    write(candidate / "capture.receipt.json", receipt)
    with pytest.raises(r.RecoverySetError):
        r.verify_recovery_set(candidate)
    assert before == {p.relative_to(original).as_posix(): p.read_bytes() for p in original.rglob("*") if p.is_file()}


@pytest.mark.parametrize("action,change", [("daily", "daily-plan"), ("pull", "primary"),
    ("collect-current", "primary"), ("collect-current", "staging"),
    ("collect", "repository"), ("collect", "key"),
    ("restore-isolated", "repository"), ("restore-isolated", "key"),
    ("retention-apply", "repository"), ("retention-apply", "key"),
    ("collect", "disabled"), ("collect", "actor")])
def test_public_cli_refuses_foreign_configured_inputs_before_operation(tmp_path, monkeypatch, capsys, action, change):
    settings = {"enabled": True, "primary_host_id": "fixture-primary", "custodian_host_id": "fixture-custodian",
                "repository": str(tmp_path / "repository"), "password_file": str(tmp_path / "fixture-key"),
                "local_staging_root": str(tmp_path / "staging"), "daily_plan_file": str(tmp_path / "daily-plan")}
    args = argparse.Namespace(recovery_action=action, root=str(tmp_path), apply=True, json=True,
        daily_plan=settings["daily_plan_file"], source_host="fixture-primary", remote_source="/fixture/remote",
        output=str(tmp_path / "never-output"), local_root=settings["local_staging_root"],
        source_dir=str(tmp_path / "fixture-set"), repository=settings["repository"], password_file=settings["password_file"],
        set_id="fixture-set", snapshot_id="a" * 64, target=str(tmp_path / "never-output"), restic="fixture-native",
        verify_target=None, receipts_dir=str(tmp_path / "receipts"), maintenance_receipt=str(tmp_path / "approval"),
        daily=1, weekly=0, monthly=0, pin=[])
    if change == "primary":
        args.source_host = "foreign-fixture-primary"
    elif change == "staging":
        args.local_root = str(tmp_path / "foreign-staging")
    elif change == "daily-plan":
        args.daily_plan = str(tmp_path / "foreign-plan")
    elif change == "repository":
        args.repository = str(tmp_path / "foreign-repository")
    elif change == "key":
        args.password_file = str(tmp_path / "foreign-key")
    elif change == "disabled":
        settings["enabled"] = False
    host = ("foreign-fixture-actor" if change == "actor" else
            "fixture-primary" if action == "daily" else "fixture-custodian")
    monkeypatch.setattr(runtime_recovery, "load_execution_fabric_config",
                        lambda _: SimpleNamespace(value={"execution_fabric": {"recovery_sets": settings}}))
    monkeypatch.setattr(runtime_recovery, "resolve_execution_fabric_host_id", lambda _: host)
    for name in ("pull_recovery_set", "collect_recovery_set", "collect_current_recovery_set",
                 "restore_recovery_set_isolated", "apply_retention"):
        monkeypatch.setattr(r, name, lambda *a, **kw: pytest.fail("refused CLI must not reach operation"))
    monkeypatch.setattr(runtime_recovery.daily, "run_daily_recovery", lambda *a, **kw: pytest.fail("no daily operation"))
    assert runtime_recovery.handle(args) == 1
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "held" and result["authorityTransferAuthorized"] is False
    assert not (tmp_path / "never-output").exists()


@pytest.mark.parametrize("problem", [ValueError, OSError, TypeError, KeyError, AttributeError])
def test_public_cli_invalid_input_redacts_detail_instead_of_echoing_fixture_payload(monkeypatch, capsys, problem):
    def invalid(_):
        raise problem("INERT_FIXTURE_DETAIL")
    monkeypatch.setattr(r, "plan_recovery_set", invalid)
    assert runtime_recovery.handle(argparse.Namespace(recovery_action="plan", capture_plan="fixture", json=True)) == 1
    output = capsys.readouterr().out
    assert "INERT_FIXTURE_DETAIL" not in output
    assert json.loads(output) == {"status": "held", "reason": "required recovery input or canonical policy is invalid",
                                  "authorityTransferAuthorized": False}


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
        assert argv[argv.index("restore") + 1] == "a" * 64 + ":" + str(target)
        restored = Path(argv[argv.index("--target") + 1])
        shutil.copytree(target, restored, dirs_exist_ok=True)
        return subprocess.CompletedProcess(argv, 0, b"")
    receipt = r.collect_recovery_set(target, str(repo), password, "daily-unit",
                                     apply=True, runner=native_fixture)
    assert receipt["snapshotId"] == "a" * 64
    assert receipt["manifestSha256"] == original["manifestSha256"]
    assert receipt["applicationRestoreQualification"] == "required"
    assert not receipt["authorityTransferAuthorized"]
    assert "fixture-secret-key" not in json.dumps(receipt) + json.dumps(seen)


def test_isolated_restore_selects_exact_native_source_subtree(capture, tmp_path):
    source, captured = prepared(capture, tmp_path)
    repository = tmp_path / "repository"
    repository.mkdir(mode=0o700)
    password = write(tmp_path / "private-key", b"fixture-only")
    destination = tmp_path / "direct-readback"
    source_pins = {p.relative_to(source).as_posix(): r.sha256(p)
                   for p in source.rglob("*") if p.is_file()}
    calls = []
    def fixture_native(argv):
        calls.append(argv)
        if "snapshots" in argv:
            return subprocess.CompletedProcess(argv, 0, json.dumps([
                {"id": "a" * 64, "paths": [str(source)]}]).encode())
        assert argv[argv.index("restore") + 1] == "a" * 64 + ":" + str(source)
        assert argv[-2:] == ["--target", str(destination)]
        shutil.copytree(source, destination, dirs_exist_ok=True)
        return subprocess.CompletedProcess(argv, 0, b"")
    result = r.restore_recovery_set_isolated(str(repository), password, "a" * 64,
        destination, apply=True, runner=fixture_native)
    assert result["manifestSha256"] == captured["manifestSha256"]
    assert not result["authorityTransferAuthorized"]
    assert (destination / "manifest.json").is_file()
    assert not (destination / str(source).lstrip("/")).exists()
    assert {p.relative_to(source).as_posix(): r.sha256(p)
            for p in source.rglob("*") if p.is_file()} == source_pins
    assert len(calls) == 2


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
    original_authority_pins = {p.relative_to(capture[2]).as_posix(): r.sha256(p)
        for p in capture[2].rglob("*") if p.is_file()
        and p != capture[2] / "osAuthorities/canonical.db-shm"}
    # Reproduce the native full gate's doubled-path failure even with a short
    # pytest root. The actual captured database path remains below that depth.
    deep = tmp_path / "long source:with spaces"
    while len(os.fsencode(deep / "set")) < 400:
        remaining = 400 - len(os.fsencode(deep / "set"))
        deep /= "x" * min(96, max(1, remaining - 1))
    target = deep / "set"
    captured = r.prepare_recovery_set(capture[0], capture[1], target, apply=True)
    source_pins = {p.relative_to(target).as_posix(): r.sha256(p)
                   for p in target.rglob("*") if p.is_file()}
    sibling = write(deep / "set-other/private-sibling", b"never captured or restored")
    sibling_pin = r.sha256(sibling)
    repository = tmp_path / "encrypted-repository"
    repository.mkdir(mode=0o700)
    password = write(tmp_path / "offline-custodian-password", os.urandom(32).hex().encode())
    r.native_command([binary, "--repo", str(repository), "--password-file", str(password), "init"])
    calls = []
    def actual_native(argv, **kwargs):
        calls.append(argv)
        assert "forget" not in argv and "prune" not in argv
        return r.native_command(argv, **kwargs)
    readback = tmp_path / "encrypted-readback"
    drill = tmp_path / "isolated-drill"
    legacy_nested = readback / str(target).lstrip("/") / "witness/witness.db"
    assert len(os.fsencode(legacy_nested)) > 512
    custody = r.collect_recovery_set(
        target, str(repository), password, "daily-unit", restic=binary, apply=True,
        verify_target=readback, runner=actual_native,
    )
    assert custody["status"] == "encrypted_bytes_verified"
    assert custody["manifestSha256"] == captured["manifestSha256"]
    assert len(custody["snapshotId"]) == 64
    restored = r.restore_recovery_set_isolated(
        str(repository), password, custody["snapshotId"], drill,
        restic=binary, apply=True, runner=actual_native,
    )
    assert restored["manifestSha256"] == captured["manifestSha256"]
    assert restored["status"] == "bytes_verified"
    assert not restored["authorityTransferAuthorized"]
    assert restored["applicationRestoreQualification"] == "required"
    custody_path = tmp_path / "recovery-receipts" / ("custody-" + custody["repositoryId"] + "-" + custody["snapshotId"] + ".json")
    assert json.loads(custody_path.read_text()) == custody
    assert [argv[argv.index("restore") + 1] for argv in calls if "restore" in argv] == [
        custody["snapshotId"] + ":" + str(target), custody["snapshotId"] + ":" + str(target)]
    for destination in (readback, drill):
        assert {p.relative_to(destination).as_posix(): r.sha256(p)
                for p in destination.rglob("*") if p.is_file()} == source_pins
        assert not (destination / str(target).lstrip("/")).exists()
        assert not (destination / "set-other").exists()
        sentinel = json.loads((destination / "witness/witness.db.initialized").read_text())
        assert sentinel["database"] == plan["componentMetadata"]["witness"]["originalDatabasePath"]
        assert sentinel["backup"] == plan["componentMetadata"]["witness"]["originalBackupPath"]
    assert {p.relative_to(target).as_posix(): r.sha256(p)
            for p in target.rglob("*") if p.is_file()} == source_pins
    assert {p.relative_to(capture[2]).as_posix(): r.sha256(p)
        for p in capture[2].rglob("*") if p.is_file()
        and p != capture[2] / "osAuthorities/canonical.db-shm"} == original_authority_pins
    assert r.sha256(sibling) == sibling_pin
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
            "directTargetSubtreeRestoreVerified": True, "originalSourceAndSentinelBytesPreserved": True,
            "siblingExcluded": True, "legacyNestedWitnessPathBytes": len(os.fsencode(legacy_nested)),
            "capturedWitnessPathBytes": len(os.fsencode(target / "witness/witness.db")),
            "directReadbackWitnessPathBytes": len(os.fsencode(readback / "witness/witness.db")),
            "nativePostgresProvenanceReceiptSha256": r.sha256(Path(native_pg) / "terminal.json") if native_pg else None,
            "nativePostgresDumpSha256": native_pg_receipt["backupSha256"] if native_pg_receipt else None,
            "nativeMinioQualified": False, "productionRecoveryQualified": False,
            "authorityTransferAuthorized": False, "applicationRestoreQualification": "required",
        })
    # Actual encrypted repository data must not expose a captured plaintext canary.
    for data in (repository / "data").rglob("*"):
        if data.is_file():
            assert b"PGDMP-test-private-ledger" not in data.read_bytes()


@pytest.mark.skipif(not os.environ.get("RUBICON_NATIVE_RESTIC"), reason="explicit native disposable subtree qualification")
def test_native_restic_subfolder_selection_excludes_exact_sibling(tmp_path):
    binary = os.environ["RUBICON_NATIVE_RESTIC"]
    parent = tmp_path / "native tree:with spaces"
    member = parent / "recovery set"
    payload = write(member / "payload", b"selected member only")
    sentinel = write(member / "witness/witness.db.initialized",
                     {"database": "/original/witness.db", "backup": "/original/witness.db.backup"})
    sibling = write(parent / "recovery set-other/private-sibling", b"excluded native snapshot sibling")
    original_pins = {str(p): r.sha256(p) for p in (payload, sentinel, sibling)}
    repository = tmp_path / "private-repository"
    repository.mkdir(mode=0o700)
    password = write(tmp_path / "private-key", os.urandom(32).hex().encode())
    prefix = [binary, "--repo", str(repository), "--password-file", str(password), "--json"]
    r.native_command(prefix + ["init"])
    output = r.native_command(prefix + ["backup", str(parent)])
    rows = [json.loads(line) for line in output.stdout.decode().splitlines()]
    identity = [row["snapshot_id"] for row in rows if row.get("message_type") == "summary"][-1]
    catalog = r._catalog(prefix, r.native_command)
    assert catalog[identity]["paths"] == [str(parent)]
    destination = tmp_path / "direct-member"
    destination.mkdir(mode=0o700)
    r.native_command(prefix + ["restore", identity + ":" + str(member), "--target", str(destination)])
    assert {p.relative_to(destination).as_posix() for p in destination.rglob("*") if p.is_file()} == {
        "payload", "witness/witness.db.initialized"}
    assert (destination / "payload").read_bytes() == payload.read_bytes()
    assert (destination / "witness/witness.db.initialized").read_bytes() == sentinel.read_bytes()
    assert {str(p): r.sha256(p) for p in (payload, sentinel, sibling)} == original_pins
    assert not (destination / "recovery set-other").exists()
    assert not (destination / str(member).lstrip("/")).exists()
    assert r._catalog(prefix, r.native_command) == catalog


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



@pytest.fixture
def collected_fixture(capture, tmp_path):
    """Controlled native command seam; no real repository or released authority."""
    target, original = prepared(capture, tmp_path)
    repo = tmp_path / "repository"
    repo.mkdir(mode=0o700)
    password = write(tmp_path / "password", b"isolated-key")
    class NativeFixture:
        def __init__(self):
            self.calls = []
            self.catalog = {}
            self.same_snapshot = False
            self.failure = None
            self.repository_id = "e" * 64
            self.sequence = 0
        def __call__(self, argv, **kwargs):
            self.calls.append(argv)
            if "cat" in argv:
                identity = "d" * 64 if self.failure == "repository-change" and self.sequence >= 2 else self.repository_id
                return subprocess.CompletedProcess(argv, 0, json.dumps({"id": identity}).encode())
            if "backup" in argv:
                self.sequence += 1
                identity = f"{1 if self.same_snapshot else self.sequence:064x}"
                self.catalog.setdefault(identity, {"id": identity, "paths": [str(target)],
                    "tags": ["rubicon-recovery:daily-unit"], "time": datetime.now(timezone.utc).isoformat()})
                if self.failure == "native":
                    raise r.RecoverySetError("fixture native actor failed")
                if self.failure == "summary":
                    return subprocess.CompletedProcess(argv, 0, b"not JSON")
                return subprocess.CompletedProcess(argv, 0, json.dumps(
                    {"message_type": "summary", "snapshot_id": identity}).encode())
            if "snapshots" in argv:
                rows = [] if self.failure == "absent" else list(self.catalog.values())
                if self.failure in {"source", "tag"}:
                    rows = [dict(row, paths=["/foreign/source"]) if self.failure == "source"
                            else dict(row, tags=["foreign:set"]) for row in rows]
                return subprocess.CompletedProcess(argv, 0, json.dumps(rows).encode())
            assert "restore" in argv and "forget" not in argv and "prune" not in argv
            destination = Path(argv[argv.index("--target") + 1])
            shutil.copytree(target, destination, dirs_exist_ok=True)
            if self.failure == "restore":
                (destination / "manifest.json").write_text("{}")
            return subprocess.CompletedProcess(argv, 0, b"")
    native = NativeFixture()
    def collect(**kwargs):
        return r.collect_recovery_set(target, str(repo), password, "daily-unit", apply=True,
                                      runner=native, **kwargs)
    return collect, native, repo, target, original


def test_repeat_set_collection_keeps_each_snapshot_and_old_receipt_with_drill_pin(collected_fixture):
    collect, native, repo, target, original = collected_fixture
    first = collect()
    receipts = repo.parent / "recovery-receipts"
    legacy = write(receipts / "daily-unit.json", first)
    original_legacy = legacy.read_bytes()
    prior = {p.name: p.read_bytes() for p in receipts.glob("*.json")}
    second = collect()
    custody = [json.loads(p.read_text()) for p in receipts.glob("custody-*.json")]
    assert {row["snapshotId"] for row in custody} == {first["snapshotId"], second["snapshotId"]}
    assert first["snapshotId"] != second["snapshotId"]
    assert all((receipts / name).read_bytes() == data for name, data in prior.items())
    assert legacy.read_bytes() == original_legacy
    plan = r.plan_retention(receipts, keep=1, weekly=0, monthly=0, pinned=(first["snapshotId"],))
    assert plan["retained"] == sorted([first["snapshotId"], second["snapshotId"]])
    assert not plan["remove"] and plan["lastGood"] == second["snapshotId"]
    assert len(list(receipts.glob("collection-*-complete.json"))) == 2
    assert r.verify_recovery_set(target)["manifestSha256"] == original["manifestSha256"]
    assert len([argv for argv in native.calls if "restore" in argv]) == 2


def test_exact_native_snapshot_replay_verifies_current_bytes_and_retains_first_proof(collected_fixture):
    collect, native, repo, _, _ = collected_fixture
    native.same_snapshot = True
    first = collect()
    path = next((repo.parent / "recovery-receipts").glob("custody-*.json"))
    original = path.read_bytes()
    second = collect()
    assert second == first and path.read_bytes() == original
    assert len([argv for argv in native.calls if "backup" in argv]) == 2
    assert len([argv for argv in native.calls if "restore" in argv]) == 2
    assert not list(path.parent.glob("*.partial"))


@pytest.mark.parametrize("failure", ["native", "summary", "absent", "source", "tag", "restore", "repository-change"])
def test_native_success_with_later_failure_stays_partial_and_prior_history_is_intact(collected_fixture, failure):
    collect, native, repo, _, _ = collected_fixture
    first = collect()
    receipts = repo.parent / "recovery-receipts"
    prior = {p.name: p.read_bytes() for p in receipts.glob("*.json")}
    native.failure = failure
    with pytest.raises(r.RecoverySetError):
        collect()
    assert all((receipts / name).read_bytes() == data for name, data in prior.items())
    failed = json.loads(next(receipts.glob("*-failed.json")).read_text())
    assert failed["status"] == ("native_outcome_uncertain" if failure in {"native", "summary"}
                                else "partial_native_snapshot")
    assert not failed["nativeSnapshotRemovalAuthorized"]
    assert len(list(receipts.glob("custody-*.json"))) == 1
    assert first["snapshotId"] in native.catalog and f"{2:064x}" in native.catalog
    assert all("forget" not in argv and "prune" not in argv for argv in native.calls)


@pytest.mark.parametrize("collision", ["foreign", "invalid", "symlink", "fifo", "oversized", "public",
                                       "time", "claims", "extra", "nonobject"])
def test_immutable_custody_collision_refuses_without_replacing_any_prior_bytes(collected_fixture, collision):
    collect, native, repo, _, _ = collected_fixture
    first = collect()
    receipts = repo.parent / "recovery-receipts"
    path = next(receipts.glob("custody-*.json"))
    if collision == "foreign":
        replacement = dict(first, manifestSha256="f" * 64)
        write(path, replacement)
    elif collision == "invalid":
        path.write_bytes(b"invalid JSON")
    elif collision == "symlink":
        path.unlink()
        destination = write(receipts / "foreign-held.json", first)
        path.symlink_to(destination)
    elif collision == "fifo":
        path.unlink()
        os.mkfifo(path, 0o600)
    elif collision == "oversized":
        path.write_bytes(b"x" * (1024 * 1024 + 1))
    elif collision == "public":
        path.chmod(0o644)
    elif collision == "time":
        write(path, dict(first, verifiedAt=(datetime.now(timezone.utc) + timedelta(days=1)).isoformat()))
    elif collision == "claims":
        write(path, dict(first, fileCount=first["fileCount"] + 1))
    elif collision == "extra":
        write(path, dict(first, unsupported="claim"))
    else:
        write(path, [])
    before = path.read_bytes() if collision != "fifo" else None
    native.same_snapshot = True
    with pytest.raises(r.RecoverySetError, match="custody collision"):
        collect()
    if before is not None:
        assert path.read_bytes() == before
    else:
        assert stat.S_ISFIFO(path.lstat().st_mode)
    failed = json.loads(next(receipts.glob("*-failed.json")).read_text())
    assert failed["status"] == "partial_native_snapshot" and failed["snapshotId"] == first["snapshotId"]
    assert not list(receipts.glob("*.partial"))


def test_custody_published_before_interrupted_completion_remains_valid_and_exact_replay_qualifies(
        collected_fixture, monkeypatch):
    collect, native, repo, _, _ = collected_fixture
    actual = r._write_immutable_receipt
    def interrupted(path, value, **kwargs):
        if path.name.endswith("-complete.json"):
            raise r.RecoverySetError("fixture completion publication interrupted")
        return actual(path, value, **kwargs)
    monkeypatch.setattr(r, "_write_immutable_receipt", interrupted)
    with pytest.raises(r.RecoverySetError, match="interrupted"):
        collect()
    receipts = repo.parent / "recovery-receipts"
    path = next(receipts.glob("custody-*.json"))
    proof = path.read_bytes()
    assert r.plan_retention(receipts)["lastGood"] == f"{1:064x}"
    failed = json.loads(next(receipts.glob("*-failed.json")).read_text())
    assert failed["snapshotId"] == f"{1:064x}" and failed["status"] == "partial_native_snapshot"
    monkeypatch.setattr(r, "_write_immutable_receipt", actual)
    native.same_snapshot = True
    result = collect()
    assert path.read_bytes() == proof and result["snapshotId"] == f"{1:064x}"
    assert len(list(receipts.glob("*-complete.json"))) == 1
    assert len(list(receipts.glob("*-failed.json"))) == 1


def test_concurrent_exact_custody_publication_keeps_one_complete_proof_and_reuses_winner(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    value = custody_fixture("a" * 64, datetime.now(timezone.utc).isoformat())
    value.update(fileCount=17, authorityTransferAuthorized=False,
                 independentDeletionProtectionVerified=False, applicationRestoreQualification="required")
    path = tmp_path / "custody.json"
    barrier = Barrier(2)
    def publish(index):
        candidate = dict(value, verifiedAt=datetime.now(timezone.utc).isoformat())
        barrier.wait(timeout=5)
        return r._write_immutable_receipt(path, candidate, reuse_custody=True)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(publish, [1, 2]))
    assert results[0] == results[1] == json.loads(path.read_text())
    assert not list(tmp_path.glob("*.partial"))


def test_exclusive_temporary_collision_preserves_foreign_partial_file(tmp_path, monkeypatch):
    monkeypatch.setattr(r, "uuid4", lambda: SimpleNamespace(hex="same-operation"))
    target = tmp_path / "custody.json"
    foreign = write(tmp_path / "custody.json.same-operation.partial", b"foreign-incomplete-owner-bytes")
    before = foreign.read_bytes()
    with pytest.raises(FileExistsError):
        r._write_immutable_receipt(target, {"status": "started"})
    assert foreign.read_bytes() == before and not target.exists()


def test_immutable_outcome_replay_is_refused_and_link_failure_never_publishes_partial_bytes(tmp_path, monkeypatch):
    path = tmp_path / "outcome.json"
    actual = r._write_immutable_receipt(path, {"status": "started"})
    before = path.read_bytes()
    with pytest.raises(r.RecoverySetError, match="already exists"):
        r._write_immutable_receipt(path, actual)
    assert path.read_bytes() == before
    def refused_link(*args, **kwargs):
        raise OSError("fixture publication interrupted before link")
    monkeypatch.setattr(os, "link", refused_link)
    target = tmp_path / "new-outcome.json"
    with pytest.raises(OSError, match="interrupted"):
        r._write_immutable_receipt(target, actual)
    assert not target.exists() and not list(tmp_path.glob("*.partial"))


@pytest.mark.parametrize("unsafe", ["symlink", "public", "inside-source"])
def test_collection_history_guard_refuses_before_native_backup(collected_fixture, unsafe):
    collect, native, repo, target, _ = collected_fixture
    receipts = repo.parent / "recovery-receipts"
    if unsafe == "symlink":
        receipts.symlink_to(target, target_is_directory=True)
    elif unsafe == "public":
        receipts.mkdir(mode=0o755)
    else:
        # The verified source remains valid, but the fixed custody destination
        # would otherwise mutate the immutable source before native backup.
        receipts.mkdir(mode=0o700)
        target.rename(receipts / "source")
        collect = lambda: r.collect_recovery_set(receipts / "source", str(repo), repo.parent / "password",
            "daily-unit", apply=True, runner=native)
    with pytest.raises(r.RecoverySetError, match="independent private owned"):
        collect()
    assert not [argv for argv in native.calls if "backup" in argv]



def test_collection_explicit_readback_is_retained_and_invalid_summary_identity_stays_uncertain(
        collected_fixture, tmp_path):
    collect, native, repo, _, original = collected_fixture
    retained = tmp_path / "retained-disposable-readback"
    receipt = collect(verify_target=retained)
    assert retained.is_dir() and r.verify_recovery_set(retained)["manifestSha256"] == original["manifestSha256"]
    assert receipt["status"] == "encrypted_bytes_verified"
    actual = native.__call__
    def invalid_identity(argv, **kwargs):
        if "backup" in argv:
            return subprocess.CompletedProcess(argv, 0, b'{"message_type":"summary","snapshot_id":"short"}')
        return actual(argv, **kwargs)
    with pytest.raises(r.RecoverySetError, match="exact snapshot"):
        r.collect_recovery_set(native.catalog[receipt["snapshotId"]]["paths"][0], str(repo),
            repo.parent / "password", "daily-unit", apply=True, runner=invalid_identity)
    failed = json.loads(next((repo.parent / "recovery-receipts").glob("*-failed.json")).read_text())
    assert failed["status"] == "native_outcome_uncertain"


def test_valid_byte_readback_of_different_manifest_never_qualifies_custody(collected_fixture, monkeypatch):
    collect, native, repo, source, original = collected_fixture
    actual = r.verify_recovery_set
    def foreign_readback(root):
        result = actual(root)
        if Path(root) != source:
            result = dict(result, manifestSha256="f" * 64)
        return result
    monkeypatch.setattr(r, "verify_recovery_set", foreign_readback)
    with pytest.raises(r.RecoverySetError, match="restore manifest identity differs"):
        collect()
    receipts = repo.parent / "recovery-receipts"
    assert not list(receipts.glob("custody-*.json"))
    failed = json.loads(next(receipts.glob("*-failed.json")).read_text())
    assert failed["snapshotId"] in native.catalog and failed["status"] == "partial_native_snapshot"


def test_directory_flush_failure_preserves_complete_immutable_bytes_for_owner_recovery(tmp_path, monkeypatch):
    actual_fsync = os.fsync
    def failed_directory_sync(descriptor):
        if stat.S_ISDIR(os.fstat(descriptor).st_mode):
            raise OSError("fixture directory durability readback failed")
        return actual_fsync(descriptor)
    monkeypatch.setattr(os, "fsync", failed_directory_sync)
    path = tmp_path / "immutable-outcome.json"
    with pytest.raises(OSError, match="durability"):
        r._write_immutable_receipt(path, {"status": "started"})
    assert json.loads(path.read_text()) == {"status": "started"}
    assert not list(tmp_path.glob("*.partial"))
