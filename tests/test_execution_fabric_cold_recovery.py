"""Isolated protocol qualification; no host, provider, or runtime is activated."""
import base64
import copy
import datetime as dt
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import shutil
from uuid import uuid4

import jsonschema
import pytest

from genomes_agentic_os import cold_recovery as cr


def write(path, value):
    path.write_bytes(cr.canonical(value))
    path.chmod(0o600)


@pytest.fixture
def packet(tmp_path):
    root = tmp_path.resolve()
    now = dt.datetime.now(dt.timezone.utc)
    stamp = lambda seconds: (now + dt.timedelta(seconds=seconds)).isoformat()
    key_files = []
    public = []
    for name in ("operator", "fence"):
        key = root / (name + ".pem")
        subprocess.run(["openssl", "genpkey", "-algorithm", "ED25519", "-out", str(key)], check=True, capture_output=True)
        key.chmod(0o600)
        key_files.append(key)
        public.append(subprocess.run(["openssl", "pkey", "-in", str(key), "-pubout"], check=True, capture_output=True).stdout.decode())

    def signed(payload, index):
        body, signature = root / "sign-input", root / "signature"
        body.write_bytes(cr.canonical(payload))
        subprocess.run(["openssl", "pkeyutl", "-sign", "-inkey", str(key_files[index]), "-rawin", "-in", str(body), "-out", str(signature)], check=True, capture_output=True)
        return {"payload": payload, "signature": base64.b64encode(signature.read_bytes()).decode()}

    policy = {
        "schemaVersion": "execution-fabric-cold-recovery-policy/v1", "enabled": True,
        "clusterId": "isolated-fabric", "allowedHosts": ["genomesbox", "bigmac"],
        "recoveryPublicKeyPem": public[0], "fencePublicKeyPem": public[1],
        "maxApprovalSeconds": 600, "witnessActorSha256": "a"*64, "controlPlaneActorSha256": "b"*64,
    }
    anchor = {"schemaVersion": "execution-fabric-recovery-anchor/v1", "clusterId": policy["clusterId"], "leader": "genomesbox", "generation": 7, "highestEpoch": 12, "publicKeySha256": "1"*64, "pending": None, "lastReceiptSha256": "c"*64}
    original = str(root / "original.sqlite")
    restored = {
        "schemaVersion": "execution-fabric-cold-restore-input/v1", "recoverySetId": "20261009T230000Z-012345abcdef",
        "manifestSha256": "d"*64, "restoreReceiptSha256": "e"*64, "sourceRelease": "0.10.1",
        "imageLockSha256": "f"*64, "capturedAt": stamp(-20), "commonWatermark": "quiesced-closure-12",
        "witness": {"clusterId": policy["clusterId"], "version": 3, "leader": "genomesbox", "epoch": 10, "auditTailSha256": "a"*64, "databaseSha256": "2"*64, "sentinelSha256": "3"*64, "backupSha256": "4"*64, "hostMarkerSha256": "5"*64, "originalDatabasePath": original, "originalBackupPath": original+".backup", "signingPublicKeySha256": anchor["publicKeySha256"]},
        "postgres": {"dumpSha256": "6"*64, "restoreReadbackSha256": "7"*64, "systemId": "12345", "majorVersion": 17},
        "artifacts": {"inventorySha256": "8"*64, "verifiedReferences": True},
        "osAuthority": {"snapshotSha256": "9"*64, "immutableReceiptInventorySha256": "a"*64},
        "custodyReceiptSha256": "b"*64,
    }
    plan = {
        "schemaVersion": "execution-fabric-cold-recovery-plan/v1", "recoveryId": str(uuid4()), "direction": "recovery",
        "clusterId": policy["clusterId"], "sourceHost": "genomesbox", "targetHost": "bigmac", "expectedEpoch": 10, "nextEpoch": 13, "generation": 8,
        "anchorSha256": cr.digest(anchor), "policySha256": cr.digest(policy), "restoreInputSha256": cr.digest(restored),
        "manifestSha256": restored["manifestSha256"], "restoreReceiptSha256": restored["restoreReceiptSha256"], "snapshotVersion": 3,
        "originalDatabasePath": original, "originalBackupPath": original+".backup", "targetDatabasePath": str(root/"target.sqlite"),
        "databaseSha256": "2"*64, "sentinelSha256": "3"*64, "backupSha256": "4"*64, "hostMarkerSha256": "5"*64,
        "oldPublicKeySha256": anchor["publicKeySha256"], "newPublicKeySha256": "c"*64, "candidateConfigDigest": "d"*64,
        "newPgSystemId": "12345", "timelineId": 1, "walPosition": 0, "createdAt": stamp(-10), "expiresAt": stamp(500),
        "canary": {"taskId": str(uuid4()), "workerId": "isolated-canary", "taskType": "fabric.cold_canary", "queue": "fabric_cold_recovery", "namespace": "fabric_cold_recovery", "payload": {}, "payloadSha256": "0"*64},
    }
    plan["canary"]["payload"] = {"schema_version": "execution-fabric-cold-canary/v1", "recovery_id": plan["recoveryId"], "cluster_id": plan["clusterId"], "epoch": plan["nextEpoch"], "generation": plan["generation"]}
    plan["canary"]["payloadSha256"] = cr.digest(plan["canary"]["payload"])
    fence = signed({"schemaVersion": "execution-fabric-external-fence/v1", "recoveryId": plan["recoveryId"], "clusterId": plan["clusterId"], "sourceHost": plan["sourceHost"], "sourceBootId": "original-boot-proof", "durable": True, "highestGeneration": 7, "highestEpoch": 12, "coveredWriterScopes": ["witness", "postgres", "producer", "provider"], "evidenceSha256": "e"*64, "issuedAt": stamp(-10), "expiresAt": stamp(500)}, 1)
    request = {"plan": plan, "restoreInput": restored, "fence": fence, "approval": signed({"schemaVersion": "execution-fabric-cold-recovery-approval/v1", "planSha256": cr.digest(plan), "policySha256": cr.digest(policy), "fenceSha256": cr.digest(fence), "approvedBy": "isolated-operator", "issuedAt": stamp(-10), "expiresAt": stamp(500)}, 0)}
    paths = {"request_file": root/"request.json", "policy_file": root/"policy.json", "anchor_file": root/"anchor.json", "journal_dir": root/"journal"}
    def save():
        write(paths["request_file"], request)
        write(paths["policy_file"], policy)
    save()
    write(paths["anchor_file"], anchor)
    def run(action, **kw):
        save()
        return cr.cold_recovery_operation(action, **paths, **kw)
    return {"root": root, "request": request, "policy": policy, "anchor": anchor, "paths": paths, "signed": signed, "stamp": stamp, "run": run}


def actor_receipt(request, operation, witness=False):
    p = request["plan"]
    result = {"schemaVersion": "execution-fabric-cold-witness-receipt/v1" if witness else "execution-fabric-cold-ledger-receipt/v1", "recoveryId": p["recoveryId"], "planSha256": cr.digest(p), "fabricEpoch": p["expectedEpoch"] if operation=="hold" else p["nextEpoch"], "generation": p["generation"], "held": operation!="accept"}
    if not witness:
        result.update(operation=operation, residualQuarantine=True)
    return result


def selective_policy(root):
    return {"enabled": True, "acceptedPolicySha256": "a" * 64, "sourceRelease": "0.10.1",
            "authority": {"backend": "sqlite", "databasePath": str(root / "existing.sqlite"), "domain": "isolated", "project": "qualification"},
            "executionPolicyFile": str(root / "execution-policy.yml"),
            "allowedLocalTaskTypes": ["fabric.cold_canary"], "heldProviders": ["claude", "codex"]}


