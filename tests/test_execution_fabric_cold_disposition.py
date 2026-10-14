"""Offline facade tests; native mocks never count as database qualification."""
from __future__ import annotations

import copy
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
from uuid import uuid4

import jsonschema
import pytest

from genomes_agentic_os import cold_quarantine_disposition as cd
from genomes_agentic_os import cold_recovery as cr
from test_execution_fabric_cold_recovery import packet, write  # noqa: F401


@pytest.fixture
def disposition(packet):
    p = packet
    accepted_policy = cr.digest(p["policy"])
    p["policy"]["selectiveDisposition"] = {
        "enabled": True, "acceptedPolicySha256": accepted_policy,
        "sourceRelease": "0.10.1", "authority": {
            "backend": "sqlite", "databasePath": str(p["root"] / "existing-authority.sqlite"),
            "domain": "isolated", "project": "disposition-test"},
        "executionPolicyFile": str(p["root"] / "execution-policy.yml"),
        "allowedLocalTaskTypes": ["fabric.cold_canary"], "heldProviders": ["claude", "codex"],
    }
    p["anchor"].update(leader="bigmac", generation=8, highestEpoch=13)
    payload = {
        "schemaVersion": "execution-fabric-cold-disposition/v1",
        "recoveryId": p["request"]["plan"]["recoveryId"], "generation": 8, "fabricEpoch": 13,
        "clusterId": p["policy"]["clusterId"], "targetHost": "bigmac", "pgSystemId": "12345",
        "planSha256": "1" * 64, "acceptedReceiptSha256": p["anchor"]["lastReceiptSha256"],
        "acceptedPolicySha256": accepted_policy, "policySha256": cr.digest(p["policy"]),
        "configFingerprint": "2" * 64, "executionPolicySha256": "3" * 64, "sourceRelease": "0.10.1",
        "itemKind": "task", "itemId": str(uuid4()), "itemSha256": "4" * 64,
        "historySha256": "5" * 64, "dependencySha256": "6" * 64,
        "workItemId": "original-work", "workItemSha256": "7" * 64,
        "owner": "original-owner", "operator": "named-operator", "contextSha256": "8" * 64,
        "approvalId": "actual-approval", "approvalSha256": "9" * 64,
        "disposition": "task_cancel", "priorDispositionSha256": None,
        "idempotencyKey": "one-owner-cancellation", "reason": "owner_cancelled",
        "issuedAt": p["stamp"](-1), "expiresAt": p["stamp"](500),
    }

    def save(inspection=False):
        body = {k: v for k, v in payload.items() if k in cd.INSPECTION_KEYS} if inspection else payload
        if inspection:
            body["schemaVersion"] = "execution-fabric-cold-disposition-inspection/v1"
        request = p["signed"](body, 0)
        write(p["paths"]["request_file"], request)
        write(p["paths"]["policy_file"], p["policy"])
        write(p["paths"]["anchor_file"], p["anchor"])
        return request

    def run(inspection=False, **kwargs):
        save(inspection)
        return cd.cold_disposition_operation("inspect-disposition" if inspection else "disposition", **p["paths"], **kwargs)

    return {**p, "payload": payload, "save": save, "run_disposition": run}


def native_result(p):
    payload = p["payload"]
    keys = cd.RECEIPT_KEYS & payload.keys()
    receipt = {k: payload[k] for k in keys}
    receipt.update(schemaVersion="execution-fabric-cold-disposition-receipt/v1",
                   requestSha256=cr.digest(payload), released=False, beforeSha256=payload["itemSha256"],
                   afterSha256="a" * 64, predecessorSha256=payload["priorDispositionSha256"], eventId=str(uuid4()))
    return {"receipt": receipt, "replayed": False, "held": True, "inspected": False}


def inspection_result(p):
    payload = p["payload"]
    result = {k: v for k, v in payload.items() if k not in {"approvalId", "approvalSha256", "disposition", "idempotencyKey", "reason", "issuedAt", "expiresAt"}}
    result.update(schemaVersion="execution-fabric-cold-disposition-inspection-receipt/v1",
                  routeQualified=False, ownerBlocked=False, providerOutcomeVerifier="unavailable",
                  requeueAvailable=False, mutationCount=0,
                  decisionHistory=[],
                  dependencyCounts={k: 1 for k in ("attempts", "runs", "effects", "artifacts", "alarms")})
    return result


