"""Byte-verified, encrypted recovery sets; never grants leadership authority.

Capture plans and quiescence proofs are explicit inputs from the supported
maintenance owner. A snapshot here does not authorize promotion or effect replay.
"""
from __future__ import annotations

from contextlib import closing
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import sqlite3
import stat
import subprocess
import tarfile
import tempfile
import time
from datetime import datetime, timezone
from typing import Any, Callable
from uuid import uuid4

MANIFEST = "execution-fabric-recovery-set/v1"
RECOVERY_ROLES = {"api", "scheduler", "workers", "artifactWriters", "witness", "osWriters"}
COMPONENTS = (
    "postgres", "witness", "artifactStore", "workerSpools", "osAuthorities",
    "immutableReceipts", "configuration", "releaseAssets", "sourceRecovery",
    "credentialEscrow",
)
HASH = re.compile(r"^[a-f0-9]{64}$")
IDENTITY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class RecoverySetError(ValueError):
    """An incomplete or unsafe recovery set; safe to show without tool output."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _read(path: str | Path) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        raise RecoverySetError("required JSON input is unavailable or invalid") from None
    if not isinstance(value, dict):
        raise RecoverySetError("required JSON input must be an object")
    return value


def _write(path: Path, value: Any) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid4().hex + ".partial")
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            os.chmod(temporary, 0o600)
            json.dump(value, stream, sort_keys=True, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _relative(value: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise RecoverySetError("unsafe relative path")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or value != path.as_posix():
        raise RecoverySetError("unsafe relative path")
    return value


def _inside(root: Path, relative: str) -> Path:
    result = root / _relative(relative)
    if any((root / Path(*PurePosixPath(relative).parts[:i])).is_symlink()
           for i in range(1, len(PurePosixPath(relative).parts) + 1)):
        raise RecoverySetError("symlink paths cannot carry recovery authority")
    if not result.resolve().is_relative_to(root.resolve()):
        raise RecoverySetError("path escapes recovery root")
    return result


def _identity(value: str) -> str:
    if not isinstance(value, str) or not IDENTITY.fullmatch(value):
        raise RecoverySetError("invalid recovery identity")
    return value


def _hash(value: Any) -> str:
    if not isinstance(value, str) or not HASH.fullmatch(value):
        raise RecoverySetError("missing valid digest binding")
    return value


def _empty_target(path: str | Path) -> Path:
    target = Path(path).expanduser().absolute()
    if target.is_symlink() or target.exists():
        raise RecoverySetError("recovery target must be new, never an existing root")
    target.mkdir(mode=0o700, parents=True)
    return target


def _sqlite_snapshot(source: Path, destination: Path) -> None:
    if not source.is_file() or source.is_symlink():
        raise RecoverySetError("SQLite source is not a regular file")
    started = time.monotonic()
    def progress(status: int, remaining: int, total: int) -> None:
        if time.monotonic() - started > 60:
            raise RecoverySetError("SQLite snapshot exceeded its bounded capture window")
    with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as live:
        with closing(sqlite3.connect(destination)) as snapshot:
            live.backup(snapshot, pages=256, progress=progress)
            # A standalone snapshot must not retain transient WAL/SHM files.
            snapshot.execute("PRAGMA journal_mode=DELETE")
            if snapshot.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
                raise RecoverySetError("SQLite snapshot failed integrity verification")
    os.chmod(destination, 0o600)


def _held_role_identities(value: Any, hold_id: str) -> None:
    """Validate every role/root binding without requiring original roots off-host."""
    if (not isinstance(hold_id, str) or not hold_id
        or not isinstance(value, dict) or set(value) != RECOVERY_ROLES):
        raise RecoverySetError("complete held role identity bindings are required")
    for identities in value.values():
        if not isinstance(identities, list) or not identities:
            raise RecoverySetError("held role identity list is empty or invalid")
        roots = set()
        for identity in identities:
            _closed(identity, {"root", "maintenanceRunId", "qualificationReceiptSha256",
                               "admissionReceiptSha256"}, "held role identity")
            root = identity["root"]
            if (not isinstance(root, str) or not Path(root).is_absolute() or root in roots
                or identity["maintenanceRunId"] != hold_id):
                raise RecoverySetError("held role root/owner identity is invalid")
            roots.add(root)
            _hash(identity["qualificationReceiptSha256"])
            _hash(identity["admissionReceiptSha256"])


def _maintenance_bytes(path: str | Path) -> bytes:
    """Read at most 4 MiB from the exact regular proof file, never a symlink/FIFO."""
    if not hasattr(os, "O_NOFOLLOW"):
        raise RecoverySetError("no-follow maintenance proof inspection is unavailable")
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor, "rb") as stream:
            info = os.fstat(stream.fileno())
            limit = 4 * 1024 * 1024
            if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
                raise RecoverySetError("maintenance proof is not a bounded regular file")
            snapshot = stream.read(limit + 1)
    except OSError:
        raise RecoverySetError("maintenance proof is unavailable or unsafe") from None
    if len(snapshot) > limit:
        raise RecoverySetError("maintenance proof exceeds the bounded byte limit")
    return snapshot


def _maintenance_snapshot(path: str | Path) -> tuple[bytes, dict[str, Any]]:
    snapshot = _maintenance_bytes(path)
    try:
        proof = json.loads(snapshot.decode("utf-8"))
    except (UnicodeError, ValueError):
        raise RecoverySetError("maintenance proof snapshot is invalid JSON") from None
    if not isinstance(proof, dict):
        raise RecoverySetError("maintenance proof snapshot must be an object")
    return snapshot, proof


def _unchanged_maintenance(path: str | Path, snapshot: bytes) -> None:
    if _maintenance_bytes(path) != snapshot:
        raise RecoverySetError("maintenance proof changed during capture")


def _maintenance(plan: dict[str, Any], proof: dict[str, Any]) -> None:
    version = proof.get("schemaVersion")
    if version == "execution-fabric-recovery-quiescence/v2":
        _closed(proof, {"schemaVersion", "status", "sourceHost", "policySha256", "commonWatermark",
                       "maintenanceRunId", "beforeWatermarks", "afterWatermarks", "heldRoleIdentities",
                       "verifiedAt", "verificationReceipts"}, "maintenance proof")
    if (version not in ("execution-fabric-recovery-quiescence/v1", "execution-fabric-recovery-quiescence/v2")
        or proof.get("status") != "verified"
        or proof.get("sourceHost") != plan.get("sourceHost")
        or proof.get("policySha256") != plan.get("policySha256")
        or proof.get("commonWatermark") != plan.get("commonWatermark")
        or not isinstance(proof.get("beforeWatermarks"), dict)
        or not proof.get("beforeWatermarks")
        or proof.get("beforeWatermarks") != proof.get("afterWatermarks")
        or not isinstance(proof.get("heldRoleIdentities"), dict)
        or not proof.get("heldRoleIdentities")
        or not proof.get("maintenanceRunId")
        or not isinstance(proof.get("verificationReceipts"), list)
        or not proof.get("verificationReceipts")):
        raise RecoverySetError("current source-bound quiescence proof is required")
    try:
        observed = datetime.fromisoformat(proof["verifiedAt"].replace("Z", "+00:00"))
        age = (datetime.now(timezone.utc) - observed).total_seconds()
    except (KeyError, ValueError, TypeError):
        raise RecoverySetError("invalid maintenance freshness") from None
    if age < 0 or age > 600:
        raise RecoverySetError("maintenance proof is stale")
    for receipt in proof["verificationReceipts"]:
        _closed(receipt, {"path", "sha256"}, "maintenance receipt")
        path = Path(receipt["path"])
        if not path.is_file() or path.is_symlink() or sha256(path) != _hash(receipt["sha256"]):
            raise RecoverySetError("maintenance verification receipt bytes mismatch")
    if version == "execution-fabric-recovery-quiescence/v2":
        _held_role_identities(proof["heldRoleIdentities"], proof["maintenanceRunId"])
        verified = {receipt["sha256"] for receipt in proof["verificationReceipts"]}
        if any(identity[field] not in verified
               for identities in proof["heldRoleIdentities"].values() for identity in identities
               for field in ("qualificationReceiptSha256", "admissionReceiptSha256")):
            raise RecoverySetError("held role identity lacks byte-verified qualification/admission receipts")


def _validate_plan(plan: dict[str, Any]) -> None:
    if plan.get("schemaVersion") != "execution-fabric-recovery-capture/v1":
        raise RecoverySetError("unsupported capture plan")
    _identity(plan.get("recoverySetId", ""))
    for name in ("imageLockSha256", "policySha256"):
        _hash(plan.get(name))
    if not plan.get("sourceRelease") or not plan.get("sourceHost") or not plan.get("commonWatermark"):
        raise RecoverySetError("capture source/version/watermark is incomplete")
    if not isinstance(plan.get("components"), dict) or set(plan["components"]) != set(COMPONENTS):
        raise RecoverySetError("all recovery authority components are required")
    if not isinstance(plan.get("componentMetadata"), dict) or set(plan["componentMetadata"]) != set(COMPONENTS):
        raise RecoverySetError("all recovery component metadata is required")
    for component, sources in plan["components"].items():
        if not isinstance(sources, list) or not sources:
            raise RecoverySetError("required component has no byte sources")
        for source in sources:
            if not isinstance(source, dict) or set(source) != {"kind", "source", "path", "sourceBinding"}:
                raise RecoverySetError("capture source must use the closed source contract")
            if source.get("kind") not in ("file", "tree", "sqlite"):
                raise RecoverySetError("unsupported component capture method")
            relative = _relative(source.get("path", ""))
            if PurePosixPath(relative).parts[0] != component:
                raise RecoverySetError("component path belongs to a different authority")
            if not source.get("sourceBinding"):
                raise RecoverySetError("source owner/context binding is required")
            if not isinstance(source.get("source"), str) or not Path(source["source"]).is_absolute():
                raise RecoverySetError("capture source must have an absolute binding")


def plan_recovery_set(capture_plan: str | Path) -> dict[str, Any]:
    plan = _read(capture_plan)
    _validate_plan(plan)
    return {
        "schemaVersion": "execution-fabric-recovery-plan/v1",
        "status": "planned", "recoverySetId": plan["recoverySetId"],
        "components": sorted(plan["components"]),
        "requiresCurrentQuiescence": True, "sourceMutation": False,
    }


def _copy_source(source: Path, target: Path, kind: str) -> None:
    if source.is_symlink():
        raise RecoverySetError("unbound source symlink")
    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if kind == "sqlite":
        _sqlite_snapshot(source.absolute(), target)
    elif kind == "file":
        if not source.is_file():
            raise RecoverySetError("required component byte source is missing")
        before = sha256(source)
        shutil.copyfile(source, target)
        os.chmod(target, 0o600)
        if before != sha256(source) or before != sha256(target):
            raise RecoverySetError("component bytes changed during capture")
    else:
        if not source.is_dir():
            raise RecoverySetError("required component tree is missing")
        paths = sorted(source.rglob("*"))
        if any(p.is_symlink() or (not p.is_dir() and not p.is_file()) for p in paths):
            raise RecoverySetError("unsafe special file in component tree")
        for path in paths:
            if path.is_file():
                _copy_source(path, target / path.relative_to(source), "file")
        if not any(p.is_file() for p in paths):
            raise RecoverySetError("required component tree is empty")
        if paths != sorted(source.rglob("*")):
            raise RecoverySetError("component tree membership changed during capture")


def _inventory(root: Path, sources: dict[str, Any]) -> list[dict[str, Any]]:
    entries = []
    for component, bindings in sources.items():
        for path in sorted((root / component).rglob("*")):
            if path.is_file():
                binding = next(
                    b["sourceBinding"] for b in bindings
                    if path.relative_to(root).as_posix() == b["path"]
                    or path.relative_to(root).as_posix().startswith(b["path"] + "/")
                )
                entries.append({
                    "relativePath": path.relative_to(root).as_posix(),
                    "component": component, "sha256": sha256(path),
                    "bytes": path.stat().st_size, "mode": "0600",
                    "sourceBinding": binding,
                })
    if {entry["component"] for entry in entries} != set(COMPONENTS):
        raise RecoverySetError("required component contains no byte inventory")
    return entries


def verify_recovery_set(root: str | Path) -> dict[str, Any]:
    directory = Path(root).expanduser().absolute()
    if directory.is_symlink() or not directory.is_dir():
        raise RecoverySetError("recovery root must be a regular private directory")
    if directory.stat().st_mode & 0o077 or (directory / "manifest.json").is_symlink():
        raise RecoverySetError("recovery manifest/root must remain private")
    manifest = _read(directory / "manifest.json")
    required = {
        "schemaVersion", "recoverySetId", "status", "capturedAt", "sourceHost",
        "sourceRelease", "imageLockSha256", "policySha256", "commonWatermark",
        "captureWindow", "components", "files", "fileInventorySha256",
    }
    if set(manifest) != required or manifest["schemaVersion"] != MANIFEST:
        raise RecoverySetError("unsupported or open recovery manifest")
    _identity(manifest["recoverySetId"])
    _hash(manifest["imageLockSha256"])
    _hash(manifest["policySha256"])
    if (manifest["status"] != "local_capture_complete"
        or not isinstance(manifest["components"], dict)
        or set(manifest["components"]) != set(COMPONENTS)
        or not manifest["sourceHost"] or not manifest["sourceRelease"]
        or not manifest["commonWatermark"]):
        raise RecoverySetError("recovery manifest omits required authority components")
    window = manifest["captureWindow"]
    if isinstance(window, dict) and "heldRoleIdentities" in window:
        _held_role_identities(window["heldRoleIdentities"], window.get("maintenanceRunId"))
    entries = manifest["files"]
    if not isinstance(entries, list) or not entries or _digest(entries) != manifest["fileInventorySha256"]:
        raise RecoverySetError("file inventory digest is invalid")
    seen = set()
    represented = set()
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {"relativePath", "component", "sha256", "bytes", "mode", "sourceBinding"}:
            raise RecoverySetError("file inventory must use the closed binding contract")
        relative = _relative(entry["relativePath"])
        if relative in seen or entry["component"] not in COMPONENTS:
            raise RecoverySetError("duplicate or invalid component identity")
        seen.add(relative)
        represented.add(entry["component"])
        if PurePosixPath(relative).parts[0] != entry["component"]:
            raise RecoverySetError("file/component mismatch")
        path = _inside(directory, relative)
        if (entry["mode"] != "0600" or type(entry["bytes"]) is not int
            or entry["bytes"] < 0 or not path.is_file() or path.stat().st_size != entry["bytes"]
            or sha256(path) != _hash(entry["sha256"]) or not entry.get("sourceBinding")):
            raise RecoverySetError("required component bytes or identity do not verify")
        if path.stat().st_mode & 0o077:
            raise RecoverySetError("recovery bytes must remain private")
        if path.suffix in (".db", ".sqlite3") and entry["component"] in ("witness", "osAuthorities"):
            with closing(sqlite3.connect(path.as_uri() + "?mode=ro&immutable=1", uri=True)) as database:
                if database.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
                    raise RecoverySetError("restored SQLite integrity failed")
    if represented != set(COMPONENTS):
        raise RecoverySetError("component byte closure is incomplete")
    paths = list(directory.rglob("*"))
    if any(p.is_symlink() or (not p.is_file() and not p.is_dir()) for p in paths):
        raise RecoverySetError("unsafe special file in recovery set")
    actual = {p.relative_to(directory).as_posix() for p in paths
              if p.is_file() and p.relative_to(directory).as_posix() not in ("manifest.json", "capture.receipt.json")}
    if actual != seen:
        raise RecoverySetError("unmanifested recovery bytes are present")
    capture_receipt = directory / "capture.receipt.json"
    if capture_receipt.exists():
        receipt = _read(capture_receipt)
        if (receipt.get("status") != "local_capture_complete"
            or receipt.get("recoverySetId") != manifest["recoverySetId"]
            or receipt.get("manifestSha256") != sha256(directory / "manifest.json")
            or receipt.get("offhostCustodyVerified") is not False
            or receipt.get("authorityTransferAuthorized") is not False):
            raise RecoverySetError("local capture receipt differs from actual manifest identity")
    _verify_postgres(directory, manifest)
    _verify_authorities(directory, manifest)
    return {
        "schemaVersion": "execution-fabric-recovery-verification/v1",
        "status": "bytes_verified", "recoverySetId": manifest["recoverySetId"],
        "manifestSha256": sha256(directory / "manifest.json"),
        "fileCount": len(seen), "authorityTransferAuthorized": False,
    }



def _closed(value: Any, fields: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != fields:
        raise RecoverySetError(label + " metadata must use the closed contract")
    return value


def _bound(root: Path, manifest: dict[str, Any], component: str, relative: Any) -> Path:
    path = _inside(root, relative)
    if not any(e["relativePath"] == relative and e["component"] == component
               for e in manifest["files"]):
        raise RecoverySetError("authority reference is absent from component inventory")
    return path


def _witness_snapshot(path: Path, cluster: str) -> tuple[int, dict[str, Any]]:
    try:
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro&immutable=1", uri=True)) as database:
            if database.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
                raise RecoverySetError("witness snapshot integrity failed")
            rows = database.execute(
                "SELECT cluster_id,version,payload FROM witness_snapshot"
            ).fetchall()
            if len(rows) != 1 or rows[0][0] != cluster or rows[0][1] < 1:
                raise RecoverySetError("witness cluster/version closure is invalid")
            payload = json.loads(rows[0][2])
            if payload.get("schemaVersion") != "execution-fabric-witness-store/v2":
                raise RecoverySetError("witness history schema is unsupported")
            for field in ("promotions", "candidates", "plans", "configRotations",
                          "configRotationAborts", "configRotationPreparations", "audit"):
                if not isinstance(payload.get(field), list):
                    raise RecoverySetError("witness history is incomplete")
            audit = database.execute(
                "SELECT payload FROM witness_audit WHERE cluster_id=?", (cluster,)
            ).fetchall()
            if sorted(_digest(json.loads(row[0])) for row in audit) != sorted(
                _digest(row) for row in payload["audit"]
            ):
                raise RecoverySetError("witness relational audit/history mismatch")
            return rows[0][1], payload
    except (sqlite3.Error, ValueError, TypeError, AttributeError):
        raise RecoverySetError("witness database/history cannot be verified") from None


def _verify_reference_inventory(root: Path, manifest: dict[str, Any], component: str,
                                schema: str, *, object_versions: bool = False) -> None:
    metadata = _closed(manifest["components"][component], {"inventory"}, component)
    inventory = _read(_bound(root, manifest, component, metadata["inventory"]))
    _closed(inventory, {"schemaVersion", "references"}, component + " inventory")
    if inventory["schemaVersion"] != schema or not isinstance(inventory["references"], list):
        raise RecoverySetError("reference inventory schema is unsupported")
    expected_fields = {"relativePath", "sha256", "bytes", "ownerBinding"}
    if object_versions:
        expected_fields |= {"artifactId", "objectKey", "versionId"}
    represented = set()
    identities = set()
    for reference in inventory["references"]:
        _closed(reference, expected_fields, component + " reference")
        relative = reference["relativePath"]
        path = _bound(root, manifest, component, relative)
        if relative in represented or not reference["ownerBinding"]:
            raise RecoverySetError("duplicate or unowned recovery reference")
        represented.add(relative)
        if sha256(path) != _hash(reference["sha256"]) or path.stat().st_size != reference["bytes"]:
            raise RecoverySetError("reference payload bytes mismatch")
        if object_versions:
            identity = (reference["artifactId"], reference["objectKey"], reference["versionId"])
            if any(not isinstance(v, str) or not v for v in identity) or identity in identities:
                raise RecoverySetError("artifact key/version closure is invalid")
            identities.add(identity)
    expected = {e["relativePath"] for e in manifest["files"]
                if e["component"] == component} - {metadata["inventory"]}
    if represented != expected:
        raise RecoverySetError("reference inventory omits available or pending/quarantined payloads")



def signing_public_key_sha256(path: Path) -> str:
    """Canonical Ed25519 SPKI DER identity, independent of PEM whitespace."""
    import base64
    data = path.read_bytes()
    if data.startswith(b"-----BEGIN PUBLIC KEY-----"):
        try:
            lines = data.strip().splitlines()
            if lines[0] != b"-----BEGIN PUBLIC KEY-----" or lines[-1] != b"-----END PUBLIC KEY-----":
                raise ValueError
            data = base64.b64decode(b"".join(lines[1:-1]), validate=True)
        except ValueError:
            raise RecoverySetError("witness public key is not valid SPKI") from None
    if len(data) != 44 or not data.startswith(bytes.fromhex("302a300506032b6570032100")):
        raise RecoverySetError("witness public key must be Ed25519 SPKI DER")
    return hashlib.sha256(data).hexdigest()
def _verify_authorities(root: Path, manifest: dict[str, Any]) -> None:
    witness = _closed(manifest["components"]["witness"], {
        "database", "sentinel", "backup", "hostMarker", "clusterId", "version",
        "leader", "epoch", "auditTailSha256", "originalDatabasePath", "originalBackupPath",
        "signingPublicKey", "signingPublicKeySha256",
    }, "witness")
    sentinel = _read(_bound(root, manifest, "witness", witness["sentinel"]))
    _closed(sentinel, {"schemaVersion", "clusterId", "initializedAt", "database", "backup"},
            "witness sentinel")
    if (sentinel["schemaVersion"] != "execution-fabric-witness-bootstrap/v1"
        or sentinel["clusterId"] != witness["clusterId"]
        or sentinel["database"] != witness["originalDatabasePath"]
        or sentinel["backup"] != witness["originalBackupPath"]
        or sentinel["backup"] != sentinel["database"] + ".backup"):
        raise RecoverySetError("original witness sentinel path/cluster binding differs")
    marker = _bound(root, manifest, "witness", witness["hostMarker"]).read_text()
    if not marker.startswith("cluster=" + witness["clusterId"] + " initialized="):
        raise RecoverySetError("standalone witness host marker binding differs")
    key = _bound(root, manifest, "witness", witness["signingPublicKey"])
    if signing_public_key_sha256(key) != _hash(witness["signingPublicKeySha256"]):
        raise RecoverySetError("witness signing public key identity differs")
    version, snapshot = _witness_snapshot(
        _bound(root, manifest, "witness", witness["database"]), witness["clusterId"]
    )
    backup_version, backup_snapshot = _witness_snapshot(
        _bound(root, manifest, "witness", witness["backup"]), witness["clusterId"]
    )
    state = snapshot.get("state", {})
    if (version != witness["version"] or backup_version != version
        or _digest(backup_snapshot) != _digest(snapshot)
        or state.get("currentLeader") != witness["leader"]
        or state.get("fabricEpoch") != witness["epoch"]
        or state.get("clusterId") != witness["clusterId"]
        or _digest(snapshot["audit"]) != _hash(witness["auditTailSha256"])):
        raise RecoverySetError("witness leader/epoch/version/history closure differs")
    _verify_reference_inventory(root, manifest, "artifactStore",
                                "execution-fabric-recovery-artifacts/v1", object_versions=True)
    _verify_reference_inventory(root, manifest, "workerSpools",
                                "execution-fabric-recovery-spools/v1")
    _verify_reference_inventory(root, manifest, "immutableReceipts",
                                "execution-fabric-recovery-receipts/v1")
    os_authority = _closed(manifest["components"]["osAuthorities"],
                           {"snapshot", "authorityId"}, "OS authority")
    os_snapshot = _bound(root, manifest, "osAuthorities", os_authority["snapshot"])
    if not os_authority["authorityId"]:
        raise RecoverySetError("canonical OS authority identity is missing")
    with closing(sqlite3.connect(os_snapshot.as_uri() + "?mode=ro&immutable=1", uri=True)) as database:
        if database.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
            raise RecoverySetError("canonical OS authority integrity failed")
        if not database.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall():
            raise RecoverySetError("canonical OS authority is an empty placeholder database")
    required = {
        "configuration": {"runtimeEnv", "hosts", "fabricPolicy", "installerState"},
        "releaseAssets": {"imageLock", "releaseManifest"},
        "sourceRecovery": {"bundle", "dirtyPatch"},
        "credentialEscrow": {"secretsBundle", "custodyMetadata"},
    }
    for component, names in required.items():
        metadata = _closed(manifest["components"][component], {"authorities"}, component)
        authorities = _closed(metadata["authorities"], names, component + " authorities")
        for relative in authorities.values():
            _bound(root, manifest, component, relative)
    lock = manifest["components"]["releaseAssets"]["authorities"]["imageLock"]
    if sha256(_bound(root, manifest, "releaseAssets", lock)) != manifest["imageLockSha256"]:
        raise RecoverySetError("release image lock identity differs")
    custody_path = manifest["components"]["credentialEscrow"]["authorities"]["custodyMetadata"]
    custody = _read(_bound(root, manifest, "credentialEscrow", custody_path))
    if (custody.get("schemaVersion") != "execution-fabric-recovery-key-custody/v1"
        or not custody.get("custodianIdentity") or not custody.get("recoveryKeyRef")
        or not custody.get("testedAt")):
        raise RecoverySetError("decryption/signing secret custody evidence is incomplete")
def postgres_source_identity(value: Any) -> dict[str, Any]:
    source = _closed(value, {"schemaVersion", "systemId", "database", "databaseOid", "majorVersion", "serverVersionNum"},
                     "actual PostgreSQL source")
    if (source["schemaVersion"] != "execution-fabric-postgres-source/v1"
        or not isinstance(source["systemId"], str) or not re.fullmatch(r"[1-9][0-9]*", source["systemId"])
        or not isinstance(source["databaseOid"], str) or not re.fullmatch(r"[1-9][0-9]*", source["databaseOid"])
        or not isinstance(source["database"], str) or not source["database"]
        or type(source["majorVersion"]) is not int or source["majorVersion"] < 10
        or type(source["serverVersionNum"]) is not int
        or source["serverVersionNum"] // 10000 != source["majorVersion"]):
        raise RecoverySetError("actual PostgreSQL native source identity is invalid")
    return source


def verify_postgres_declaration(declaration: dict[str, Any], observed: Any) -> dict[str, Any]:
    actual = postgres_source_identity(observed)
    if any(declaration.get(name) != actual[name] for name in ("systemId", "database", "databaseOid", "majorVersion")):
        raise RecoverySetError("declared PostgreSQL system/database/version differs from native source")
    return actual


def _verify_postgres(root: Path, manifest: dict[str, Any]) -> None:
    component = _closed(manifest["components"]["postgres"],
                        {"receipt", "restoreManifest", "dump", "systemId", "database", "databaseOid", "majorVersion"}, "postgres")
    receipt = _read(_bound(root, manifest, "postgres", component["receipt"]))
    sidecar_path = _bound(root, manifest, "postgres", component["restoreManifest"])
    sidecar = _read(sidecar_path)
    dump = _bound(root, manifest, "postgres", component["dump"])
    actual = verify_postgres_declaration(component, receipt.get("sourceIdentity"))
    if (receipt.get("sourceIdentityVerified") is not True or sidecar.get("sourceIdentityVerified") is not True
        or sidecar.get("sourceIdentityBefore") != actual or sidecar.get("sourceIdentityAfter") != actual):
        raise RecoverySetError("native PostgreSQL source before/after provenance differs")
    if (receipt.get("schemaVersion") != "execution-fabric-backup-health/v1"
        or receipt.get("status") != "passed"
        or receipt.get("runId") != sidecar.get("runId")
        or receipt.get("backupSha256") != sha256(dump)
        or sidecar.get("backupSha256") != sha256(dump)
        or sidecar.get("backupBytes") != dump.stat().st_size
        or receipt.get("restoreManifest", {}).get("sha256") != sha256(sidecar_path)
        or sidecar.get("schemaVersion") != "execution-fabric-postgres-restore-manifest/v1"
        or any(sidecar.get(flag) is not True for flag in (
            "restoreDatabaseCreated", "restoreCompleted",
            "readbackCompleted", "restoreDatabaseDropped"))):
        raise RecoverySetError("PostgreSQL dump bytes lack matching real restore proof")


def prepare_recovery_set(capture_plan: str | Path, maintenance_receipt: str | Path,
                         output: str | Path, *, apply: bool = False) -> dict[str, Any]:
    plan = _read(capture_plan)
    _validate_plan(plan)
    if not apply:
        return plan_recovery_set(capture_plan)
    proof_bytes, proof = _maintenance_snapshot(maintenance_receipt)
    proof_sha256 = hashlib.sha256(proof_bytes).hexdigest()
    _maintenance(plan, proof)
    root = _empty_target(output)
    try:
        occupied = set()
        for component, sources in plan["components"].items():
            for source in sources:
                relative = source["path"]
                if relative in occupied or any(
                    relative.startswith(p + "/") or p.startswith(relative + "/") for p in occupied
                ):
                    raise RecoverySetError("overlapping component destinations")
                occupied.add(relative)
                original = Path(source["source"]).expanduser().absolute()
                if original.is_relative_to(root) or root.is_relative_to(original):
                    raise RecoverySetError("capture source and target overlap")
                _copy_source(original, _inside(root, relative), source["kind"])
        _unchanged_maintenance(maintenance_receipt, proof_bytes)
        _maintenance(plan, proof)
        files = _inventory(root, plan["components"])
        manifest = {
            "schemaVersion": MANIFEST, "recoverySetId": plan["recoverySetId"],
            "status": "local_capture_complete",
            "capturedAt": datetime.now(timezone.utc).isoformat(),
            "sourceHost": plan["sourceHost"], "sourceRelease": plan["sourceRelease"],
            "imageLockSha256": plan["imageLockSha256"], "policySha256": plan["policySha256"],
            "commonWatermark": plan["commonWatermark"],
            "captureWindow": {
                "maintenanceReceiptSha256": proof_sha256,
                "maintenanceRunId": proof["maintenanceRunId"],
                "beforeWatermarks": proof["beforeWatermarks"],
                "afterWatermarks": proof["afterWatermarks"],
            },
            "components": plan["componentMetadata"],
            "files": files, "fileInventorySha256": _digest(files),
        }
        if proof["schemaVersion"] == "execution-fabric-recovery-quiescence/v2":
            manifest["captureWindow"]["heldRoleIdentities"] = proof["heldRoleIdentities"]
        if set(manifest["components"]) != set(COMPONENTS):
            raise RecoverySetError("component metadata is incomplete")
        # Validate only the retained snapshot; comparison reads never supply new bindings/digests.
        _maintenance(plan, proof)
        _unchanged_maintenance(maintenance_receipt, proof_bytes)
        _write(root / "manifest.json", manifest)
        verified = verify_recovery_set(root)
        _verify_postgres(root, manifest)
        receipt = {**verified, "status": "local_capture_complete",
                   "offhostCustodyVerified": False}
        _maintenance(plan, proof)
        _unchanged_maintenance(maintenance_receipt, proof_bytes)
        _write(root / "capture.receipt.json", receipt)
        _unchanged_maintenance(maintenance_receipt, proof_bytes)
        return receipt
    except Exception:
        # Only this operation's new staging root is owned; never retain a success artifact on refusal.
        (root / "manifest.json").unlink(missing_ok=True)
        (root / "capture.receipt.json").unlink(missing_ok=True)
        # Never erase another root or replace the last successful recovery set.
        _write(root / "failed.receipt.json", {
            "schemaVersion": "execution-fabric-recovery-failure/v1",
            "recoverySetId": plan["recoverySetId"], "status": "incomplete",
        })
        raise


def native_command(argv: list[str], *, timeout: int = 120,
                   stdout: Any = subprocess.PIPE) -> subprocess.CompletedProcess:
    try:
        result = subprocess.run(argv, stdout=stdout, stderr=subprocess.PIPE,
                                timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired):
        raise RecoverySetError("required native tool is unavailable; no fallback attempted") from None
    if result.returncode:
        raise RecoverySetError("native recovery command failed; private output withheld")
    return result


def pull_recovery_set(source_host: str, source_dir: str, output: str | Path,
                      *, registered_hosts: dict[str, Any], source_root: str,
                      apply: bool = False,
                      runner: Callable = native_command) -> dict[str, Any]:
    _identity(source_host)
    if source_host not in registered_hosts or not source_dir.startswith("/") or "\n" in source_dir:
        raise RecoverySetError("fixed registered source host/path required")
    # Restrict remote shell syntax even though the argument is quoted below.
    if not re.fullmatch(r"/[A-Za-z0-9/._ -]+", source_dir) or ".." in PurePosixPath(source_dir).parts:
        raise RecoverySetError("unsafe remote source path")
    if (not source_root.startswith("/") or ".." in PurePosixPath(source_root).parts
        or not PurePosixPath(source_dir).is_relative_to(PurePosixPath(source_root))
        or PurePosixPath(source_dir) == PurePosixPath(source_root)):
        raise RecoverySetError("remote source must be an exact set beneath the declared staging root")
    alias = registered_hosts[source_host].get("ssh_alias", source_host)
    _identity(alias)
    if not apply:
        return {"status": "planned", "sourceHost": source_host, "transport": "fixed_ssh_tar"}
    import shlex
    root = _empty_target(output)
    archive = root.parent / ("." + root.name + "." + uuid4().hex + ".tar")
    try:
        with archive.open("xb") as stream:
            os.chmod(archive, 0o600)
            runner(["ssh", "-o", "BatchMode=yes", "-o", "ClearAllForwardings=yes",
                    "-o", "ConnectTimeout=10", alias,
                    "tar -C " + shlex.quote(source_dir) + " -cf - ."],
                   stdout=stream, timeout=120)
        with tarfile.open(archive) as incoming:
            for member in incoming.getmembers():
                name = member.name.removeprefix("./")
                if not name or name == ".":
                    continue
                target = _inside(root, name)
                if member.isdir():
                    target.mkdir(mode=0o700, parents=True, exist_ok=True)
                elif member.isfile():
                    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                    payload = incoming.extractfile(member)
                    if payload is None:
                        raise RecoverySetError("missing transfer payload")
                    with target.open("xb") as destination:
                        shutil.copyfileobj(payload, destination)
                    os.chmod(target, 0o600)
                else:
                    raise RecoverySetError("unsafe link/device in transfer")
        verified = verify_recovery_set(root)
        if _read(root / "manifest.json")["sourceHost"] != source_host:
            raise RecoverySetError("transferred set belongs to another source host")
        return verified
    finally:
        archive.unlink(missing_ok=True)



def collect_current_recovery_set(source_host: str, local_root: str | Path,
                                 repository: str, password_file: str | Path, *,
                                 source_root: str, registered_hosts: dict[str, Any],
                                 restic: str = "restic", apply: bool = False,
                                 max_age_seconds: int = 86400,
                                 runner: Callable = native_command) -> dict[str, Any]:
    _identity(source_host)
    if source_host not in registered_hosts or not re.fullmatch(r"/[A-Za-z0-9/._ -]+", source_root):
        raise RecoverySetError("fixed registered source host/staging root required")
    if ".." in PurePosixPath(source_root).parts:
        raise RecoverySetError("unsafe source staging root")
    alias = registered_hosts[source_host].get("ssh_alias", source_host)
    _identity(alias)
    if not apply:
        return {"status": "planned", "selection": "source_current_success_manifest",
                "authorityTransferAuthorized": False}
    import shlex
    response = runner(["ssh", "-o", "BatchMode=yes", "-o", "ClearAllForwardings=yes",
                       "-o", "ConnectTimeout=10", alias,
                       "cat -- " + shlex.quote(source_root.rstrip("/") + "/current-success.json")])
    try:
        if len(response.stdout) > 65536:
            raise ValueError
        current = json.loads(response.stdout)
    except (ValueError, TypeError):
        raise RecoverySetError("current successful source set reference is invalid") from None
    _closed(current, {"schemaVersion", "status", "recoverySetId", "sourceHost",
                      "relativePath", "manifestSha256", "capturedAt", "restorationVerified",
                      "authorityTransferAuthorized"}, "current set")
    set_id = _identity(current["recoverySetId"])
    if (current["schemaVersion"] != "execution-fabric-recovery-current/v1"
        or current["status"] != "complete" or current["sourceHost"] != source_host
        or current["relativePath"] != "sets/" + set_id
        or current["restorationVerified"] is not True
        or current["authorityTransferAuthorized"] is not False):
        raise RecoverySetError("current source reference lacks complete original-state restoration")
    _hash(current["manifestSha256"])
    destination = Path(local_root).expanduser().absolute() / (set_id + "-" + uuid4().hex[:12])
    verified = pull_recovery_set(
        source_host, source_root.rstrip("/") + "/" + current["relativePath"], destination,
        source_root=source_root, registered_hosts=registered_hosts, apply=True, runner=runner,
    )
    if verified["manifestSha256"] != current["manifestSha256"] or verified["recoverySetId"] != set_id:
        raise RecoverySetError("transferred source current-set identity differs")
    return collect_recovery_set(destination, repository, password_file, set_id,
                                restic=restic, apply=True, max_age_seconds=max_age_seconds,
                                runner=runner)
def _password(path: str | Path) -> Path:
    result = Path(path).expanduser().absolute()
    if (not result.is_file() or result.is_symlink() or result.stat().st_mode & 0o077
        or result.stat().st_size == 0):
        raise RecoverySetError("protected custodian password file required")
    return result


def _native_json(prefix: list[str], command: list[str], runner: Callable) -> Any:
    response = runner(prefix + command)
    try:
        return json.loads(response.stdout)
    except (ValueError, TypeError, AttributeError):
        raise RecoverySetError("native repository identity/catalog readback is invalid") from None


def _repository_id(prefix: list[str], runner: Callable) -> str:
    value = _native_json(prefix, ["cat", "config"], runner)
    if not isinstance(value, dict):
        raise RecoverySetError("native repository config identity is unavailable")
    return _hash(value.get("id"))


def _catalog(prefix: list[str], runner: Callable) -> dict[str, dict[str, Any]]:
    rows = _native_json(prefix, ["snapshots"], runner)
    if not isinstance(rows, list):
        raise RecoverySetError("native snapshot catalog must be an array")
    result = {}
    for row in rows:
        if not isinstance(row, dict):
            raise RecoverySetError("native snapshot catalog identity is malformed")
        identity = _hash(row.get("id"))
        if identity in result:
            raise RecoverySetError("native snapshot catalog identity is ambiguous")
        result[identity] = row
    return result


def _snapshot_binding(row: dict[str, Any]) -> dict[str, Any]:
    identity = _hash(row.get("id"))
    paths, tags = row.get("paths"), row.get("tags")
    try:
        datetime.fromisoformat(row["time"].replace("Z", "+00:00"))
        if (not isinstance(paths, list) or len(paths) != 1 or not isinstance(paths[0], str)
            or not PurePosixPath(paths[0]).is_absolute() or not isinstance(tags, list)
            or any(not isinstance(tag, str) or not tag for tag in tags) or len(tags) != len(set(tags))):
            raise ValueError
        _relative(paths[0].lstrip("/"))
    except (ValueError, TypeError, KeyError, AttributeError):
        raise RecoverySetError("native recovery snapshot source/tag/time binding is invalid") from None
    return {"snapshotId": identity, "sourceRoot": paths[0], "tags": sorted(tags), "createdAt": row["time"]}


def _custody_binding(receipt: dict[str, Any]) -> dict[str, Any]:
    repository_id = _hash(receipt.get("repositoryId"))
    identity = _hash(receipt.get("snapshotId"))
    _hash(receipt.get("manifestSha256"))
    set_id = _identity(receipt.get("recoverySetId"))
    binding = _closed(receipt.get("nativeSnapshot"), {"snapshotId", "sourceRoot", "tags", "createdAt"},
                      "custody native snapshot")
    observed = _snapshot_binding({"id": binding["snapshotId"], "paths": [binding["sourceRoot"]],
                                  "tags": binding["tags"], "time": binding["createdAt"]})
    if (binding != observed or identity != binding["snapshotId"]
        or receipt.get("sourceRoot") != binding["sourceRoot"]
        or receipt.get("sourceTag") != "rubicon-recovery:" + set_id
        or receipt["sourceTag"] not in binding["tags"]):
        raise RecoverySetError("custody source snapshot identity differs")
    if _digest(binding) != _hash(receipt.get("snapshotMetadataSha256")):
        raise RecoverySetError("custody native snapshot byte binding differs")
    return {"repositoryId": repository_id, "snapshotId": identity,
            "manifestSha256": receipt["manifestSha256"], "snapshotMetadataSha256": receipt["snapshotMetadataSha256"],
            "recoverySetId": set_id, "sourceRoot": binding["sourceRoot"]}


def collect_recovery_set(source_dir: str | Path, repository: str,
                         password_file: str | Path, set_id: str, *,
                         restic: str = "restic", verify_target: str | Path | None = None,
                         apply: bool = False, max_age_seconds: int = 86400,
                         runner: Callable = native_command) -> dict[str, Any]:
    _identity(set_id)
    verified = verify_recovery_set(source_dir)
    if verified["recoverySetId"] != set_id:
        raise RecoverySetError("requested recovery set identity differs")
    try:
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(
            _read(Path(source_dir) / "manifest.json")["capturedAt"].replace("Z", "+00:00")
        )).total_seconds()
    except (ValueError, TypeError):
        raise RecoverySetError("invalid recovery capture freshness") from None
    if max_age_seconds < 1 or age < 0 or age > max_age_seconds:
        raise RecoverySetError("recovery set is stale for daily collection")
    if not apply:
        return {**verified, "status": "would_encrypt", "authorityTransferAuthorized": False}
    password = _password(password_file)
    # Credentials in repository URLs/argv are forbidden. Use a local independent repo.
    repo = Path(repository).expanduser().absolute()
    if not repo.is_dir() or repo.is_symlink():
        raise RecoverySetError("custodian repository must be initialized separately")
    source = Path(source_dir).expanduser().absolute()
    if repo.is_relative_to(source) or source.is_relative_to(repo):
        raise RecoverySetError("repository and recovery set overlap")
    prefix = [restic, "--repo", str(repo), "--password-file", str(password), "--json"]
    repository_id = _repository_id(prefix, runner)
    output = runner(prefix + ["backup", "--tag", "rubicon-recovery:" + set_id, str(source)])
    try:
        messages = [json.loads(line) for line in output.stdout.decode().splitlines() if line.strip()]
        ids = [m["snapshot_id"] for m in messages if m.get("message_type") == "summary"]
        snapshot_id = ids[-1]
        if not re.fullmatch(r"[a-f0-9]{64}", snapshot_id):
            raise ValueError
    except (ValueError, KeyError, IndexError):
        raise RecoverySetError("native encryption did not return an exact snapshot identity") from None
    catalog = _catalog(prefix, runner)
    if snapshot_id not in catalog:
        raise RecoverySetError("native encrypted snapshot is absent from its repository catalog")
    binding = _snapshot_binding(catalog[snapshot_id])
    if binding["sourceRoot"] != str(source) or "rubicon-recovery:" + set_id not in binding["tags"]:
        raise RecoverySetError("native encrypted snapshot source/set tag differs")
    if verify_target is None:
        private = Path(tempfile.mkdtemp(prefix="rubicon-restore-"))
        private.rmdir()
    else:
        private = Path(verify_target)
    target = _empty_target(private)
    try:
        runner(prefix + ["restore", snapshot_id, "--target", str(target)])
        restored = target / str(source).lstrip("/")
        restored_receipt = verify_recovery_set(restored)
        if restored_receipt["manifestSha256"] != verified["manifestSha256"]:
            raise RecoverySetError("encrypted restore manifest identity differs")
        if _repository_id(prefix, runner) != repository_id:
            raise RecoverySetError("native repository identity changed during collection")
    finally:
        # Only this invocation's generated temporary readback is removed.
        # Explicit targets remain private for the separately owned application drill.
        if verify_target is None:
            shutil.rmtree(target)
    receipt = {
        "schemaVersion": "execution-fabric-recovery-custody/v1",
        "status": "encrypted_bytes_verified", "recoverySetId": set_id,
        "manifestSha256": verified["manifestSha256"], "snapshotId": snapshot_id,
        "repositoryId": repository_id, "sourceRoot": str(source),
        "sourceTag": "rubicon-recovery:" + set_id, "nativeSnapshot": binding,
        "snapshotMetadataSha256": _digest(binding),
        "verifiedAt": datetime.now(timezone.utc).isoformat(),
        "fileCount": verified["fileCount"], "authorityTransferAuthorized": False,
        "independentDeletionProtectionVerified": False,
        "applicationRestoreQualification": "required",
    }
    _write(repo.parent / "recovery-receipts" / (set_id + ".json"), receipt)
    return receipt


def restore_recovery_set_isolated(repository: str, password_file: str | Path,
                                 snapshot_id: str, target: str | Path, *,
                                 restic: str = "restic", apply: bool = False,
                                 runner: Callable = native_command) -> dict[str, Any]:
    if not isinstance(snapshot_id, str) or not re.fullmatch(r"[a-f0-9]{64}", snapshot_id):
        raise RecoverySetError("an exact snapshot ID is required")
    if Path(target).exists() or Path(target).is_symlink():
        raise RecoverySetError("isolated restore target must be new")
    if not apply:
        return {"status": "planned", "snapshotId": snapshot_id,
                "authorityTransferAuthorized": False}
    repo = Path(repository).expanduser().absolute()
    if not repo.is_dir() or repo.is_symlink():
        raise RecoverySetError("custodian repository must be a protected local directory")
    password = _password(password_file)
    prefix = [restic, "--repo", str(repo), "--password-file", str(password), "--json"]
    # A legitimate history component may contain other files named manifest.json.
    # Bind the restore root to native immutable snapshot metadata instead of guessing.
    snapshot = runner(prefix + ["snapshots", snapshot_id])
    try:
        metadata = json.loads(snapshot.stdout)
        paths = metadata[0]["paths"]
        if (len(metadata) != 1 or metadata[0]["id"] != snapshot_id or not isinstance(paths, list)
            or len(paths) != 1 or not isinstance(paths[0], str) or not PurePosixPath(paths[0]).is_absolute()):
            raise ValueError
        original_relative = _relative(paths[0].lstrip("/"))
    except (ValueError, TypeError, KeyError, IndexError):
        raise RecoverySetError("exact native snapshot source identity is unavailable") from None
    destination = _empty_target(target)
    runner(prefix + ["restore", snapshot_id, "--target", str(destination)])
    root = _inside(destination, original_relative)
    verified = verify_recovery_set(root)
    _verify_postgres(root, _read(root / "manifest.json"))
    return {**verified, "schemaVersion": "execution-fabric-recovery-restore/v1",
            "snapshotId": snapshot_id, "status": "bytes_verified",
            "applicationRestoreQualification": "required",
            "authorityTransferAuthorized": False}


def plan_retention(receipts_dir: str | Path, *, keep: int = 14,
                   weekly: int = 4, monthly: int = 3,
                   pinned: tuple[str, ...] = (), repository_id: str | None = None) -> dict[str, Any]:
    if keep < 1 or weekly < 0 or monthly < 0:
        raise RecoverySetError("retention must preserve at least one verified set")
    receipts = []
    bindings = {}
    repositories = set()
    for path in Path(receipts_dir).glob("*.json"):
        receipt = _read(path)
        if receipt.get("status") == "encrypted_bytes_verified":
            binding = _custody_binding(receipt)
            repositories.add(binding["repositoryId"])
            if binding["snapshotId"] in bindings and bindings[binding["snapshotId"]] != binding:
                raise RecoverySetError("custody snapshot provenance is ambiguous")
            bindings[binding["snapshotId"]] = binding
            try:
                receipt["_time"] = datetime.fromisoformat(receipt["verifiedAt"].replace("Z", "+00:00"))
            except (KeyError, ValueError, TypeError):
                raise RecoverySetError("custody receipt has invalid freshness") from None
            receipts.append(receipt)
    if not receipts:
        raise RecoverySetError("retention requires at least one byte-verified custody receipt")
    if len(repositories) != 1 or (repository_id is not None and repositories != {_hash(repository_id)}):
        raise RecoverySetError("retention cannot mix or substitute native repository identities")
    for identity in pinned:
        _hash(identity)
    receipts.sort(key=lambda r: r["_time"], reverse=True)
    retained = set(pinned)
    for limit, bucket in (
        (keep, lambda d: d.date().isoformat()),
        (weekly, lambda d: d.strftime("%G-%V")),
        (monthly, lambda d: d.strftime("%Y-%m")),
    ):
        seen = set()
        for receipt in receipts:
            period = bucket(receipt["_time"])
            if period not in seen and len(seen) < limit:
                seen.add(period)
                retained.add(receipt["snapshotId"])
    retained.add(receipts[0]["snapshotId"])
    plan = {
        "schemaVersion": "execution-fabric-recovery-retention/v1", "status": "planned",
        "repositoryId": next(iter(repositories)),
        "verifiedReceiptsSha256": _digest(sorted(bindings.values(), key=lambda value: value["snapshotId"])),
        "daily": keep, "weekly": weekly, "monthly": monthly,
        "retained": sorted(retained),
        "remove": sorted({r["snapshotId"] for r in receipts} - retained),
        "lastGood": receipts[0]["snapshotId"], "prune": False,
    }
    return {**plan, "planSha256": _digest(plan)}


def apply_retention(receipts_dir: str | Path, repository: str, password_file: str | Path,
                    maintenance_receipt: str | Path, *, keep: int = 14,
                    weekly: int = 4, monthly: int = 3, pinned: tuple[str, ...] = (),
                    restic: str = "restic", apply: bool = False,
                    runner: Callable = native_command) -> dict[str, Any]:
    plan = plan_retention(receipts_dir, keep=keep, weekly=weekly, monthly=monthly, pinned=pinned)
    if not apply:
        return plan
    proof = _read(maintenance_receipt)
    repo = Path(repository).expanduser().absolute()
    if (not repo.is_dir() or repo.is_symlink()
        or proof.get("schemaVersion") != "execution-fabric-recovery-retention-approval/v1"
        or proof.get("status") != "verified" or proof.get("planSha256") != plan["planSha256"]
        or proof.get("repositoryId") != plan["repositoryId"]
        or proof.get("repository") != str(repo)
        or proof.get("drillPinnedSnapshots") != sorted(pinned)
        or not proof.get("custodianIdentity")
        or proof.get("independentDeletionProtectionVerified") is not True
        or not proof.get("verificationReceipts")):
        raise RecoverySetError("fresh custodian retention approval and protected independent copy required")
    try:
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(
            proof["verifiedAt"].replace("Z", "+00:00")
        )).total_seconds()
    except (KeyError, TypeError, ValueError):
        raise RecoverySetError("invalid retention approval freshness") from None
    if age < 0 or age > 600:
        raise RecoverySetError("retention approval is stale")
    for reference in proof["verificationReceipts"]:
        _closed(reference, {"path", "sha256"}, "retention verification")
        path = Path(reference["path"])
        if path.is_symlink() or not path.is_file() or sha256(path) != _hash(reference["sha256"]):
            raise RecoverySetError("retention independent custody proof bytes differ")
    password = _password(password_file)
    prefix = [restic, "--repo", str(repo), "--password-file", str(password), "--json"]
    if _repository_id(prefix, runner) != plan["repositoryId"]:
        raise RecoverySetError("actual native repository differs from receipt/approval provenance")
    before = _catalog(prefix, runner)
    if not set(plan["retained"]).issubset(before) or plan["lastGood"] not in before:
        raise RecoverySetError("actual repository lacks retained/last-good/drill-pinned snapshots")
    for path in Path(receipts_dir).glob("*.json"):
        custody = _read(path)
        if custody.get("status") == "encrypted_bytes_verified" and custody["snapshotId"] in before:
            if _digest(_snapshot_binding(before[custody["snapshotId"]])) != custody["snapshotMetadataSha256"]:
                raise RecoverySetError("actual catalog source snapshot provenance differs from custody receipt")
    # A fresh second read detects concurrent tag/catalog edits before the actor.
    if _repository_id(prefix, runner) != plan["repositoryId"] or _digest(_catalog(prefix, runner)) != _digest(before):
        raise RecoverySetError("native repository/catalog changed before retention")
    remove = sorted(set(plan["remove"]) & set(before))
    unknown = sorted(set(before) - set(plan["remove"]) - set(plan["retained"]))
    if remove:
        runner(prefix + ["forget", *remove])
    after = _catalog(prefix, runner)
    survivors = set(before) - set(remove)
    if (_repository_id(prefix, runner) != plan["repositoryId"] or not survivors.issubset(after)
        or any(_digest(after[identity]) != _digest(before[identity]) for identity in survivors)
        or set(remove) & set(after)):
        raise RecoverySetError("retention native survivor readback failed")
    receipt = {**plan, "status": "forgot_exact_snapshots", "prune": False,
               "forgotSnapshots": remove, "alreadyAbsentSnapshots": sorted(set(plan["remove"]) - set(before)),
               "preservedUnknownSnapshots": unknown, "catalogBeforeSha256": _digest(before),
               "catalogAfterSha256": _digest(after), "retainedReadbackVerified": True,
               "approvalSha256": sha256(Path(maintenance_receipt)),
               "verifiedAt": datetime.now(timezone.utc).isoformat()}
    _write(Path(receipts_dir) / ("retention-" + uuid4().hex + ".json"), receipt)
    return receipt
