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
        "schemaVersion": "execution-fabric-cold-restore-input/v1", "recoverySetId": str(uuid4()),
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
    assert len(calls) == before
    assert calls.count(("ledger", "hold")) == 1
    with pytest.raises(cr.ColdRecoveryError, match="sealed"):
        packet["run"]("approve")


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


@pytest.fixture
def disposable_runner(tmp_path, monkeypatch):
    """Exercise fixture admission/teardown without invoking Docker or providers."""
    script = Path(__file__).resolve().parent / "scripts/run-fabric-cold-recovery.py"
    spec = importlib.util.spec_from_file_location("fabric_cold_runner", script)
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
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
        runner.document(child / "DATABASE-QUALIFICATION.json", {
            "schemaVersion": "execution-fabric-isolated-cold-qualification/v1", "databaseName": "fabric_cold_test_" + token,
            "accepted": True, "epoch": 7, "generation": 3, "providerOrObjectCalls": 0,
            "canaryHandler": "fabric_cold_canary_v1", "canaryExecutor": "execute_assignment", "canaryResultVerified": True,
            "quarantine": {"tasks": 1, "effects": 1, "alarms": 1, "artifacts": 1}, "migrationVersions": ["016_cold_recovery.sql"],
            "recoveryId": str(uuid4()), "canaryTaskId": str(uuid4())})
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