def test_optional_signed_policy_transition_preserves_legacy_plan_digest(packet):
    original = cr.digest(packet["request"]["plan"])
    assert cr.digest(cr.validate_plan(packet["request"]["plan"], packet["policy"], dt.datetime.now(dt.timezone.utc))) == original
    packet["request"]["plan"]["policyTransition"] = {"expectedSourceFingerprint": "a" * 64,
        "candidateExecutionPolicyFile": str(packet["root"] / "candidate-policy.yml"), "candidateExecutionPolicySha256": "b" * 64}
    plan = cr.validate_plan(packet["request"]["plan"], packet["policy"], dt.datetime.now(dt.timezone.utc))
    schema = json.loads((Path(__file__).parents[1] / "schemas/execution-fabric-cold-recovery.schema.json").read_text())
    jsonschema.validate(plan, {**schema, "$ref": "#/$defs/plan"}, format_checker=jsonschema.FormatChecker())
    assert plan["policyTransition"] == packet["request"]["plan"]["policyTransition"] and cr.digest(plan) != original
    # This is structural parity only. Native PolicyManager/source-store tests
    # independently qualify the selected file and actual A-to-B transition.


@pytest.mark.parametrize("field,value", [("expectedSourceFingerprint", "a" * 63), ("expectedSourceFingerprint", True),
    ("expectedSourceFingerprint", "a" * 64 + "\n"), ("candidateExecutionPolicySha256", "b" * 64 + "\n"), ("candidateExecutionPolicyFile", "relative.yml"),
    ("candidateExecutionPolicyFile", "/tmp/../foreign"), ("candidateExecutionPolicyFile", "//foreign/policy"),
    ("candidateExecutionPolicyFile", "/tmp//policy"), ("extra", True)])
def test_optional_signed_policy_transition_closed_python_schema_parity(packet, field, value):
    plan = packet["request"]["plan"]
    plan["policyTransition"] = {"expectedSourceFingerprint": "a" * 64,
        "candidateExecutionPolicyFile": str(packet["root"] / "candidate.yml"), "candidateExecutionPolicySha256": "b" * 64}
    plan["policyTransition"][field] = value
    schema = json.loads((Path(__file__).parents[1] / "schemas/execution-fabric-cold-recovery.schema.json").read_text())
    with pytest.raises(cr.ColdRecoveryError): cr.validate_plan(plan, packet["policy"], dt.datetime.now(dt.timezone.utc))
    with pytest.raises(jsonschema.ValidationError): jsonschema.validate(plan, {**schema, "$ref": "#/$defs/plan"})


@pytest.mark.parametrize("transition", [None, {}, {"approved": True}])
def test_signed_policy_transition_cannot_be_empty_or_caller_approval(packet, transition):
    packet["request"]["plan"]["policyTransition"] = transition
    with pytest.raises(cr.ColdRecoveryError): cr.validate_plan(packet["request"]["plan"], packet["policy"], dt.datetime.now(dt.timezone.utc))


def test_optional_selective_policy_preserves_legacy_digest_and_disabled_defaults(packet):
    original = cr.canonical(packet["policy"])
    assert cr.canonical(cr.validate_policy(packet["policy"])) == original
    schema = json.loads((Path(__file__).parents[1] / "schemas/execution-fabric-cold-recovery.schema.json").read_text())
    policy_schema = {**schema, "$ref": "#/$defs/policy"}
    packet["policy"]["selectiveDisposition"] = selective_policy(packet["root"])
    assert cr.validate_policy(packet["policy"])["selectiveDisposition"]["enabled"] is True
    jsonschema.validate(packet["policy"], policy_schema)
    selection = packet["policy"]["selectiveDisposition"]
    selection.update(enabled=False, acceptedPolicySha256=None, sourceRelease=None, authority=None, executionPolicyFile=None, allowedLocalTaskTypes=[])
    assert cr.validate_policy(packet["policy"])["selectiveDisposition"]["enabled"] is False
    jsonschema.validate(packet["policy"], policy_schema)


@pytest.mark.parametrize("field,value", [("enabled", 1), ("acceptedPolicySha256", "f" * 64 + "\n"), ("sourceRelease", "💥" * 129), ("authority", None), ("executionPolicyFile", None), ("executionPolicyFile", "relative.yml"), ("executionPolicyFile", "/a/../b"), ("executionPolicyFile", "/a//b"), ("executionPolicyFile", "//host/path"), ("allowedLocalTaskTypes", ["fabric.cold_canary", "fabric.cold_canary"]), ("allowedLocalTaskTypes", ["fabric.cold_canary\n"]), ("heldProviders", ["💥"]), ("heldProviders", ["x"] * 33)])
def test_optional_policy_closed_bounds_match_json_schema(packet, field, value):
    policy = packet["policy"]
    policy["selectiveDisposition"] = selective_policy(packet["root"])
    policy["selectiveDisposition"][field] = value
    schema = json.loads((Path(__file__).parents[1] / "schemas/execution-fabric-cold-recovery.schema.json").read_text())
    schema["$ref"] = "#/$defs/policy"
    with pytest.raises(cr.ColdRecoveryError): cr.validate_policy(policy)
    with pytest.raises(jsonschema.ValidationError): jsonschema.validate(policy, schema)


@pytest.mark.parametrize("field,value", [("backend", "postgres"), ("databasePath", None), ("databasePath", "/tmp/./db"), ("domain", ""), ("project", "x" * 129)])
def test_selected_authority_is_closed_existing_sqlite_only(packet, field, value):
    selection = selective_policy(packet["root"])
    selection["authority"][field] = value
    with pytest.raises(cr.ColdRecoveryError): cr.validate_disposition_selection(selection)
    selection = selective_policy(packet["root"])
    selection["authority"]["fallback"] = True
    with pytest.raises(cr.ColdRecoveryError): cr.validate_disposition_selection(selection)


def rebind_set_id(packet, recovery_set_id):
    request = packet["request"]
    request["restoreInput"]["recoverySetId"] = recovery_set_id
    request["plan"]["restoreInputSha256"] = cr.digest(request["restoreInput"])
    request["approval"] = packet["signed"]({**request["approval"]["payload"], "planSha256": cr.digest(request["plan"])}, 0)


@pytest.mark.parametrize("recovery_set_id", ["20261009T230000Z-012345abcdef", "3ebd266b-2f8d-4b85-9e6d-cd908a232eb0", "A", "a_B.c-d", "A" + "x" * 127])
def test_original_manifest_set_id_grammar_is_interoperable(packet, recovery_set_id, monkeypatch):
    rebind_set_id(packet, recovery_set_id)
    schema = json.loads((Path(__file__).parents[1]/"schemas/execution-fabric-cold-recovery.schema.json").read_text())
    jsonschema.validate(packet["request"], schema)
    monkeypatch.setattr(cr, "_actor", lambda *args: pytest.fail("dry-run launched an actor"))
    before = packet["paths"]["anchor_file"].read_bytes()
    assert packet["run"]("prepare", dry_run=True)["ok"] is True
    assert packet["request"]["restoreInput"]["recoverySetId"] == recovery_set_id
    assert packet["paths"]["anchor_file"].read_bytes() == before
    assert not packet["paths"]["journal_dir"].exists()


@pytest.mark.parametrize("recovery_set_id", ["", "../escape", "/absolute", "a/b", "a\\b", ".hidden", "_leading", "-leading", "white space", "a\n", "a\r", "a\u2028", "a\x00", "é", "💥", "A" + "x" * 128, None, 42, True])
def test_unsafe_manifest_set_id_refuses_schema_and_coordinator_before_mutation(packet, recovery_set_id, monkeypatch):
    rebind_set_id(packet, recovery_set_id)
    schema = json.loads((Path(__file__).parents[1]/"schemas/execution-fabric-cold-recovery.schema.json").read_text())
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(packet["request"], schema)
    monkeypatch.setattr(cr, "_actor", lambda *args: pytest.fail("invalid set ID launched an actor"))
    before = packet["paths"]["anchor_file"].read_bytes()
    with pytest.raises(cr.ColdRecoveryError, match="recovery set identity"):
        packet["run"]("prepare", dry_run=True)
    assert packet["paths"]["anchor_file"].read_bytes() == before
    assert not packet["paths"]["journal_dir"].exists()


