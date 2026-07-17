from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path

import yaml

from genomes_agentic_os.cli import main
from genomes_agentic_os.first_class_registry import (
    API_VERSION,
    REGISTRY_PATH,
    query_first_class_registry,
    refresh_first_class_registry,
)


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _yaml(path: Path, value: object) -> None:
    _write(path, yaml.safe_dump(value, sort_keys=False))


def _root(tmp_path: Path) -> Path:
    root = tmp_path / "os"
    _write(root / ".agentic_root", "agentic-os\n")
    _write(root / "harness/rules/os-authoring-rules.md", "# Rules\n")
    _yaml(
        root / "harness/registries/skills.yml",
        {
            "skills": [
                {
                    "id": "review",
                    "name": "Review",
                    "description": "Review work.",
                    "source": "harness/skills/review/SKILL.md",
                }
            ]
        },
    )
    _yaml(
        root / "harness/registries/commands.yml",
        {
            "commands": [
                {
                    "id": "review",
                    "command": "/review",
                    "description": "Review work.",
                    "source": "harness/commands/review.md",
                }
            ]
        },
    )
    _yaml(root / "harness/registries/rules.yml", {"rules": []})
    _yaml(root / "harness/registries/reports.yml", {"reports": []})
    _yaml(
        root / "harness/registries/report-definitions.yml",
        {
            "definitions": [
                {
                    "id": "daily",
                    "name": "Daily report",
                    "summary": "Daily status.",
                    "scope": {"domain": "work", "project": "demo"},
                }
            ]
        },
    )
    _write(
        root / "harness/shared_factory/03-workflows/engineering/review/workflow.md",
        "# Workflow: Review\n\n## Purpose\n\nReview changes safely.\n",
    )
    _write(
        root / "work/02-projects/demo/RULES.md",
        "# Demo rules\n\n## Purpose\n\nProject constraints.\n",
    )
    _yaml(
        root / "work/02-projects/demo/config/resource-registries/skills.yml",
        {
            "skills": [
                {
                    "id": "demo-helper",
                    "name": "Demo helper",
                    "description": "Project helper.",
                    "source": "work/02-projects/demo/TOOLS.md",
                }
            ]
        },
    )
    return root


def test_refresh_materializes_scoped_atomic_registry_and_query_is_snapshot_only(
    tmp_path: Path,
) -> None:
    root = _root(tmp_path)
    payload = refresh_first_class_registry(root)

    assert payload["api_version"] == API_VERSION
    target = root / REGISTRY_PATH
    assert target.is_file()
    assert not list(target.parent.glob(".*.tmp"))
    by_id = {item["id"]: item for item in payload["resources"]}
    assert by_id[
        "workflow:harness:shared_factory:03-workflows:engineering:review:workflow.md"
    ]["scope"] == {"domain": "shared_factory", "project": None}
    project_skill = next(
        item for item in payload["resources"] if item["native_id"] == "demo-helper"
    )
    assert project_skill["scope"] == {"domain": "work", "project": "demo"}
    report = next(item for item in payload["resources"] if item["native_id"] == "daily")
    assert report["id"] == "report:typed:definition:daily"

    # Prove a normal query does not rediscover the tree: remove a source after refresh.
    (root / "harness/registries/skills.yml").unlink()
    queried = query_first_class_registry(root, kind="skill")
    assert {item["native_id"] for item in queried["resources"]} == {
        "review",
        "demo-helper",
    }
    assert queried["fingerprint"] == payload["fingerprint"]


def test_refresh_fingerprint_ignores_refresh_timestamp(tmp_path: Path) -> None:
    root = _root(tmp_path)

    first = refresh_first_class_registry(
        root, now=datetime(2026, 7, 17, 12, tzinfo=UTC)
    )
    second = refresh_first_class_registry(
        root, now=datetime(2026, 7, 17, 13, tzinfo=UTC)
    )

    assert first["generated_at"] != second["generated_at"]
    assert first["resources"][0]["observed_at"] != second["resources"][0]["observed_at"]
    assert first["fingerprint"] == second["fingerprint"]
    assert not list((root / REGISTRY_PATH).parent.glob(".*.tmp"))


def test_refresh_excludes_templates_artifacts_and_worktrees(tmp_path: Path) -> None:
    root = _root(tmp_path)
    for excluded in ("templates", "artifacts", "worktrees", "logs"):
        _write(root / f"work/{excluded}/bad/workflow.md", "# Workflow: Must not load\n")
    payload = refresh_first_class_registry(root)
    sources = {item["source"] for item in payload["resources"]}
    assert not any("/bad/workflow.md" in source for source in sources)


