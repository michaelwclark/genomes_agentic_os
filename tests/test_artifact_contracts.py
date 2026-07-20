from __future__ import annotations

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
NOW = "2026-07-19T12:00:00Z"


def _artifact_evidence(value: dict) -> dict:
    return {
        **value,
        "evidence_receipts": {
            "source identity": {
                "status": "verified",
                "value": "TEST-1",
                "evidence_ref": "test-fixture",
                "captured_at": NOW,
            }
        },
    }


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


def test_provider_type_accepts_ordered_one_to_many_markdown_addenda(tmp_path: Path) -> None:
    root = _root(tmp_path)
    _contract(
        root / "harness/artifact-config/jira/story/10-product-outcome.md",
        provider="jira",
        artifact_type="story",
        extra={"required_sections": ["User Outcome"]},
        body="# Outcome module",
    )
    _contract(
        root / "harness/artifact-config/jira/story/20-qa-scenarios.md",
        provider="jira",
        artifact_type="story",
        extra={"required_sections": ["Acceptance Criteria"], "validation": ["gherkin_is_testable"]},
        body="# QA module",
    )

    resolution = resolve_artifact_contract(root, "jira", "story")

    assert [item["source_ref"] for item in resolution["sources"]][-2:] == [
        "harness/artifact-config/jira/story/10-product-outcome.md",
        "harness/artifact-config/jira/story/20-qa-scenarios.md",
    ]
    assert resolution["effective"]["required_sections"] == ["User Outcome", "Acceptance Criteria"]
    assert resolution["effective"]["validation"] == ["gherkin_is_testable"]
    assert "Outcome module" in resolution["effective"]["guidance_markdown"]
    assert "QA module" in resolution["effective"]["guidance_markdown"]


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
            _artifact_evidence({
                "title": "Borrower cannot submit",
                "summary": "Submission fails after document upload.",
                "observed_behavior": "The API returns 500.",
                "expected_behavior": "The application submits successfully.",
                "reproduction": ["Open an eligible application", "Upload a document", "Submit"],
                "impact": "Eligible borrowers cannot continue.",
                "acceptance_criteria": ["Submission returns success", "Existing validation remains active"],
                "facts": ["Failure reproduced in preprod"],
            }),
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

    evidence.write_text(
        yaml.safe_dump(_artifact_evidence({"title": "Missing evidence", "observed_behavior": "broken"})),
        encoding="utf-8",
    )
    incomplete = render_artifact(root, "jira", "bug", evidence)
    artifact.write_text(json.dumps(incomplete), encoding="utf-8")
    invalid = validate_rendered_artifact(artifact)
    assert invalid["valid"] is False
    assert {item["code"] for item in invalid["findings"]} == {"missing_required_section"}


