"""Offline, fail-closed cold recovery of a stopped standalone Fabric.

This coordinator never stops a host or infers fencing from reachability. Signed
external fencing and a separately retained freshness anchor are prerequisites.
Actors are fixed entrypoints from explicitly reviewed builds or installations.
"""
from __future__ import annotations

import base64
import datetime as dt
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
from typing import Any, Mapping, Sequence
from uuid import UUID, uuid4

class ColdRecoveryError(ValueError):
    """A cold operation was refused without admitting ordinary work."""

ACTIONS = {"inspect", "prepare", "approve", "apply", "status", "resume", "canary", "accept", "initialize-anchor"}
PHASES = ("PREPARED", "APPROVED", "RESERVED", "LEDGER_HELD", "WITNESS_COMMITTED_HELD", "LEDGER_COMMITTED_HELD", "ANCHOR_COMMITTED", "CANARY_ADMITTED", "ACCEPTED")
HEX = re.compile(r"^[a-f0-9]{64}$")
PLAN_KEYS = {"schemaVersion", "recoveryId", "direction", "clusterId", "sourceHost", "targetHost", "expectedEpoch", "nextEpoch", "generation", "anchorSha256", "policySha256", "restoreInputSha256", "manifestSha256", "restoreReceiptSha256", "snapshotVersion", "originalDatabasePath", "originalBackupPath", "targetDatabasePath", "databaseSha256", "sentinelSha256", "backupSha256", "hostMarkerSha256", "oldPublicKeySha256", "newPublicKeySha256", "candidateConfigDigest", "newPgSystemId", "timelineId", "walPosition", "createdAt", "expiresAt", "canary"}
POLICY_KEYS = {"schemaVersion", "enabled", "clusterId", "allowedHosts", "recoveryPublicKeyPem", "fencePublicKeyPem", "maxApprovalSeconds", "witnessActorSha256", "controlPlaneActorSha256"}
REQUEST_KEYS = {"plan", "restoreInput", "approval", "fence", "signingPrivateKeyFile", "hostMarkerFile", "baseline", "authorityProof", "policySha256"}

def canonical(value: Any) -> bytes:
    def safe(item: Any) -> None:
        if isinstance(item, float) or (type(item) is int and abs(item) > 9_007_199_254_740_991):
            raise ColdRecoveryError("cold protocol numbers must be safe integers")
        if isinstance(item, dict):
            for k, v in item.items():
                if not isinstance(k, str):
                    raise ColdRecoveryError("cold protocol keys must be strings")
                safe(v)
        elif isinstance(item, list):
            for v in item:
                safe(v)
    safe(value)
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()

def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()

