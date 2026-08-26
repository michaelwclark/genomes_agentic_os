from __future__ import annotations

from pathlib import Path
import shutil

import yaml

from genomes_agentic_os import execution_fabric_remote
from genomes_agentic_os.runtime_snapshot import build_runtime_snapshot


SOURCE_ROOT = Path(__file__).parents[1]


def _remote_root(tmp_path: Path) -> Path:
    root = tmp_path / "agentic_os"
    config_path = root / "harness/config/execution-fabric.yml"
    config_path.parent.mkdir(parents=True)
    shutil.copy2(SOURCE_ROOT / "harness/config/execution-fabric.yml", config_path)
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    config["execution_fabric"]["transport"] = {
        "mode": "remote",
        "control_plane_url": "http://127.0.0.1:3180",
        "request_timeout_seconds": 5,
        "long_poll_seconds": 1,
        "submit_token_env": "TEST_FABRIC_SUBMIT_TOKEN",
        "worker_token_env": "TEST_FABRIC_WORKER_TOKEN",
        "observer_token_env": "TEST_FABRIC_OBSERVER_TOKEN",
    }
    config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    return root


def test_backend_neutral_snapshot_routes_remote_mode_through_the_service_projection(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root = _remote_root(tmp_path)
    monkeypatch.setenv("TEST_FABRIC_SUBMIT_TOKEN", "not-a-real-submit-token")
    monkeypatch.setenv("TEST_FABRIC_WORKER_TOKEN", "not-a-real-worker-token")
    monkeypatch.setenv("TEST_FABRIC_OBSERVER_TOKEN", "not-a-real-observer-token")
    observed: dict[str, int] = {}

    def fake_remote_snapshot(_root, *, limit, task_id=None):
        observed["limit"] = limit
        observed["task_id"] = task_id
        return {
            "schema_version": "agentic-os-runtime-snapshot/v1",
            "captured_at": "2026-07-24T18:00:00Z",
            "root": str(root),
            "queue_mode": "execution_fabric",
            "consistency": "remote_api_snapshot",
            "queues": [
                {
                    "queue_name": "codex",
                    "statuses": {"queued": 1, "running": 1},
                    "total": 2,
                    "depth": 1,
                    "running": 1,
                    "failed": 0,
                    "dead_letter": 0,
                }
            ],
            "workers": [],
            "tasks": [
                {"id": "waiting", "status": "queued", "queue_name": "codex", "worker_pool": "codex_workers"},
                {"id": "running", "status": "running", "queue_name": "codex", "worker_pool": "codex_workers"},
            ],
            "summary": {
                "queued": 1,
                "running": 1,
                "succeeded": 4,
                "failed": 0,
                "dead_lettered": 0,
                "registered_workers": 0,
                "active_workers": 0,
                "unhealthy_worker_count": 0,
            },
            "control_plane": {"transport": "remote", "active_host": "genomesbox"},
            "alarms": [],
            "recent_run_reports": [],
        }

    monkeypatch.setattr(
        execution_fabric_remote,
        "build_remote_runtime_snapshot",
        fake_remote_snapshot,
    )

    snapshot = build_runtime_snapshot(
        root,
        queue_name="codex",
        statuses=["queued"],
        task_limit=20,
        task_id="task-waiting",
    )

    assert observed["limit"] == 20
    assert observed["task_id"] == "task-waiting"
    assert snapshot["consistency"] == "remote_api_snapshot"
    assert snapshot["health"] == "healthy"
    assert snapshot["summary"]["done"] == 4
    assert snapshot["summary"]["max_interactive_running"] == 1
    assert snapshot["filters"]["matching_tasks"] == 1
    assert [task["id"] for task in snapshot["tasks"]] == ["waiting"]
    assert [task["id"] for task in snapshot["running_tasks"]] == ["running"]
