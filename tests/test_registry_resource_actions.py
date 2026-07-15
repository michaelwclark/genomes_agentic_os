from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from genomes_agentic_os.cli import main


KINDS = ("rule", "report", "skill", "command")


def _init(root: Path, capsys) -> None:
    assert main(["init", "--target", str(root)]) == 0
    capsys.readouterr()


def _json(capsys) -> dict:
    return json.loads(capsys.readouterr().out)


def _create_args(root: Path, kind: str, resource_id: str, *extra: str) -> list[str]:
    return [
        "resource",
        "create",
        kind,
        resource_id,
        "--display-name",
        f"Demo {kind.title()}",
        "--description",
        f"A governed {kind} definition.",
        "--prompt",
        f"Use this {kind} only after validating its inputs.",
        *extra,
        "--root",
        str(root),
        "--json",
    ]


def _apply(args: list[str]) -> list[str]:
    return [*args[:-3], "--apply", *args[-3:]]


@pytest.mark.parametrize("kind", KINDS)
def test_system_registry_resource_create_validate_get_and_list(tmp_path: Path, capsys, kind: str) -> None:
    root = tmp_path / "agentic_os"
    _init(root, capsys)
    resource_id = f"demo_{kind}"

    assert main(_create_args(root, kind, resource_id)) == 0
    planned = _json(capsys)
    assert planned["api_version"] == "resource-actions/v1"
    assert planned["status"] == "planned"
    assert not Path(planned["resource"]["source"]).exists()

    assert main(_create_args(root, kind, resource_id, "--apply")) == 0
    created = _json(capsys)
    assert created["status"] == "created"
    assert created["readback"]["ok"] is True
    assert created["backup_id"]
    assert Path(created["receipt"]).is_file()
    source = Path(created["resource"]["source"])
    assert source.is_file()
    assert root in source.parents

    assert main(["resource", "validate", kind, resource_id, "--root", str(root), "--json"]) == 0
    validation = _json(capsys)
    assert validation["ok"] is True
    assert validation["resource"]["mutable"] is True

    assert main(["resource", "get", kind, resource_id, "--root", str(root), "--json"]) == 0
    fetched = _json(capsys)
    assert fetched["resource"]["id"] == resource_id
    assert fetched["resource"]["status"] == "draft"
    assert f"Use this {kind}" in fetched["resource"]["source_content"]

    assert main(["resource", "list", kind, "--root", str(root), "--json"]) == 0
    listed = _json(capsys)
    row = next(item for item in listed["resources"] if item["id"] == resource_id)
    assert row["mutable"] is True
    assert listed["resources"] == sorted(listed["resources"], key=lambda item: item["id"])

    collection = f"{kind}s"
    registry = yaml.safe_load((root / f"harness/registries/{collection}.yml").read_text())
    assert any(item["id"] == resource_id for item in registry[collection])
    capabilities = yaml.safe_load((root / "harness/registries/capabilities.yml").read_text())
    assert any(item["id"] == f"{kind}:system:{resource_id}" for item in capabilities["capabilities"])


def test_update_archive_restore_and_rollback_are_dry_run_first(tmp_path: Path, capsys) -> None:
    root = tmp_path / "agentic_os"
    _init(root, capsys)
    assert main(_create_args(root, "report", "weekly_review", "--apply")) == 0
    _json(capsys)

    update = [
        "resource",
        "update",
        "report",
        "weekly_review",
        "--description",
        "Updated description.",
        "--prompt",
        "Build a concise weekly review from verified sources.",
        "--root",
        str(root),
        "--json",
    ]
    assert main(update) == 0
    assert _json(capsys)["status"] == "planned"
    assert main(["resource", "get", "report", "weekly_review", "--root", str(root), "--json"]) == 0
    assert _json(capsys)["resource"]["description"] == "A governed report definition."

    assert main(_apply(update)) == 0
    updated = _json(capsys)
    assert updated["status"] == "updated"
    update_backup = updated["backup_id"]
    assert updated["readback"]["entry"]["description"] == "Updated description."

    archive = ["resource", "archive", "report", "weekly_review", "--root", str(root), "--json"]
    assert main(archive) == 0
    assert _json(capsys)["status"] == "planned"
    assert main(_apply(archive)) == 0
    assert _json(capsys)["readback"]["entry"]["status"] == "archived"

    restore = ["resource", "restore", "report", "weekly_review", "--root", str(root), "--json"]
    assert main(_apply(restore)) == 0
    assert _json(capsys)["readback"]["entry"]["status"] == "draft"

    rollback = [
        "resource",
        "rollback",
        "report",
        "weekly_review",
        "--backup-id",
        update_backup,
        "--root",
        str(root),
        "--json",
    ]
    assert main(rollback) == 0
    assert _json(capsys)["status"] == "planned"
    assert main(_apply(rollback)) == 0
    rolled_back = _json(capsys)
    assert rolled_back["status"] == "rolled_back"
    assert rolled_back["readback"]["entry"]["description"] == "A governed report definition."
    assert rolled_back["rollback_backup_id"]