def test_external_safety_blocks_paths_private_links_and_secrets(tmp_path: Path) -> None:
    root = _root(tmp_path)
    evidence = root / "evidence.yml"
    evidence.write_text(
        yaml.safe_dump(
            _artifact_evidence(
                {
                    "title": "Unsafe",
                    "summary": "See /Users/genome/private and https://app.notion.com/private with token=abcdefghijklmnopqrstuvwxyz",
                }
            )
        ),
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


def test_evidence_semantic_governance_and_live_readback_fail_closed(tmp_path: Path) -> None:
    root = _root(tmp_path)
    _contract(
        root / "harness/artifact-config/linear/issue.md",
        provider="linear",
        artifact_type="issue",
        extra={
            "validation": ["acceptance criteria are testable"],
            "readback": ["team", "issue_type"],
        },
    )
    evidence = root / "evidence.yml"
    evidence.write_text(
        yaml.safe_dump(
            {
                "title": "Governed issue",
                "summary": "A bounded, safe issue.",
            }
        ),
        encoding="utf-8",
    )
    artifact = root / "rendered.json"
    rendered = render_artifact(root, "linear", "issue", evidence)
    artifact.write_text(json.dumps(rendered), encoding="utf-8")
    findings = {item["code"] for item in validate_rendered_artifact(artifact)["findings"]}
    assert findings == {"missing_required_evidence", "missing_validation_assertion"}

    evidence.write_text(
        yaml.safe_dump(
            {
                **_artifact_evidence(
                    {
                        "title": "Governed issue",
                        "summary": "A bounded, safe issue.",
                    }
                ),
                "validation_assertions": {
                    "acceptance criteria are testable": {
                        "status": "passed",
                        "evidence_ref": "review:acceptance",
                        "checked_at": NOW,
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    rendered = render_artifact(root, "linear", "issue", evidence)
    artifact.write_text(json.dumps(rendered), encoding="utf-8")
    assert validate_rendered_artifact(artifact)["valid"] is True

    with pytest.raises(ArtifactContractError, match="approval receipt"):
        prepare_artifact_apply(
            root,
            artifact,
            target="team:ENG",
            execute=True,
            receipt_path=root / "runs/apply.json",
        )

    approval = root / "runs/approval.json"
    target_receipt = root / "runs/target.json"
    approval.parent.mkdir(parents=True, exist_ok=True)
    approval.write_text(
        json.dumps(
            {
                "schema": "artifact-approval/v1",
                "status": "approved",
                "provider": "linear",
                "artifact_type": "issue",
                "contract_fingerprint": rendered["contract_fingerprint"],
                "target": "team:ENG",
                "approved_by": "test-user",
                "approved_at": NOW,
            }
        ),
        encoding="utf-8",
    )
    target_receipt.write_text(
        json.dumps(
            {
                "schema": "artifact-target-verification/v1",
                "status": "verified",
                "provider": "linear",
                "target": "team:ENG",
                "resolver": "test-adapter",
                "verified_at": NOW,
                "evidence_ref": "linear-team-readback",
            }
        ),
        encoding="utf-8",
    )
    apply_receipt = root / "runs/linear-apply.json"
    prepare_artifact_apply(
        root,
        artifact,
        target="team:ENG",
        execute=True,
        receipt_path=apply_receipt,
        approval_receipt=approval,
        target_receipt=target_receipt,
    )
    bad_readback = root / "runs/bad-readback.json"
    bad_readback.write_text(
        json.dumps(
            {
                "schema": "artifact-provider-readback/v1",
                "status": "verified",
                "provider": "linear",
                "target": "team:ENG",
                "external_id": "ENG-1",
                "verified_at": NOW,
                "observed": {"team": "ENG", "issue_type": "Issue"},
                "content": {"title": "Provider silently changed content"},
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ArtifactContractError, match="does not match"):
        record_artifact_readback(root, apply_receipt, readback_receipt=bad_readback)


def test_filesystem_apply_and_external_provider_handoff_are_receipted(tmp_path: Path) -> None:
    root = _root(tmp_path)
    evidence = root / "evidence.yml"
    evidence.write_text(
        yaml.safe_dump(_artifact_evidence({"title": "Local summary", "summary": "A safe outcome."})),
        encoding="utf-8",
    )
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
    approval_path = root / "runs/approval.json"
    approval_path.parent.mkdir(parents=True, exist_ok=True)
    approval_path.write_text(
        json.dumps(
            {
                "schema": "artifact-approval/v1",
                "status": "approved",
                "provider": "linear",
                "artifact_type": "status",
                "contract_fingerprint": rendered["contract_fingerprint"],
                "target": "team:ENG",
                "approved_by": "test-user",
                "approved_at": NOW,
            }
        ),
        encoding="utf-8",
    )
    target_path = root / "runs/target.json"
    target_path.write_text(
        json.dumps(
            {
                "schema": "artifact-target-verification/v1",
                "status": "verified",
                "provider": "linear",
                "target": "team:ENG",
                "resolver": "test-fixture",
                "verified_at": NOW,
                "evidence_ref": "linear-team-readback",
            }
        ),
        encoding="utf-8",
    )
    handoff = prepare_artifact_apply(
        root,
        artifact,
        target="team:ENG",
        execute=True,
        receipt_path=root / "runs/linear-apply.json",
        approval_receipt=approval_path,
        target_receipt=target_path,
    )
    assert handoff["status"] == "awaiting_provider_adapter"
    readback_path = root / "runs/readback.json"
    readback_path.write_text(
        json.dumps(
            {
                "schema": "artifact-provider-readback/v1",
                "status": "verified",
                "provider": "linear",
                "target": "team:ENG",
                "external_id": "ENG-123",
                "external_url": "https://linear.app/example/issue/ENG-123",
                "verified_at": NOW,
                "observed": {},
                "content": rendered["provider_payload"],
            }
        ),
        encoding="utf-8",
    )
    closed = record_artifact_readback(
        root,
        root / "runs/linear-apply.json",
        readback_receipt=readback_path,
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
            approval_receipt=approval_path,
            target_receipt=target_path,
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
