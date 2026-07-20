from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil

import pytest

import yaml

from genomes_agentic_os.artifact_contracts import (
    ArtifactContractError,
    artifact_contract_doctor,
    prepare_artifact_apply,
    record_artifact_readback,
    render_artifact,
    resolve_artifact_contract,
    validate_rendered_artifact,
)
from genomes_agentic_os.cli import main


REPOSITORY = Path(__file__).resolve().parents[1]


def _contract(path: Path, *, provider: str, artifact_type: str, extra: dict | None = None, body: str = "") -> None:
    value = {
        "schema_version": 1,
        "provider": provider,
        "artifact_type": artifact_type,
        "mode": "compose",
        **(extra or {}),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "---\n" + yaml.safe_dump(value, sort_keys=False) + "---\n\n" + body.strip() + "\n",
        encoding="utf-8",
    )


def _root(tmp_path: Path) -> Path:
    root = tmp_path / "os"
    _contract(
        root / "harness/artifact-config/any/any.md",
        provider="any",
        artifact_type="any",
        extra={
            "approval": {"write": "explicit"},
            "required_evidence": ["source identity"],
            "safety": {"sanitize_external_output": True, "verify_target": True},
            "format": {"renderer": "markdown"},
        },
        body="# Root\n\nWrite for the intended audience.",
    )
    return root


def test_fallback_precedence_is_deterministic_and_safety_is_monotonic(tmp_path: Path) -> None:
    root = _root(tmp_path)
    _contract(
        root / "harness/artifact-config/any/bug.md",
        provider="any",
        artifact_type="bug",
        extra={"required_sections": ["Observed Behavior"], "format": {"renderer": "markdown"}},
    )
    _contract(
        root / "harness/artifact-config/jira/any.md",
        provider="jira",
        artifact_type="any",
        extra={"format": {"renderer": "jira_adf"}},
    )
    _contract(
        root / "domains/los/artifact-config/jira/bug.md",
        provider="jira",
        artifact_type="bug",
        extra={
            "approval": {"write": "none"},
            "required_sections": ["Expected Behavior"],
            "safety": {"sanitize_external_output": False},
        },
    )
    project = root / "domains/los/02-projects/app"
    project.mkdir(parents=True)
    _contract(
        project / "artifact-config/jira/bug.md",
        provider="jira",
        artifact_type="bug",
        extra={"required_sections": ["Acceptance Criteria"]},
    )

    first = resolve_artifact_contract(root, "jira", "bug", domain="los", project="app")
    second = resolve_artifact_contract(root, "jira", "bug", domain="los", project="app")

    assert first["fingerprint"] == second["fingerprint"]
    assert [Path(item["source_ref"]).name for item in first["sources"]] == ["any.md", "bug.md", "any.md", "bug.md", "bug.md"]
    assert first["effective"]["format"]["renderer"] == "jira_adf"
    assert first["effective"]["approval"]["write"] == "explicit"
    assert first["effective"]["safety"]["sanitize_external_output"] is True
    assert first["effective"]["required_sections"] == [
        "Observed Behavior",
        "Expected Behavior",
        "Acceptance Criteria",
    ]
    assert sum(item["code"] == "blocked_safety_override" for item in first["diagnostics"]) == 2