@pytest.mark.parametrize(
    ("scope", "extra", "registry_suffix", "source_fragment"),
    [
        (
            "domain",
            ("--scope", "domain", "--domain", "work"),
            "work/00-control-plane/resource-registries/rules.yml",
            "work/00-control-plane/registry-resources/rule/domain_rule.md",
        ),
        (
            "project",
            ("--scope", "project", "--domain", "work", "--project", "demo_project"),
            "work/02-projects/demo_project/config/resource-registries/rules.yml",
            "work/02-projects/demo_project/config/registry-resources/rule/project_rule.md",
        ),
    ],
)
def test_scoped_targets_are_canonical_and_contained(
    tmp_path: Path,
    capsys,
    scope: str,
    extra: tuple[str, ...],
    registry_suffix: str,
    source_fragment: str,
) -> None:
    root = tmp_path / "agentic_os"
    _init(root, capsys)
    if scope == "project":
        assert main(["project", "create", "work", "demo_project", "--root", str(root)]) == 0
        capsys.readouterr()
    resource_id = "domain_rule" if scope == "domain" else "project_rule"
    assert main(_create_args(root, "rule", resource_id, *extra, "--apply")) == 0
    created = _json(capsys)
    assert created["resource"]["registry"].endswith(registry_suffix)
    assert created["resource"]["source"].endswith(source_fragment)
    assert root in Path(created["resource"]["registry"]).parents
    assert root in Path(created["resource"]["source"]).parents
    assert main(["validate", "--root", str(root), "--strict"]) == 0
    capsys.readouterr()


def test_builtin_entries_are_visible_but_read_only(tmp_path: Path, capsys) -> None:
    root = tmp_path / "agentic_os"
    _init(root, capsys)

    assert main(["resource", "get", "rule", "route-read-cd-repeat", "--root", str(root), "--json"]) == 0
    assert _json(capsys)["resource"]["mutable"] is False
    assert main(
        [
            "resource",
            "update",
            "rule",
            "route-read-cd-repeat",
            "--description",
            "Attempted change.",
            "--apply",
            "--root",
            str(root),
            "--json",
        ]
    ) == 2
    assert "read-only" in capsys.readouterr().err


@pytest.mark.parametrize("resource_id", ["../escape", "has space", "UPPER", "has-hyphen"])
def test_registry_authoring_rejects_noncanonical_ids(tmp_path: Path, capsys, resource_id: str) -> None:
    root = tmp_path / "agentic_os"
    _init(root, capsys)
    assert main(_create_args(root, "skill", resource_id)) == 2
    assert "lowercase letters, numbers, and underscores" in capsys.readouterr().err


def test_project_scope_rejects_unknown_project_and_system_rejects_domain(tmp_path: Path, capsys) -> None:
    root = tmp_path / "agentic_os"
    _init(root, capsys)
    assert main(_create_args(root, "command", "bad_scope", "--domain", "work")) == 2
    assert "system scope does not accept" in capsys.readouterr().err
    assert main(
        _create_args(
            root,
            "command",
            "missing_project",
            "--scope",
            "project",
            "--domain",
            "work",
            "--project",
            "missing",
        )
    ) == 2
    assert "unknown installed project" in capsys.readouterr().err


def test_rollback_rejects_path_like_or_cross_resource_backup_ids(tmp_path: Path, capsys) -> None:
    root = tmp_path / "agentic_os"
    _init(root, capsys)
    assert main(_create_args(root, "rule", "alpha_rule", "--apply")) == 0
    created = _json(capsys)
    assert main(_create_args(root, "rule", "beta_rule", "--apply")) == 0
    _json(capsys)

    assert main(
        [
            "resource",
            "rollback",
            "rule",
            "alpha_rule",
            "--backup-id",
            "../escape",
            "--root",
            str(root),
            "--json",
        ]
    ) == 2
    assert "invalid backup_id" in capsys.readouterr().err
    assert main(
        [
            "resource",
            "rollback",
            "rule",
            "beta_rule",
            "--backup-id",
            created["backup_id"],
            "--root",
            str(root),
            "--json",
        ]
    ) == 2
    assert "identity does not match" in capsys.readouterr().err


def test_analytics_registry_is_presentation_only_and_strictly_validated(tmp_path: Path, capsys) -> None:
    root = tmp_path / "agentic_os"
    _init(root, capsys)
    path = root / "harness/registries/analytics-metrics.yml"
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert {metric["id"] for metric in payload["metrics"]} >= {
        "queue_depth",
        "task_process_time_seconds",
        "messages",
        "workers",
        "token_count",
        "chats_by_harness",
        "automation_runs",
        "errors",
        "tool_runs",
    }
    serialized = yaml.safe_dump(payload)
    for forbidden in ("query:", "sql:", "command:", "path:", "url:"):
        assert forbidden not in serialized
    assert main(["validate", "--root", str(root), "--strict"]) == 0
    capsys.readouterr()

    payload["metrics"][0]["query"] = "select * from runtime"
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    assert main(["validate", "--root", str(root), "--strict"]) == 1
    assert "analytics-metrics.schema.json" in capsys.readouterr().err


def test_canonical_target_rejects_symlink_escape(tmp_path: Path, capsys) -> None:
    root = tmp_path / "agentic_os"
    _init(root, capsys)
    outside = tmp_path / "outside"
    outside.mkdir()
    reports = root / "harness/reports"
    reports.rmdir()
    reports.symlink_to(outside, target_is_directory=True)

    assert main(_create_args(root, "report", "escaped_report", "--apply")) == 2
    assert "escaped the installed root" in capsys.readouterr().err
    assert list(outside.iterdir()) == []