@pytest.mark.parametrize("field", ["recoveryId", "taskId"])
def test_transition_and_task_ids_remain_uuids(packet, field):
    plan = packet["request"]["plan"]
    if field == "recoveryId":
        plan[field] = "20261009T230000Z-012345abcdef"
    else:
        plan["canary"][field] = "20261009T230000Z-012345abcdef"
    with pytest.raises(cr.ColdRecoveryError, match="identity|task"):
        cr.validate_plan(plan, packet["policy"], dt.datetime.now(dt.timezone.utc))


def test_dry_run_prepares_no_lock_journal_or_actor(packet, monkeypatch):
    monkeypatch.setattr(cr, "_actor", lambda *args: pytest.fail("dry-run launched an actor"))
    original = packet["paths"]["anchor_file"].read_bytes()
    assert packet["run"]("prepare", dry_run=True)["mutation_allowed"] is False
    assert not packet["paths"]["journal_dir"].exists()
    assert not Path(str(packet["paths"]["anchor_file"])+".lock").exists()
    assert packet["paths"]["anchor_file"].read_bytes() == original


def test_disabled_template_inspects_but_refuses_activation(packet):
    packet["policy"].update(enabled=False, recoveryPublicKeyPem=None, fencePublicKeyPem=None, witnessActorSha256=None, controlPlaneActorSha256=None)
    packet["request"].clear()
    assert packet["run"]("inspect")["held"] is True
    with pytest.raises(cr.ColdRecoveryError, match="disabled"):
        packet["run"]("apply")


@pytest.mark.parametrize("field,value", [("generation", 7), ("nextEpoch", 12), ("oldPublicKeySha256", "0"*64), ("anchorSha256", "0"*64)])
def test_prepare_dry_run_refuses_stale_anchor_bindings(packet, field, value):
    packet["request"]["plan"][field] = value
    with pytest.raises(cr.ColdRecoveryError):
        packet["run"]("prepare", dry_run=True)
    assert not packet["paths"]["journal_dir"].exists()


def test_missing_anchor_is_not_epoch_zero_grant(packet):
    packet["paths"]["anchor_file"].unlink()
    with pytest.raises(cr.ColdRecoveryError, match="missing"):
        packet["run"]("prepare", dry_run=True)


def test_schema_closure_and_number_parity(packet):
    schema = json.loads((Path(__file__).parents[1]/"schemas/execution-fabric-cold-recovery.schema.json").read_text())
    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.validate(packet["request"], schema)
    with pytest.raises(cr.ColdRecoveryError, match="safe integers"):
        cr.canonical({"payload": {"cost": 1.1}})
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({**packet["request"], "unknown": True}, schema)


def test_invalid_signature_and_partial_fence_never_reserve(packet):
    packet["run"]("prepare")
    packet["request"]["approval"]["signature"] = base64.b64encode(bytes(64)).decode()
    with pytest.raises(cr.ColdRecoveryError, match="signature"):
        packet["run"]("approve")
    assert cr.read_document(packet["paths"]["anchor_file"])["pending"] is None


@pytest.mark.parametrize("field,value", [("taskType", "llm.claude"), ("queue", "codex"), ("namespace", "ordinary")])
def test_cold_plan_refuses_arbitrary_canary_route(packet, field, value):
    packet["request"]["plan"]["canary"][field] = value
    with pytest.raises(cr.ColdRecoveryError, match="fixed inert"):
        packet["run"]("prepare")
    assert list(packet["paths"]["journal_dir"].glob("*.json")) == []
    assert cr.read_document(packet["paths"]["anchor_file"])["pending"] is None


@pytest.mark.parametrize("extra", [{"command": "never"}, {"epoch": 1}, {"generation": True}])
def test_cold_plan_refuses_unbound_or_effectful_canary_payload(packet, extra):
    canary = packet["request"]["plan"]["canary"]
    canary["payload"].update(extra)
    canary["payloadSha256"] = cr.digest(canary["payload"])
    with pytest.raises(cr.ColdRecoveryError, match="signed payload"):
        packet["run"]("prepare")


def test_forward_resume_and_quarantine_receipts(packet, monkeypatch):
    calls = []
    failed = False
    def actor(command, operation, policy, anchor, request):
        nonlocal failed
        witness = command == ("witness",)
        calls.append(("witness" if witness else "ledger", operation))
        if witness and not failed:
            failed = True
            raise cr.ColdRecoveryError("isolated injected crash before witness commit")
        return actor_receipt(request, operation, witness)
    monkeypatch.setattr(cr, "_actor", actor)
    packet["run"]("prepare")
    packet["run"]("approve")
    commands = {"witness_command": ("witness",), "ledger_command": ("ledger",)}
    with pytest.raises(cr.ColdRecoveryError, match="injected crash"):
        packet["run"]("apply", **commands)
    assert packet["run"]("status")["phase"] == "LEDGER_HELD"
    assert cr.read_document(packet["paths"]["anchor_file"])["pending"]["phase"] == "RESERVED"
    assert packet["run"]("resume", **commands)["phase"] == "ANCHOR_COMMITTED"
    packet["run"]("canary", **commands)
    assert packet["run"]("accept", **commands)["phase"] == "ACCEPTED"
    assert cr.read_document(packet["paths"]["anchor_file"])["pending"] is None
    before = len(calls)
    assert packet["run"]("resume", **commands)["phase"] == "ACCEPTED"
    assert calls[before:] == [("ledger", "accept")]
    assert calls.count(("ledger", "hold")) == 1
    with pytest.raises(cr.ColdRecoveryError, match="sealed"):
        packet["run"]("approve")


@pytest.fixture
def accepted_history(packet, monkeypatch):
    """Sealed facade journal fixture; actor mocks are never live authority."""
    original_actor = cr._actor
    commands = {"witness_command": ("witness",), "ledger_command": ("ledger",)}
    monkeypatch.setattr(cr, "_actor", lambda command, operation, policy, anchor, request: actor_receipt(request, operation, command == ("witness",)))
    for action in ["prepare", "approve", "apply", "canary", "accept"]:
        packet["run"](action, **commands)
    def immutable_bytes():
        return {str(path): path.read_bytes() for path in packet["paths"]["journal_dir"].glob("*.json")} | {"anchor": packet["paths"]["anchor_file"].read_bytes()}
    return packet, commands, immutable_bytes, original_actor


@pytest.mark.parametrize("action", ["accept", "apply", "resume"])
def test_accepted_reuse_requires_current_native_readback_without_rewriting_history(accepted_history, monkeypatch, action):
    packet, commands, snapshot, _ = accepted_history
    before = snapshot()
    calls = []
    def current_actor(command, operation, policy, anchor, request):
        assert command == commands["ledger_command"] and operation == "accept"
        calls.append(operation)
        return actor_receipt(request, operation)
    monkeypatch.setattr(cr, "_actor", current_actor)
    original = packet["run"]("status")
    assert packet["run"](action, **commands) == original
    assert calls == ["accept"] and snapshot() == before


@pytest.mark.parametrize("field,value", [("generation", 9), ("highestEpoch", 14), ("leader", "genomesbox"), ("publicKeySha256", "f" * 64), ("lastReceiptSha256", "f" * 64), ("pending", "new-operation")])
def test_old_accepted_history_refuses_changed_selected_anchor_before_actor(accepted_history, monkeypatch, field, value):
    packet, commands, snapshot, _ = accepted_history
    anchor = cr.read_document(packet["paths"]["anchor_file"])
    if field == "pending":
        value = {"recoveryId": str(uuid4()), "planSha256": "f" * 64, "generation": 8, "nextEpoch": 13, "targetHost": "bigmac", "phase": "ANCHOR_COMMITTED"}
    anchor[field] = value
    write(packet["paths"]["anchor_file"], anchor)
    before = snapshot()
    monkeypatch.setattr(cr, "_actor", lambda *a: pytest.fail("stale selected anchor launched native actor"))
    with pytest.raises(cr.ColdRecoveryError): packet["run"]("resume", **commands)
    assert snapshot() == before
    assert packet["run"]("status")["phase"] == "ACCEPTED"


