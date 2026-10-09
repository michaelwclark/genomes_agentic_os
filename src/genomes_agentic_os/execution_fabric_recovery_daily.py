"""Deterministic daily capture under independently qualified installed barriers.

The coordinator cannot qualify its own writers. Missing AGE224 or full participant
qualification refuses before holds, backup actors, output creation or publication.
"""
from __future__ import annotations

from contextlib import ExitStack
from datetime import datetime, timezone
import importlib
import json
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from . import execution_fabric_recovery as r

ROLES = {"api", "scheduler", "workers", "artifactWriters", "witness", "osWriters"}
PLAN = "execution-fabric-recovery-daily/v1"


def _installed_admission(expected_sha: str):
    try:
        module = importlib.import_module("genomes_agentic_os.producer_admission")
    except ImportError:
        raise r.RecoverySetError("qualified released producer-admission protocol is unavailable") from None
    path = Path(module.__file__).resolve()
    if path.parent != Path(__file__).resolve().parent or r.sha256(path) != r._hash(expected_sha):
        raise r.RecoverySetError("installed admission source identity differs from qualified release")
    if getattr(module, "PROTOCOL", None) != "producer-admission/v1" or any(
        not callable(getattr(module, name, None)) for name in (
            "producer_inventory", "pause_producers", "admission_receipt_binding",
            "verify_admission_binding", "migration_admission_guard", "resume_producers",
        )
    ):
        raise r.RecoverySetError("required installed reversible admission contract is unavailable")
    return module


def _current(value: str, limit: int = 86400) -> None:
    try:
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(value.replace("Z", "+00:00"))).total_seconds()
    except (ValueError, TypeError, AttributeError):
        raise r.RecoverySetError("qualification freshness is invalid") from None
    if age < 0 or age > limit:
        raise r.RecoverySetError("qualification is stale")