def _closed(value: Any, keys: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        raise ColdRecoveryError(f"{label} has missing or unknown fields")
    return value

def _time(value: Any) -> dt.datetime:
    if not isinstance(value, str):
        raise ColdRecoveryError("timestamp is not text")
    try:
        result = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ColdRecoveryError("timestamp is invalid") from exc
    if result.tzinfo is None:
        raise ColdRecoveryError("timestamp must include a timezone")
    return result

def _window(start: str, end: str, seconds: int, now: dt.datetime) -> None:
    a, b = _time(start), _time(end)
    if not a <= now < b or not 0 < (b-a).total_seconds() <= seconds:
        raise ColdRecoveryError("approval window is expired, future, or excessive")

def _safe_file(path: str | Path, *, missing: bool = False) -> Path:
    p = Path(path).expanduser()
    if not p.is_absolute() or p != p.resolve():
        raise ColdRecoveryError("path must be absolute, canonical, and free of symlinks")
    if not p.exists():
        if missing:
            return p
        raise ColdRecoveryError("required file is missing")
    s = p.stat()
    if not p.is_file() or s.st_uid != os.geteuid() or s.st_mode & 0o022:
        raise ColdRecoveryError("file ownership or permissions are unsafe")
    return p

def read_document(path: str | Path) -> dict[str, Any]:
    p = _safe_file(path)
    if p.stat().st_size > 4_194_304:
        raise ColdRecoveryError("document exceeds the cold protocol size limit")
    try:
        value = json.loads(p.read_text())
    except (ValueError, UnicodeError) as exc:
        raise ColdRecoveryError("document is invalid JSON") from exc
    if not isinstance(value, dict):
        raise ColdRecoveryError("document must be an object")
    return value

def _write(path: Path, value: Any, *, exclusive: bool = False) -> None:
    path = _safe_file(path, missing=True)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.parent.stat().st_mode & 0o022:
        raise ColdRecoveryError("journal directory is writable by other users")
    if exclusive:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(canonical(value) + b"\n")
            f.flush()
            os.fsync(f.fileno())
    else:
        fd, temporary = tempfile.mkstemp(prefix=".cold-", dir=path.parent)
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(canonical(value) + b"\n")
                f.flush()
                os.fsync(f.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)

def _signature(payload: Any, signature: str, public_key: str) -> None:
    """Verify Ed25519 with the required local OpenSSL tool, without a shell."""
    try:
        sig = base64.b64decode(signature, validate=True)
    except (ValueError, TypeError) as exc:
        raise ColdRecoveryError("signature encoding is invalid") from exc
    try:
        encoded = "".join(public_key.splitlines()[1:-1])
        der = base64.b64decode(encoded, validate=True)
    except (ValueError, TypeError, AttributeError) as exc:
        raise ColdRecoveryError("Ed25519 public key encoding is invalid") from exc
    if len(sig) != 64 or len(der) != 44 or der[:12] != bytes.fromhex("302a300506032b6570032100") or not public_key.startswith("-----BEGIN PUBLIC KEY-----") or not public_key.rstrip().endswith("-----END PUBLIC KEY-----"):
        raise ColdRecoveryError("Ed25519 signature/public key is invalid")
    with tempfile.TemporaryDirectory(prefix="fabric-cold-signature-") as directory:
        p = Path(directory)
        (p/"public.pem").write_text(public_key)
        (p/"payload").write_bytes(canonical(payload))
        (p/"signature").write_bytes(sig)
        try:
            result = subprocess.run(
                ["openssl", "pkeyutl", "-verify", "-pubin", "-inkey", str(p/"public.pem"),
                 "-rawin", "-in", str(p/"payload"), "-sigfile", str(p/"signature")],
                capture_output=True, timeout=10, check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ColdRecoveryError("local signature verifier is unavailable") from exc
        if result.returncode:
            raise ColdRecoveryError("signature verification failed")

def _signed(envelope: Any, key: str, keys: set[str], label: str) -> dict[str, Any]:
    e = _closed(envelope, {"payload", "signature"}, label)
    payload = _closed(e["payload"], keys, label + " payload")
    _signature(payload, e["signature"], key)
    return payload

def validate_policy(value: Mapping[str, Any], *, require_enabled: bool = True) -> dict[str, Any]:
    p = _closed(dict(value), POLICY_KEYS, "cold policy")
    if p["schemaVersion"] != "execution-fabric-cold-recovery-policy/v1" or type(p["enabled"]) is not bool:
        raise ColdRecoveryError("cold policy schema is invalid")
    if p["enabled"] is not True:
        if require_enabled:
            raise ColdRecoveryError("cold recovery is disabled; provision reviewed trust and actor identities before explicit activation")
        return p
    if not isinstance(p["allowedHosts"], list) or len(p["allowedHosts"]) < 2 or any(not isinstance(h, str) or not re.fullmatch(r"[a-zA-Z0-9._-]{1,128}", h) for h in p["allowedHosts"]) or len(set(p["allowedHosts"])) != len(p["allowedHosts"]):
        raise ColdRecoveryError("cold policy requires distinct declared hosts")
    if type(p["maxApprovalSeconds"]) is not int or not 60 <= p["maxApprovalSeconds"] <= 3600:
        raise ColdRecoveryError("cold approval duration is invalid")
    for key in ("clusterId", "recoveryPublicKeyPem", "fencePublicKeyPem"):
        if not isinstance(p[key], str) or not p[key]:
            raise ColdRecoveryError("cold trust configuration is incomplete")
    for key in ("witnessActorSha256", "controlPlaneActorSha256"):
        if not isinstance(p[key], str) or not HEX.fullmatch(p[key]):
            raise ColdRecoveryError("reviewed offline actor identity is missing")
    return p

def validate_plan(value: Any, policy: Mapping[str, Any], now: dt.datetime, *, check_window: bool = True) -> dict[str, Any]:
    p = _closed(value, PLAN_KEYS, "cold plan")
    if p["schemaVersion"] != "execution-fabric-cold-recovery-plan/v1" or p["direction"] not in {"recovery", "failback"}:
        raise ColdRecoveryError("cold plan schema/direction is invalid")
    try:
        UUID(p["recoveryId"])
    except (ValueError, TypeError, AttributeError) as exc:
        raise ColdRecoveryError("recovery identity is invalid") from exc
    if p["clusterId"] != policy["clusterId"] or p["sourceHost"] == p["targetHost"] or any(p[k] not in policy["allowedHosts"] for k in ("sourceHost", "targetHost")):
        raise ColdRecoveryError("cold plan host or cluster differs from policy")
    if p["policySha256"] != digest(policy):
        raise ColdRecoveryError("cold plan differs from the approved policy")
    for key in PLAN_KEYS:
        if key.endswith("Sha256") or key == "candidateConfigDigest":
            if not isinstance(p[key], str) or not HEX.fullmatch(p[key]):
                raise ColdRecoveryError("cold plan digest is invalid")
    for key in ("expectedEpoch", "nextEpoch", "generation", "snapshotVersion", "timelineId"):
        if type(p[key]) is not int or not 1 <= p[key] <= 9_007_199_254_740_991:
            raise ColdRecoveryError("cold plan counter is invalid")
    if p["nextEpoch"] <= p["expectedEpoch"] or p["oldPublicKeySha256"] == p["newPublicKeySha256"]:
        raise ColdRecoveryError("cold recovery must advance epoch and rotate witness trust")
    if not isinstance(p["newPgSystemId"], str) or not re.fullmatch(r"[0-9]{1,32}", p["newPgSystemId"]) or type(p["walPosition"]) is not int or p["walPosition"] < 0:
        raise ColdRecoveryError("restored PostgreSQL identity is invalid")
    for key in ("originalDatabasePath", "originalBackupPath", "targetDatabasePath"):
        if not isinstance(p[key], str) or not Path(p[key]).is_absolute() or os.path.normpath(p[key]) != p[key]:
            raise ColdRecoveryError("witness binding is not an absolute normalized path")
    c = _closed(p["canary"], {"taskId", "workerId", "taskType", "queue", "namespace", "payload", "payloadSha256"}, "canary")
    try:
        UUID(c["taskId"])
    except (ValueError, TypeError, AttributeError) as exc:
        raise ColdRecoveryError("canary identity is invalid") from exc
    if c["payloadSha256"] != digest(c["payload"]) or not isinstance(c["payload"], dict):
        raise ColdRecoveryError("canary payload binding differs")
    from .execution_fabric_cold_canary import CANARY_TASK_TYPE, CANARY_QUEUE, CANARY_NAMESPACE, validate_canary_payload
    if (c["taskType"], c["queue"], c["namespace"]) != (CANARY_TASK_TYPE, CANARY_QUEUE, CANARY_NAMESPACE):
        raise ColdRecoveryError("cold canary must use the fixed inert task route")
    try:
        validate_canary_payload(c["payload"], recovery_id=p["recoveryId"], cluster_id=p["clusterId"], epoch=p["nextEpoch"], generation=p["generation"])
    except (ValueError, TypeError, AttributeError) as exc:
        raise ColdRecoveryError("cold canary signed payload binding differs") from exc
    if any(not isinstance(c[k], str) or not re.fullmatch(r"[a-zA-Z0-9._-]{1,128}", c[k]) for k in ("workerId", "taskType", "queue", "namespace")):
        raise ColdRecoveryError("canary selector is invalid")
    if check_window:
        _window(p["createdAt"], p["expiresAt"], policy["maxApprovalSeconds"], now)
    return p

def _anchor(value: Any, policy: Mapping[str, Any]) -> dict[str, Any]:
    a = _closed(value, {"schemaVersion", "clusterId", "leader", "generation", "highestEpoch", "publicKeySha256", "pending", "lastReceiptSha256"}, "recovery anchor")
    if a["schemaVersion"] != "execution-fabric-recovery-anchor/v1" or a["clusterId"] != policy["clusterId"] or a["leader"] not in policy["allowedHosts"]:
        raise ColdRecoveryError("recovery anchor identity differs")
    if any(type(a[k]) is not int or not 1 <= a[k] <= 9_007_199_254_740_991 for k in ("generation", "highestEpoch")) or any(not isinstance(a[k], str) or not HEX.fullmatch(a[k]) for k in ("publicKeySha256", "lastReceiptSha256")):
        raise ColdRecoveryError("recovery anchor is incomplete")
    if a["pending"] is not None:
        _closed(a["pending"], {"recoveryId", "planSha256", "generation", "nextEpoch", "targetHost", "phase"}, "anchor reservation")
    return a

def _prepared_binding(plan: dict[str, Any], anchor: dict[str, Any]) -> None:
    if anchor["pending"] is not None or plan["anchorSha256"] != digest(anchor) or plan["sourceHost"] != anchor["leader"] or plan["oldPublicKeySha256"] != anchor["publicKeySha256"] or plan["generation"] != anchor["generation"] + 1 or plan["nextEpoch"] != max(anchor["highestEpoch"], plan["expectedEpoch"]) + 1:
        raise ColdRecoveryError("prepared plan differs from current external authority anchor")

def _journal(value: Any, plan: dict[str, Any], directory: Path) -> dict[str, Any]:
    j = _closed(value, {"ok", "schemaVersion", "recoveryId", "planSha256", "phase", "receipts"}, "recovery journal")
    if j["ok"] is not True or j["schemaVersion"] != "execution-fabric-cold-journal/v1" or j["recoveryId"] != plan["recoveryId"] or j["planSha256"] != digest(plan) or j["phase"] not in PHASES or not isinstance(j["receipts"], list):
        raise ColdRecoveryError("recovery journal identity or phase differs")
    phase = "PREPARED"
    for item in j["receipts"]:
        r = _closed(item, {"phase", "ref", "sha256"}, "immutable receipt reference")
        if r["phase"] not in PHASES or PHASES.index(r["phase"]) not in {PHASES.index(phase), PHASES.index(phase) + 1}:
            raise ColdRecoveryError("recovery journal phase sequence differs")
        path = _safe_file(r["ref"])
        if path.parent != directory or not path.name.startswith(plan["recoveryId"] + "-" + r["phase"] + "-") or digest(read_document(path)) != r["sha256"]:
            raise ColdRecoveryError("immutable recovery receipt differs")
        phase = r["phase"]
    if phase != j["phase"]:
        raise ColdRecoveryError("recovery journal has no immutable phase receipt")
    return j

def _baseline(request: dict[str, Any], policy: dict[str, Any], now: dt.datetime) -> dict[str, Any]:
    keys = {"schemaVersion", "clusterId", "leader", "generation", "highestEpoch", "publicKeySha256", "authorityProofSha256", "issuedAt", "expiresAt"}
    b = _signed(request.get("baseline"), policy["recoveryPublicKeyPem"], keys, "external durable baseline")
    proof = _signed(request.get("authorityProof"), policy["fencePublicKeyPem"], keys, "authority proof")
    if b["schemaVersion"] != "execution-fabric-recovery-baseline/v1" or proof != b or b["clusterId"] != policy["clusterId"] or not isinstance(b["authorityProofSha256"], str) or not HEX.fullmatch(b["authorityProofSha256"]):
        raise ColdRecoveryError("external baseline authority differs")
    _window(b["issuedAt"], b["expiresAt"], policy["maxApprovalSeconds"], now)
    return _anchor({"schemaVersion": "execution-fabric-recovery-anchor/v1", "clusterId": b["clusterId"], "leader": b["leader"], "generation": b["generation"], "highestEpoch": b["highestEpoch"], "publicKeySha256": b["publicKeySha256"], "pending": None, "lastReceiptSha256": digest(request)}, policy)

def _restore_binding(request: dict[str, Any], plan: dict[str, Any]) -> None:
    r = _closed(request.get("restoreInput"), {"schemaVersion", "recoverySetId", "manifestSha256", "restoreReceiptSha256", "sourceRelease", "imageLockSha256", "capturedAt", "commonWatermark", "witness", "postgres", "artifacts", "osAuthority", "custodyReceiptSha256"}, "cold restore input")
    w = _closed(r["witness"], {"clusterId", "version", "leader", "epoch", "auditTailSha256", "databaseSha256", "sentinelSha256", "backupSha256", "hostMarkerSha256", "originalDatabasePath", "originalBackupPath", "signingPublicKeySha256"}, "restored witness")
    if r["schemaVersion"] != "execution-fabric-cold-restore-input/v1" or digest(r) != plan["restoreInputSha256"] or not isinstance(r["commonWatermark"], str) or not r["commonWatermark"] or not isinstance(r["sourceRelease"], str) or not r["sourceRelease"]:
        raise ColdRecoveryError("consistent isolated restore proof is missing or differs")
    try:
        UUID(r["recoverySetId"])
    except (ValueError, TypeError, AttributeError) as exc:
        raise ColdRecoveryError("recovery set identity is invalid") from exc
    _time(r["capturedAt"])
    if not isinstance(w["auditTailSha256"], str) or not HEX.fullmatch(w["auditTailSha256"]):
        raise ColdRecoveryError("restored witness audit closure is missing")
    for field, expected in (("clusterId", plan["clusterId"]), ("leader", plan["sourceHost"]), ("epoch", plan["expectedEpoch"]), ("version", plan["snapshotVersion"]), ("signingPublicKeySha256", plan["oldPublicKeySha256"])):
        if w[field] != expected:
            raise ColdRecoveryError("restored witness identity differs from plan")
    for field in ("databaseSha256", "sentinelSha256", "backupSha256", "hostMarkerSha256", "originalDatabasePath", "originalBackupPath"):
        if w[field] != plan[field]:
            raise ColdRecoveryError("restored witness path or hash differs")
    for field in ("manifestSha256", "restoreReceiptSha256"):
        if r[field] != plan[field]:
            raise ColdRecoveryError("restore manifest binding differs")
    for field in ("imageLockSha256", "custodyReceiptSha256"):
        if not isinstance(r[field], str) or not HEX.fullmatch(r[field]):
            raise ColdRecoveryError("restore custody or release closure is missing")
    pg = _closed(r["postgres"], {"dumpSha256", "restoreReadbackSha256", "systemId", "majorVersion"}, "restored PostgreSQL")
    if pg["systemId"] != plan["newPgSystemId"] or not HEX.fullmatch(pg["dumpSha256"]) or not HEX.fullmatch(pg["restoreReadbackSha256"]) or type(pg["majorVersion"]) is not int:
        raise ColdRecoveryError("restored PostgreSQL readback is incomplete")
    artifacts = _closed(r["artifacts"], {"inventorySha256", "verifiedReferences"}, "restored artifacts")
    authority = _closed(r["osAuthority"], {"snapshotSha256", "immutableReceiptInventorySha256"}, "OS authority")
    if artifacts["verifiedReferences"] is not True or any(not isinstance(v, str) or not HEX.fullmatch(v) for v in (artifacts["inventorySha256"], *authority.values())):
        raise ColdRecoveryError("artifact or immutable OS authority closure is unproved")

FENCE_KEYS = {"schemaVersion", "recoveryId", "clusterId", "sourceHost", "sourceBootId", "durable", "highestGeneration", "highestEpoch", "coveredWriterScopes", "evidenceSha256", "issuedAt", "expiresAt"}
APPROVAL_KEYS = {"schemaVersion", "planSha256", "policySha256", "fenceSha256", "approvedBy", "issuedAt", "expiresAt"}

def _authorization(request: dict[str, Any], plan: dict[str, Any], policy: dict[str, Any], anchor: dict[str, Any], now: dt.datetime) -> None:
    f = _signed(request.get("fence"), policy["fencePublicKeyPem"], FENCE_KEYS, "external fence")
    a = _signed(request.get("approval"), policy["recoveryPublicKeyPem"], APPROVAL_KEYS, "operator approval")
    if f["schemaVersion"] != "execution-fabric-external-fence/v1" or a["schemaVersion"] != "execution-fabric-cold-recovery-approval/v1" or f["durable"] is not True:
        raise ColdRecoveryError("durable external fencing was not proved")
    if any(f[k] != plan[k] for k in ("clusterId", "recoveryId", "sourceHost")) or not f["sourceBootId"] or set(f["coveredWriterScopes"]) != {"witness", "postgres", "producer", "provider"}:
        raise ColdRecoveryError("external fence does not cover this original writer")
    pending = anchor["pending"]
    previous_generation = plan["generation"] - 1
    if f["highestGeneration"] != previous_generation or f["highestEpoch"] != plan["nextEpoch"] - 1:
        raise ColdRecoveryError("fresh external anchor high-watermark differs")
    committed = anchor["generation"] == plan["generation"] and anchor["highestEpoch"] == plan["nextEpoch"] and anchor["leader"] == plan["targetHost"] and anchor["publicKeySha256"] == plan["newPublicKeySha256"]
    original = anchor["leader"] == plan["sourceHost"] and anchor["publicKeySha256"] == plan["oldPublicKeySha256"] and anchor["highestEpoch"] == plan["nextEpoch"] - 1
    reserved = pending is not None and pending == {"recoveryId": plan["recoveryId"], "planSha256": digest(plan), "generation": plan["generation"], "nextEpoch": plan["nextEpoch"], "targetHost": plan["targetHost"], "phase": "ANCHOR_COMMITTED" if committed else "RESERVED"} and anchor["generation"] == plan["generation"]
    if not ((pending is None and ((anchor["generation"] == previous_generation and original and digest(anchor) == plan["anchorSha256"]) or committed)) or (reserved and (original or committed))):
        raise ColdRecoveryError("recovery anchor is stale or rolled back")
    if a["planSha256"] != digest(plan) or a["policySha256"] != digest(policy) or a["fenceSha256"] != digest(request["fence"]) or not a["approvedBy"] or not HEX.fullmatch(f["evidenceSha256"]):
        raise ColdRecoveryError("operator approval does not bind this plan and fence")
    _window(f["issuedAt"], f["expiresAt"], policy["maxApprovalSeconds"], now)
    _window(a["issuedAt"], a["expiresAt"], policy["maxApprovalSeconds"], now)

def _actor(command: Sequence[str], operation: str, policy_file: Path, anchor_file: Path, request: dict[str, Any]) -> dict[str, Any]:
    if not command or any(not isinstance(s, str) or not s for s in command):
        raise ColdRecoveryError("trusted installed actor is unavailable")
    if len(command) not in {2, 4} or not Path(command[0]).is_absolute() or Path(command[0]).name not in {"node", "nodejs"} or not os.access(command[0], os.X_OK) or Path(command[1]).name != "cold-recovery-main.js" or (len(command) == 4 and command[2] != "--database-url-file"):
        raise ColdRecoveryError("offline actor argv is not a supported fixed entrypoint")
    script = _safe_file(command[1])
    policy = read_document(policy_file)
    field = "witnessActorSha256" if len(command) == 2 else "controlPlaneActorSha256"
    if hashlib.sha256(script.read_bytes()).hexdigest() != policy[field]:
        raise ColdRecoveryError("offline actor differs from the reviewed policy")
    try:
        result = subprocess.run([*command, operation, str(policy_file), str(anchor_file)], input=canonical(request), capture_output=True, timeout=60, check=False, env={k: v for k, v in os.environ.items() if k not in {"ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "FABRIC_DATABASE_URL", "DATABASE_URL", "NODE_OPTIONS"}})
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ColdRecoveryError("offline actor unavailable; recovery remains held") from exc
    if result.returncode:
        lines = result.stderr.decode("utf-8", errors="replace").strip().splitlines()
        refusal = lines[-1] if lines else ""
        safe_reason = re.fullmatch(r"cold_recovery_refused:(postgres_[0-9A-Z]{5}|schema|actor_or_authorization)", refusal)
        classification = f" ({safe_reason.group(1)})" if safe_reason else ""
        raise ColdRecoveryError(f"offline {operation} refused{classification}; recovery remains held")
    try:
        value = json.loads(result.stdout)
    except (ValueError, UnicodeError) as exc:
        raise ColdRecoveryError("offline actor produced no verifiable receipt") from exc
    p = request["plan"]
    expected_epoch = p["expectedEpoch"] if operation == "hold" else p["nextEpoch"]
    role = "witness" if len(command) == 2 else "ledger"
    if not isinstance(value, dict) or value.get("schemaVersion") != f"execution-fabric-cold-{role}-receipt/v1" or value.get("recoveryId") != p["recoveryId"] or value.get("planSha256") != digest(p) or value.get("fabricEpoch") != expected_epoch or value.get("generation") != p["generation"] or value.get("held") is not (operation != "accept"):
        raise ColdRecoveryError("offline actor receipt binding differs")
    if role == "ledger" and (value.get("operation") != operation or value.get("residualQuarantine") is not True):
        raise ColdRecoveryError("offline ledger receipt lost its quarantine binding")
    return value

def cold_recovery_operation(action: str, request_file: str | Path, *, policy_file: str | Path, anchor_file: str | Path, journal_dir: str | Path, witness_command: Sequence[str] = (), ledger_command: Sequence[str] = (), dry_run: bool = False) -> dict[str, Any]:
    """Run an explicit offline operation; commands come from trusted installation."""
    if action not in ACTIONS:
        raise ColdRecoveryError("unknown cold recovery action")
    policy_path = _safe_file(policy_file)
    policy = validate_policy(read_document(policy_path), require_enabled=not dry_run and action not in {"inspect", "status"})
    request = read_document(request_file)
    if set(request) - REQUEST_KEYS:
        raise ColdRecoveryError("cold request has unknown fields")
    if request.get("policySha256", digest(policy)) != digest(policy):
        raise ColdRecoveryError("request policy binding differs")
    now = dt.datetime.now(dt.timezone.utc)
    anchor_path = _safe_file(anchor_file, missing=True)
    journal = Path(journal_dir).expanduser()
    if not journal.is_absolute() or journal != journal.resolve() or anchor_path.is_relative_to(journal):
        raise ColdRecoveryError("anchor must be canonical and separately retained outside the recovery journal")
    if not policy["enabled"]:
        return {"ok": True, "schemaVersion": "execution-fabric-cold-plan/v1", "dry_run": True, "held": True, "enabled": False, "action": action, "mutation_allowed": False, "next_action": "Provision exact cluster, independent baseline, trusted signer keys and reviewed actor hashes before enabling cold recovery."}
    if dry_run or action in {"inspect", "status"}:
        if action == "initialize-anchor":
            if anchor_path.exists():
                raise ColdRecoveryError("an existing recovery anchor cannot be initialized again")
            _baseline(request, policy, now)
            return {"ok": True, "schemaVersion": "execution-fabric-cold-plan/v1", "dry_run": True, "action": action, "mutation_allowed": False, "baselineSha256": digest(request)}
        anchor = _anchor(read_document(anchor_path), policy)
        plan = validate_plan(request.get("plan"), policy, now, check_window=action == "prepare")
        _restore_binding(request, plan)
        if action == "prepare":
            _prepared_binding(plan, anchor)
        if action == "status":
            result = _journal(read_document(journal / f'{plan["recoveryId"]}.json'), plan, journal)
            return {"ok": True, **result}
        if action not in {"prepare", "inspect"}:
            _authorization(request, plan, policy, anchor, now)
        return {"ok": True, "schemaVersion": "execution-fabric-cold-plan/v1", "dry_run": True, "held": True, "action": action, "mutation_allowed": False, "recoveryId": plan["recoveryId"], "planSha256": digest(plan), "anchorSha256": digest(anchor), "nextEpoch": plan["nextEpoch"]}
    journal.mkdir(parents=True, exist_ok=True, mode=0o700)
    anchor_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock_path = anchor_path.with_name(anchor_path.name + ".lock")
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    lock_stat = os.fstat(fd)
    if lock_stat.st_uid != os.geteuid() or lock_stat.st_mode & 0o077:
        os.close(fd)
        raise ColdRecoveryError("external anchor lock ownership or permissions are unsafe")
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        os.close(fd)
        raise ColdRecoveryError("another cold recovery coordinator owns this journal") from exc
    try:
        if action == "initialize-anchor":
            if anchor_path.exists():
                raise ColdRecoveryError("anchor bootstrap requires a missing anchor and matching authenticated baseline")
            anchor = _baseline(request, policy, now)
            receipt = {"schemaVersion": "execution-fabric-anchor-initialization/v1", "anchorSha256": digest(anchor), "baselineSha256": digest(request), "initializedAt": now.isoformat()}
            _write(journal / f"anchor-initialization-{uuid4()}.json", receipt, exclusive=True)
            _write(anchor_path, anchor, exclusive=True)
            return {"ok": True, **receipt}
        anchor = _anchor(read_document(anchor_path), policy)
        plan = validate_plan(request.get("plan"), policy, now, check_window=action == "prepare")
        _restore_binding(request, plan)
        operation_path = journal / f'{plan["recoveryId"]}.json'
        plan_hash = digest(plan)
        if action == "inspect":
            return {"schemaVersion": "execution-fabric-cold-inspection/v1", "recoveryId": plan["recoveryId"], "planSha256": plan_hash, "anchorSha256": digest(anchor), "held": True, "sourceHost": plan["sourceHost"], "targetHost": plan["targetHost"], "nextEpoch": plan["nextEpoch"]}
        if action == "prepare":
            _prepared_binding(plan, anchor)
            operation = {"ok": True, "schemaVersion": "execution-fabric-cold-journal/v1", "recoveryId": plan["recoveryId"], "planSha256": plan_hash, "phase": "PREPARED", "receipts": []}
            if operation_path.exists():
                old = _journal(read_document(operation_path), plan, journal)
                if old["planSha256"] != plan_hash:
                    raise ColdRecoveryError("same recovery identity has another plan")
                return old
            _write(operation_path, operation, exclusive=True)
            return operation
        operation = _journal(read_document(operation_path), plan, journal)
        if action == "status":
            return operation
        if operation["phase"] == "ACCEPTED" and action in {"accept", "apply", "resume"}:
            return operation
        if operation["phase"] == "ACCEPTED":
            raise ColdRecoveryError("accepted recovery history is sealed; use a new recovery identity")
        _authorization(request, plan, policy, anchor, now)
        def record(phase: str, receipt: dict[str, Any]) -> None:
            receipt_path = journal / f'{plan["recoveryId"]}-{phase}-{uuid4()}.json'
            _write(receipt_path, receipt, exclusive=True)
            operation["receipts"].append({"phase": phase, "ref": str(receipt_path), "sha256": digest(receipt)})
            operation["phase"] = phase
            _write(operation_path, operation)
        if action == "approve":
            phase = "APPROVED" if operation["phase"] == "PREPARED" else operation["phase"]
            record(phase, {"approvalSha256": digest(request["approval"]), "fenceSha256": digest(request["fence"])})
            return operation
        if action in {"apply", "resume"}:
            if operation["phase"] == "PREPARED":
                raise ColdRecoveryError("plan has not been explicitly approved")
            if operation["phase"] == "APPROVED":
                exact_pending = anchor["pending"] is not None and anchor["pending"]["recoveryId"] == plan["recoveryId"] and anchor["pending"]["planSha256"] == plan_hash and anchor["generation"] == plan["generation"]
                if not exact_pending and (anchor["pending"] is not None or digest(anchor) != plan["anchorSha256"]):
                    raise ColdRecoveryError("another recovery already reserved this anchor")
                anchor["generation"] = plan["generation"]
                anchor["pending"] = {"recoveryId": plan["recoveryId"], "planSha256": plan_hash, "generation": plan["generation"], "nextEpoch": plan["nextEpoch"], "targetHost": plan["targetHost"], "phase": "RESERVED"}
                _write(anchor_path, anchor)
                record("RESERVED", {"anchorSha256": digest(anchor)})
            if operation["phase"] != "ACCEPTED":
                pending = anchor["pending"]
                if pending is not None and (pending["recoveryId"] != plan["recoveryId"] or pending["planSha256"] != plan_hash):
                    raise ColdRecoveryError("anchor reservation differs; recovery stays held")
            steps = [("RESERVED", "LEDGER_HELD", ledger_command, "hold"), ("LEDGER_HELD", "WITNESS_COMMITTED_HELD", witness_command, "commit"), ("WITNESS_COMMITTED_HELD", "LEDGER_COMMITTED_HELD", ledger_command, "commit")]
            for before, after, command, operation_name in steps:
                if operation["phase"] == before:
                    record(after, _actor(command, operation_name, policy_path, anchor_path, request))
            if operation["phase"] == "LEDGER_COMMITTED_HELD":
                receipt = {"recoveryId": plan["recoveryId"], "planSha256": plan_hash, "generation": plan["generation"], "epoch": plan["nextEpoch"]}
                anchor.update({"leader": plan["targetHost"], "highestEpoch": plan["nextEpoch"], "publicKeySha256": plan["newPublicKeySha256"], "lastReceiptSha256": digest(receipt)})
                anchor["pending"]["phase"] = "ANCHOR_COMMITTED"
                _write(anchor_path, anchor)
                record("ANCHOR_COMMITTED", receipt)
            return operation
        if action == "canary":
            if operation["phase"] not in {"ANCHOR_COMMITTED", "CANARY_ADMITTED"}:
                raise ColdRecoveryError("canary requires matching committed held stores")
            record("CANARY_ADMITTED", _actor(ledger_command, "canary", policy_path, anchor_path, request))
            return operation
        if action == "accept":
            if operation["phase"] == "ACCEPTED":
                return operation
            if operation["phase"] != "CANARY_ADMITTED":
                raise ColdRecoveryError("acceptance requires the declared canary")
            receipt = _actor(ledger_command, "accept", policy_path, anchor_path, request)
            anchor["pending"] = None
            anchor["lastReceiptSha256"] = digest(receipt)
            _write(anchor_path, anchor)
            record("ACCEPTED", receipt)
            return operation
        raise ColdRecoveryError("unsupported cold transition")
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)
