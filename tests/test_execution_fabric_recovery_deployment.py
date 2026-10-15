from __future__ import annotations

import copy
import json
from pathlib import Path
from types import SimpleNamespace

import jsonschema
import pytest
import yaml

from genomes_agentic_os.cli import main
from genomes_agentic_os.cli import runtime_recovery as cli

ROOT = Path(__file__).resolve().parents[1]


def test_disabled_clone_configuration_is_valid_but_missing_credentials_cannot_enable():
    config = yaml.safe_load((ROOT / "harness/config/execution-fabric.yml").read_text())
    schema = json.loads((ROOT / "schemas/execution-fabric.schema.json").read_text())
    jsonschema.validate(config, schema)
    settings = config["execution_fabric"]["recovery_sets"]
    assert settings["enabled"] is False
    assert settings["daily_plan_file"] is None
    enabled = copy.deepcopy(config)
    enabled["execution_fabric"]["recovery_sets"]["enabled"] = True
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(enabled, schema)


def test_recovery_policy_rejects_unrecognized_credentials_surface():
    config = yaml.safe_load((ROOT / "harness/config/execution-fabric.yml").read_text())
    config["execution_fabric"]["recovery_sets"]["password"] = "must-never-be-configured-here"
    schema = json.loads((ROOT / "schemas/execution-fabric.schema.json").read_text())
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(config, schema)


@pytest.mark.parametrize("enabled,host", [(False, "genomesbox"), (True, "bigmac")])
def test_registered_capture_cannot_mutate_without_enabled_primary_policy(
    tmp_path, monkeypatch, capsys, enabled, host,
):
    settings = {"enabled": enabled, "primary_host_id": "genomesbox", "custodian_host_id": "bigmac"}
    monkeypatch.setattr(
        cli, "load_execution_fabric_config",
        lambda _: SimpleNamespace(value={"execution_fabric": {"recovery_sets": settings}}),
    )
    monkeypatch.setattr(cli, "resolve_execution_fabric_host_id", lambda _: host)

    def unexpected(*args, **kwargs):
        pytest.fail("capture cannot run outside admitted primary policy")

    monkeypatch.setattr(cli.recovery, "prepare_recovery_set", unexpected)
    output = tmp_path / "never-created"
    assert main([
        "runtime", "recovery-set", "prepare", "--capture-plan", "unused-plan.json",
        "--maintenance-receipt", "unused-maintenance.json", "--output", str(output),
        "--root", str(tmp_path), "--apply", "--json",
    ]) == 1
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "held"
    assert result["authorityTransferAuthorized"] is False
    assert not output.exists()
