from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import subprocess

import yaml

from genomes_agentic_os.runtime_health import (
    build_runtime_health,
    render_runtime_health,
    write_runtime_health,
)
from genomes_agentic_os.runtime_ops import (
    _local_script_dispatch_preflight,
    runtime_init,
)


def _launchctl(*, exit_code: int = 0, returncode: int = 0):
    def run() -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            ["launchctl"],
            returncode,
            stdout=f"state = not running\nlast exit code = {exit_code}\n",
            stderr="",
        )

    return run


def test_runtime_health_distinguishes_terminal_history_from_stale_queue(
    tmp_path: Path,
) -> None:
    root = tmp_path / "os"
    runtime_init(root)
    log = root / "harness/shared_factory/06-runs-and-logs/supervisor.out.log"
    log.write_text("tick\n", encoding="utf-8")
    queue_path = root / "harness/shared_factory/00-control-plane/run-queue.yml"
    queue = yaml.safe_load(queue_path.read_text(encoding="utf-8"))
    queue["items"] = [
        {
            "id": "done",
            "status": "done",
            "ref": "history",
            "updated_at": "2026-07-14T05:30:00Z",
        },
        {
            "id": "stale",
            "status": "queued",
            "ref": "watcher",
            "due_at": "2026-07-12T00:00:00Z",
        },
        {
            "id": "fresh",
            "status": "queued",
            "ref": "watcher",
            "due_at": "2026-07-14T05:45:00Z",
        },
    ]
    queue_path.write_text(yaml.safe_dump(queue, sort_keys=False), encoding="utf-8")
    report = build_runtime_health(
        root,
        now=datetime(2026, 7, 14, 6, 0, tzinfo=timezone.utc),
        launchctl_runner=_launchctl(),
    )
    assert report["status"] == "critical"
    assert report["queue"]["total_records"] == 3
    assert report["queue"]["queued"] == 2
    assert report["queue"]["stale_queued_over_24h"] == 1
    assert report["queue"]["top_backlogs"] == [{"ref": "watcher", "queued": 2}]


def test_runtime_health_writes_json_and_markdown(tmp_path: Path) -> None:
    root = tmp_path / "os"
    runtime_init(root)
    log = root / "harness/shared_factory/06-runs-and-logs/supervisor.out.log"
    log.write_text("tick\n", encoding="utf-8")
    report = build_runtime_health(root, launchctl_runner=_launchctl())
    paths = write_runtime_health(root, report)
    assert Path(paths["latest_json"]).is_file()
    assert Path(paths["latest_markdown"]).read_text(encoding="utf-8") == render_runtime_health(report)


def test_default_health_and_prune_schedules_use_priority_dispatch(
    tmp_path: Path,
) -> None:
    root = tmp_path / "os"
    runtime_init(root)
    registry = yaml.safe_load(
        (root / "harness/shared_factory/00-control-plane/runtime-registry.yml").read_text(encoding="utf-8")
    )
    schedules = {item["id"]: item for item in registry["schedules"]}
    assert schedules["queue_worker_health_report"]["enabled"] is False
    assert schedules["queue_worker_health_report"]["cadence"] == "hourly"
    assert schedules["queue_worker_health_report"]["supervisor_priority"] is True
    assert schedules["run_queue_prune_daily"]["supervisor_priority"] is True
    assert schedules["adaptive_routing_observation_report"]["supervisor_priority"] is True


def test_health_report_command_passes_local_dispatch_preflight(tmp_path: Path) -> None:
    root = tmp_path / "os"
    runtime_init(root)
    command = "agentic-os runtime health-report --root <root> --apply-notion"
    assert _local_script_dispatch_preflight(root, command) is None
