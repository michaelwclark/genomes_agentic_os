from __future__ import annotations

import json
from pathlib import Path
import shutil

import pytest
import yaml

from genomes_agentic_os.artifact_contracts import validate_rendered_artifact
from genomes_agentic_os.cli import main
from genomes_agentic_os.investigation_contracts import (
    InvestigationContractError,
    analyze_investigation,
    investigation_contract_doctor,
    pause_investigation,
    record_deployed_version,
    record_investigation_evidence,
    record_source_disposition,
    render_investigation_artifact,
    resolve_investigation_contract,
    resume_investigation,
    start_investigation,
)


REPOSITORY = Path(__file__).resolve().parents[1]


def _root(tmp_path: Path) -> Path:
    root = tmp_path / "os"
    shutil.copytree(REPOSITORY / "harness/investigation-config", root / "harness/investigation-config")
    shutil.copytree(REPOSITORY / "harness/artifact-config", root / "harness/artifact-config")
    (root / "domains/acme/02-projects/app").mkdir(parents=True)
    return root


def _policy(path: Path, value: dict, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "---\n" + yaml.safe_dump(value, sort_keys=False) + "---\n\n" + body.strip() + "\n",
        encoding="utf-8",
    )


def test_root_domain_project_sources_compose_with_provenance(tmp_path: Path) -> None:
    root = _root(tmp_path)
    _policy(
        root / "domains/acme/investigation-config/sources/source-code.md",
        {
            "schema_version": 1,
            "id": "source-code",
            "kind": "source",
            "priority": 18,
            "tools": ["acme-repository-map"],
            "authority": {"repository": "service-api"},
        },
        "Inspect the exact Acme service repository.",
    )
    _policy(
        root / "domains/acme/02-projects/app/investigation-config/sources/data-contract.md",
        {
            "schema_version": 1,
            "id": "data-contract",
            "kind": "source",
            "priority": 25,
            "tools": ["schema-inspector"],
        },
        "Compare the deployed schema contract.",
    )

    first = resolve_investigation_contract(
        root,
        trigger="bug",
        environment="preprod",
        domain="acme",
        project="app",
    )
    second = resolve_investigation_contract(
        root,
        trigger="bug",
        environment="preprod",
        domain="acme",
        project="app",
    )

    assert first["fingerprint"] == second["fingerprint"]
    assert first["version_gate"] == "required_before_evidence"
    assert "data-contract" in first["effective"]["source_ids"]
    code = next(item for item in first["effective"]["source_catalog"] if item["id"] == "source-code")
    assert code["authority"]["repository"] == "service-api"
    assert "acme-repository-map" in code["tools"]
    assert len(code["source_refs"]) == 2
    assert len(code["instructions_markdown"]) == 2


