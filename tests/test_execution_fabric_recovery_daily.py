from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import subprocess

import pytest
from genomes_agentic_os import execution_fabric_recovery as r
from genomes_agentic_os import execution_fabric_recovery_daily as daily
from test_execution_fabric_recovery_sets import PG_SOURCE, capture, write


@pytest.fixture
def daily_plan(capture, tmp_path):
    plan = json.loads(capture[0].read_text())
    source = capture[2]
    data = {"schemaVersion": daily.PLAN, "sourceHost": plan["sourceHost"],
            "sourceRelease": plan["sourceRelease"], "imageLockSha256": plan["imageLockSha256"],
            "policySha256": plan["policySha256"], "qualificationFile": str(tmp_path / "qualification.json"),
            "captureTemplate": str(capture[0]), "exportPlan": str(tmp_path / "export-plan.json"),
            "stagingRoot": str(tmp_path / "daily-staging"), "releaseRoot": str(tmp_path / "release"),
            "backupHealthReceipt": str(source / "postgres/health.json"),
            "backupDirectory": str(source / "postgres"), "backupSourceScript": str(tmp_path / "source-backup.sh"), "node": "/fixture/node"}
    script = write(Path(data["backupSourceScript"]), b"isolated-source-script-fixture")
    write(Path(data["qualificationFile"]), {"schemaVersion": "isolated-test-fixture-only",
                                          "postgresBackupScriptSha256": r.sha256(script)})
    write(Path(data["exportPlan"]), {"schemaVersion": "isolated-test-fixture-only"})
    return write(tmp_path / "daily-plan.json", data), data


def fixture_participants(root):
    receipt = write(root / "participant-fixture.json", {"status": "isolated-fixture-only"})
    return [{"role": role, "root": str(root), "reviewRoots": [],
             "qualificationReceipt": str(receipt), "qualificationSha256": r.sha256(receipt)}
            for role in sorted(daily.ROLES)]


class AdmissionFixture:
    """Isolated supported-protocol seam double; never a runtime qualification."""
    def __init__(self, root, *, stale_restore=False, refuse_guard=False):
        self.root = root
        self.events = []
        self.stale_restore = stale_restore
        self.refuse_guard = refuse_guard
        self.hold = None
    def producer_inventory(self, root):
        return {"producers": [{"kind": "schedule", "id": "original-producer", "owner": "original-owner",
                              "definition_hash": "a" * 64, "enabled": True}]}
    def pause_producers(self, root, **kwargs):
        self.events.append("pause")
        self.hold = {"status": "holding", "readback_verified": True, "receipt": str(self.root / "hold.json")}
        r._write(Path(self.hold["receipt"]), {"status": "holding", **kwargs})
        return self.hold
    def admission_receipt_binding(self, root, **kwargs):
        self.events.append("binding")
        return {"root": root, "hold_id": kwargs["hold_id"], "owner": kwargs["owner"]}
    def verify_admission_binding(self, binding):
        self.events.append("verify")
    @contextmanager
    def migration_admission_guard(self, root, **kwargs):
        self.events.append("guard-enter")
        if self.refuse_guard:
            raise r.RecoverySetError("fixture active original producer did not drain")
        try:
            yield {"protocol": "producer-admission/v1", "drained": True, "admission_lock_retained": True}
        finally:
            self.events.append("guard-exit")
    def resume_producers(self, root, **kwargs):
        self.events.append("resume")
        if self.stale_restore:
            raise r.RecoverySetError("fixture changed original definition, hold preserved")
        r._write(Path(self.hold["receipt"]), {"status": "restored", "readback_verified": True})
        return {"status": "restored", "readback_verified": True}


def test_daily_refuses_unqualified_all_writers_before_any_hold_or_output(daily_plan):
    path, plan = daily_plan
    write(Path(plan["qualificationFile"]), {"schemaVersion": "execution-fabric-recovery-daily-qualification/v1",
                                           "status": "qualified", "allWritersParticipate": False})
    calls = []
    with pytest.raises(r.RecoverySetError, match="before holds"):
        daily.run_daily_recovery(path, apply=True, runner=lambda *a: calls.append(a))
    assert calls == [] and not Path(plan["stagingRoot"]).exists()


def test_missing_released_admission_protocol_cannot_be_loaded_from_age224_source():
    with pytest.raises(r.RecoverySetError, match="unavailable|differs"):
        daily._installed_admission("f" * 64)


def test_daily_dry_run_never_loads_admission_or_creates_output(daily_plan, monkeypatch):
    monkeypatch.setattr(daily, "_qualification", lambda _: pytest.fail("dry-run loaded admission"))
    result = daily.run_daily_recovery(daily_plan[0])
    assert result["status"] == "planned" and result["lastGoodPreserved"]
    assert not Path(daily_plan[1]["stagingRoot"]).exists()