@pytest.mark.parametrize("case", ["refused", "different", "numeric-shape", "expired", "missing"])
def test_accepted_history_does_not_override_expiry_or_native_refusal(accepted_history, monkeypatch, case):
    packet, commands, snapshot, original_actor = accepted_history
    before = snapshot()
    if case == "refused":
        def actor(*a): raise cr.ColdRecoveryError("current PostgreSQL or selected witness authority differs")
        monkeypatch.setattr(cr, "_actor", actor)
    if case == "different":
        monkeypatch.setattr(cr, "_actor", lambda *a: {**actor_receipt(packet["request"], "accept"), "unexpected": True})
    if case == "numeric-shape":
        monkeypatch.setattr(cr, "_actor", lambda *a: {**actor_receipt(packet["request"], "accept"), "generation": float(packet["request"]["plan"]["generation"])})
    if case == "expired":
        payload = packet["request"]["approval"]["payload"]
        payload.update(issuedAt=packet["stamp"](-100), expiresAt=packet["stamp"](-1))
        packet["request"]["approval"] = packet["signed"](payload, 0)
        monkeypatch.setattr(cr, "_actor", lambda *a: pytest.fail("expired historical authorization launched actor"))
    if case == "missing":
        monkeypatch.setattr(cr, "_actor", original_actor)
        commands["ledger_command"] = ()
    with pytest.raises(cr.ColdRecoveryError): packet["run"]("accept", **commands)
    assert snapshot() == before
    monkeypatch.setattr(cr, "_actor", lambda *a: pytest.fail("historical status launched actor"))
    assert packet["run"]("status")["phase"] == "ACCEPTED"


def test_receipt_tamper_refuses_status(packet):
    packet["run"]("prepare")
    journal = packet["run"]("approve")
    receipt = Path(journal["receipts"][0]["ref"])
    write(receipt, {"approvalSha256": "0"*64, "fenceSha256": "0"*64})
    with pytest.raises(cr.ColdRecoveryError, match="immutable"):
        packet["run"]("status")


def test_journal_cannot_skip_phases(packet):
    packet["run"]("prepare")
    path = packet["paths"]["journal_dir"]/(packet["request"]["plan"]["recoveryId"]+".json")
    journal = cr.read_document(path)
    journal["phase"] = "ACCEPTED"
    write(path, journal)
    with pytest.raises(cr.ColdRecoveryError, match="immutable phase"):
        packet["run"]("status")


def test_same_identity_different_plan_preserves_original(packet):
    first = packet["run"]("prepare")
    packet["request"]["plan"]["candidateConfigDigest"] = "0"*64
    with pytest.raises(cr.ColdRecoveryError, match="identity|phase"):
        packet["run"]("prepare")
    path = packet["paths"]["journal_dir"]/(first["recoveryId"]+".json")
    assert cr.read_document(path) == first


def test_anchor_initialization_needs_two_authenticated_matching_baselines(packet):
    packet["paths"]["anchor_file"].unlink()
    baseline = {"schemaVersion": "execution-fabric-recovery-baseline/v1", "clusterId": packet["policy"]["clusterId"], "leader": "genomesbox", "generation": 7, "highestEpoch": 12, "publicKeySha256": "1"*64, "authorityProofSha256": "f"*64, "issuedAt": packet["stamp"](-10), "expiresAt": packet["stamp"](500)}
    packet["request"].clear()
    packet["request"].update(baseline=packet["signed"](baseline, 0), authorityProof=packet["signed"](baseline, 1))
    assert packet["run"]("initialize-anchor", dry_run=True)["mutation_allowed"] is False
    assert not packet["paths"]["anchor_file"].exists()
    assert packet["run"]("initialize-anchor")["ok"] is True
    assert cr.read_document(packet["paths"]["anchor_file"])["highestEpoch"] == 12
    with pytest.raises(cr.ColdRecoveryError, match="missing anchor"):
        packet["run"]("initialize-anchor")


def test_actor_identity_and_receipt_are_verified_without_shell(packet, monkeypatch):
    script = packet["root"]/"cold-recovery-main.js"
    script.write_text("// isolated fixture")
    script.chmod(0o600)
    packet["policy"]["witnessActorSha256"] = hashlib.sha256(script.read_bytes()).hexdigest()
    write(packet["paths"]["policy_file"], packet["policy"])
    monkeypatch.setattr(cr.subprocess, "run", lambda *a, **kw: subprocess.CompletedProcess(a, 0, cr.canonical({"recoveryId": packet["request"]["plan"]["recoveryId"], "planSha256": cr.digest(packet["request"]["plan"])}), b""))
    with pytest.raises(cr.ColdRecoveryError, match="receipt"):
        cr._actor((shutil.which("node"), str(script)), "commit", packet["paths"]["policy_file"], packet["paths"]["anchor_file"], packet["request"])
    script.write_text("// modified")
    with pytest.raises(cr.ColdRecoveryError, match="reviewed"):
        cr._actor((shutil.which("node"), str(script)), "commit", packet["paths"]["policy_file"], packet["paths"]["anchor_file"], packet["request"])


def test_actor_refusal_preserves_only_closed_nonsecret_classification(packet, monkeypatch):
    script = packet["root"] / "cold-recovery-main.js"
    script.write_text("// isolated fixture")
    script.chmod(0o600)
    packet["policy"]["witnessActorSha256"] = hashlib.sha256(script.read_bytes()).hexdigest()
    write(packet["paths"]["policy_file"], packet["policy"])
    secret = b"untrusted message with fixture-password-never-print"
    monkeypatch.setattr(cr.subprocess, "run", lambda *args, **kw: subprocess.CompletedProcess(args, 1, b"", secret + b"\ncold_recovery_refused:postgres_42P18\n"))
    with pytest.raises(cr.ColdRecoveryError, match="postgres_42P18") as error:
        cr._actor((shutil.which("node"), str(script)), "commit", packet["paths"]["policy_file"], packet["paths"]["anchor_file"], packet["request"])
    assert "fixture-password" not in str(error.value)


