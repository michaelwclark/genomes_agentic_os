from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import subprocess

import yaml

from genomes_agentic_os.runtime_backend import apply_queue_mode, runtime_queue_items
from genomes_agentic_os.runtime_health import (
    build_runtime_health,
    notify_runtime_health,
    queue_runtime_self_heal,
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
        {
            "id": "retrying",
            "status": "queued",
            "ref": "provider",
            "attempts": 1,
            "due_at": "2026-07-14T06:05:00Z",
        },
    ]
    queue_path.write_text(yaml.safe_dump(queue, sort_keys=False), encoding="utf-8")
    report = build_runtime_health(
        root,
        now=datetime(2026, 7, 14, 6, 0, tzinfo=timezone.utc),
        launchctl_runner=_launchctl(),
    )
    assert report["status"] == "critical"
    assert report["queue"]["total_records"] == 4
    assert report["queue"]["queued"] == 3
    assert report["queue"]["retrying"] == 1
    assert report["queue"]["delayed_retries"] == 1
    assert report["queue"]["stale_queued_over_24h"] == 1
    assert report["queue"]["top_backlogs"] == [
        {"ref": "watcher", "queued": 2},
        {"ref": "provider", "queued": 1},
    ]


def test_runtime_health_writes_json_and_markdown(tmp_path: Path) -> None:
    root = tmp_path / "os"
    runtime_init(root)
    log = root / "harness/shared_factory/06-runs-and-logs/supervisor.out.log"
    log.write_text("tick\n", encoding="utf-8")
    report = build_runtime_health(root, launchctl_runner=_launchctl())
    paths = write_runtime_health(root, report)
    assert Path(paths["latest_json"]).is_file()
    assert Path(paths["latest_markdown"]).read_text(encoding="utf-8") == render_runtime_health(report)


def test_long_running_worker_is_healthy_inside_declared_budget(tmp_path: Path) -> None:
    root = tmp_path / "os"
    runtime_init(root)
    now = datetime.now(timezone.utc)
    log = root / "harness/shared_factory/06-runs-and-logs/supervisor.out.log"
    log.write_text("tick\n", encoding="utf-8")
    queue_path = root / "harness/shared_factory/00-control-plane/run-queue.yml"
    queue = yaml.safe_load(queue_path.read_text(encoding="utf-8"))
    queue["items"] = [
        {
            "id": "long-but-bounded",
            "status": "running",
            "ref": "bounded-worker",
            "started_at": (now - timedelta(hours=2)).isoformat(),
            "timeout_seconds": 4 * 3600,
        }
    ]
    queue_path.write_text(yaml.safe_dump(queue, sort_keys=False), encoding="utf-8")

    report = build_runtime_health(root, now=now, launchctl_runner=_launchctl())

    assert report["status"] == "healthy"
    assert report["workers"]["stale_running_over_budget"] == 0


def test_default_health_and_prune_schedules_use_priority_dispatch(
    tmp_path: Path,
) -> None:
    root = tmp_path / "os"
    runtime_init(root)
    registry = yaml.safe_load(
        (root / "harness/shared_factory/00-control-plane/runtime-registry.yml").read_text(encoding="utf-8")
    )
    schedules = {item["id"]: item for item in registry["schedules"]}
    assert schedules["queue_worker_health_report"]["enabled"] is True
    assert schedules["queue_worker_health_report"]["cadence"] == "hourly"
    assert schedules["queue_worker_health_report"]["supervisor_priority"] is True
    assert schedules["run_queue_prune_daily"]["supervisor_priority"] is True
    assert schedules["adaptive_routing_observation_report"]["supervisor_priority"] is True


def test_health_report_command_passes_local_dispatch_preflight(tmp_path: Path) -> None:
    root = tmp_path / "os"
    runtime_init(root)
    command = "agentic-os runtime health-report --root <root> --apply-remediation --notify"
    assert _local_script_dispatch_preflight(root, command) is None


def test_runtime_init_upgrades_required_health_enforcement_schedule(tmp_path: Path) -> None:
    root = tmp_path / "os"
    runtime_init(root)
    registry_path = root / "harness/shared_factory/00-control-plane/runtime-registry.yml"
    registry = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    schedule = next(item for item in registry["schedules"] if item["id"] == "queue_worker_health_report")
    schedule.update({"enabled": False, "command": "old-health-command", "notion_update": {"workspace": "legacy"}})
    registry_path.write_text(yaml.safe_dump(registry, sort_keys=False), encoding="utf-8")

    result = runtime_init(root)
    upgraded = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    schedule = next(item for item in upgraded["schedules"] if item["id"] == "queue_worker_health_report")

    assert result["runtime_defaults"]["changed"] is True
    assert schedule["enabled"] is True
    assert schedule["command"].endswith("--apply-remediation --notify")
    assert "notion_update" not in schedule


def test_interim_executor_is_queue_only_compatibility_shim() -> None:
    script = (Path(__file__).parents[1] / "harness/bin/agentic-os-interim-executor").read_text(encoding="utf-8")
    assert '\"runtime\", \"supervise\"' in script
    assert 'shutil.which("agentic-os")' in script
    assert 'args.root / "harness/bin/agentic-os"' not in script
    assert "interim_execute" not in script
    assert "run_schedule" not in script


def test_unhealthy_report_queues_one_codex_self_heal_and_notifies(tmp_path: Path) -> None:
    root = tmp_path / "os"
    runtime_init(root)
    apply_queue_mode(root, "execution_fabric", dry_run=False)
    report = build_runtime_health(root, launchctl_runner=_launchctl(returncode=1))
    paths = write_runtime_health(root, report)

    first = queue_runtime_self_heal(root, report, paths)
    second = queue_runtime_self_heal(root, report, paths)
    calls: list[list[str]] = []

    def runner(command, **_kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, "", "")

    notification = notify_runtime_health(root, report, runner=runner)
    items = [item for item in runtime_queue_items(root) if item.get("kind") == "runtime_self_heal"]

    assert report["status"] == "critical"
    assert first["queued"] is True
    assert second["queued"] is False
    assert len(items) == 1
    assert items[0]["queue_name"] == "codex"
    assert items[0]["worker_pool"] == "codex_workers"
    assert items[0]["execution_target"] == "codex_harness"
    assert items[0]["worker_materialized"] is True
    assert items[0]["command"].startswith("codex exec --cd")
    assert "--ephemeral --json" in items[0]["command"]
    assert notification["sent"] is True
    assert "runtime.execution_fabric.health" in calls[0]
    assert "--dedupe-key" in calls[0]