def test_default_dry_run_proves_only_signed_structure(disposition, monkeypatch):
    p = disposition
    monkeypatch.setattr(cd, "_invoke_actor", lambda *a: pytest.fail("static dry-run invoked native authority"))
    result = p["run_disposition"]()
    assert result == {"ok": True, "dryRun": True, "staticValidated": True,
                      "canonicalAuthorityValidated": False, "databaseValidated": False,
                      "held": True, "providerOutcomeVerifier": "unavailable"}
    assert not p["paths"]["journal_dir"].exists()
    assert not Path(p["policy"]["selectiveDisposition"]["authority"]["databasePath"]).exists()
    assert p["run_disposition"](inspection=True) == result


@pytest.mark.parametrize("field,value", [
    ("generation", True), ("fabricEpoch", 0), ("generation", 9_007_199_254_740_992),
    ("recoveryId", "not-an-id"), ("itemId", str(uuid4()).upper()),
    ("contextSha256", "a" * 64 + "\n"), ("owner", ""), ("operator", "💥" * 129),
    ("targetHost", "bigmac\n"), ("itemKind", []), ("pgSystemId", "123\n"),
    ("idempotencyKey", "../escape"), ("issuedAt", "2026-10-12"),
    ("expiresAt", "2026-99-99T00:00:00Z"), ("reason", True), ("disposition", "delete"),
])
def test_malformed_request_refuses_before_actor_or_journal(disposition, monkeypatch, field, value):
    disposition["payload"][field] = value
    monkeypatch.setattr(cd, "_invoke_actor", lambda *a: pytest.fail("invalid request invoked native actor"))
    with pytest.raises(cr.ColdRecoveryError):
        disposition["run_disposition"]()
    assert not disposition["paths"]["journal_dir"].exists()


@pytest.mark.parametrize("mutation", ["unknown", "missing", "signature", "policy", "anchor", "release", "receipt", "duration", "disabled"])
def test_signed_authority_and_closed_bindings_refuse(disposition, mutation):
    p = disposition
    request = p["save"]()
    if mutation == "unknown": request["payload"]["approved"] = True
    if mutation == "missing": request["payload"].pop("owner")
    if mutation == "signature": request["signature"] = "A" * 86 + "=="
    if mutation == "policy": p["policy"]["clusterId"] = "different"
    if mutation == "anchor": p["anchor"]["generation"] += 1
    if mutation == "release": request["payload"]["sourceRelease"] = "foreign-release"
    if mutation == "receipt": request["payload"]["acceptedReceiptSha256"] = "f" * 64
    if mutation == "duration": request["payload"]["expiresAt"] = p["stamp"](601)
    if mutation == "disabled": p["policy"]["selectiveDisposition"]["enabled"] = False
    with pytest.raises(cr.ColdRecoveryError):
        cd.validate_request(request, p["policy"], p["anchor"])


@pytest.mark.parametrize("kind,verb", [("effect", "effect_delivered"), ("effect", "effect_retry"), ("task", "effect_retry"), ("task", "task_requeue")])
def test_unqualified_provider_or_positive_requeue_remains_unavailable(disposition, kind, verb):
    p = disposition
    p["payload"].update(itemKind=kind, disposition=verb)
    with pytest.raises(cr.ColdRecoveryError, match="unavailable"):
        p["run_disposition"]()


def test_approval_binding_is_noncircular_and_does_not_accept_identity_boolean(disposition):
    p = disposition["payload"]
    original = cd.approval_binding(p)
    p["approvalSha256"] = "0" * 64
    assert cd.approval_binding(p) == original
    p["owner"] = "new-owner"
    assert cd.approval_binding(p) != original


def test_apply_requires_fixed_native_boundary(disposition):
    with pytest.raises(cr.ColdRecoveryError, match="fixed native"):
        disposition["run_disposition"](dry_run=False)


def test_native_refusal_has_no_local_receipt(disposition, monkeypatch):
    def refused(*a): raise cr.ColdRecoveryError("actual native authority refused")
    monkeypatch.setattr(cd, "_invoke_actor", refused)
    with pytest.raises(cr.ColdRecoveryError, match="native authority"):
        disposition["run_disposition"](dry_run=False, ledger_command=["node", "actor", "--database-url-file", "private"])
    assert not disposition["paths"]["journal_dir"].exists()


