from __future__ import annotations

from datetime import UTC, datetime
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import shutil

import pytest
import yaml

import genomes_agentic_os.first_class_registry as registry
from genomes_agentic_os.cli import main
from genomes_agentic_os.first_class_registry import (
    API_VERSION,
    REGISTRY_PATH,
    TAG_MUTATION_API_VERSION,
    TAG_OVERLAY_PATH,
    list_resource_tags,
    mutate_resource_tag,
    normalize_resource_tag,
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
    _yaml(root / "work/domain.yml", {"id": "work", "name": "Work"})
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


def test_refresh_discovers_installed_inactive_execution_fabric(tmp_path: Path) -> None:
    root = tmp_path / "agentic_os"
    assert main(["init", "--target", str(root)]) == 0

    payload = refresh_first_class_registry(root)
    resource = next(
        item
        for item in payload["resources"]
        if item["id"] == "program_definition:execution_fabric"
    )

    assert resource["kind"] == "program"
    assert resource["native_id"] == "program_definition:execution_fabric"
    assert resource["source"] == "harness/shared_factory/00-programs/execution_fabric"
    assert resource["scope"] == {"domain": None, "project": None}


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


def test_automation_evidence_refs_are_bounded_root_relative_and_honest(
    tmp_path: Path,
) -> None:
    root = _root(tmp_path)
    automation = root / "work/04-automations/engineering/digest"
    _write(
        automation / "automation.md",
        "# Automation: Digest\n\n## Purpose\n\nBuild a digest.\n",
    )
    _write(automation / "logs/latest.log", "ok\n")
    _write(automation / "runs/receipt.json", "{}\n")
    _write(root / "harness/shared_factory/00-control-plane/run-queue.yml", "items: []\n")

    payload = refresh_first_class_registry(root)
    item = next(
        resource
        for resource in payload["resources"]
        if resource["id"] == "automation_definition:work:engineering:digest"
    )

    assert item["evidence"]["logs"] == {
        "available": True,
        "reason": "1 canonical log reference(s) available.",
        "unavailable_code": None,
        "references": [
            {
                "path": "work/04-automations/engineering/digest/logs",
                "kind": "directory",
                "label": "Logs folder",
                "source": "automation_definition",
                "observed_at": None,
            }
        ],
    }
    assert item["evidence"]["runs"]["available"] is True
    assert item["evidence"]["runs"]["references"][0]["kind"] == "directory"
    recent_paths = {
        ref["path"] for ref in item["evidence"]["recent"]["references"]
    }
    assert recent_paths == {
        "work/04-automations/engineering/digest/logs/latest.log",
        "work/04-automations/engineering/digest/runs/receipt.json",
    }
    assert all(
        not Path(ref["path"]).is_absolute() and ".." not in Path(ref["path"]).parts
        for group in item["evidence"].values()
        for ref in group["references"]
    )


def test_automation_evidence_rejects_absolute_traversal_and_symlink_escape(
    tmp_path: Path,
) -> None:
    root = _root(tmp_path)
    automation = root / "work/04-automations/engineering/digest"
    _write(automation / "automation.md", "# Automation: Digest\n")
    outside = tmp_path / "outside"
    _write(outside / "secret.log", "secret\n")
    (automation / "logs").symlink_to(outside, target_is_directory=True)
    _yaml(
        root / "harness/shared_factory/00-control-plane/runtime-registry.yml",
        {
            "schedules": [
                {
                    "id": "digest-schedule",
                    "automation_id": "work:engineering:digest",
                    "enabled": True,
                }
            ]
        },
    )
    _yaml(
        root / "harness/shared_factory/00-control-plane/run-queue.yml",
        {
            "items": [
                {
                    "id": "absolute",
                    "ref": "digest-schedule",
                    "status": "done",
                    "log": str(outside / "secret.log"),
                },
                {
                    "id": "traversal",
                    "ref": "digest-schedule",
                    "status": "done",
                    "log": "../outside/secret.log",
                },
            ]
        },
    )

    payload = refresh_first_class_registry(root)
    item = next(
        resource
        for resource in payload["resources"]
        if resource["id"] == "automation_definition:work:engineering:digest"
    )

    assert item["evidence"]["logs"] == {
        "available": False,
        "reason": "No canonical root-relative log evidence is available.",
        "unavailable_code": "no_log_evidence",
        "references": [],
    }
    # Joined run receipts still provide a safe entry point to the canonical queue.
    assert item["evidence"]["runs"]["available"] is True
    assert item["evidence"]["runs"]["references"] == [
        {
            "path": "harness/shared_factory/00-control-plane/run-queue.yml",
            "kind": "file",
            "label": "Run queue receipts",
            "source": "run_receipt",
            "observed_at": None,
        }
    ]
    assert item["evidence"]["recent"] == {
        "available": False,
        "reason": "No recent root-relative evidence file is available.",
        "unavailable_code": "no_recent_evidence",
        "references": [],
    }


def test_automation_without_evidence_has_deterministic_disabled_reasons(
    tmp_path: Path,
) -> None:
    root = _root(tmp_path)
    _write(
        root / "work/04-automations/engineering/digest/automation.md",
        "# Automation: Digest\n",
    )

    payload = refresh_first_class_registry(root)
    item = next(
        resource
        for resource in payload["resources"]
        if resource["id"] == "automation_definition:work:engineering:digest"
    )

    assert item["evidence"]["logs"]["unavailable_code"] == "no_log_evidence"
    assert item["evidence"]["runs"]["unavailable_code"] == "no_run_evidence"
    assert item["evidence"]["recent"]["unavailable_code"] == "no_recent_evidence"


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
def test_custom_tags_are_durable_and_merged_with_explicit_provenance(
    tmp_path: Path,
) -> None:
    root = _root(tmp_path)
    initial = refresh_first_class_registry(root)
    resource = next(item for item in initial["resources"] if item["kind"] == "skill")

    receipt = mutate_resource_tag(
        root,
        operation="add",
        resource_id=resource["id"],
        tag="Needs Review",
        now=datetime(2026, 7, 17, 15, tzinfo=UTC),
    )

    assert receipt["api_version"] == TAG_MUTATION_API_VERSION
    assert receipt["tag"] == "needs-review"
    assert receipt["changed"] is True
    assert (root / receipt["receipt_path"]).is_file()
    overlay = json.loads((root / TAG_OVERLAY_PATH).read_text(encoding="utf-8"))
    assert overlay["resources"][resource["id"]]["tags"] == ["needs-review"]

    refreshed = refresh_first_class_registry(root)
    tagged = next(
        item for item in refreshed["resources"] if item["id"] == resource["id"]
    )
    assert tagged["tag_provenance"]["custom"] == ["needs-review"]
    assert set(tagged["tag_provenance"]["derived"]).issubset(tagged["tags"])
    assert "needs-review" in tagged["tags"]
    assert list_resource_tags(root, resource["id"])["custom_tags"] == ["needs-review"]

    removed = mutate_resource_tag(
        root, operation="remove", resource_id=resource["id"], tag="needs_review"
    )
    assert removed["changed"] is True
    assert removed["custom_tags"] == []


def test_tag_mutations_reject_invalid_unknown_and_traversal_inputs(
    tmp_path: Path,
) -> None:
    root = _root(tmp_path)
    refresh_first_class_registry(root)
    resource_id = query_first_class_registry(root, kind="skill")["resources"][0]["id"]

    for invalid in ("", "🔥", "x" * 33, "customer/private"):
        with pytest.raises(ValueError):
            mutate_resource_tag(
                root, operation="add", resource_id=resource_id, tag=invalid
            )
    for resource_id in ("../../etc/passwd", "skill:unknown"):
        with pytest.raises(ValueError):
            mutate_resource_tag(
                root, operation="add", resource_id=resource_id, tag="review"
            )
    assert normalize_resource_tag(" Needs__Review ") == "needs-review"
    assert not (root / TAG_OVERLAY_PATH).exists()


def test_concurrent_tag_writes_are_serialized_without_lost_updates(
    tmp_path: Path,
) -> None:
    root = _root(tmp_path)
    snapshot = refresh_first_class_registry(root)
    resource_id = next(
        item["id"] for item in snapshot["resources"] if item["kind"] == "skill"
    )

    with ThreadPoolExecutor(max_workers=8) as pool:
        receipts = list(
            pool.map(
                lambda tag: mutate_resource_tag(
                    root, operation="add", resource_id=resource_id, tag=tag
                ),
                [f"team-{index}" for index in range(8)],
            )
        )

    expected = [f"team-{index}" for index in range(8)]
    assert list_resource_tags(root, resource_id)["custom_tags"] == expected
    assert len({receipt["receipt_path"] for receipt in receipts}) == 8
    assert not list((root / TAG_OVERLAY_PATH).parent.glob(".*.tmp"))


def _tag_mutation_baseline(root: Path) -> tuple[str, bytes, bytes]:
    snapshot = refresh_first_class_registry(root)
    resource_id = next(
        item["id"]
        for item in snapshot["resources"]
        if item["kind"] == "skill" and item["native_id"] == "review"
    )
    mutate_resource_tag(root, operation="add", resource_id=resource_id, tag="before")
    return (
        resource_id,
        (root / TAG_OVERLAY_PATH).read_bytes(),
        (root / REGISTRY_PATH).read_bytes(),
    )


@pytest.mark.parametrize("failure_stage", ["snapshot", "refresh", "receipt"])
def test_tag_mutation_failure_restores_exact_overlay_and_snapshot_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure_stage: str
) -> None:
    root = _root(tmp_path)
    resource_id, overlay_before, snapshot_before = _tag_mutation_baseline(root)
    receipt_names_before = {
        path.name for path in (root / registry.TAG_RECEIPT_ROOT).glob("*.json")
    }
    original_write = registry._write_json_atomic

    if failure_stage == "snapshot":
        def fail_snapshot(root_arg: Path, relative: Path, value: dict[str, object]) -> None:
            if relative == REGISTRY_PATH:
                raise OSError("simulated snapshot write failure")
            original_write(root_arg, relative, value)

        monkeypatch.setattr(registry, "_write_json_atomic", fail_snapshot)
        expected = "snapshot write"
    elif failure_stage == "refresh":
        def fail_refresh(*_args: object, **_kwargs: object) -> dict[str, object]:
            raise RuntimeError("simulated refresh failure")

        monkeypatch.setattr(registry, "_refresh_first_class_registry_unlocked", fail_refresh)
        expected = "refresh failure"
    else:
        def fail_receipt(root_arg: Path, relative: Path, value: dict[str, object]) -> None:
            original_write(root_arg, relative, value)
            if relative.parent == registry.TAG_RECEIPT_ROOT:
                raise OSError("simulated receipt write failure")

        monkeypatch.setattr(registry, "_write_json_atomic", fail_receipt)
        expected = "receipt write"

    with pytest.raises((OSError, RuntimeError), match=expected):
        mutate_resource_tag(root, operation="add", resource_id=resource_id, tag="after")

    assert (root / TAG_OVERLAY_PATH).read_bytes() == overlay_before
    assert (root / REGISTRY_PATH).read_bytes() == snapshot_before
    assert {
        path.name for path in (root / registry.TAG_RECEIPT_ROOT).glob("*.json")
    } == receipt_names_before