def mock_metadata_output(runner, child, recovery_id):
    """Typed output parser fixture only; never a native authority/PG proof."""
    meta = copy.deepcopy(runner.METADATA_FACTS)
    task, sibling = str(uuid4()), str(uuid4())
    source_policy = {"schema_version": 1, "execution_fabric": {"queues": [{"id": "fabric_cold_recovery", "enabled": False}],
        "worker_pools": [{"id": "fabric_cold_recovery_workers", "enabled": False}]}}
    candidate_policy = copy.deepcopy(source_policy)
    candidate_policy["execution_fabric"]["queues"][0]["enabled"] = True
    candidate_policy["execution_fabric"]["worker_pools"][0]["enabled"] = True
    for name, policy, key in [("SOURCE-EXECUTION-POLICY.yml", source_policy, "source"), ("CANDIDATE-EXECUTION-POLICY.yml", candidate_policy, "candidate")]:
        runner.document(child / name, policy)
        meta[key + "ExecutionPolicy"] = name
        meta[key + "ExecutionPolicySha256"] = hashlib.sha256((child / name).read_bytes()).hexdigest()
    source_fingerprint, candidate_fingerprint = cr.digest(source_policy), cr.digest(candidate_policy)
    plan = {key: "a" * 64 for key in cr.PLAN_KEYS if key.endswith("Sha256")}
    canary_payload = {"schema_version": "execution-fabric-cold-canary/v1", "recovery_id": recovery_id, "cluster_id": "isolated-fabric", "epoch": 7, "generation": 3}
    plan.update(schemaVersion="execution-fabric-cold-recovery-plan/v1", recoveryId=recovery_id, direction="recovery", clusterId="isolated-fabric",
        sourceHost="genomesbox", targetHost="bigmac", expectedEpoch=4, nextEpoch=7, generation=3, snapshotVersion=1,
        originalDatabasePath=str(child / "original.sqlite"), originalBackupPath=str(child / "original.sqlite.backup"), targetDatabasePath=str(child / "target.sqlite"),
        oldPublicKeySha256="b" * 64, newPublicKeySha256="c" * 64, candidateConfigDigest=candidate_fingerprint,
        newPgSystemId="12345", timelineId=1, walPosition=0, createdAt="2026-10-12T00:00:00Z", expiresAt="2026-10-12T00:05:00Z",
        canary={"taskId": str(uuid4()), "workerId": "isolated-canary", "taskType": "fabric.cold_canary", "queue": "fabric_cold_recovery", "namespace": "fabric_cold_recovery", "payload": canary_payload, "payloadSha256": cr.digest(canary_payload)},
        policyTransition={"expectedSourceFingerprint": source_fingerprint, "candidateExecutionPolicyFile": str(child / "CANDIDATE-EXECUTION-POLICY.yml"), "candidateExecutionPolicySha256": meta["candidateExecutionPolicySha256"]})
    meta.update(schemaVersion="execution-fabric-isolated-metadata-disposition-qualification/v1",
                canonicalProducers=runner.CANONICAL_PRODUCERS, originalTaskId=task, foreignSiblingTaskId=sibling,
                contextSha256="a" * 64, legacy016RowsSha256="b" * 64)
    for name, key in [("ORIGINAL-ASSOCIATION.json", "originalAssociationProofSha256"), ("ORIGINAL-CONTEXT.json", "originalContextReceiptSha256")]:
        runner.document(child / name, {"mockOutputParserFixture": True, "task": {"id": task, "config_fingerprint": source_fingerprint}})
        meta[key] = hashlib.sha256((child / name).read_bytes()).hexdigest()
    inspection = {key: "a" * 64 for key in ["planSha256", "acceptedReceiptSha256", "acceptedPolicySha256", "policySha256", "configFingerprint", "executionPolicySha256", "itemSha256", "historySha256", "dependencySha256", "workItemSha256", "contextSha256"]}
    inspection.update(schemaVersion="execution-fabric-cold-disposition-inspection-receipt/v1", recoveryId=recovery_id,
        generation=3, fabricEpoch=7, clusterId="isolated-fabric", targetHost="bigmac", pgSystemId="12345", sourceRelease="0.10.1",
        itemKind="task", itemId=task, workItemId=meta["originalWorkItemId"], owner=meta["owner"], operator=meta["operator"],
        priorDispositionSha256=None, routeQualified=False, ownerBlocked=False, decisionHistory=[], requeueAvailable=False,
        providerOutcomeVerifier="unavailable", mutationCount=0, dependencyCounts={k: 1 for k in ["attempts", "runs", "effects", "artifacts", "alarms"]})
    inspection.update(planSha256=cr.digest(plan), configFingerprint=candidate_fingerprint)
    accepted = {"schemaVersion": "execution-fabric-cold-ledger-receipt/v1", "operation": "accept", "recoveryId": recovery_id,
        "planSha256": inspection["planSha256"], "fabricEpoch": 7, "generation": 3, "held": False, "residualQuarantine": True}
    inspection["acceptedReceiptSha256"] = cr.digest(accepted)
    meta.update(coldLedgerAcceptedReceipt=accepted, coldLedgerAcceptedReceiptSha256=cr.digest(accepted))
    anchor = {"schemaVersion": "execution-fabric-recovery-anchor/v1", "clusterId": inspection["clusterId"], "leader": inspection["targetHost"],
        "generation": 3, "highestEpoch": 7, "publicKeySha256": plan["newPublicKeySha256"], "lastReceiptSha256": cr.digest(accepted), "pending": None}
    phases = ["APPROVED", "RESERVED", "LEDGER_HELD", "WITNESS_COMMITTED_HELD", "LEDGER_COMMITTED_HELD", "ANCHOR_COMMITTED", "CANARY_ADMITTED", "ACCEPTED"]
    journal = {"ok": True, "schemaVersion": "execution-fabric-cold-journal/v1", "recoveryId": recovery_id,
        "planSha256": inspection["planSha256"], "phase": "ACCEPTED", "receipts": [{"phase": phase,
            "ref": str(child / (recovery_id + "-" + phase + "-" + str(uuid4()) + ".json")),
            "sha256": cr.digest(accepted) if phase == "ACCEPTED" else "e" * 64} for phase in phases]}
    for name, value, key in [("ACCEPTED-ANCHOR.json", anchor, "unchangedAcceptedAnchorSha256"),
            ("ACCEPTED-COLD-JOURNAL.json", journal, "unchangedColdRecoveryJournalSha256")]:
        runner.document(child / name, value)
        meta[key] = hashlib.sha256((child / name).read_bytes()).hexdigest()
    def pg_observation(epoch, leader, fingerprint, held_id, generation, phase):
        return {"current_epoch": epoch, "leader_host_id": leader, "policy_fingerprint": fingerprint,
            "cold_recovery_id": held_id, "cold_recovery_generation": generation, "cold_recovery_phase": phase}
    witness_receipt = {"schemaVersion": "execution-fabric-cold-witness-receipt/v1", "recoveryId": recovery_id,
        "planSha256": cr.digest(plan), "previousLeader": "genomesbox", "currentLeader": "bigmac", "fabricEpoch": 7, "generation": 3,
        "originalDatabasePath": plan["originalDatabasePath"], "targetDatabasePath": plan["targetDatabasePath"], "newPublicKeySha256": plan["newPublicKeySha256"], "committedAt": "2026-10-12T00:00:01Z", "held": True}
    policy_proof = {"schemaVersion": "execution-fabric-isolated-policy-transition-proof/v1", "plan": plan,
        "source": {"file": meta["sourceExecutionPolicy"], "rawSha256": meta["sourceExecutionPolicySha256"], "appliedFingerprint": source_fingerprint, "effectivePolicy": source_policy, "state": "applied", "canaryEnabled": False},
        "candidate": {"file": meta["candidateExecutionPolicy"], "rawSha256": meta["candidateExecutionPolicySha256"], "appliedFingerprint": candidate_fingerprint, "effectivePolicy": candidate_policy, "state": "applied", "canaryEnabled": True},
        "postgresBeforeHold": pg_observation(4, "genomesbox", source_fingerprint, None, 0, None),
        "postgresAfterHold": pg_observation(4, "genomesbox", source_fingerprint, recovery_id, 3, "LEDGER_HELD"),
        "postgresAfterCommit": pg_observation(7, "bigmac", candidate_fingerprint, recovery_id, 3, "LEDGER_COMMITTED_HELD"),
        "witnessSource": {"state": {"currentLeader": "genomesbox", "fabricEpoch": 4, "configDigest": source_fingerprint, "upstreamSystemId": None}, "version": 1},
        "witnessTarget": {"state": {"currentLeader": "bigmac", "fabricEpoch": 7, "configDigest": candidate_fingerprint, "upstreamSystemId": "12345"}, "version": 2, "receipt": witness_receipt},
        "originalTaskConfigFingerprint": source_fingerprint, "foreignSiblingConfigFingerprint": source_fingerprint, "acceptedPolicyFingerprint": candidate_fingerprint,
        "scope": "native disposable supported A initial activation and signed A-to-B cold transition; not a live or installed host transition"}
    runner.document(child / "POLICY-TRANSITION-PROOF.json", policy_proof)
    meta.update(policyTransitionProof="POLICY-TRANSITION-PROOF.json", policyTransitionProofSha256=hashlib.sha256((child / "POLICY-TRANSITION-PROOF.json").read_bytes()).hexdigest())
    meta.update(inspection=inspection, inspectionSha256=cr.digest(inspection))
    previous = None
    histories = []
    for sequence, name, event_key, kind, verb in [(1, "cancellation", "cancellationEventSha256", "task", "task_cancel"),
            (2, "reaffirmedCancellation", "reaffirmationEventSha256", "task", "task_cancel"), (3, "effectHold", "effectHoldEventSha256", "effect", "hold")]:
        keys = ["recoveryId", "generation", "fabricEpoch", "clusterId", "targetHost", "pgSystemId", "planSha256", "configFingerprint",
            "acceptedReceiptSha256", "executionPolicySha256", "itemKind", "itemId", "historySha256", "dependencySha256", "owner", "operator", "contextSha256", "workItemSha256", "policySha256"]
        receipt = {key: inspection[key] for key in keys}
        receipt.update(schemaVersion="execution-fabric-cold-disposition-receipt/v1", requestSha256="c" * 64,
            itemKind=kind, itemId=task if kind == "task" else str(uuid4()), disposition=verb, released=False,
            beforeSha256=previous["afterSha256"] if previous and kind == "task" else inspection["itemSha256"],
            afterSha256=str(sequence) * 64, approvalSha256="d" * 64,
            predecessorSha256=meta["cancellationSha256"] if name == "reaffirmedCancellation" else None, eventId=str(uuid4()))
        meta[name] = receipt
        meta[name + "Sha256"] = cr.digest(receipt)
        meta[event_key] = cr.digest(receipt)
        histories.append({"sequence": sequence, "recoveryId": recovery_id, "generation": 3, "fabricEpoch": 7,
            "disposition": verb, "receiptSha256": cr.digest(receipt), "predecessorSha256": receipt["predecessorSha256"], "eventId": receipt["eventId"]})
        if kind == "task": previous = receipt
    meta.update(taskDecisionHistory=histories[:2], effectDecisionHistory=histories[2:])
    return meta