@pytest.mark.parametrize("field,value", [("held", False), ("replayed", 1), ("inspected", True), ("released", True), ("generation", True), ("eventId", "invalid"), ("afterSha256", "wrong"), ("owner", "different"), ("predecessorSha256", "f" * 64), ("beforeSha256", "e" * 64)])
def test_native_result_cannot_fabricate_eligibility_or_identity(disposition, field, value):
    result = native_result(disposition)
    target = result if field in result else result["receipt"]
    target[field] = value
    with pytest.raises(cr.ColdRecoveryError): cd._receipt(result, disposition["payload"])


@pytest.mark.parametrize("mutation", ["unknown", "missing", "version", "request"])
def test_native_receipt_closed_immutable_proof(disposition, mutation):
    result = native_result(disposition)
    if mutation == "unknown": result["receipt"]["approved"] = True
    if mutation == "missing": result["receipt"].pop("eventId")
    if mutation == "version": result["receipt"]["schemaVersion"] = "future-version"
    if mutation == "request": result["receipt"]["requestSha256"] = "e" * 64
    with pytest.raises(cr.ColdRecoveryError): cd._receipt(result, disposition["payload"])


def test_committed_proof_publishes_once_and_exact_replay_repairs_only_absence(disposition, monkeypatch):
    result = native_result(disposition)
    monkeypatch.setattr(cd, "_invoke_actor", lambda *a: copy.deepcopy(result))
    kwargs = {"dry_run": False, "ledger_command": ["node", "actor", "--database-url-file", "private"]}
    first = disposition["run_disposition"](**kwargs)
    output = Path(first["receiptFile"])
    assert output.stat().st_mode & 0o077 == 0
    original = output.read_bytes()
    result["replayed"] = True
    replay = disposition["run_disposition"](**kwargs)
    assert replay["replayed"] is True and output.read_bytes() == original
    output.unlink()  # Disposable local publication loss, not native history loss.
    assert disposition["run_disposition"](**kwargs)["replayed"] is True
    assert output.read_bytes() == original
    output.write_text('{"foreign":"immutable"}')
    with pytest.raises(cr.ColdRecoveryError, match="conflicts"):
        disposition["run_disposition"](**kwargs)
    assert output.read_text() == '{"foreign":"immutable"}'


def test_postcommit_publication_failure_keeps_exact_receipt_replay(disposition, monkeypatch):
    """A facade actor seam proves publication recovery, not a PG commit."""
    p = disposition
    p["save"]()
    before = _local_snapshot(p["root"])
    result = native_result(p)
    calls = []

    def committed(*args):
        calls.append(args[1])
        return copy.deepcopy(result)

    original_link = cd.os.link

    def publication_failure(*args, **kwargs):
        raise OSError("injected postcommit local publication failure")

    monkeypatch.setattr(cd, "_invoke_actor", committed)
    monkeypatch.setattr(cd.os, "link", publication_failure)
    kwargs = {**p["paths"], "dry_run": False,
              "ledger_command": ["node", "actor", "--database-url-file", "private"]}
    with pytest.raises(OSError, match="postcommit local publication"):
        cd.cold_disposition_operation("disposition", **kwargs)
    assert calls == ["disposition"]
    output_dir = p["paths"]["journal_dir"] / "dispositions" / p["payload"]["recoveryId"]
    assert list(output_dir.iterdir()) == []
    after_failure = _local_snapshot(p["root"])
    assert all(after_failure[path] == value for path, value in before.items())

    monkeypatch.setattr(cd.os, "link", original_link)
    result["replayed"] = True
    replay = cd.cold_disposition_operation("disposition", **kwargs)
    assert calls == ["disposition", "disposition"] and replay["replayed"] is True
    output = Path(replay["receiptFile"])
    assert list(output_dir.iterdir()) == [output]
    assert output.read_bytes() == cr.canonical({
        "schemaVersion": "execution-fabric-cold-disposition-journal/v1",
        "requestSha256": cr.digest(p["payload"]),
        "receiptSha256": cr.digest(result["receipt"]), "receipt": result["receipt"],
    }) + b"\n"
    assert output.stat().st_mode & 0o077 == 0
    after_replay = _local_snapshot(p["root"])
    assert all(after_replay[path] == value for path, value in before.items())