def test_tag_mutation_source_disappearance_restores_exact_prior_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _root(tmp_path)
    resource_id, overlay_before, snapshot_before = _tag_mutation_baseline(root)
    source = root / "harness/registries/skills.yml"
    original_write = registry._write_json_atomic

    def disappear_after_overlay(root_arg: Path, relative: Path, value: dict[str, object]) -> None:
        original_write(root_arg, relative, value)
        if relative == TAG_OVERLAY_PATH:
            source.unlink()

    monkeypatch.setattr(registry, "_write_json_atomic", disappear_after_overlay)

    with pytest.raises(ValueError, match="resource disappeared"):
        mutate_resource_tag(root, operation="add", resource_id=resource_id, tag="after")

    assert (root / TAG_OVERLAY_PATH).read_bytes() == overlay_before
    assert (root / REGISTRY_PATH).read_bytes() == snapshot_before


def test_tag_mutation_rejects_symlinked_overlay_and_lock_file_escapes(
    tmp_path: Path,
) -> None:
    for path_name in (registry.TAG_OVERLAY_PATH, registry.TAG_LOCK_PATH):
        root = _root(tmp_path / path_name.stem)
        snapshot = refresh_first_class_registry(root)
        resource_id = next(item["id"] for item in snapshot["resources"] if item["kind"] == "skill")
        outside = root.parent / f"outside-{path_name.stem}"
        outside.mkdir()
        target = root / path_name
        target.unlink(missing_ok=True)
        target.symlink_to(outside / path_name.name)

        with pytest.raises(ValueError, match="escaped the installed root"):
            mutate_resource_tag(root, operation="add", resource_id=resource_id, tag="review")
        assert not (outside / path_name.name).exists()