@pytest.mark.parametrize("change", ["node", "backup", "scope", "duplicate", "expired", "root"])
def test_daily_qualification_refuses_changed_actor_or_participant_scope_before_holds(daily_plan, tmp_path, monkeypatch, change):
    path, plan = daily_plan
    root = tmp_path / "qualified-fixture-root"
    write(root / ".agentic_root", b"fixture-only")
    actor = write(Path(plan["releaseRoot"]) / "bin/backup-health.sh", b"qualified-fixture-pg-actor")
    export = write(Path(plan["releaseRoot"]) / "services/execution-fabric-control-plane/dist/src/recovery-export-main.js",
                   b"qualified-fixture-export-actor")
    export_module = write(export.with_name("recovery-export.js"), b"qualified-fixture-export-module")
    backup_lib = write(actor.with_name("_lib.sh"), b"qualified-fixture-backup-lib")
    validator = write(actor.with_name("validate-backup-health-receipt.sh"), b"qualified-fixture-validator")
    node = write(tmp_path / "qualified-fixture-node", b"qualified-fixture-native-actor")
    plan["node"] = str(node)
    write(path, plan)
    now = datetime.now(timezone.utc)
    participants = []
    for role in sorted(daily.ROLES):
        receipt = write(tmp_path / (role + "-qualification.json"), {
            "schemaVersion": "execution-fabric-recovery-participant-qualification/v1", "status": "qualified",
            "role": role, "root": str(root), "reviewRoots": [], "sourceRelease": plan["sourceRelease"],
            "protocol": "producer-admission/v1", "allWriterEntryPointsParticipate": True,
            "admissionModuleSha256": "a" * 64, "qualifiedAt": (now - timedelta(days=2)).isoformat(),
            "validUntil": (now + timedelta(days=1)).isoformat()})
        participants.append({"role": role, "root": str(root), "reviewRoots": [],
                             "qualificationReceipt": str(receipt), "qualificationSha256": r.sha256(receipt)})
    qualified = {"schemaVersion": "execution-fabric-recovery-daily-qualification/v1", "status": "qualified",
        **{field: plan[field] for field in ("sourceHost", "sourceRelease", "imageLockSha256", "policySha256")},
        "allWritersParticipate": True, "participants": participants,
        "qualifiedAt": (now - timedelta(days=2)).isoformat(), "validUntil": (now + timedelta(days=1)).isoformat(),
        "admissionModuleSha256": "a" * 64, "nodeSha256": r.sha256(node),
        "backupHealthSha256": r.sha256(actor), "backupLibSha256": r.sha256(backup_lib),
        "backupReceiptValidatorSha256": r.sha256(validator), "exportMainSha256": r.sha256(export),
        "exportModuleSha256": r.sha256(export_module), "postgresBackupScriptSha256": r.sha256(Path(plan["backupSourceScript"]))}
    if change == "node":
        write(node, b"changed-native-binary")
    elif change == "backup":
        write(actor, b"changed-backup-actor")
    elif change == "scope":
        participants[0]["reviewRoots"] = [str(tmp_path)]
    elif change == "duplicate":
        participants.append(dict(participants[0]))
    elif change == "expired":
        qualified["validUntil"] = (now - timedelta(days=1)).isoformat()
    else:
        (root / ".agentic_root").unlink()
    write(Path(plan["qualificationFile"]), qualified)
    monkeypatch.setattr(daily, "_installed_admission", lambda _: object())
    calls = []
    with pytest.raises(r.RecoverySetError, match="unqualified|unavailable|invalid|expired"):
        daily.run_daily_recovery(path, apply=True, runner=lambda *args: calls.append(args))
    assert not calls and not Path(plan["stagingRoot"]).exists()


def test_failed_guard_restores_exact_owned_hold_without_native_actor(daily_plan, tmp_path, monkeypatch):
    fixture = AdmissionFixture(tmp_path, refuse_guard=True)
    participants = fixture_participants(tmp_path)
    monkeypatch.setattr(daily, "_qualification", lambda plan: (fixture, participants))
    def forbidden(*args):
        pytest.fail("refused guard invoked backup/export actor")
    with pytest.raises(r.RecoverySetError, match="did not drain"):
        daily.run_daily_recovery(daily_plan[0], apply=True, runner=forbidden)
    assert fixture.events == ["pause", "binding", "guard-enter", "resume"]
    assert not (Path(daily_plan[1]["stagingRoot"]) / "current-success.json").exists()


def test_daily_failure_preserves_last_good_pointer_and_reports_stale_hold(daily_plan, tmp_path, monkeypatch):
    fixture = AdmissionFixture(tmp_path, stale_restore=True)
    participants = fixture_participants(tmp_path)
    monkeypatch.setattr(daily, "_qualification", lambda plan: (fixture, participants))
    staging = Path(daily_plan[1]["stagingRoot"])
    previous = write(staging / "current-success.json", {"recoverySetId": "previous-immutable-good"})
    original = previous.read_bytes()
    with pytest.raises(r.RecoverySetError, match="hold preserved"):
        daily.run_daily_recovery(daily_plan[0], apply=True)
    assert previous.read_bytes() == original
    assert "resume" in fixture.events