def test_atomic_publication_crash_and_concurrent_exact_replay(tmp_path, monkeypatch):
    output = tmp_path / "private" / "receipt.json"
    envelope = {"receipt": "complete disposable proof"}
    original_link = cd.os.link
    def crash(*a, **kw): raise OSError("injected pre-publication failure")
    monkeypatch.setattr(cd.os, "link", crash)
    with pytest.raises(OSError): cd._publish_immutable(output, envelope)
    assert not output.exists() and list(output.parent.iterdir()) == []
    monkeypatch.setattr(cd.os, "link", original_link)
    with ThreadPoolExecutor(max_workers=2) as executor:
        for future in [executor.submit(cd._publish_immutable, output, envelope) for _ in range(2)]: future.result()
    assert json.loads(output.read_text()) == envelope
    assert list(output.parent.iterdir()) == [output]


def test_publication_refuses_symlink_or_public_directory(tmp_path):
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    real = private / "real.json"
    real.write_text("original")
    alias = private / "alias.json"
    alias.symlink_to(real)
    with pytest.raises(cr.ColdRecoveryError): cd._publish_immutable(alias, {})
    assert real.read_text() == "original"
    private.chmod(0o755)
    with pytest.raises(cr.ColdRecoveryError, match="private"): cd._publish_immutable(private / "new.json", {})


@pytest.mark.parametrize("field,value", [("mutationCount", True), ("mutationCount", 1), ("requeueAvailable", True), ("routeQualified", 1), ("providerOutcomeVerifier", "generic-proof"), ("acceptedReceiptSha256", "f" * 64), ("acceptedPolicySha256", "f" * 64), ("sourceRelease", "foreign"), ("pgSystemId", 12345), ("contextSha256", "e" * 64), ("dependencyCounts", {"effects": 0})])
def test_inspection_boundary_rejects_false_admission_proof(disposition, monkeypatch, field, value):
    result = inspection_result(disposition)
    result[field] = value
    monkeypatch.setattr(cd, "_invoke_actor", lambda *a: result)
    with pytest.raises(cr.ColdRecoveryError):
        disposition["run_disposition"](inspection=True, dry_run=False, ledger_command=["node", "actor", "--database-url-file", "private"])
    assert not disposition["paths"]["journal_dir"].exists()


def test_actual_inspection_facade_returns_only_references_and_no_journal(disposition, monkeypatch):
    result = inspection_result(disposition)
    monkeypatch.setattr(cd, "_invoke_actor", lambda *a: result)
    assert disposition["run_disposition"](inspection=True, dry_run=False, ledger_command=["node", "actor", "--database-url-file", "private"]) == {"ok": True, "inspection": result, "held": True}
    assert not disposition["paths"]["journal_dir"].exists()


@pytest.mark.parametrize("count", [-1, True, 1001])
def test_actual_inspection_dependency_bounds_are_not_booleans(disposition, monkeypatch, count):
    result = inspection_result(disposition)
    result["dependencyCounts"]["effects"] = count
    monkeypatch.setattr(cd, "_invoke_actor", lambda *a: result)
    with pytest.raises(cr.ColdRecoveryError, match="dependency bound"):
        disposition["run_disposition"](inspection=True, dry_run=False, ledger_command=["node", "actor", "--database-url-file", "private"])


def test_inspection_honestly_reports_unapplied_configuration(disposition, monkeypatch):
    result = inspection_result(disposition)
    result["configFingerprint"] = None
    monkeypatch.setattr(cd, "_invoke_actor", lambda *a: result)
    assert disposition["run_disposition"](inspection=True, dry_run=False, ledger_command=["node", "actor", "--database-url-file", "private"])["inspection"]["routeQualified"] is False
    result["routeQualified"] = True
    with pytest.raises(cr.ColdRecoveryError, match="proof"):
        disposition["run_disposition"](inspection=True, dry_run=False, ledger_command=["node", "actor", "--database-url-file", "private"])