@pytest.fixture
def disposable_runner(tmp_path, monkeypatch):
    """Exercise fixture admission/teardown without invoking Docker or providers."""
    script = Path(__file__).resolve().parent / "scripts/run-fabric-cold-recovery.py"
    spec = importlib.util.spec_from_file_location("fabric_cold_runner", script)
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    # Deliberately mocked output observations only. Genuine native qualification
    # uses the actual source-bound PolicyManager and real private A/B sidecars.
    def observed_policies(source_file, candidate_file):
        return [{"effectivePolicy": json.loads(file.read_text()), "appliedFingerprint": cr.digest(json.loads(file.read_text())), "state": "applied"}
            for file in (source_file, candidate_file)]
    monkeypatch.setattr(runner, "observe_execution_policies", observed_policies)
    source = tmp_path.resolve() / "source"
    output = tmp_path.resolve() / "output"
    source.mkdir(mode=0o700)
    output.mkdir(mode=0o700)
    for relative in ("pyproject.toml", runner.CONTROL + "/package.json", runner.WITNESS + "/package.json",
                     runner.CONTROL + "/dist/src/cold-recovery-main.js", runner.WITNESS + "/dist/src/cold-recovery-main.js", ".venv/bin/python"):
        path = source / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("fixture")
        path.chmod(0o700 if relative.endswith("bin/python") else 0o600)
    token = "a" * 32
    monkeypatch.setattr(runner, "uuid4", lambda: type("Uuid", (), {"hex": token})())
    calls = []
    cid, image_id = "c" * 64, "sha256:" + "b" * 64
    container = {"Id": cid, "Name": "/fabric-cold-test-" + token, "Image": image_id,
                 "Config": {"Labels": {runner.LABEL: token}}, "Mounts": [],
                 "HostConfig": {"RestartPolicy": {"Name": "no"}, "Binds": None, "Memory": 512 * 1024 * 1024, "NanoCpus": 1_000_000_000},
                 "NetworkSettings": {"Ports": {"5432/tcp": [{"HostIp": "127.0.0.1", "HostPort": "54321"}]}}}
    def command(argv, timeout=30):
        calls.append(argv)
        if argv[:3] == ["docker", "image", "inspect"]:
            value = {"Id": image_id, "RepoDigests": [runner.IMAGE]}
        elif argv[:2] == ["docker", "run"]:
            return subprocess.CompletedProcess(argv, 0, cid + "\n", "")
        elif argv[:2] == ["docker", "inspect"]:
            value = container
        elif argv[:2] == ["docker", "exec"] or argv[:2] == ["docker", "rm"] or argv[:3] == ["docker", "container", "ls"]:
            return subprocess.CompletedProcess(argv, 0, "", "")
        else:
            raise AssertionError("unexpected fixture command")
        return subprocess.CompletedProcess(argv, 0, json.dumps(value), "")
    monkeypatch.setattr(runner, "command", command)
    def run_tests(root, child, url_file, password):
        assert url_file.stat().st_mode & 0o077 == 0
        recovery_id = str(uuid4())
        metadata = mock_metadata_output(runner, child, recovery_id)
        runner.document(child / "DATABASE-QUALIFICATION.json", {
            "schemaVersion": "execution-fabric-isolated-cold-qualification/v1", "databaseName": "fabric_cold_test_" + token,
            "accepted": True, "epoch": 7, "generation": 3, "providerOrObjectCalls": 0,
            "canaryHandler": "fabric_cold_canary_v1", "canaryExecutor": "execute_assignment", "canaryResultVerified": True,
            "quarantine": {"tasks": 2, "effects": 1, "alarms": 1, "artifacts": 1}, "migrationVersions": ["016_cold_recovery.sql", "017_cold_quarantine_dispositions.sql"],
            "recoveryId": recovery_id, "canaryTaskId": str(uuid4()), "metadataDisposition": metadata})
        return 0
    monkeypatch.setattr(runner, "run_tests", run_tests)
    args = ["--source-root", str(source), "--output-parent", str(output)]
    child = output / ("fabric-cold-recovery-" + token)
    return runner, args, child, calls, container


def test_disposable_runner_refuses_unsafe_output_before_docker(disposable_runner):
    runner, args, child, calls, _ = disposable_runner
    child.parent.chmod(0o777)
    assert runner.main(args) == 2
    assert calls == [] and not child.exists()


def test_disposable_runner_refuses_symlink_and_collision(disposable_runner):
    runner, args, child, calls, _ = disposable_runner
    link = child.parent.parent / "linked-output"
    link.symlink_to(child.parent, target_is_directory=True)
    assert runner.main(args[:-1] + [str(link)]) == 2
    child.mkdir(mode=0o700)
    marker = child / "foreign.txt"
    marker.write_text("preserve")
    assert runner.main(args) == 2
    assert marker.read_text() == "preserve" and calls == []


def test_disposable_runner_unavailable_image_is_failure_not_skip(disposable_runner, monkeypatch):
    runner, args, child, calls, _ = disposable_runner
    def unavailable(argv, timeout=30):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 1, "", "image unavailable")
    monkeypatch.setattr(runner, "command", unavailable)
    assert runner.main(args) == 3
    receipt = json.loads((child / "RUN-RECEIPT.json").read_text())
    assert receipt["status"] == "image_unavailable"
    assert receipt["database_tests_executed"] is False and receipt["teardown_verified"] is True
    assert len(calls) == 1 and calls[0][:3] == ["docker", "image", "inspect"]
    assert not any("pull" in call for call in calls)


def test_disposable_runner_requires_actual_application_receipt(disposable_runner, monkeypatch):
    runner, args, child, calls, _ = disposable_runner
    monkeypatch.setattr(runner, "run_tests", lambda *args: 0)
    assert runner.main(args) == 3
    receipt = json.loads((child / "RUN-RECEIPT.json").read_text())
    assert receipt["application_acceptance_verified"] is False and receipt["teardown_verified"] is True
    assert any(call[:2] == ["docker", "rm"] for call in calls)
    assert not (child / "container-test.env").exists() and not (child / "database-url.private").exists()


@pytest.mark.parametrize("mutation", ["missing", "unknown", "boolean", "sibling", "proof-bytes", "inspection", "event", "release", "accepted-generation", "before", "chain", "history",
    "accept-missing", "accept-extra", "accept-identity", "accept-boolean", "accept-digest", "replay-boolean", "privacy-boolean",
    "anchor-bytes", "anchor-missing", "anchor-symlink", "anchor-mode", "anchor-identity", "anchor-receipt", "anchor-pending",
    "journal-bytes", "journal-identity", "journal-phase", "journal-receipt", "journal-sequence",
    "policy-missing", "policy-name", "policy-bytes", "policy-loaded", "policy-source-pg", "policy-held-pg", "policy-committed-pg",
    "policy-source-witness", "policy-target-witness", "policy-target-receipt", "policy-original", "policy-plan", "policy-boolean"])
