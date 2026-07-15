from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from genomes_agentic_os.cli import main


def _init(root: Path, capsys) -> None:
    assert main(["init", "--target", str(root)]) == 0
    capsys.readouterr()
    assert main(["runtime", "init", "--root", str(root)]) == 0
    capsys.readouterr()


def _json_output(capsys) -> dict:
    return json.loads(capsys.readouterr().out)


def _registry_path(root: Path) -> Path:
    return root / "harness/shared_factory/00-control-plane/runtime-registry.yml"


def _schedule(root: Path, schedule_id: str) -> dict:
    registry = yaml.safe_load(_registry_path(root).read_text(encoding="utf-8"))
    return next(item for item in registry["schedules"] if item["id"] == schedule_id)


def test_schedule_list_get_and_json_contract(tmp_path: Path, capsys) -> None:
    root = tmp_path / "agentic_os"
    _init(root, capsys)

    assert main(["schedule", "list", "--root", str(root), "--json"]) == 0
    listed = _json_output(capsys)
    assert listed["api_version"] == "resource-actions/v1"
    assert listed["action"] == "schedule.list"
    assert listed["count"] == len(listed["schedules"])
    assert listed["schedules"] == sorted(listed["schedules"], key=lambda item: item["id"])

    assert main(["schedule", "get", "daily_agentic_os_doctor", "--root", str(root), "--json"]) == 0
    fetched = _json_output(capsys)
    assert fetched["resource"]["id"] == "daily_agentic_os_doctor"
    assert fetched["validation"]["normalized"]["execution_target"] == "script"


def test_schedule_create_preserves_legacy_apply_and_supports_explicit_dry_run(tmp_path: Path, capsys) -> None:
    root = tmp_path / "agentic_os"
    _init(root, capsys)

    assert main(["schedule", "create", "planned_only", "--root", str(root), "--dry-run", "--json"]) == 0
    planned = _json_output(capsys)
    assert planned["status"] == "planned"
    assert all(item["id"] != "planned_only" for item in yaml.safe_load(_registry_path(root).read_text())["schedules"])

    assert main(["schedule", "create", "legacy_apply", "--root", str(root), "--cadence", "weekly"]) == 0
    capsys.readouterr()
    assert _schedule(root, "legacy_apply")["cadence"] == "weekly"
    assert _schedule(root, "legacy_apply")["enabled"] is True

    assert main(["schedule", "create", "governed_apply", "--root", str(root), "--apply", "--json"]) == 0
    governed = _json_output(capsys)
    assert governed["readback"]["schedule"]["enabled"] is False

    receipts = root / "harness/shared_factory/06-runs-and-logs/resource-actions"
    assert list((receipts / "backups").glob("runtime-registry-*.yml"))
    assert list(receipts.glob("*-schedule-legacy_apply-create.yml"))


def test_schedule_update_enable_disable_and_delete_are_guarded_and_read_back(tmp_path: Path, capsys) -> None:
    root = tmp_path / "agentic_os"
    _init(root, capsys)
    assert main(["schedule", "create", "ui_refresh", "--root", str(root), "--disabled"]) == 0
    capsys.readouterr()

    assert main(
        [
            "schedule",
            "update",
            "ui_refresh",
            "--root",
            str(root),
            "--cadence",
            "daily",
            "--local-time",
            "06:30",
            "--dry-run",
            "--json",
        ]
    ) == 0
    planned = _json_output(capsys)
    assert planned["status"] == "planned"
    assert _schedule(root, "ui_refresh")["cadence"] == "manual"

    assert main(
        [
            "schedule",
            "update",
            "ui_refresh",
            "--root",
            str(root),
            "--cadence",
            "daily",
            "--local-time",
            "06:30",
            "--apply",
            "--json",
        ]
    ) == 0
    updated = _json_output(capsys)
    assert updated["status"] == "updated"
    assert updated["readback"]["ok"] is True
    assert updated["readback"]["schedule"]["local_time"] == "06:30"
    assert Path(updated["backup"]).is_file()
    assert Path(updated["receipt"]).is_file()

    assert main(["schedule", "enable", "ui_refresh", "--root", str(root), "--apply", "--json"]) == 0
    assert _json_output(capsys)["readback"]["schedule"]["enabled"] is True
    assert main(["schedule", "delete", "ui_refresh", "--root", str(root), "--apply", "--json"]) == 2
    assert "must be disabled" in capsys.readouterr().err

    assert main(["schedule", "disable", "ui_refresh", "--root", str(root), "--apply", "--json"]) == 0
    _json_output(capsys)
    assert main(["schedule", "delete", "ui_refresh", "--root", str(root), "--dry-run", "--json"]) == 0
    assert _json_output(capsys)["status"] == "planned"
    assert _schedule(root, "ui_refresh")["id"] == "ui_refresh"
    assert main(["schedule", "delete", "ui_refresh", "--root", str(root), "--apply", "--json"]) == 0
    deleted = _json_output(capsys)
    assert deleted["status"] == "deleted"
    assert deleted["readback"] == {"ok": True, "schedule": None}