@pytest.mark.parametrize("mutation", ["bound", "type", "identity", "boolean", "future", "sequence", "verb", "hash", "chain", "predecessor"])
def test_inspection_history_is_closed_bounded_ordered_and_current(disposition, mutation):
    result = inspection_result(disposition)
    entry = {"sequence": 1, "recoveryId": result["recoveryId"], "generation": result["generation"],
             "fabricEpoch": result["fabricEpoch"], "disposition": "task_cancel", "receiptSha256": "d" * 64,
             "predecessorSha256": None, "eventId": str(uuid4())}
    result.update(decisionHistory=[entry], priorDispositionSha256=entry["receiptSha256"])
    cd._history(result["decisionHistory"], result)
    if mutation == "bound": result["decisionHistory"] = [entry] * 1001
    if mutation == "type": result["decisionHistory"] = {}
    if mutation == "identity": entry["eventId"] = "invalid"
    if mutation == "boolean": entry["sequence"] = True
    if mutation == "future": entry["generation"] += 1
    if mutation == "sequence": result["decisionHistory"].append(copy.deepcopy(entry))
    if mutation == "verb": entry["disposition"] = "release"
    if mutation == "hash": entry["receiptSha256"] = "invalid"
    if mutation == "chain": entry["predecessorSha256"] = "f" * 64
    if mutation == "predecessor": result["priorDispositionSha256"] = None
    with pytest.raises(cr.ColdRecoveryError): cd._history(result["decisionHistory"], result)


def _local_snapshot(root):
    """Compare local fixture content and modes without recording key bytes."""
    result = {}
    for path in root.rglob("*"):
        mode = path.lstat().st_mode
        value = str(path.readlink()) if path.is_symlink() else (
            hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None)
        result[str(path.relative_to(root))] = (mode, value)
    return result


def test_unknown_action_refuses_before_actor(disposition, monkeypatch):
    p = disposition
    calls = []
    monkeypatch.setattr(cd, "_invoke_actor", lambda *a: calls.append(a))
    before = _local_snapshot(p["root"])
    with pytest.raises(cr.ColdRecoveryError, match="unknown"):
        cd.cold_disposition_operation("delete", **p["paths"])
    assert calls == [] and _local_snapshot(p["root"]) == before


@pytest.mark.parametrize("inspection", [False, True])
@pytest.mark.parametrize("reference", ["relative", "dotdot", "symlink", "contains-anchor", "equals-anchor"])
def test_invalid_journal_reference_refuses_before_actor_or_files(disposition, monkeypatch, inspection, reference):
    p = disposition
    p["save"](inspection)
    original = p["paths"]["journal_dir"]
    if reference == "relative":
        journal = Path("relative-journal")
    elif reference == "dotdot":
        journal = p["root"] / "unused" / ".." / "journal"
    elif reference == "symlink":
        journal = p["root"] / "journal-alias"
        journal.symlink_to(original, target_is_directory=True)
    elif reference == "contains-anchor":
        journal = p["root"]
    else:
        journal = p["paths"]["anchor_file"]
    calls = []
    monkeypatch.setattr(cd, "_invoke_actor", lambda *a: calls.append(a))
    before = _local_snapshot(p["root"])
    kwargs = {**p["paths"], "journal_dir": journal, "dry_run": False,
              "ledger_command": ["node", "actor", "--database-url-file", "private"]}
    with pytest.raises(cr.ColdRecoveryError, match="outside" if "anchor" in reference else "absolute"):
        cd.cold_disposition_operation("inspect-disposition" if inspection else "disposition", **kwargs)
    assert calls == [] and _local_snapshot(p["root"]) == before
    assert not original.exists()


def test_dry_run_validates_journal_reference_without_actor_or_files(disposition, monkeypatch):
    p = disposition
    p["save"]()
    calls = []
    monkeypatch.setattr(cd, "_invoke_actor", lambda *a: calls.append(a))
    before = _local_snapshot(p["root"])
    with pytest.raises(cr.ColdRecoveryError, match="absolute"):
        cd.cold_disposition_operation("disposition", **{**p["paths"], "journal_dir": Path("relative-journal")})
    assert calls == [] and _local_snapshot(p["root"]) == before


def test_request_and_inspection_json_schema_match_closed_structure(disposition):
    schema = json.loads((Path(__file__).parents[1] / "schemas/execution-fabric-cold-disposition.schema.json").read_text())
    jsonschema.validate(disposition["save"](), schema, format_checker=jsonschema.FormatChecker())
    inspection_schema = {**schema, "$ref": "#/$defs/inspectionRequest"}
    jsonschema.validate(disposition["save"](inspection=True), inspection_schema, format_checker=jsonschema.FormatChecker())
    request = disposition["save"]()
    request["payload"]["approved"] = True
    with pytest.raises(jsonschema.ValidationError): jsonschema.validate(request, schema)
