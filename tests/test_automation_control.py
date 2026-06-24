from __future__ import annotations

from pathlib import Path

import yaml

from genomes_agentic_os.automation_control import CONTROL_CONFIG, run_automation_control
from genomes_agentic_os.cli import main
from genomes_agentic_os.runtime_ops import runtime_run_next


def _fresh_root(tmp_path: Path) -> Path:
    root = tmp_path / "agentic_os"
    assert main(["init", "--target", str(root)]) == 0
    assert main(["runtime", "init", "--root", str(root)]) == 0
    return root


def _write_watch_source(root: Path) -> None:
    path = root / "harness/shared_factory/00-control-plane/watch-sources.yml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(
            {
                "watch_sources": [
                    {
                        "id": "los_auto_dev_queue_start",
                        "display_name": "LOS Auto Dev Queue Start rows",
                        "connected_system": "notion_genome",
                        "source_type": "notion_database",
                        "external_ref": {"database_id": "db1", "data_source_url": "collection://ds1"},
                        "watch_method": "poll",
                        "cadence": "manual",
                        "enabled": True,
                        "cursor": {
                            "type": "notion_page_status_cursor",
                            "state_ref": "harness/shared_factory/00-control-plane/watch-cursors.yml",
                        },
                        "dedupe": {"idempotency_key": "{source_type}:{source_id}:{event_id}"},
                        "filters": {
                            "status_field": "Status",
                            "status_value": "Queue Start",
                            "skip_states": ["Running", "Watching PR", "Ready for Merge", "Done"],
                        },
                        "trigger_rules": [],
                        "route": {
                            "command": "agentic-os route",
                            "context_command": "agentic-os context build",
                            "fallback_domain": "los/00-programs/auto_dev_queue",
                        },
                        "outputs": {
                            "source_events_dir": "harness/shared_factory/06-runs-and-logs/source-events",
                            "run_queue_ref": "harness/shared_factory/00-control-plane/run-queue.yml",
                        },
                    }
                ]
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )


def _write_control(root: Path, rows: list[dict]) -> None:
    path = root / CONTROL_CONFIG
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "enabled": True,
                "managed_automations": [
                    {
                        "id": "auto_dev_queue",
                        "display_name": "Auto Dev Queue",
                        "enabled": True,
                        "source_probe": {
                            "type": "notion_queue",
                            "watch_source_id": "los_auto_dev_queue_start",
                            "status_field": "Status",
                            "actionable_statuses": ["Queue Start"],
                            "in_flight_statuses": ["Running", "Watching PR", "Ready for Merge"],
                            "max_in_flight": 3,
                            "fixture_items": rows,
                        },
                        "target": {
                            "execution_target": "script",
                            "command": "agentic-os watch-source poll los_auto_dev_queue_start --root <root> --apply",
                        },
                        "idempotency_key": "automation_control:{automation_id}:{source_id}:{source_digest}",
                    }
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )


def test_automation_control_config_installed_by_default(tmp_path: Path) -> None:
    root = _fresh_root(tmp_path)
    assert (root / CONTROL_CONFIG).is_file()
    assert main(["automation-control", "list", "--root", str(root)]) == 0


def test_automation_control_idle_does_not_enqueue(tmp_path: Path) -> None:
    root = _fresh_root(tmp_path)
    _write_watch_source(root)
    _write_control(root, [{"id": "page1", "last_edited_time": "2026-06-22T00:00:00Z", "Status": "Done"}])

    result = run_automation_control(root, dry_run=False)

    assert result["actions"][0]["decision"] == "idle"
    assert result["actions"][0]["action"] == "none"
    queue = yaml.safe_load((root / "harness/shared_factory/00-control-plane/run-queue.yml").read_text())
    assert queue["items"] == []


def test_automation_control_ready_enqueues_once(tmp_path: Path) -> None:
    root = _fresh_root(tmp_path)
    _write_watch_source(root)
    _write_control(root, [{"id": "page1", "last_edited_time": "2026-06-22T00:00:00Z", "Status": "Queue Start"}])

    first = run_automation_control(root, dry_run=False)
    second = run_automation_control(root, dry_run=False)

    assert first["actions"][0]["decision"] == "ready"
    assert first["actions"][0]["action"] == "enqueued"
    assert second["actions"][0]["action"] == "already_queued"
    queue = yaml.safe_load((root / "harness/shared_factory/00-control-plane/run-queue.yml").read_text())
    assert len(queue["items"]) == 1
    assert queue["items"][0]["kind"] == "automation_control"


def test_automation_control_cli_apply_enqueues(tmp_path: Path) -> None:
    root = _fresh_root(tmp_path)
    _write_watch_source(root)
    _write_control(root, [{"id": "page1", "last_edited_time": "2026-06-22T00:00:00Z", "Status": "Queue Start"}])

    assert main(["automation-control", "run", "--root", str(root), "--apply"]) == 0

    queue = yaml.safe_load((root / "harness/shared_factory/00-control-plane/run-queue.yml").read_text())
    assert len(queue["items"]) == 1
    assert queue["items"][0]["kind"] == "automation_control"


def test_automation_control_capacity_saturation_does_not_enqueue(tmp_path: Path) -> None:
    root = _fresh_root(tmp_path)
    _write_watch_source(root)
    _write_control(
        root,
        [
            {"id": "page1", "last_edited_time": "2026-06-22T00:00:00Z", "Status": "Queue Start"},
            {"id": "page2", "last_edited_time": "2026-06-22T00:00:00Z", "Status": "Running"},
            {"id": "page3", "last_edited_time": "2026-06-22T00:00:00Z", "Status": "Watching PR"},
            {"id": "page4", "last_edited_time": "2026-06-22T00:00:00Z", "Status": "Ready for Merge"},
        ],
    )

    result = run_automation_control(root, dry_run=False)

    assert result["actions"][0]["decision"] == "running"
    assert result["actions"][0]["action"] == "none"


def test_runtime_can_dispatch_controller_and_watch_source_commands(tmp_path: Path) -> None:
    root = _fresh_root(tmp_path)
    _write_watch_source(root)
    _write_control(root, [])
    command = f"agentic-os automation-control run --root {root} --apply"
    queue_item = {
        "id": "queue_controller",
        "kind": "schedule",
        "ref": "automation_control_tick",
        "status": "queued",
        "approval_state": "not_required",
        "execution_target": "script",
        "command": command,
        "idempotency_key": "schedule:automation_control_tick:test",
    }
    queue_path = root / "harness/shared_factory/00-control-plane/run-queue.yml"
    queue = yaml.safe_load(queue_path.read_text())
    queue["items"] = [queue_item]
    queue["run_queue"] = [queue_item]
    queue_path.write_text(yaml.safe_dump(queue, sort_keys=False), encoding="utf-8")

    result = runtime_run_next(root, dry_run=False)

    assert result["status"] == "done"
    assert result["queue_item"]["status"] == "done"