def test_refresh_rejects_symlinked_snapshot_escape(tmp_path: Path) -> None:
    root = _root(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    target = root / REGISTRY_PATH
    target.symlink_to(outside / target.name)

    with pytest.raises(ValueError, match="escaped the installed root"):
        refresh_first_class_registry(root)
    assert not (outside / target.name).exists()


def test_tag_mutation_rejects_symlinked_receipt_directory_and_rolls_back(
    tmp_path: Path,
) -> None:
    root = _root(tmp_path)
    resource_id, overlay_before, snapshot_before = _tag_mutation_baseline(root)
    outside = tmp_path / "outside"
    outside.mkdir()
    receipt_root = root / registry.TAG_RECEIPT_ROOT
    shutil.rmtree(receipt_root)
    receipt_root.symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError, match="escaped the installed root"):
        mutate_resource_tag(root, operation="add", resource_id=resource_id, tag="after")

    assert (root / TAG_OVERLAY_PATH).read_bytes() == overlay_before
    assert (root / REGISTRY_PATH).read_bytes() == snapshot_before
    assert not list(outside.iterdir())


def test_cli_tag_add_list_remove_round_trip(tmp_path: Path, capsys) -> None:
    root = _root(tmp_path)
    snapshot = refresh_first_class_registry(root)
    resource_id = next(
        item["id"] for item in snapshot["resources"] if item["kind"] == "skill"
    )

    assert (
        main(
            [
                "resource-registry",
                "tags",
                "add",
                "--resource-id",
                resource_id,
                "--tag",
                "priority",
                "--root",
                str(root),
            ]
        )
        == 0
    )
    added = json.loads(capsys.readouterr().out)
    assert added["custom_tags"] == ["priority"]

    assert (
        main(
            [
                "resource-registry",
                "tags",
                "list",
                "--resource-id",
                resource_id,
                "--root",
                str(root),
            ]
        )
        == 0
    )
    listed = json.loads(capsys.readouterr().out)
    assert listed["custom_tags"] == ["priority"]

    assert (
        main(
            [
                "resource-registry",
                "tags",
                "remove",
                "--resource-id",
                resource_id,
                "--tag",
                "priority",
                "--root",
                str(root),
            ]
        )
        == 0
    )
    removed = json.loads(capsys.readouterr().out)
    assert removed["custom_tags"] == []
