from __future__ import annotations

import json
from pathlib import Path

import yaml

from genomes_agentic_os.scaffold import install_docs


SOURCE_ROOT = Path(__file__).parents[1]


def test_universal_long_running_contract_is_registered_and_enforced() -> None:
    config = yaml.safe_load(
        (SOURCE_ROOT / "harness/config/long-running-execution.yml").read_text(encoding="utf-8")
    )["long_running_execution"]
    expected_kinds = {
        "install",
        "sync",
        "import",
        "export",
        "backfill",
        "cleanup",
        "deployment",
        "migration",
    }

    assert config["enabled"] is True
    assert config["threshold_seconds"] == 120
    assert config["require_governed_runner"] is True
    assert expected_kinds.issubset(config["mutating_kinds"])
    assert config["required_high_risk_preflight_evidence"] == ["complexity", "performance"]
    assert config["central_registry"].endswith("long-running-runs.json")
    assert set(config["required_terminal_artifacts"]) == {
        "state.json",
        "events.jsonl",
        "terminal-receipt.json",
        "summary.md",
    }

    rules = (SOURCE_ROOT / "harness/rules/os-authoring-rules.md").read_text(encoding="utf-8")
    command = (SOURCE_ROOT / "harness/commands/os-quiet-run.md").read_text(encoding="utf-8")
    skill = (SOURCE_ROOT / "harness/skills/quiet-async-runner/SKILL.md").read_text(encoding="utf-8")
    wrapper = (SOURCE_ROOT / "harness/bin/agentic-os-quiet-run").read_text(encoding="utf-8")
    for required in ("no-progress", "pause", "resume", "cancel", "terminal receipt"):
        assert required in rules.lower()
    assert "long-running execution" in command.lower()
    assert "two minutes" in skill.lower()
    assert '"long-run"' in wrapper


def test_incident_regression_fixtures_are_sanitized_and_complete() -> None:
    queue = json.loads(
        (SOURCE_ROOT / "tests/fixtures/execution_fabric_stale_activation_incident.json").read_text(
            encoding="utf-8"
        )
    )
    process = json.loads(
        (SOURCE_ROOT / "tests/fixtures/uncontrolled_long_running_process_incident.json").read_text(
            encoding="utf-8"
        )
    )

    assert queue["sqlite_projection"]["stale_nonterminal"] == 1819
    assert queue["filesystem_authority"]["queued"] == 2
    assert process["failure_modes"]
    assert all("/Users/" not in json.dumps(fixture) for fixture in (queue, process))


def test_docs_install_additively_delivers_long_running_configuration(tmp_path: Path) -> None:
    root = tmp_path / "agentic_os"
    target = root / "harness/config/long-running-execution.yml"
    install_docs(root)
    assert target.is_file()

    target.write_text("local: preserved\n", encoding="utf-8")
    install_docs(root)
    assert target.read_text(encoding="utf-8") == "local: preserved\n"