def _qualified_lifetime(evidence: dict[str, Any]) -> None:
    """An independent owner chooses expiry; the daily job never renews itself."""
    try:
        qualified = datetime.fromisoformat(evidence["qualifiedAt"].replace("Z", "+00:00"))
        expires = datetime.fromisoformat(evidence["validUntil"].replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        if qualified > now or expires <= now or expires <= qualified:
            raise ValueError
    except (KeyError, ValueError, TypeError, AttributeError):
        raise r.RecoverySetError("independent qualification lifetime is invalid or expired") from None


def _qualification(plan: dict[str, Any]) -> tuple[Any, list[dict[str, Any]]]:
    qualified = r._read(plan["qualificationFile"])
    if (qualified.get("schemaVersion") != "execution-fabric-recovery-daily-qualification/v1"
        or qualified.get("status") != "qualified"
        or any(qualified.get(field) != plan[field] for field in
               ("sourceHost", "sourceRelease", "imageLockSha256", "policySha256"))
        or qualified.get("allWritersParticipate") is not True
        or not isinstance(qualified.get("participants"), list)
        or any(not isinstance(p, dict) for p in qualified["participants"])
        or {p.get("role") for p in qualified["participants"]} != ROLES):
        raise r.RecoverySetError("independent full writer/role qualification is required before holds")
    _qualified_lifetime(qualified)
    module = _installed_admission(qualified.get("admissionModuleSha256"))
    participants = qualified["participants"]
    identities = set()
    for participant in participants:
        r._closed(participant, {"role", "root", "reviewRoots", "qualificationReceipt", "qualificationSha256"},
                  "daily participant")
        receipt = Path(participant["qualificationReceipt"])
        if receipt.is_symlink() or not receipt.is_file() or r.sha256(receipt) != r._hash(participant["qualificationSha256"]):
            raise r.RecoverySetError("independent participant qualification receipt bytes differ")
        evidence = r._read(receipt)
        if (evidence.get("schemaVersion") != "execution-fabric-recovery-participant-qualification/v1"
            or evidence.get("status") != "qualified" or evidence.get("role") != participant["role"]
            or evidence.get("root") != participant["root"]
            or evidence.get("sourceRelease") != plan["sourceRelease"]
            or evidence.get("protocol") != "producer-admission/v1"
            or evidence.get("allWriterEntryPointsParticipate") is not True
            or evidence.get("admissionModuleSha256") != qualified["admissionModuleSha256"]
            or evidence.get("reviewRoots") != participant["reviewRoots"]):
            raise r.RecoverySetError("full participant entry-point qualification is unavailable")
        _qualified_lifetime(evidence)
        root = Path(participant["root"])
        reviews = participant["reviewRoots"]
        identity = (participant["role"], participant["root"])
        if (not root.is_absolute() or root.is_symlink() or not (root / ".agentic_root").is_file()
            or not isinstance(reviews, list) or any(not isinstance(p, str) or not Path(p).is_absolute() for p in reviews)
            or len(reviews) != len(set(reviews)) or identity in identities):
            raise r.RecoverySetError("participant root/review scope is invalid")
        identities.add(identity)
    export_main = Path(plan["releaseRoot"]) / "services/execution-fabric-control-plane/dist/src/recovery-export-main.js"
    actors = ((export_main, "exportMainSha256"),
              (export_main.with_name("recovery-export.js"), "exportModuleSha256"),
              (Path(plan["releaseRoot"]) / "bin/backup-health.sh", "backupHealthSha256"),
              (Path(plan["releaseRoot"]) / "bin/_lib.sh", "backupLibSha256"),
              (Path(plan["releaseRoot"]) / "bin/validate-backup-health-receipt.sh", "backupReceiptValidatorSha256"),
              (Path(plan["node"]), "nodeSha256"))
    for actor, digest in actors:
        if not actor.is_file() or r.sha256(actor) != r._hash(qualified.get(digest)):
            raise r.RecoverySetError("fixed released recovery native actor is unqualified")
    return module, participants


def _validate(plan: dict[str, Any]) -> None:
    r._closed(plan, {
        "schemaVersion", "sourceHost", "sourceRelease", "imageLockSha256", "policySha256",
        "qualificationFile", "captureTemplate", "exportPlan", "stagingRoot",
        "releaseRoot", "backupHealthReceipt", "backupDirectory", "node",
    }, "daily plan")
    if plan["schemaVersion"] != PLAN:
        raise r.RecoverySetError("unsupported daily recovery plan")
    r._identity(plan["sourceHost"])
    for name in ("imageLockSha256", "policySha256"):
        r._hash(plan[name])
    for name in ("qualificationFile", "captureTemplate", "exportPlan", "stagingRoot",
                 "releaseRoot", "backupHealthReceipt", "backupDirectory"):
        if not isinstance(plan[name], str) or not Path(plan[name]).is_absolute():
            raise r.RecoverySetError("daily input paths require exact absolute bindings")
    if not isinstance(plan["node"], str) or not Path(plan["node"]).is_absolute():
        raise r.RecoverySetError("exact absolute native Node executable is required")
    template = r._read(plan["captureTemplate"])
    r._validate_plan(template)
    for name in ("sourceHost", "sourceRelease", "imageLockSha256", "policySha256"):
        if plan[name] != template[name]:
            raise r.RecoverySetError("daily template source/version/policy differs")


def plan_daily_recovery(plan_file: str | Path) -> dict[str, Any]:
    plan = r._read(plan_file)
    _validate(plan)
    return {"schemaVersion": "execution-fabric-recovery-daily-plan/v1", "status": "planned",
            "requiresQualifiedInstalledAdmission": True, "requiresAllWriters": sorted(ROLES),
            "perRunIdentity": True, "lastGoodPreserved": True}


def _export(plan: dict[str, Any], working: Path, label: str, runner: Callable, *,
            watermark_only: bool = False) -> dict[str, Any]:
    receipt = working / (label + ".json")
    entry = Path(plan["releaseRoot"]) / "services/execution-fabric-control-plane/dist/src/recovery-export-main.js"
    command = [plan["node"], str(entry), "--plan", plan["exportPlan"],
               "--receipt", str(receipt)]
    if watermark_only:
        command += ["--watermark-only"]
    else:
        command += ["--output", str(working / "artifact-export")]
    runner(command)
    value = r._read(receipt)
    if value.get("status") != ("watermark_verified" if watermark_only else "exported_bytes_verified"):
        raise r.RecoverySetError("actual read-only export receipt did not qualify")
    if value.get("sourceHost") != plan["sourceHost"]:
        raise r.RecoverySetError("export source host differs")
    return value


def _watermarks(template: dict[str, Any], working: Path, label: str,
                exported: dict[str, Any]) -> dict[str, Any]:
    def source_for(component: str, relative: str) -> Path:
        exact = [s for s in template["components"][component] if s["path"] == relative]
        if len(exact) != 1:
            raise r.RecoverySetError("daily authority source must have one exact SQLite binding")
        return Path(exact[0]["source"])
    witness = template["componentMetadata"]["witness"]
    witness_path = working / ("witness-" + label + ".db")
    r._sqlite_snapshot(source_for("witness", witness["database"]), witness_path)
    version, snapshot = r._witness_snapshot(witness_path, witness["clusterId"])
    os_path = working / ("os-" + label + ".db")
    os_meta = template["componentMetadata"]["osAuthorities"]
    r._sqlite_snapshot(source_for("osAuthorities", os_meta["snapshot"]), os_path)
    return {"postgresWalLsn": exported["postgresWalLsn"],
            "artifactInventorySha256": exported["versionInventorySha256"],
            "ledgerReferenceSha256": exported["ledgerReferenceSha256"],
            "witnessVersion": version, "witnessAuditSha256": r._digest(snapshot["audit"]),
            "osAuthoritySha256": r.sha256(os_path)}


def _freeze_file(source: str | Path, destination: Path) -> Path:
    """Preserve actual bytes before the supported writer advances a live receipt."""
    if destination.exists() or destination.is_symlink():
        raise r.RecoverySetError("daily evidence destination must be new")
    r._copy_source(Path(source), destination, "file")
    return destination


def _bind_daily_evidence(capture: Path, evidence: Path, owner: str) -> dict[str, Any]:
    """Finish this unpublished set; never amend a previously published manifest."""
    manifest = r._read(capture / "manifest.json")
    inventory_relative = manifest["components"]["immutableReceipts"]["inventory"]
    inventory_path = r._inside(capture, inventory_relative)
    inventory = r._read(inventory_path)
    represented = {entry["relativePath"] for entry in manifest["files"]}
    for source in sorted(evidence.iterdir()):
        if not source.is_file() or source.is_symlink():
            raise r.RecoverySetError("daily proof closure requires regular immutable files")
        relative = "immutableReceipts/recovery-daily/" + source.name
        if relative in represented:
            raise r.RecoverySetError("daily proof destination overlaps captured immutable history")
        destination = _freeze_file(source, r._inside(capture, relative))
        reference = {"relativePath": relative, "sha256": r.sha256(destination),
                     "bytes": destination.stat().st_size, "ownerBinding": owner}
        inventory["references"].append(reference)
        manifest["files"].append({**{key: reference[key] for key in ("relativePath", "sha256", "bytes")},
                                 "component": "immutableReceipts", "mode": "0600", "sourceBinding": owner})
    r._write(inventory_path, inventory)
    for entry in manifest["files"]:
        if entry["relativePath"] == inventory_relative:
            entry.update(sha256=r.sha256(inventory_path), bytes=inventory_path.stat().st_size)
    manifest["files"].sort(key=lambda entry: (entry["component"], entry["relativePath"]))
    manifest["fileInventorySha256"] = r._digest(manifest["files"])
    r._write(capture / "manifest.json", manifest)
    # The receipt describes only this new unpublished local set.
    receipt = {"schemaVersion": "execution-fabric-recovery-verification/v1", "status": "local_capture_complete",
               "recoverySetId": manifest["recoverySetId"], "manifestSha256": r.sha256(capture / "manifest.json"),
               "fileCount": len(manifest["files"]), "offhostCustodyVerified": False,
               "authorityTransferAuthorized": False}
    r._write(capture / "capture.receipt.json", receipt)
    return r.verify_recovery_set(capture)


def run_daily_recovery(plan_file: str | Path, *, apply: bool = False,
                       runner: Callable = r.native_command) -> dict[str, Any]:
    plan = r._read(plan_file)
    _validate(plan)
    if not apply:
        return plan_daily_recovery(plan_file)
    # This preflight is deliberately before any pause, filesystem or native actor.
    module, participants = _qualification(plan)
    template = r._read(plan["captureTemplate"])
    set_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:12]
    hold_id = "recovery-" + set_id
    owner = "recovery:" + plan["sourceHost"] + ":" + set_id
    staging = Path(plan["stagingRoot"])
    if staging.is_symlink():
        raise r.RecoverySetError("daily staging root cannot be a symlink")
    working = r._empty_target(staging / ".attempts" / set_id)
    evidence_dir = working / "evidence"
    evidence_dir.mkdir(mode=0o700)
    paused: list[tuple[str, dict[str, Any]]] = []
    bindings = []
    restorations = []
    capture = working / "capture"
    try:
        _freeze_file(plan_file, evidence_dir / "daily-plan.json")
        _freeze_file(plan["captureTemplate"], evidence_dir / "original-capture-template.json")
        _freeze_file(plan["exportPlan"], evidence_dir / "export-plan.json")
        _freeze_file(plan["qualificationFile"], evidence_dir / "qualification.json")
        for index, participant in enumerate(participants):
            _freeze_file(participant["qualificationReceipt"], evidence_dir / ("participant-" + str(index) + ".json"))
        # Same root participants share one exact overlay; preserve all foreign holds.
        by_root: dict[str, list[dict[str, Any]]] = {}
        for participant in participants:
            by_root.setdefault(participant["root"], []).append(participant)
        with ExitStack() as guards:
            for root, owned_participants in sorted(by_root.items()):
                inventory = module.producer_inventory(root)["producers"]
                hold = module.pause_producers(root, hold_id=hold_id, owner=owner,
                                              selectors=inventory, allow_empty=not inventory)
                paused.append((root, hold))
                binding = module.admission_receipt_binding(root, hold_id=hold_id, owner=owner)
                bindings.append(binding)
                review_roots = sorted({p for item in owned_participants for p in item["reviewRoots"]})
                evidence = guards.enter_context(module.migration_admission_guard(
                    root, hold_id=hold_id, owner=owner, review_roots=review_roots, restore=False))
                if (evidence.get("drained") is not True or evidence.get("admission_lock_retained") is not True
                    or evidence.get("protocol") != "producer-admission/v1"):
                    raise r.RecoverySetError("actual retained writer barrier did not qualify")
                index = len(paused) - 1
                _freeze_file(hold["receipt"], evidence_dir / ("holding-" + str(index) + ".json"))
                r._write(evidence_dir / ("guard-" + str(index) + ".json"), evidence)
            # Fixed supported PG actor; missing tools/permissions stop without alternate APIs.
            backup = Path(plan["releaseRoot"]) / "bin/backup-health.sh"
            if not backup.is_file():
                raise r.RecoverySetError("released PostgreSQL backup actor is unavailable")
            runner([str(backup)])
            health = r._read(plan["backupHealthReceipt"])
            if health.get("status") != "passed" or health.get("schemaVersion") != "execution-fabric-backup-health/v1":
                raise r.RecoverySetError("fresh actual PostgreSQL restore proof is missing")
            _current(health.get("verifiedAt"), 600)
            sidecar_name = health.get("restoreManifest", {}).get("file")
            dump_name = Path(health.get("backupFile", "")).name
            if not sidecar_name or Path(sidecar_name).name != sidecar_name or not dump_name.endswith(".dump"):
                raise r.RecoverySetError("actual backup sidecar/dump identity is invalid")
            pg_sources = [
                (Path(plan["backupDirectory"]) / dump_name, "postgres/ledger.dump"),
                (Path(plan["backupHealthReceipt"]), "postgres/health.json"),
                (Path(plan["backupHealthReceipt"]).parent / sidecar_name, "postgres/restore.json"),
            ]
            template["components"]["postgres"] = [
                {"kind": "file", "source": str(source), "path": relative,
                 "sourceBinding": owner + ":postgres:" + health["runId"]} for source, relative in pg_sources
            ]
            template["componentMetadata"]["postgres"].update(
                {"dump": "postgres/ledger.dump", "receipt": "postgres/health.json",
                 "restoreManifest": "postgres/restore.json"})
            exported = _export(plan, working, "export-before", runner)
            before = _watermarks(template, working, "before", exported)
            witness = template["componentMetadata"]["witness"]
            version, snapshot = r._witness_snapshot(working / "witness-before.db", witness["clusterId"])
            witness.update(version=version, leader=snapshot["state"]["currentLeader"],
                           epoch=snapshot["state"]["fabricEpoch"], auditTailSha256=r._digest(snapshot["audit"]))
            template["components"]["artifactStore"] = [
                {"kind": "tree", "source": str(working / "artifact-export"), "path": "artifactStore",
                 "sourceBinding": owner + ":original-object-key-and-version"}
            ]
            template["componentMetadata"]["artifactStore"] = {"inventory": "artifactStore/inventory.json"}
            template.update(recoverySetId=set_id, commonWatermark=r._digest(before))
            receipt_paths = [{"path": str(evidence_dir / ("holding-" + str(index) + ".json")),
                              "sha256": r.sha256(evidence_dir / ("holding-" + str(index) + ".json"))}
                             for index, _ in enumerate(paused)]
            receipt_paths += [{"path": str(working / "export-before.json"),
                               "sha256": r.sha256(working / "export-before.json")}]
            proof = {"schemaVersion": "execution-fabric-recovery-quiescence/v1", "status": "verified",
                "sourceHost": plan["sourceHost"], "policySha256": plan["policySha256"],
                "commonWatermark": template["commonWatermark"], "maintenanceRunId": hold_id,
                "beforeWatermarks": before, "afterWatermarks": before,
                "heldRoleIdentities": {p["role"]: p["root"] + ":" + hold_id for p in participants},
                "verifiedAt": datetime.now(timezone.utc).isoformat(), "verificationReceipts": receipt_paths}
            capture_plan = working / "capture-plan.json"
            maintenance = working / "maintenance.json"
            r._write(capture_plan, template)
            r._write(maintenance, proof)
            _freeze_file(maintenance, evidence_dir / "maintenance.json")
            _freeze_file(working / "export-before.json", evidence_dir / "export-before.json")
            captured = r.prepare_recovery_set(capture_plan, maintenance, capture, apply=True)
            after_export = _export(plan, working, "export-after", runner, watermark_only=True)
            after = _watermarks(template, working, "after", after_export)
            if before != after:
                raise r.RecoverySetError("actual source watermarks changed during daily capture")
            _freeze_file(working / "export-after.json", evidence_dir / "export-after.json")
            r._write(evidence_dir / "final-watermarks.json", {
                "schemaVersion": "execution-fabric-recovery-daily-watermarks/v1", "status": "verified",
                "beforeWatermarks": before, "afterWatermarks": after, "ownerBinding": owner})
            for binding in bindings:
                module.verify_admission_binding(binding)
            for root, _ in reversed(paused):
                restored = module.resume_producers(root, hold_id=hold_id, owner=owner)
                if restored.get("status") != "restored" or restored.get("readback_verified") is not True:
                    raise r.RecoverySetError("original producer admission readback did not restore")
                restorations.append(root)
                r._write(evidence_dir / ("restoration-" + str(len(restorations) - 1) + ".json"),
                         {"root": root, "holdId": hold_id, "ownerBinding": owner, "readback": restored})
            captured = _bind_daily_evidence(capture, evidence_dir, owner)
            # Publication stays inside retained barriers and after all restoration readbacks.
            destination = staging / "sets" / set_id
            destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            if destination.exists() or destination.is_symlink():
                raise r.RecoverySetError("immutable daily set destination already exists")
            capture.rename(destination)
            result = {"schemaVersion": "execution-fabric-recovery-current/v1",
                      "status": "complete", "recoverySetId": set_id, "sourceHost": plan["sourceHost"],
                      "relativePath": "sets/" + set_id, "manifestSha256": captured["manifestSha256"],
                      "capturedAt": r._read(destination / "manifest.json")["capturedAt"],
                      "restorationVerified": True, "authorityTransferAuthorized": False}
            r._write(staging / "current-success.json", result)
            r._write(working / "daily.receipt.json", result)
            return result
    except Exception:
        r._write(working / "failure.json", {"schemaVersion": "execution-fabric-recovery-daily-failure/v1",
            "status": "held", "recoverySetId": set_id, "lastGoodPreserved": True,
            "authorityTransferAuthorized": False})
        raise
    finally:
        for root, _ in reversed(paused):
            if root not in restorations:
                restored = module.resume_producers(root, hold_id=hold_id, owner=owner)
                if restored.get("status") != "restored" or restored.get("readback_verified") is not True:
                    raise r.RecoverySetError("daily failure left an unresolved original-state restoration")