def test_render_jira_native_and_validate_required_evidence(tmp_path: Path) -> None:
    root = _root(tmp_path)
    _contract(
        root / "harness/artifact-config/any/bug.md",
        provider="any",
        artifact_type="bug",
        extra={
            "required_sections": [
                "Observed Behavior",
                "Expected Behavior",
                "Reproduction",
                "Impact",
                "Acceptance Criteria",
            ]
        },
    )
    _contract(
        root / "harness/artifact-config/jira/any.md",
        provider="jira",
        artifact_type="any",
        extra={"format": {"renderer": "jira_adf"}},
    )
    evidence = root / "evidence.yml"
    evidence.write_text(
        yaml.safe_dump(
            {
                "title": "Borrower cannot submit",
                "summary": "Submission fails after document upload.",
                "observed_behavior": "The API returns 500.",
                "expected_behavior": "The application submits successfully.",
                "reproduction": ["Open an eligible application", "Upload a document", "Submit"],
                "impact": "Eligible borrowers cannot continue.",
                "acceptance_criteria": ["Submission returns success", "Existing validation remains active"],
                "facts": ["Failure reproduced in preprod"],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    rendered = render_artifact(root, "jira", "bug", evidence)
    artifact = root / "rendered.json"
    artifact.write_text(json.dumps(rendered), encoding="utf-8")

    assert rendered["renderer"] == "jira_adf"
    assert rendered["native"]["type"] == "doc"
    validation = validate_rendered_artifact(artifact)
    assert validation["valid"] is True

    evidence.write_text("title: Missing evidence\nobserved_behavior: broken\n", encoding="utf-8")
    incomplete = render_artifact(root, "jira", "bug", evidence)
    artifact.write_text(json.dumps(incomplete), encoding="utf-8")
    invalid = validate_rendered_artifact(artifact)
    assert invalid["valid"] is False
    assert {item["code"] for item in invalid["findings"]} == {"missing_required_section"}


def test_external_safety_blocks_paths_private_links_and_secrets(tmp_path: Path) -> None:
    root = _root(tmp_path)
    evidence = root / "evidence.yml"
    evidence.write_text(
        "title: Unsafe\nsummary: See /Users/genome/private and https://app.notion.com/private with token=abcdefghijklmnopqrstuvwxyz\n",
        encoding="utf-8",
    )
    rendered = render_artifact(root, "slack", "status", evidence)
    artifact = root / "unsafe.json"
    artifact.write_text(json.dumps(rendered), encoding="utf-8")
    validation = validate_rendered_artifact(artifact)
    assert validation["valid"] is False
    assert {item["code"] for item in validation["findings"]} == {
        "local_path",
        "private_notion_link",
        "secret_fragment",
    }


def test_filesystem_apply_and_external_provider_handoff_are_receipted(tmp_path: Path) -> None:
    root = _root(tmp_path)
    evidence = root / "evidence.yml"
    evidence.write_text("title: Local summary\nsummary: A safe outcome.\n", encoding="utf-8")
    rendered = render_artifact(root, "filesystem", "status", evidence)
    artifact = root / "rendered.json"
    artifact.write_text(json.dumps(rendered), encoding="utf-8")
    receipt = root / "runs/apply.json"
    target = root / "artifacts/status.md"
    result = prepare_artifact_apply(root, artifact, target=target, execute=True, receipt_path=receipt)
    assert result["status"] == "completed"
    assert result["readback"]["verified"] is True
    assert target.read_text(encoding="utf-8") == rendered["body_markdown"]

    rendered = render_artifact(root, "linear", "status", evidence)
    artifact.write_text(json.dumps(rendered), encoding="utf-8")
    handoff = prepare_artifact_apply(
        root,
        artifact,
        target="team:ENG",
        execute=True,
        receipt_path=root / "runs/linear-apply.json",
    )
    assert handoff["status"] == "awaiting_provider_adapter"
    closed = record_artifact_readback(
        root,
        root / "runs/linear-apply.json",
        external_id="ENG-123",
        external_url="https://linear.app/example/issue/ENG-123",
        readback_sha256=hashlib.sha256(b"readback").hexdigest(),
    )
    assert closed["status"] == "completed"
    assert closed["readback"]["external_id"] == "ENG-123"

    with pytest.raises(ArtifactContractError, match="outside the Agentic OS root"):
        prepare_artifact_apply(
            root,
            artifact,
            target="team:ENG",
            execute=True,
            receipt_path=tmp_path / "outside.json",
        )


def test_repository_contract_library_doctor_and_cli_explain(tmp_path: Path, capsys) -> None:
    root = tmp_path / "os"
    shutil.copytree(REPOSITORY / "harness/artifact-config", root / "harness/artifact-config")
    result = artifact_contract_doctor(root)
    assert result["ok"] is True
    assert result["counts"]["files"] >= 25
    assert result["counts"]["representative_resolutions"] >= 100

    assert main(
        [
            "artifacts",
            "resolve",
            "--provider",
            "notion",
            "--type",
            "program",
            "--explain",
            "--root",
            str(root),
            "--json",
        ]
    ) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["effective"]["format"]["renderer"] == "notion_enhanced_markdown"
    assert output["sources"][-1]["source_ref"].endswith("notion/program.md")
