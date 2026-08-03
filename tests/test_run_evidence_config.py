"""Tests for the canonical run-evidence model registry."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator

from genomes_agentic_os.run_evidence_config import (
    RunEvidenceConfigurationError,
    configured_model_keys,
    load_run_evidence_config,
)


REPO = Path(__file__).parents[1]

RUN_EVIDENCE_PATH_MARKERS = ("06-runs-and-logs", "async-runs", "logs/conversations")
READ_ONLY_RUN_EVIDENCE_REFERENCES = {
    "harness/config/long-running-execution.yml",
    "harness/config/run-evidence.yml",
    "harness/registries/alerts.yml",
    "harness/registries/health-monitor.yml",
    "harness/shared_factory/00-programs/auto_dev/components.yml",
    "harness/shared_factory/04-automations/operations/work_item_archive/object.yml",
    "harness/skills/initiative-context-resume/scripts/update_initiative_context.py",
    "src/genomes_agentic_os/artifact_migration.py",
    "src/genomes_agentic_os/cli/cockpit.py",
    "src/genomes_agentic_os/cli/long_run.py",
    "src/genomes_agentic_os/cli/runtime.py",
    "src/genomes_agentic_os/cockpit.py",
    "src/genomes_agentic_os/conversation_reports.py",
    "src/genomes_agentic_os/doctor.py",
    "src/genomes_agentic_os/first_class_registry.py",
    "src/genomes_agentic_os/gui_snapshot.py",
    "src/genomes_agentic_os/hosts.py",
    "src/genomes_agentic_os/lifecycle.py",
    "src/genomes_agentic_os/metrics_ops.py",
    "src/genomes_agentic_os/notion_sync.py",
    "src/genomes_agentic_os/ps_ops.py",
    "src/genomes_agentic_os/report_registry.py",
    "src/genomes_agentic_os/self_improvement.py",
    "src/genomes_agentic_os/source_observation.py",
    "src/genomes_agentic_os/spec_adapters/filesystem.py",
    "src/genomes_agentic_os/spec_engine.py",
    "src/genomes_agentic_os/validate.py",
    "src/genomes_agentic_os/work_lifecycle.py",
    "src/genomes_agentic_os/workflow_engine.py",
}


def _run_evidence_reference_paths() -> set[str]:
    references: set[str] = set()
    for base_name in ("src", "harness", "deploy", "installers", "services"):
        base = REPO / base_name
        if not base.is_dir():
            continue
        for path in base.rglob("*"):
            if not path.is_file() or path.suffix not in {"", ".py", ".sh", ".yaml", ".yml", ".zsh"}:
                continue
            body = path.read_text(encoding="utf-8", errors="ignore")
            if any(marker in body for marker in RUN_EVIDENCE_PATH_MARKERS):
                references.add(path.relative_to(REPO).as_posix())
    return references


def test_shipped_registry_is_schema_valid_and_selects_mongodb() -> None:
    schema = json.loads((REPO / "schemas" / "run-evidence-config.schema.json").read_text(encoding="utf-8"))
    document = yaml.safe_load((REPO / "harness" / "config" / "run-evidence.yml").read_text(encoding="utf-8"))

    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(document)
    assert document["backend"] == "mongodb"
    assert document["datastores"]["mongodb"]["database"] == "agentic_os"
    assert document["host_registry"]["initial_host"] == "bigmac"


def test_every_model_has_age_and_count_cleanup_policy() -> None:
    document = yaml.safe_load((REPO / "harness" / "config" / "run-evidence.yml").read_text(encoding="utf-8"))
    assert len(document["models"]) >= 12
    for model_key, model in document["models"].items():
        assert model["retention"]["max_age_days"] > 0, model_key
        assert model["retention"]["max_objects"] > 0, model_key
        assert model["source_patterns"], model_key
        assert model["indexes"], model_key
    priorities = [model["routing_priority"] for model in document["models"].values()]
    assert len(priorities) == len(set(priorities))
    assert len(document["writers"]) >= 15
    assert all(writer["cutover_issue"] == "AGE-155" for writer in document["writers"].values())


def test_direct_run_evidence_references_are_registered_or_read_only() -> None:
    document = yaml.safe_load((REPO / "harness" / "config" / "run-evidence.yml").read_text(encoding="utf-8"))
    registered = {path for writer in document["writers"].values() for path in writer["paths"]}

    assert all((REPO / path).is_file() for path in registered)
    assert _run_evidence_reference_paths() <= registered | READ_ONLY_RUN_EVIDENCE_REFERENCES


def test_loader_uses_installed_schema_and_returns_sorted_models(tmp_path: Path) -> None:
    config_dir = tmp_path / "harness" / "config"
    schema_dir = tmp_path / "harness" / "schemas"
    config_dir.mkdir(parents=True)
    schema_dir.mkdir(parents=True)
    config_dir.joinpath("run-evidence.yml").write_text(
        (REPO / "harness" / "config" / "run-evidence.yml").read_text(encoding="utf-8"), encoding="utf-8"
    )
    schema_dir.joinpath("run-evidence-config.schema.json").write_text(
        (REPO / "schemas" / "run-evidence-config.schema.json").read_text(encoding="utf-8"), encoding="utf-8"
    )

    config = load_run_evidence_config(tmp_path)
    assert configured_model_keys(config) == tuple(sorted(config["models"]))


def test_loader_falls_back_to_repository_schema(tmp_path: Path) -> None:
    config_dir = tmp_path / "harness" / "config"
    config_dir.mkdir(parents=True)
    config_dir.joinpath("run-evidence.yml").write_text(
        (REPO / "harness" / "config" / "run-evidence.yml").read_text(encoding="utf-8"), encoding="utf-8"
    )

    config = load_run_evidence_config(tmp_path)

    assert config["backend"] == "mongodb"


def test_loader_rejects_model_without_count_limit(tmp_path: Path) -> None:
    config_dir = tmp_path / "harness" / "config"
    config_dir.mkdir(parents=True)
    document = yaml.safe_load((REPO / "harness" / "config" / "run-evidence.yml").read_text(encoding="utf-8"))
    del document["models"]["run_log"]["retention"]["max_objects"]
    config_dir.joinpath("run-evidence.yml").write_text(yaml.safe_dump(document), encoding="utf-8")

    with pytest.raises(RunEvidenceConfigurationError, match="max_objects"):
        load_run_evidence_config(tmp_path)


def test_loader_rejects_ambiguous_model_routing_priority(tmp_path: Path) -> None:
    config_dir = tmp_path / "harness" / "config"
    config_dir.mkdir(parents=True)
    document = yaml.safe_load((REPO / "harness" / "config" / "run-evidence.yml").read_text(encoding="utf-8"))
    document["models"]["conversation"]["routing_priority"] = document["models"]["run_log"]["routing_priority"]
    config_dir.joinpath("run-evidence.yml").write_text(yaml.safe_dump(document), encoding="utf-8")

    with pytest.raises(RunEvidenceConfigurationError, match="routing_priority"):
        load_run_evidence_config(tmp_path)


def test_loader_rejects_writer_with_unknown_model(tmp_path: Path) -> None:
    config_dir = tmp_path / "harness" / "config"
    config_dir.mkdir(parents=True)
    document = yaml.safe_load((REPO / "harness" / "config" / "run-evidence.yml").read_text(encoding="utf-8"))
    document["writers"]["runtime_ops"]["model_keys"].append("missing_model")
    config_dir.joinpath("run-evidence.yml").write_text(yaml.safe_dump(document), encoding="utf-8")

    with pytest.raises(RunEvidenceConfigurationError, match="missing_model"):
        load_run_evidence_config(tmp_path)
