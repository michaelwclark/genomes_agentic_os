from __future__ import annotations

import json
from pathlib import Path

import pytest

from genomes_agentic_os.cli import main
from genomes_agentic_os.cli import runtime_cold_recovery as cli


def arguments(tmp_path: Path, action: str = "inspect") -> list[str]:
    return [
        "runtime", "cold-recovery", action,
        "--request", str(tmp_path / "request.json"),
        "--policy", str(tmp_path / "policy.json"),
        "--anchor", str(tmp_path / "anchor.json"),
        "--journal-dir", str(tmp_path / "journal"),
        "--service-root", str(tmp_path / "reviewed-services"),
        "--database-url-file", str(tmp_path / "database-url.private"),
        "--json",
    ]


@pytest.mark.parametrize("action", cli.ACTIONS)
def test_registered_cli_defaults_to_read_only_plan(tmp_path, monkeypatch, capsys, action):
    calls = []

    def operation(*args, **kwargs):
        calls.append((args, kwargs))
        return {"ok": True, "status": "validated_plan"}

    monkeypatch.setattr(cli, "cold_recovery_operation", operation)
    monkeypatch.setattr(cli.shutil, "which", lambda _: "/reviewed/node")
    assert main(arguments(tmp_path, action)) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "validated_plan"
    args, kw = calls.pop()
    assert args == (action, str(tmp_path / "request.json"))
    assert kw["dry_run"] is True
    root = tmp_path / "reviewed-services"
    assert kw["witness_command"] == [
        "/reviewed/node",
        str(root / "execution-fabric-leadership-witness/dist/src/cold-recovery-main.js"),
    ]
    assert kw["ledger_command"] == [
        "/reviewed/node",
        str(root / "execution-fabric-control-plane/dist/src/cold-recovery-main.js"),
        "--database-url-file", str(tmp_path / "database-url.private"),
    ]
    assert calls == []


def test_explicit_apply_does_not_bypass_coordinator_refusal(tmp_path, monkeypatch, capsys):
    calls = []

    def operation(*args, **kwargs):
        calls.append(kwargs)
        return {"ok": False, "status": "held"}

    monkeypatch.setattr(cli, "cold_recovery_operation", operation)
    monkeypatch.setattr(cli.shutil, "which", lambda _: "/reviewed/node")
    assert main(arguments(tmp_path, "apply") + ["--apply"]) == 1
    assert calls[0]["dry_run"] is False
    assert json.loads(capsys.readouterr().out) == {"ok": False, "status": "held"}


def test_actor_error_does_not_expose_credentials(tmp_path, monkeypatch, capsys):
    secret = "postgresql://user:private-password@localhost/only-target"

    def operation(*args, **kwargs):
        raise RuntimeError(secret)

    monkeypatch.setattr(cli, "cold_recovery_operation", operation)
    monkeypatch.setattr(cli.shutil, "which", lambda _: "/reviewed/node")
    assert main(arguments(tmp_path, "apply") + ["--apply"]) == 1
    output = capsys.readouterr().out
    assert secret not in output
    assert "private-password" not in output
    assert json.loads(output) == {
        "ok": False, "error": "cold_recovery_refused", "error_class": "RuntimeError",
    }


def test_missing_actor_runtime_is_held_without_coordinator_call(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli.shutil, "which", lambda _: None)

    def unexpected(*args, **kwargs):
        pytest.fail("coordinator must not execute without the fixed actor runtime")

    monkeypatch.setattr(cli, "cold_recovery_operation", unexpected)
    assert main(arguments(tmp_path)) == 1
    assert json.loads(capsys.readouterr().out) == {"ok": False, "error": "node_unavailable"}


def test_fresh_policy_delivery_and_update_preserve_operator_binding(tmp_path):
    from genomes_agentic_os.scaffold import install_docs

    install_docs(tmp_path)
    policy_file = tmp_path / "harness/config/execution-fabric-cold-recovery.json"
    policy = json.loads(policy_file.read_text())
    assert policy["enabled"] is False
    assert policy["recoveryPublicKeyPem"] is None
    assert (tmp_path / "harness/schemas/execution-fabric-cold-recovery.schema.json").is_file()
    policy["clusterId"] = "operator-bound-cluster"
    configured = json.dumps(policy, sort_keys=True).encode()
    policy_file.write_bytes(configured)
    install_docs(tmp_path)
    assert policy_file.read_bytes() == configured