def test_cli_refresh_then_filtered_query(tmp_path: Path, capsys) -> None:
    root = _root(tmp_path)
    assert main(["resource-registry", "refresh", "--root", str(root)]) == 0
    capsys.readouterr()
    assert (
        main(
            [
                "resource-registry",
                "query",
                "--kind",
                "workflow",
                "--domain",
                "shared_factory",
                "--root",
                str(root),
            ]
        )
        == 0
    )
    result = json.loads(capsys.readouterr().out)
    assert result["query"]["kind"] == "workflow"
    assert [item["native_id"] for item in result["resources"]] == ["review"]


def test_summary_counts_every_diagnostic_and_static_health_is_not_applicable(
    tmp_path: Path,
) -> None:
    root = _root(tmp_path)
    _write(
        root / "harness/shared_factory/00-programs/broken/program.md",
        "# OSProgram: Broken\n",
    )
    _yaml(
        root / "harness/shared_factory/00-programs/broken/components.yml",
        {"components": {"scripts": [{"id": "missing", "path": "missing.py"}]}},
    )
    _yaml(
        root / "harness/shared_factory/00-control-plane/runtime-registry.yml",
        {"schedules": [{"id": "orphan", "enabled": True}]},
    )

    payload = refresh_first_class_registry(root)
    summary = payload["summary"]

    assert summary["diagnostics"] == len(payload["diagnostics"])
    assert summary["diagnostics"] == (
        summary["info"] + summary["warnings"] + summary["errors"]
    )
    assert summary["warnings"] == 1
    assert summary["info"] == 1
    assert summary["by_diagnostic_code"] == {
        "automation_schedule_unassociated": 1,
        "dependency_missing": 1,
    }
    assert summary["partial"] is True
    assert all(
        {"resource_id", "path", "repair_kind", "guidance"}.issubset(item)
        for item in payload["diagnostics"]
    )
    assert all(item["resource_id"] for item in payload["diagnostics"])
    skill = next(item for item in payload["resources"] if item["kind"] == "skill")
    assert skill["health"] == {
        "state": "not_applicable",
        "summary": "Runtime health does not apply to this canonical registry definition.",
        "evidence_basis": "static_registry_presence",
        "liveness_observed": False,
        "observed_at": None,
    }


def test_filtered_query_recomputes_exact_diagnostic_summary(tmp_path: Path) -> None:
    root = _root(tmp_path)
    _write(
        root / "harness/shared_factory/00-programs/broken/program.md",
        "# OSProgram: Broken\n",
    )
    _yaml(
        root / "harness/shared_factory/00-programs/broken/components.yml",
        {"components": {"scripts": [{"id": "missing", "path": "missing.py"}]}},
    )
    _yaml(
        root / "harness/shared_factory/00-control-plane/runtime-registry.yml",
        {"schedules": [{"id": "orphan", "enabled": True}]},
    )
    refresh_first_class_registry(root)

    result = query_first_class_registry(root, kind="automation")

    assert result["summary"]["diagnostics"] == len(result["diagnostics"])
    assert result["summary"]["warnings"] == 0
    assert result["summary"]["info"] == 1
    assert result["summary"]["by_diagnostic_code"] == {
        "automation_schedule_unassociated": 1
    }
    assert result["summary"]["partial"] is False


def test_schedule_orphan_exception_requires_an_explicit_reason(tmp_path: Path) -> None:
    root = _root(tmp_path)
    _yaml(
        root / "harness/shared_factory/00-control-plane/runtime-registry.yml",
        {
            "schedules": [
                {
                    "id": "runtime-only-with-reason",
                    "enabled": True,
                    "intentional_orphan": True,
                    "orphan_reason": "This is a host maintenance job, not an automation.",
                },
                {
                    "id": "runtime-only-missing-reason",
                    "enabled": True,
                    "intentional_orphan": True,
                },
            ]
        },
    )

    payload = refresh_first_class_registry(root)
    schedule_diagnostics = [
        item
        for item in payload["diagnostics"]
        if item["code"] == "automation_schedule_unassociated"
    ]

    assert len(schedule_diagnostics) == 1
    assert schedule_diagnostics[0]["severity"] == "warning"
    assert schedule_diagnostics[0]["resource_id"] == (
        "automation_schedule:runtime-only-missing-reason"
    )
    assert "orphan_reason" in schedule_diagnostics[0]["message"]


def test_unnamed_schedule_diagnostic_identity_is_stable(tmp_path: Path) -> None:
    root = _root(tmp_path)
    _yaml(
        root / "harness/shared_factory/00-control-plane/runtime-registry.yml",
        {"schedules": [{"enabled": True, "command": "run-maintenance"}]},
    )

    first = refresh_first_class_registry(root)
    second = refresh_first_class_registry(root)

    first_id = next(
        item["resource_id"]
        for item in first["diagnostics"]
        if item["code"] == "automation_schedule_unassociated"
    )
    second_id = next(
        item["resource_id"]
        for item in second["diagnostics"]
        if item["code"] == "automation_schedule_unassociated"
    )
    assert first_id == second_id
    assert first_id.startswith("automation_schedule:unnamed-")
