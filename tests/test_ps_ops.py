from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path

import yaml

from genomes_agentic_os.cli import main
from genomes_agentic_os.ps_ops import format_ps_result, ps_snapshot


def _fresh_root(tmp_path: Path) -> Path:
    root = tmp_path / "agentic_os"
    assert main(["init", "--target", str(root)]) == 0
    assert main(["runtime", "init", "--root", str(root)]) == 0
    return root


def _active_work_item(root: Path) -> Path:
    assert main(["project", "create", "shared_factory", "genomes_agentic_os", "--root", str(root)]) == 0
    assert (
        main(
            [
                "project",
                "work-item",
                "create",
                "shared_factory",
                "genomes_agentic_os",
                "--root",
                str(root),
                "--title",
                "PS Runtime View",
                "--summary",
                "Exercise process-style runtime inventory.",
                "--status",
                "building",
                "--format",
                "packet",
            ]
        )
        == 0
    )
    active_root = root / "harness" / "shared_factory" / "02-projects" / "genomes_agentic_os" / "work-items" / "02-active"
    return next(path for path in active_root.iterdir() if path.is_dir())


def _age_files(path: Path, *, days: int) -> None:
    old = (datetime.now(timezone.utc) - timedelta(days=days)).timestamp()
    for child in path.rglob("*"):
        if child.is_file():
            os.utime(child, (old, old))


def _seed_runtime_state(root: Path) -> None:
    control = root / "harness" / "shared_factory" / "00-control-plane"
    registry_path = control / "runtime-registry.yml"
    registry = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    for schedule in registry["schedules"]:
        schedule["enabled"] = schedule["id"] == "daily_agentic_os_doctor"
        schedule["next_due_at"] = "2026-01-01T00:00:00Z"
    registry_path.write_text(yaml.safe_dump(registry, sort_keys=False), encoding="utf-8")

    queue_path = control / "run-queue.yml"
    queue = yaml.safe_load(queue_path.read_text(encoding="utf-8"))
    queue["items"] = [
        {
            "id": "queue_ps_queued",
            "kind": "schedule",
            "ref": "daily_agentic_os_doctor",
            "status": "queued",
            "approval_state": "not_required",
            "created_at": "2026-06-27T00:00:00Z",
            "execution_target": "script",
            "command": "agentic-os validate --root <root>",
        },
        {
            "id": "queue_ps_running",
            "kind": "schedule",
            "ref": "running_doctor",
            "status": "running",
            "approval_state": "not_required",
            "created_at": "2026-06-27T00:01:00Z",
            "execution_target": "script",
            "command": "agentic-os doctor --root <root>",
        }
    ]
    queue["run_queue"] = queue["items"]
    queue_path.write_text(yaml.safe_dump(queue, sort_keys=False), encoding="utf-8")

    (control / "watch-sources.yml").write_text(
        yaml.safe_dump(
            {
                "watch_sources": [
                    {
                        "id": "ps_watch",
                        "display_name": "PS Watch",
                        "enabled": True,
                        "source_type": "filesystem_glob",
                        "connected_system": "filesystem_local",
                        "cadence": "manual",
                    }
                ]
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (control / "automation-control.yml").write_text(
        yaml.safe_dump(
            {
                "managed_automations": [
                    {
                        "id": "ps_automation",
                        "enabled": True,
                        "target": {"command": "agentic-os watch-source poll ps_watch --root <root> --apply"},
                        "source_probe": {"type": "fixture", "source_id": "ps_watch"},
                    }
                ]
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )


def test_ps_snapshot_rolls_up_active_runtime_surfaces(tmp_path: Path) -> None:
    root = _fresh_root(tmp_path)
    _active_work_item(root)
    _seed_runtime_state(root)

    default_snapshot = ps_snapshot(root, stale_days=999)
    assert {row["status"] for row in default_snapshot["rows"]} == {"running"}
    assert default_snapshot["counts"]["by_kind"]["queue"] == 1

    snapshot = ps_snapshot(root, mode="active", stale_days=999)
    kinds = {row["kind"] for row in snapshot["rows"]}

    assert {"automation", "queue", "schedule", "watch", "workflow"}.issubset(kinds)
    assert snapshot["counts"]["by_kind"]["queue"] == 2
    assert any(row["status"] == "due" and row["id"] == "daily_agentic_os_doctor" for row in snapshot["rows"])


def test_ps_cli_json_includes_thread_candidates(tmp_path: Path, capsys) -> None:
    root = _fresh_root(tmp_path)
    work_item = _active_work_item(root)
    _seed_runtime_state(root)
    _age_files(work_item, days=5)
    capsys.readouterr()

    assert main(["ps", "--root", str(root), "--active", "--json", "--stale-days", "3"]) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["counts"]["by_kind"]["thread"] == 1
    assert any(row["kind"] == "thread" and row["status"] == "stale" for row in payload["rows"])


def test_ps_table_groups_and_colorizes(tmp_path: Path) -> None:
    root = _fresh_root(tmp_path)
    _seed_runtime_state(root)
    snapshot = ps_snapshot(root)

    plain = format_ps_result(snapshot)
    colored = format_ps_result(snapshot, color=True)

    assert "RUNNING NOW" in plain
    assert "running_doctor" in plain
    assert "\033[" in colored