def test_success_generates_distinct_sets_and_restores_before_pointer_publication(daily_plan, capture, tmp_path, monkeypatch):
    fixture = AdmissionFixture(tmp_path)
    participants = fixture_participants(tmp_path)
    monkeypatch.setattr(daily, "_qualification", lambda plan: (fixture, participants))
    template = json.loads(capture[0].read_text())
    backup_actor = Path(daily_plan[1]["releaseRoot"]) / "bin/backup-health.sh"
    write(backup_actor, b"fixture-actor-only")
    health_path = Path(daily_plan[1]["backupHealthReceipt"])
    health = json.loads(health_path.read_text())
    health.update({"verifiedAt": datetime.now(timezone.utc).isoformat(),
                   "backupFile": "ledger.dump", "restoreManifest": {"file": "restore.json",
                    "sha256": r.sha256(capture[2] / "postgres/restore.json")}})
    write(health_path, health)
    def fixture_export(plan, working, label, runner, *, watermark_only=False):
        receipt = {"schemaVersion": "execution-fabric-recovery-export/v1",
                   "status": "watermark_verified" if watermark_only else "exported_bytes_verified",
                   "sourceHost": "genomesbox", "postgresWalLsn": "0/ABCD",
                   "postgresSource": PG_SOURCE, "postgresSourceVerified": True,
                   "versionInventorySha256": "b" * 64, "ledgerReferenceSha256": "c" * 64}
        write(working / (label + ".json"), receipt)
        if not watermark_only:
            artifact = working / "artifact-export"
            artifact.mkdir(mode=0o700)
            payload = write(artifact / "object-version-1", b"private-object-or-receipt-content")
            write(artifact / "inventory.json", {"schemaVersion": "execution-fabric-recovery-artifacts/v1",
                "references": [{"relativePath": "artifactStore/object-version-1", "sha256": r.sha256(payload),
                "bytes": payload.stat().st_size, "ownerBinding": "original-owner",
                "artifactId": "artifact-1", "objectKey": "objects/key", "versionId": "version-1"}]})
        return receipt
    monkeypatch.setattr(daily, "_export", fixture_export)
    calls = []
    def fixture_actor(argv):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, b"")
    first = daily.run_daily_recovery(daily_plan[0], apply=True, runner=fixture_actor)
    second = daily.run_daily_recovery(daily_plan[0], apply=True, runner=fixture_actor)
    assert first["recoverySetId"] != second["recoverySetId"]
    staging = Path(daily_plan[1]["stagingRoot"])
    assert (staging / first["relativePath"] / "manifest.json").is_file()
    assert (staging / second["relativePath"] / "manifest.json").is_file()
    assert json.loads((staging / "current-success.json").read_text()) == second
    assert fixture.events.index("resume") < fixture.events.index("guard-exit")
    assert len(calls) == 2 and all(call == [str(backup_actor), "--require-source-provenance",
        "--source-script-sha256", r.sha256(Path(daily_plan[1]["backupSourceScript"]))] for call in calls)
    first_root = staging / first["relativePath"]
    verified = r.verify_recovery_set(first_root)
    assert verified["manifestSha256"] == first["manifestSha256"]
    proofs = first_root / "immutableReceipts/recovery-daily"
    assert json.loads((proofs / "holding-0.json").read_text())["status"] == "holding"
    assert json.loads((tmp_path / "hold.json").read_text())["status"] == "restored"
    assert json.loads((proofs / "restoration-0.json").read_text())["readback"]["readback_verified"]
    assert json.loads((proofs / "final-watermarks.json").read_text())["status"] == "verified"
    for proof in ("maintenance.json", "qualification.json", "original-capture-template.json",
                  "daily-plan.json", "export-plan.json", "export-before.json", "export-after.json"):
        assert (proofs / proof).is_file()
    manifest = json.loads((first_root / "manifest.json").read_text())
    assert manifest["captureWindow"]["maintenanceReceiptSha256"] == r.sha256(proofs / "maintenance.json")


@pytest.mark.parametrize("field", ["systemId", "database"])
def test_daily_refuses_backup_export_native_source_mismatch_without_publication(daily_plan, capture, tmp_path, monkeypatch, field):
    fixture = AdmissionFixture(tmp_path)
    monkeypatch.setattr(daily, "_qualification", lambda _: (fixture, fixture_participants(tmp_path)))
    write(Path(daily_plan[1]["releaseRoot"]) / "bin/backup-health.sh", b"fixture-only")
    health_path = Path(daily_plan[1]["backupHealthReceipt"])
    health = json.loads(health_path.read_text())
    health.update(verifiedAt=datetime.now(timezone.utc).isoformat(), backupFile="ledger.dump",
        restoreManifest={"file": "restore.json", "sha256": r.sha256(capture[2] / "postgres/restore.json")})
    write(health_path, health)
    foreign = dict(PG_SOURCE)
    foreign[field] = "99999"
    monkeypatch.setattr(daily, "_export", lambda *args, **kwargs: {"postgresSource": foreign})
    with pytest.raises(r.RecoverySetError, match="sources differ"):
        daily.run_daily_recovery(daily_plan[0], apply=True, runner=lambda _: None)
    assert "resume" in fixture.events
    staging = Path(daily_plan[1]["stagingRoot"])
    assert not (staging / "current-success.json").exists() and not (staging / "sets").exists()
