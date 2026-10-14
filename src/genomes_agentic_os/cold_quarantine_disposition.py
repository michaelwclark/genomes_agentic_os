"""Signed, exact-item offline disposition; the native actor retains authority.

Static dry-run never certifies a database, owner, provider outcome or live host.
Positive provider reconciliation remains unavailable. Ambiguous effects stay held.
"""
from __future__ import annotations

from pathlib import Path
import os
import re
import tempfile
from typing import Any, Mapping, Sequence
from uuid import UUID

from .cold_recovery import (
    ColdRecoveryError, HEX, _anchor, _closed, _invoke_actor, _safe_file,
    _signature, _time, canonical, digest, read_document, validate_policy,
)

INSPECTION_KEYS = {
    "schemaVersion", "recoveryId", "generation", "fabricEpoch", "clusterId",
    "targetHost", "itemKind", "itemId", "workItemId", "owner", "operator",
    "contextSha256", "policySha256", "issuedAt", "expiresAt",
}
PAYLOAD_KEYS = INSPECTION_KEYS | {
    "pgSystemId", "planSha256", "acceptedReceiptSha256", "acceptedPolicySha256",
    "configFingerprint", "executionPolicySha256", "sourceRelease", "itemSha256",
    "historySha256", "dependencySha256", "workItemSha256", "approvalId",
    "approvalSha256", "disposition", "priorDispositionSha256", "idempotencyKey", "reason",
}
HASH_KEYS = {key for key in PAYLOAD_KEYS if key.endswith("Sha256")} | {"configFingerprint"}
TEXT_KEYS = {"clusterId", "workItemId", "owner", "operator", "sourceRelease", "approvalId"}
STAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})")
RECEIPT_KEYS = {
    "schemaVersion", "requestSha256", "recoveryId", "generation", "fabricEpoch",
    "itemKind", "itemId", "disposition", "released", "beforeSha256", "afterSha256",
    "historySha256", "dependencySha256", "owner", "operator", "contextSha256",
    "workItemSha256", "approvalSha256", "policySha256", "predecessorSha256", "eventId",
    "clusterId", "targetHost", "pgSystemId", "planSha256", "configFingerprint",
    "acceptedReceiptSha256", "executionPolicySha256",
}


def _uuid(value: Any) -> bool:
    try:
        return isinstance(value, str) and str(UUID(value)) == value
    except ValueError:
        return False


def approval_binding(payload: Mapping[str, Any]) -> str:
    """The normal approval metadata binds this hash without a circular row hash."""
    return digest({key: value for key, value in payload.items() if key != "approvalSha256"})