def test_disposable_parser_cannot_promote_partial_or_fabricated_shape(disposable_runner, tmp_path, mutation):
    runner, _, _, _, _ = disposable_runner
    directory = tmp_path / "typed-output-unit"
    directory.mkdir(mode=0o700)
    recovery_id = str(uuid4())
    meta = mock_metadata_output(runner, directory, recovery_id)
    data = {"recoveryId": recovery_id, "metadataDisposition": meta}
    assert runner.metadata_disposition_accepted(directory, data) is meta
    if mutation == "missing": data.pop("metadataDisposition")
    if mutation == "unknown": meta["approved"] = True
    if mutation == "boolean": meta["foreignSiblingUnchanged"] = 1
    if mutation == "sibling": meta["foreignSiblingTaskId"] = meta["originalTaskId"]
    if mutation == "proof-bytes": (directory / "ORIGINAL-CONTEXT.json").write_text("changed")
    if mutation == "inspection": meta["inspection"]["generation"] = 4
    if mutation == "event": meta["cancellationEventSha256"] = "f" * 64
    if mutation == "release": meta["effectHold"]["released"] = True
    if mutation == "accepted-generation": meta["cancellation"]["generation"] = 4
    if mutation == "before": meta["cancellation"]["beforeSha256"] = "f" * 64
    if mutation == "chain": meta["reaffirmedCancellation"]["predecessorSha256"] = None
    if mutation == "history": meta["taskDecisionHistory"][1]["sequence"] = True
    if mutation == "accept-missing": meta.pop("coldLedgerAcceptedReceipt")
    if mutation == "accept-extra": meta["coldLedgerAcceptedReceipt"]["approved"] = True
    if mutation == "accept-identity": meta["coldLedgerAcceptedReceipt"]["recoveryId"] = str(uuid4())
    if mutation == "accept-boolean": meta["coldLedgerAcceptedReceipt"]["held"] = 0
    if mutation == "accept-digest": meta["coldLedgerAcceptedReceiptSha256"] = "f" * 64
    if mutation == "replay-boolean": meta["sameGenerationColdLedgerReplayVerified"] = 1
    if mutation == "privacy-boolean": meta["authorityPrivacyPreservesRows"] = 1
    anchor_file, journal_file = directory / "ACCEPTED-ANCHOR.json", directory / "ACCEPTED-COLD-JOURNAL.json"
    if mutation == "anchor-bytes": anchor_file.write_text("changed")
    if mutation == "anchor-missing": anchor_file.unlink()
    if mutation == "anchor-symlink":
        relocated = directory / "relocated-anchor.json"
        anchor_file.rename(relocated); anchor_file.symlink_to(relocated)
    if mutation == "anchor-mode": anchor_file.chmod(0o644)
    if mutation in {"anchor-identity", "anchor-receipt", "anchor-pending"}:
        anchor = json.loads(anchor_file.read_text())
        anchor[{"anchor-identity": "highestEpoch", "anchor-receipt": "lastReceiptSha256", "anchor-pending": "pending"}[mutation]] = {"anchor-identity": 8, "anchor-receipt": "f" * 64, "anchor-pending": {"phase": "RESERVED"}}[mutation]
        write(anchor_file, anchor)
        meta["unchangedAcceptedAnchorSha256"] = hashlib.sha256(anchor_file.read_bytes()).hexdigest()
    if mutation == "journal-bytes": journal_file.write_text("changed")
    if mutation in {"journal-identity", "journal-phase", "journal-receipt", "journal-sequence"}:
        journal = json.loads(journal_file.read_text())
        if mutation == "journal-identity": journal["recoveryId"] = str(uuid4())
        if mutation == "journal-phase": journal["phase"] = "CANARY_ADMITTED"
        if mutation == "journal-receipt": journal["receipts"][-1]["sha256"] = "f" * 64
        if mutation == "journal-sequence": journal["receipts"][0]["phase"] = "RESERVED"
        write(journal_file, journal)
        meta["unchangedColdRecoveryJournalSha256"] = hashlib.sha256(journal_file.read_bytes()).hexdigest()
    if mutation == "policy-missing": meta.pop("policyTransitionProof")
    if mutation == "policy-name": meta["sourceExecutionPolicy"] = "../foreign.yml"
    if mutation == "policy-bytes": (directory / "CANDIDATE-EXECUTION-POLICY.yml").write_text("changed")
    if mutation == "policy-original":
        producer = json.loads((directory / "ORIGINAL-ASSOCIATION.json").read_text())
        producer["task"]["config_fingerprint"] = "f" * 64
        write(directory / "ORIGINAL-ASSOCIATION.json", producer)
        meta["originalAssociationProofSha256"] = hashlib.sha256((directory / "ORIGINAL-ASSOCIATION.json").read_bytes()).hexdigest()
    if mutation in {"policy-loaded", "policy-source-pg", "policy-held-pg", "policy-committed-pg", "policy-source-witness", "policy-target-witness", "policy-target-receipt", "policy-plan", "policy-boolean"}:
        proof_file = directory / "POLICY-TRANSITION-PROOF.json"
        proof = json.loads(proof_file.read_text())
        if mutation == "policy-loaded": proof["source"]["effectivePolicy"]["extra"] = True
        if mutation == "policy-source-pg": proof["postgresBeforeHold"]["policy_fingerprint"] = proof["candidate"]["appliedFingerprint"]
        if mutation == "policy-held-pg": proof["postgresAfterHold"]["policy_fingerprint"] = proof["candidate"]["appliedFingerprint"]
        if mutation == "policy-committed-pg": proof["postgresAfterCommit"]["policy_fingerprint"] = proof["source"]["appliedFingerprint"]
        if mutation == "policy-source-witness": proof["witnessSource"]["state"]["configDigest"] = "f" * 64
        if mutation == "policy-target-witness": proof["witnessTarget"]["state"]["upstreamSystemId"] = "999"
        if mutation == "policy-target-receipt": proof["witnessTarget"]["receipt"]["planSha256"] = "f" * 64
        if mutation == "policy-plan": proof["plan"]["policyTransition"]["approved"] = True
        if mutation == "policy-boolean": proof["candidate"]["canaryEnabled"] = 1
        write(proof_file, proof)
        meta["policyTransitionProofSha256"] = hashlib.sha256(proof_file.read_bytes()).hexdigest()
    # Preserve digest consistency for identity/semantic corruptions so the
    # checker must detect the specific wrong binding, not just a stale hash.
    if mutation == "inspection": meta["inspectionSha256"] = cr.digest(meta["inspection"])
    for name, event in [("cancellation", "cancellationEventSha256"), ("reaffirmedCancellation", "reaffirmationEventSha256"), ("effectHold", "effectHoldEventSha256")]:
        if mutation != "event":
            meta[name + "Sha256"] = cr.digest(meta[name]);meta[event] = meta[name + "Sha256"]
    if mutation in {"accept-extra", "accept-identity", "accept-boolean"}: meta["coldLedgerAcceptedReceiptSha256"] = cr.digest(meta["coldLedgerAcceptedReceipt"])
    with pytest.raises((ValueError, OSError, jsonschema.ValidationError)):
        runner.metadata_disposition_accepted(directory, data)