def test_version_gate_pause_resume_conclusion_and_artifact_render(tmp_path: Path) -> None:
    root = _root(tmp_path)
    request = root / "request.yml"
    request.write_text(
        yaml.safe_dump(
            {
                "title": "Checkout fails in preprod",
                "summary": "Acme checkout returns an error after submit.",
                "observed": "HTTP 500",
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    run_dir = root / "runs/checkout"

    started = start_investigation(
        root,
        request,
        trigger="bug",
        environment="preprod",
        tenant="acme-bank",
        domain="acme",
        project="app",
        run_id="checkout-investigation",
        run_dir=run_dir,
    )
    assert started["state"] == "version_pending"
    assert start_investigation(
        root,
        request,
        trigger="bug",
        environment="preprod",
        tenant="acme-bank",
        domain="acme",
        project="app",
        run_id="checkout-investigation",
        run_dir=run_dir,
    )["run_id"] == started["run_id"]
    with pytest.raises(InvestigationContractError, match="deployed environment version"):
        record_investigation_evidence(root, run_dir, source_id="source-code", summary="Looked at code")

    paused = pause_investigation(
        root,
        run_dir,
        reason="vpn-unavailable",
        resume_when="VPN connectivity is verified",
    )
    assert paused["state"] == "paused"
    availability = root / "availability.json"
    availability.write_text(
        json.dumps(
            {
                "schema": "investigation-availability/v1",
                "status": "available",
                "reason": "vpn-unavailable",
                "checked_at": "2026-07-19T12:00:00Z",
                "evidence_ref": "vpn-route-probe",
            }
        ),
        encoding="utf-8",
    )
    resumed = resume_investigation(root, run_dir, availability_receipt=availability)
    assert resumed["state"] == "version_pending"

    version_receipt = root / "version-authority.json"
    version_receipt.write_text(
        json.dumps(
            {
                "schema": "investigation-version-authority/v1",
                "status": "verified",
                "source_id": "deployed-version",
                "authority_class": "domain-defined deployment authority",
                "environment": "preprod",
                "tenant": "acme-bank",
                "version": "v1.2.3",
                "source": "deployment registry",
                "git_ref": "refs/tags/v1.2.3",
                "commit_sha": "abcdef1234567",
                "evidence_ref": "deployment-registry:preprod",
                "captured_at": "2026-07-19T12:00:00Z",
            }
        ),
        encoding="utf-8",
    )
    versioned = record_deployed_version(
        root,
        run_dir,
        authority_receipt=version_receipt,
    )
    assert versioned["state"] == "evidence_planned"
    gathered = record_investigation_evidence(
        root,
        run_dir,
        source_id="source-code",
        summary="The deployed handler dereferences a missing response field.",
        facts=["Commit abcdef1 contains the unsafe dereference."],
        limitations=["The production data shape was not inspected."],
        authority="version-controlled repository",
        evidence_ref="git:abcdef1234567:checkout-handler",
    )
    assert gathered["evidence_count"] == 1
    evidence_id = json.loads((run_dir / "evidence.jsonl").read_text(encoding="utf-8").splitlines()[-1])["evidence_id"]
    manifest = json.loads((run_dir / "source-manifest.json").read_text(encoding="utf-8"))
    for source in manifest["sources"]:
        if source["id"] in {"deployed-version", "source-code"}:
            continue
        record_source_disposition(
            root,
            run_dir,
            source_id=source["id"],
            status="not-applicable",
            reason="Not needed to decide this bounded fixture investigation.",
            evidence_ref="test-scope-decision",
        )

    analysis = root / "analysis.yml"
    analysis.write_text(
        yaml.safe_dump(
            {
                "facts": [
                    {
                        "claim": "The deployed commit dereferences response.customer without a null guard.",
                        "evidence_ids": [evidence_id],
                    }
                ],
                "hypotheses": [
                    {
                        "claim": "A missing customer response causes the 500.",
                        "support_evidence_ids": [evidence_id],
                        "falsifier": "A complete customer response reproduces the same stack trace.",
                    }
                ],
                "contradictions": [
                    {"claim": "No environment log receipt was available.", "evidence_ids": [evidence_id]}
                ],
                "disconfirming_evidence": [
                    {"claim": "The same version succeeds when customer is present.", "evidence_ids": [evidence_id]}
                ],
                "unknowns": ["Frequency across other tenants"],
                "causes": ["Missing null handling in the deployed checkout handler"],
                "conclusion": "The deployed handler most likely fails when the upstream customer field is absent.",
                "conclusion_evidence_ids": [evidence_id],
                "confidence": "medium",
                "scope": "Preprod Acme checkout requests with a missing customer field",
                "recommendations": ["Add a guarded response contract and regression test."],
                "next_owner": "Acme checkout engineering",
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    concluded = analyze_investigation(root, run_dir, analysis, conclude=True)
    assert concluded["state"] == "complete"
    assert (run_dir / "result.json").is_file()
    assert (run_dir / "result.md").is_file()

    rendered = render_investigation_artifact(
        root,
        run_dir,
        provider="filesystem",
        artifact_type="investigation-report",
    )
    artifact = root / rendered["artifact_ref"]
    assert validate_rendered_artifact(artifact)["valid"] is True
    assert rendered["receipt_ref"].endswith(".receipt.json")


def test_non_environment_source_code_requires_explicit_version_not_applicable(tmp_path: Path) -> None:
    root = _root(tmp_path)
    request = root / "request.yml"
    request.write_text(yaml.safe_dump({"title": "Source-only investigation", "summary": "Inspect the local source contract."}), encoding="utf-8")
    run_dir = root / "runs/source-only"
    start_investigation(root, request, trigger="question", domain="acme", project="app", run_dir=run_dir)

    with pytest.raises(InvestigationContractError, match="unsatisfied prerequisites"):
        record_investigation_evidence(
            root,
            run_dir,
            source_id="source-code",
            summary="Inspected source.",
            authority="version-controlled repository",
            evidence_ref="git:source-only:handler",
        )

    record_source_disposition(
        root,
        run_dir,
        source_id="deployed-version",
        status="not-applicable",
        reason="The investigation has no environment scope.",
        evidence_ref="scope:environment-not-specified",
    )
    result = record_investigation_evidence(
        root,
        run_dir,
        source_id="source-code",
        summary="Inspected source after the conditional version source was dispositioned.",
        authority="version-controlled repository",
        evidence_ref="git:source-only:handler",
    )
    assert result["evidence_count"] == 1


def test_environment_source_code_still_requires_resolved_version(tmp_path: Path) -> None:
    root = _root(tmp_path)
    request = root / "request.yml"
    request.write_text(yaml.safe_dump({"title": "Environment investigation", "summary": "Inspect deployed source."}), encoding="utf-8")
    run_dir = root / "runs/environment"
    start_investigation(root, request, trigger="bug", environment="preprod", domain="acme", project="app", run_dir=run_dir)

    with pytest.raises(InvestigationContractError, match="deployed environment version"):
        record_investigation_evidence(
            root,
            run_dir,
            source_id="source-code",
            summary="Inspected source.",
            authority="version-controlled repository",
            evidence_ref="git:environment:handler",
        )


def test_declared_authority_source_coverage_and_evidence_citations_fail_closed(tmp_path: Path) -> None:
    root = _root(tmp_path)
    request = root / "request.yml"
    request.write_text(
        yaml.safe_dump({"title": "Bounded failure", "summary": "Investigate one preprod failure."}),
        encoding="utf-8",
    )
    run_dir = root / "runs/enforcement"
    start_investigation(
        root,
        request,
        trigger="bug",
        environment="preprod",
        tenant="acme-bank",
        domain="acme",
        project="app",
        run_dir=run_dir,
    )
    version_receipt = root / "version.json"
    version = {
        "schema": "investigation-version-authority/v1",
        "status": "verified",
        "source_id": "deployed-version",
        "authority_class": "wrong authority",
        "environment": "preprod",
        "tenant": "acme-bank",
        "version": "v1.2.3",
        "source": "deployment registry",
        "git_ref": "refs/tags/v1.2.3",
        "commit_sha": "abcdef1234567",
        "evidence_ref": "deployment:preprod",
        "captured_at": "2026-07-19T12:00:00Z",
    }
    version_receipt.write_text(json.dumps(version), encoding="utf-8")
    with pytest.raises(InvestigationContractError, match="authority_class"):
        record_deployed_version(root, run_dir, authority_receipt=version_receipt)

    version["authority_class"] = "domain-defined deployment authority"
    version_receipt.write_text(json.dumps(version), encoding="utf-8")
    record_deployed_version(root, run_dir, authority_receipt=version_receipt)

    with pytest.raises(InvestigationContractError, match="not declared"):
        record_investigation_evidence(
            root,
            run_dir,
            source_id="invented-source",
            summary="This source was not in the pinned plan.",
            authority="unknown",
            evidence_ref="invalid",
        )
    with pytest.raises(InvestigationContractError, match="requires authority"):
        record_investigation_evidence(
            root,
            run_dir,
            source_id="source-code",
            summary="Inspected the version-matched handler.",
            authority="default branch",
            evidence_ref="git:abcdef1:handler",
        )
    record_investigation_evidence(
        root,
        run_dir,
        source_id="source-code",
        summary="Inspected the version-matched handler.",
        facts=["The handler returns an error for the fixture input."],
        authority="version-controlled repository",
        evidence_ref="git:abcdef1:handler",
    )
    evidence_id = json.loads((run_dir / "evidence.jsonl").read_text(encoding="utf-8").splitlines()[-1])["evidence_id"]
    analysis = {
        "facts": [{"claim": "The version-matched handler fails.", "evidence_ids": [evidence_id]}],
        "hypotheses": [
            {
                "claim": "The handler defect causes the failure.",
                "support_evidence_ids": [evidence_id],
                "falsifier": "The same deployed handler succeeds for the same bounded input.",
            }
        ],
        "disconfirming_evidence": [
            {"claim": "An alternate input succeeds.", "evidence_ids": [evidence_id]}
        ],
        "unknowns": ["Frequency outside the bounded fixture"],
        "conclusion": "The handler defect is the most likely bounded cause.",
        "conclusion_evidence_ids": [evidence_id],
        "confidence": "medium",
        "scope": "Acme preprod on v1.2.3",
        "next_owner": "Acme engineering",
    }
    analysis_path = root / "analysis.yml"
    analysis_path.write_text(yaml.safe_dump(analysis, sort_keys=False), encoding="utf-8")
    with pytest.raises(InvestigationContractError, match="all planned sources"):
        analyze_investigation(root, run_dir, analysis_path, conclude=True)

    manifest = json.loads((run_dir / "source-manifest.json").read_text(encoding="utf-8"))
    for source in manifest["sources"]:
        if source["status"] == "pending":
            record_source_disposition(
                root,
                run_dir,
                source_id=source["id"],
                status="not-applicable",
                reason="Outside the bounded enforcement fixture.",
                evidence_ref="fixture-scope",
            )
    analysis["facts"][0]["evidence_ids"] = ["unknown-evidence-id"]
    analysis_path.write_text(yaml.safe_dump(analysis, sort_keys=False), encoding="utf-8")
    with pytest.raises(InvestigationContractError, match="unknown evidence ids"):
        analyze_investigation(root, run_dir, analysis_path, conclude=True)


def test_repository_investigation_library_doctor_and_cli(tmp_path: Path, capsys) -> None:
    root = _root(tmp_path)
    doctor = investigation_contract_doctor(root)
    assert doctor["ok"] is True
    assert doctor["counts"]["files"] >= 20
    assert doctor["counts"]["representative_resolutions"] == 14
    assert "deployed-version" in doctor["source_ids"]

    assert main(
        [
            "detective",
            "resolve",
            "--trigger",
            "qa-failure",
            "--environment",
            "preprod",
            "--root",
            str(root),
            "--json",
        ]
    ) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["version_gate"] == "required_before_evidence"
    assert "source-code" in output["source_ids"]