def validate_request(value: Any, policy: Mapping[str, Any], anchor: Mapping[str, Any], *, inspection: bool = False) -> dict[str, Any]:
    request = _closed(value, {"payload", "signature"}, "disposition request")
    p = _closed(request["payload"], INSPECTION_KEYS if inspection else PAYLOAD_KEYS, "disposition payload")
    version = "execution-fabric-cold-disposition-inspection/v1" if inspection else "execution-fabric-cold-disposition/v1"
    if p["schemaVersion"] != version:
        raise ColdRecoveryError("disposition request version differs")
    for key in ("recoveryId", "itemId"):
        if not _uuid(p[key]):
            raise ColdRecoveryError("disposition identity must be a canonical UUID")
    for key in ("generation", "fabricEpoch"):
        if type(p[key]) is not int or not 1 <= p[key] <= 9_007_199_254_740_991:
            raise ColdRecoveryError("disposition counter must be a safe positive integer")
    for key in HASH_KEYS & p.keys():
        if key == "priorDispositionSha256" and p[key] is None:
            continue
        if not isinstance(p[key], str) or not HEX.fullmatch(p[key]):
            raise ColdRecoveryError("disposition digest is invalid")
    for key in TEXT_KEYS & p.keys():
        if not isinstance(p[key], str) or not 1 <= len(p[key]) <= 128:
            raise ColdRecoveryError("disposition identifier is invalid")
    if not isinstance(p["targetHost"], str) or not re.fullmatch(r"[A-Za-z0-9._-]{1,128}", p["targetHost"]) or not isinstance(p["itemKind"], str) or p["itemKind"] not in {"task", "effect"}:
        raise ColdRecoveryError("disposition host or item kind is invalid")
    for key in ("issuedAt", "expiresAt"):
        if not isinstance(p[key], str) or not STAMP.fullmatch(p[key]):
            raise ColdRecoveryError("disposition time must be RFC3339")
    duration = (_time(p["expiresAt"]) - _time(p["issuedAt"])).total_seconds()
    if not 0 < duration <= policy["maxApprovalSeconds"]:
        raise ColdRecoveryError("disposition authorization duration is invalid")
    selected = policy.get("selectiveDisposition")
    if policy.get("enabled") is not True or not isinstance(selected, dict) or selected.get("enabled") is not True:
        raise ColdRecoveryError("selective disposition is disabled")
    if p["policySha256"] != digest(policy) or p["clusterId"] != policy["clusterId"] or p["targetHost"] not in policy["allowedHosts"]:
        raise ColdRecoveryError("disposition current policy binding differs")
    if anchor["pending"] is not None or anchor["leader"] != p["targetHost"] or anchor["clusterId"] != p["clusterId"] or anchor["generation"] != p["generation"] or anchor["highestEpoch"] != p["fabricEpoch"]:
        raise ColdRecoveryError("disposition current accepted anchor differs")
    if not inspection:
        if not isinstance(p["pgSystemId"], str) or not re.fullmatch(r"[0-9]{1,32}", p["pgSystemId"]):
            raise ColdRecoveryError("disposition PostgreSQL identity is invalid")
        if not isinstance(p["idempotencyKey"], str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", p["idempotencyKey"]):
            raise ColdRecoveryError("disposition idempotency key is invalid")
        if p["acceptedPolicySha256"] != selected["acceptedPolicySha256"] or p["sourceRelease"] != selected["sourceRelease"] or p["acceptedReceiptSha256"] != anchor["lastReceiptSha256"]:
            raise ColdRecoveryError("disposition accepted receipt, policy or release differs")
        if not isinstance(p["disposition"], str) or p["disposition"] not in {"hold", "task_cancel", "task_requeue", "effect_delivered", "effect_retry"} or not isinstance(p["reason"], str) or p["reason"] not in {"outcome_unknown", "owner_cancelled", "local_task_reconciled"}:
            raise ColdRecoveryError("disposition or reason is unsupported")
        if (p["itemKind"] == "effect" and p["disposition"] != "hold") or (p["itemKind"] == "task" and p["disposition"] not in {"hold", "task_cancel", "task_requeue"}):
            raise ColdRecoveryError("qualified provider outcome verifier unavailable")
        if p["disposition"] == "task_requeue":
            raise ColdRecoveryError("genuine supported positive requeue admission unavailable")
    if not isinstance(request["signature"], str) or not re.fullmatch(r"[A-Za-z0-9+/]{86}==", request["signature"]):
        raise ColdRecoveryError("disposition signature encoding is invalid")
    _signature(p, request["signature"], policy["recoveryPublicKeyPem"])
    return request


def _receipt(value: Any, payload: dict[str, Any]) -> dict[str, Any]:
    result = _closed(value, {"receipt", "replayed", "held", "inspected"}, "native disposition result")
    if type(result["replayed"]) is not bool or type(result["held"]) is not bool or result["inspected"] is not False:
        raise ColdRecoveryError("native disposition result classification differs")
    receipt = _closed(result["receipt"], RECEIPT_KEYS, "native disposition receipt")
    if receipt["schemaVersion"] != "execution-fabric-cold-disposition-receipt/v1" or receipt["requestSha256"] != digest(payload):
        raise ColdRecoveryError("native disposition immutable request differs")
    for key in ("recoveryId", "generation", "fabricEpoch", "clusterId", "targetHost", "pgSystemId", "planSha256", "configFingerprint", "acceptedReceiptSha256", "executionPolicySha256", "itemKind", "itemId", "disposition", "historySha256", "dependencySha256", "owner", "operator", "contextSha256", "workItemSha256", "approvalSha256", "policySha256"):
        if type(receipt[key]) is not type(payload[key]) or receipt[key] != payload[key]:
            raise ColdRecoveryError("native disposition receipt identity differs")
    released = False
    if receipt["released"] is not released or result["held"] is released or receipt["beforeSha256"] != payload["itemSha256"] or receipt["predecessorSha256"] != payload["priorDispositionSha256"]:
        raise ColdRecoveryError("native disposition eligibility or predecessor differs")
    if not isinstance(receipt["afterSha256"], str) or not HEX.fullmatch(receipt["afterSha256"]) or not _uuid(receipt["eventId"]):
        raise ColdRecoveryError("native disposition actual readback differs")
    return result


def _publish_immutable(output: Path, envelope: dict[str, Any]) -> None:
    """Publish complete bytes atomically without replacing a previous receipt."""
    _safe_file(output, missing=True)
    output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if output.parent.stat().st_uid != os.geteuid() or output.parent.stat().st_mode & 0o077:
        raise ColdRecoveryError("disposition receipt directory must be private")
    fd, temporary = tempfile.mkstemp(prefix=".disposition-", dir=output.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(canonical(envelope) + b"\n")
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, output, follow_symlinks=False)
        except FileExistsError:
            if read_document(output) != envelope:
                raise ColdRecoveryError("immutable local disposition receipt conflicts")
        directory_fd = os.open(output.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        os.unlink(temporary)


def _history(value: Any, inspection: dict[str, Any]) -> None:
    if not isinstance(value, list) or len(value) > 1000:
        raise ColdRecoveryError("native disposition history bound differs")
    predecessors: dict[str, str] = {}
    sequence = 0
    for value_row in value:
        row = _closed(value_row, {"sequence", "recoveryId", "generation", "fabricEpoch", "disposition", "receiptSha256", "predecessorSha256", "eventId"}, "native disposition history entry")
        if not _uuid(row["recoveryId"]) or not _uuid(row["eventId"]) or any(type(row[key]) is not int or not 1 <= row[key] <= 9_007_199_254_740_991 for key in ("sequence", "generation", "fabricEpoch")):
            raise ColdRecoveryError("native disposition history identity differs")
        if row["sequence"] <= sequence or row["generation"] > inspection["generation"] or row["fabricEpoch"] > inspection["fabricEpoch"] or not isinstance(row["disposition"], str) or row["disposition"] not in {"hold", "task_cancel"}:
            raise ColdRecoveryError("native disposition history ordering differs")
        if not isinstance(row["receiptSha256"], str) or not HEX.fullmatch(row["receiptSha256"]) or row["predecessorSha256"] != predecessors.get(row["recoveryId"]):
            raise ColdRecoveryError("native disposition history chain differs")
        predecessors[row["recoveryId"]] = row["receiptSha256"]
        sequence = row["sequence"]
    if inspection["priorDispositionSha256"] != predecessors.get(inspection["recoveryId"]):
        raise ColdRecoveryError("native disposition history current predecessor differs")


def cold_disposition_operation(action: str, request_file: str | Path, *, policy_file: str | Path, anchor_file: str | Path, journal_dir: str | Path, ledger_command: Sequence[str] = (), dry_run: bool = True) -> dict[str, Any]:
    """Invoke the fixed actor; committed proof survives local publication failure."""
    if action not in {"disposition", "inspect-disposition"}:
        raise ColdRecoveryError("unknown selective disposition action")
    policy_path, anchor_path = _safe_file(policy_file), _safe_file(anchor_file)
    journal = Path(journal_dir).expanduser()
    if not journal.is_absolute() or journal != journal.resolve():
        raise ColdRecoveryError("disposition journal must be absolute and canonical")
    if anchor_path.is_relative_to(journal):
        raise ColdRecoveryError("anchor must be separately retained outside the disposition journal")
    policy = validate_policy(read_document(policy_path))
    anchor = _anchor(read_document(anchor_path), policy)
    inspection = action == "inspect-disposition"
    request = validate_request(read_document(request_file), policy, anchor, inspection=inspection)
    payload = request["payload"]
    if dry_run:
        return {"ok": True, "dryRun": True, "staticValidated": True,
                "canonicalAuthorityValidated": False, "databaseValidated": False,
                "held": True, "providerOutcomeVerifier": "unavailable"}
    if len(ledger_command) != 4:
        raise ColdRecoveryError("fixed native control-plane actor required")
    value = _invoke_actor(ledger_command, action, policy_path, anchor_path, request)
    if inspection:
        required = {"schemaVersion", "recoveryId", "generation", "fabricEpoch", "clusterId", "targetHost", "pgSystemId", "planSha256", "acceptedReceiptSha256", "acceptedPolicySha256", "policySha256", "configFingerprint", "executionPolicySha256", "sourceRelease", "itemKind", "itemId", "itemSha256", "historySha256", "dependencySha256", "workItemId", "workItemSha256", "owner", "operator", "contextSha256", "priorDispositionSha256", "routeQualified", "ownerBlocked", "dependencyCounts", "decisionHistory", "providerOutcomeVerifier", "requeueAvailable", "mutationCount"}
        _closed(value, required, "native inspection receipt")
        if value["schemaVersion"] != "execution-fabric-cold-disposition-inspection-receipt/v1" or type(value["mutationCount"]) is not int or value["mutationCount"] != 0 or value["providerOutcomeVerifier"] != "unavailable" or value["requeueAvailable"] is not False or value["routeQualified"] is not False or type(value["ownerBlocked"]) is not bool:
            raise ColdRecoveryError("native inspection proof differs")
        for key in ("recoveryId", "generation", "fabricEpoch", "clusterId", "targetHost", "itemKind", "itemId", "workItemId", "owner", "operator", "contextSha256", "policySha256"):
            if type(value[key]) is not type(payload[key]) or value[key] != payload[key]:
                raise ColdRecoveryError("native inspection identity differs")
        for key in HASH_KEYS & value.keys():
            if key == "priorDispositionSha256" and value[key] is None:
                continue
            if key == "configFingerprint" and value[key] is None and value["routeQualified"] is False:
                continue
            if not isinstance(value[key], str) or not HEX.fullmatch(value[key]):
                raise ColdRecoveryError("native inspection digest differs")
        selected = policy["selectiveDisposition"]
        if value["acceptedReceiptSha256"] != anchor["lastReceiptSha256"] or value["acceptedPolicySha256"] != selected["acceptedPolicySha256"] or value["sourceRelease"] != selected["sourceRelease"] or not isinstance(value["pgSystemId"], str) or not re.fullmatch(r"[0-9]{1,32}", value["pgSystemId"]):
            raise ColdRecoveryError("native inspection accepted identity differs")
        counts = _closed(value["dependencyCounts"], {"attempts", "runs", "effects", "artifacts", "alarms"}, "inspection dependency counts")
        if any(type(count) is not int or not 0 <= count <= 1000 for count in counts.values()):
            raise ColdRecoveryError("native inspection dependency bound differs")
        _history(value["decisionHistory"], value)
        return {"ok": True, "inspection": value, "held": True}
    result = _receipt(value, payload)
    # The filename binds the stable operation, not a mutable timestamp. All first
    # results and native refusals remain intact; exact replay repairs only absence.
    output = journal / "dispositions" / payload["recoveryId"] / (digest({"operation": "cold-disposition:" + payload["idempotencyKey"]}) + ".json")
    envelope = {"schemaVersion": "execution-fabric-cold-disposition-journal/v1",
                "requestSha256": digest(payload), "receiptSha256": digest(result["receipt"]),
                "receipt": result["receipt"]}
    _publish_immutable(output, envelope)
    return {"ok": True, **result, "receiptFile": str(output)}