@pytest.mark.parametrize("mutation, message", [
    ("invalid-task-uuid", "genuine native task"),
    ("invalid-digest", "qualification digest"),
    ("journal-count", "journal phase history"),
    ("transition-extra", "closed actual policy transition proof"),
    ("transition-scope", "closed actual policy transition proof"),
    ("plan-identity", "signed actual policy transition plan"),
    ("applied-fingerprint", "applied execution policy fingerprint"),
    ("canary-descriptor", "source/target inert canary policy"),
    ("signed-source", "signed source-to-candidate execution policy"),
    ("original-policy", "original and current execution policy bindings"),
    ("task-item", "native exact item disposition"),
])
def test_disposable_parser_refuses_independent_semantic_bindings(disposable_runner, tmp_path, monkeypatch, mutation, message):
    # Decoder-only negative fixtures; these never establish native authority,
    # policy activation, provider outcomes, or an eligible recovered task.
    runner, _, _, _, _ = disposable_runner
    directory = tmp_path / "semantic-output-unit"
    directory.mkdir(mode=0o700)
    recovery_id = str(uuid4())
    meta = mock_metadata_output(runner, directory, recovery_id)
    data = {"recoveryId": recovery_id, "metadataDisposition": meta}
    assert runner.metadata_disposition_accepted(directory, data) is meta
    if mutation == "invalid-task-uuid":
        meta["originalTaskId"] = "not-a-uuid"
    elif mutation == "invalid-digest":
        meta["originalContextReceiptSha256"] = "not-a-digest"
    elif mutation == "journal-count":
        file = directory / "ACCEPTED-COLD-JOURNAL.json"
        journal = json.loads(file.read_text())
        journal["receipts"].pop()
        write(file, journal)
        meta["unchangedColdRecoveryJournalSha256"] = hashlib.sha256(file.read_bytes()).hexdigest()
    elif mutation == "task-item":
        meta["cancellation"]["itemId"] = meta["foreignSiblingTaskId"]
        meta["cancellationSha256"] = cr.digest(meta["cancellation"])
        meta["cancellationEventSha256"] = meta["cancellationSha256"]
    else:
        file = directory / "POLICY-TRANSITION-PROOF.json"
        proof = json.loads(file.read_text())
        if mutation == "transition-extra": proof["unknown"] = True
        if mutation == "transition-scope": proof["scope"] = "unqualified live recovery"
        if mutation == "plan-identity": proof["plan"]["clusterId"] = "another-cluster"
        if mutation == "applied-fingerprint": proof["source"]["appliedFingerprint"] = "not-a-digest"
        if mutation == "canary-descriptor": proof["source"]["effectivePolicy"]["execution_fabric"]["queues"][0]["enabled"] = True
        if mutation == "signed-source": proof["source"]["appliedFingerprint"] = "e" * 64
        if mutation == "original-policy": proof["originalTaskConfigFingerprint"] = proof["candidate"]["appliedFingerprint"]
        if mutation in {"applied-fingerprint", "canary-descriptor", "signed-source"}:
            observations = [{key: copy.deepcopy(proof[name][key]) for key in ("effectivePolicy", "appliedFingerprint", "state")}
                for name in ("source", "candidate")]
            monkeypatch.setattr(runner, "observe_execution_policies", lambda *args: observations)
        write(file, proof)
        meta["policyTransitionProofSha256"] = hashlib.sha256(file.read_bytes()).hexdigest()
    with pytest.raises(ValueError, match=message):
        runner.metadata_disposition_accepted(directory, data)


@pytest.mark.parametrize("refusal", ["missing-node", "unsafe-node", "unsafe-module", "nonzero", "oversized", "wrong-shape"])
def test_policy_observation_loader_refuses_unqualified_transport(tmp_path, monkeypatch, refusal):
    script = Path(__file__).resolve().parent / "scripts/run-fabric-cold-recovery.py"
    spec = importlib.util.spec_from_file_location("fabric_cold_observation_refusals", script)
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    # Only the decoder/transport refusal is mocked. No Node child, Docker
    # command, provider, or alternate policy loader is executed by this test.
    root = tmp_path / "isolated-observer"
    module = root / runner.CONTROL / "dist/src/policy.js"
    module.parent.mkdir(parents=True)
    module.write_text("// inert negative transport fixture")
    module.chmod(0o600)
    node = root / "node"
    node.write_text("inert negative runtime fixture")
    node.chmod(0o700)
    monkeypatch.setattr(runner, "__file__", str(root / "tests/scripts/run-fabric-cold-recovery.py"))
    monkeypatch.setattr(runner.shutil, "which", lambda name: None if refusal == "missing-node" else str(node))
    if refusal == "unsafe-node": node.chmod(0o722)
    if refusal == "unsafe-module": module.chmod(0o622)
    selectors = {"NODE_OPTIONS", "NODE_PATH", "NODE_V8_COVERAGE", "FABRIC_RUNTIME_ENV_FILE",
        "FABRIC_DATABASE_URL", "DATABASE_URL", "FABRIC_TEST_DATABASE_URL", "FABRIC_COLD_TEST_DATABASE_URL_FILE",
        "FABRIC_INTEGRATION_TESTS", "FABRIC_COLD_INTEGRATION_TESTS"}
    for key in selectors: monkeypatch.setenv(key, "unqualified-fixture-selector")
    calls = []
    def refused_child(argv, **kwargs):
        calls.append((argv, kwargs))
        output = b"x" * 4_194_305 if refusal == "oversized" else b"{}"
        return subprocess.CompletedProcess(argv, 1 if refusal == "nonzero" else 0, output, b"")
    monkeypatch.setattr(runner.subprocess, "run", refused_child)
    source, candidate = root / "source.yml", root / "candidate.yml"
    expected = "unavailable" if refusal in {"missing-node", "unsafe-node", "unsafe-module"} else "observation refused|observation differs"
    with pytest.raises(ValueError, match=expected):
        runner.observe_execution_policies(source, candidate)
    if refusal in {"missing-node", "unsafe-node", "unsafe-module"}:
        assert calls == []
    else:
        assert len(calls) == 1
        argv, kwargs = calls[0]
        assert argv[:3] == [str(node), "--input-type=module", "--eval"]
        assert argv[4:] == [str(module), str(source), str(candidate)]
        assert "PolicyManager" in argv[3] and "pathToFileURL(module)" in argv[3]
        assert kwargs["capture_output"] is True and kwargs["timeout"] == 15 and kwargs["check"] is False
        assert not selectors.intersection(kwargs["env"])
    assert not source.exists() and not candidate.exists()


def test_disposable_runner_failed_test_cleans_exact_owner(disposable_runner, monkeypatch):
    runner, args, child, calls, _ = disposable_runner
    monkeypatch.setattr(runner, "run_tests", lambda *args: 1)
    assert runner.main(args) == 1
    receipt = json.loads((child / "RUN-RECEIPT.json").read_text())
    assert receipt["status"] == "test_failed" and receipt["teardown_verified"] is True
    removed = [call for call in calls if call[:2] == ["docker", "rm"]]
    assert removed == [["docker", "rm", "--force", "--volumes", "c" * 64]]
    assert receipt["generated_test_credentials_removed"] is True


def test_disposable_runner_foreign_owner_never_deleted(disposable_runner):
    runner, args, child, calls, container = disposable_runner
    container["Config"]["Labels"][runner.LABEL] = "foreign"
    assert runner.main(args) == 4
    assert not any(call[:2] == ["docker", "rm"] for call in calls)
    assert json.loads((child / "RUN-RECEIPT.json").read_text())["teardown_verified"] is False


def test_disposable_runner_daemon_failure_is_not_absence(disposable_runner, monkeypatch):
    runner, args, child, calls, _ = disposable_runner
    original = runner.command
    def command(argv, timeout=30):
        if argv[:3] == ["docker", "container", "ls"]:
            calls.append(argv)
            return subprocess.CompletedProcess(argv, 1, "", "daemon unavailable")
        return original(argv, timeout)
    monkeypatch.setattr(runner, "command", command)
    assert runner.main(args) == 4
    assert json.loads((child / "RUN-RECEIPT.json").read_text())["status"] == "cleanup_unverified"


def test_disposable_runner_success_requires_acceptance_and_cleanup(disposable_runner):
    runner, args, child, calls, _ = disposable_runner
    assert runner.main(args) == 0
    receipt = json.loads((child / "RUN-RECEIPT.json").read_text())
    assert receipt["application_acceptance_verified"] is True and receipt["teardown_verified"] is True
    assert receipt["provider_actions"] == 0 and receipt["host_database_volumes"] == 0
    assert (child / "RUN-RECEIPT.json").stat().st_mode & 0o077 == 0