def test_queue_now_never_dispatches_and_delete_refuses_active_queue_ref(tmp_path: Path, capsys, monkeypatch) -> None:
    root = tmp_path / "agentic_os"
    _init(root, capsys)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("queue-now must never launch a process")

    monkeypatch.setattr("subprocess.run", forbidden)
    assert main(
        ["schedule", "queue-now", "daily_agentic_os_doctor", "--root", str(root), "--dry-run", "--json"]
    ) == 0
    planned = _json_output(capsys)
    assert planned["queue_item"]["dispatch_performed"] is False
    queue_path = root / "harness/shared_factory/00-control-plane/run-queue.yml"
    assert yaml.safe_load(queue_path.read_text())["items"] == []

    assert main(
        ["schedule", "queue-now", "daily_agentic_os_doctor", "--root", str(root), "--apply", "--json"]
    ) == 0
    queued = _json_output(capsys)
    assert queued["status"] == "queued"
    assert queued["external_effects"] == "none; item was not dispatched"
    queue = yaml.safe_load(queue_path.read_text())
    assert queue["items"][0]["ref"] == "daily_agentic_os_doctor"
    assert queue["items"][0]["status"] == "queued"

    assert main(["schedule", "disable", "daily_agentic_os_doctor", "--root", str(root), "--apply", "--json"]) == 0
    _json_output(capsys)
    assert main(
        ["schedule", "delete", "daily_agentic_os_doctor", "--root", str(root), "--apply", "--json"]
    ) == 2
    assert "active run-queue" in capsys.readouterr().err


def test_resource_create_is_dry_run_by_default_and_validates_supported_kinds(tmp_path: Path, capsys) -> None:
    root = tmp_path / "agentic_os"
    _init(root, capsys)

    assert main(["resource", "create", "program", "command_center", "--root", str(root), "--json"]) == 0
    planned = _json_output(capsys)
    assert planned["status"] == "planned"
    assert not Path(planned["resource"]["path"]).exists()

    assert main(
        ["resource", "create", "program", "command_center", "--root", str(root), "--apply", "--json"]
    ) == 0
    created = _json_output(capsys)
    assert created["status"] == "created"
    assert created["validation"]["ok"] is True
    assert Path(created["resource"]["path"]).is_dir()
    assert main(["resource", "validate", "program", "command_center", "--root", str(root), "--json"]) == 0
    assert _json_output(capsys)["ok"] is True

    assert main(
        [
            "resource",
            "create",
            "workflow",
            "operator_review",
            "--domain",
            "work",
            "--lane",
            "engineering",
            "--root",
            str(root),
            "--apply",
            "--json",
        ]
    ) == 0
    workflow = _json_output(capsys)
    assert workflow["readback"]["ok"] is True
    assert workflow["validation"]["resource"]["kind"] == "workflow"


@pytest.mark.parametrize("invalid_id", ["UPPER", "has-hyphen", "has space", "../escape"])
def test_resource_actions_reject_invalid_identifiers(tmp_path: Path, capsys, invalid_id: str) -> None:
    root = tmp_path / "agentic_os"
    _init(root, capsys)
    assert main(["schedule", "get", invalid_id, "--root", str(root), "--json"]) == 2
    assert "lowercase letters, numbers, and underscores" in capsys.readouterr().err
