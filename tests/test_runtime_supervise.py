from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import time

import pytest
import yaml

from genomes_agentic_os import runtime_ops, supervisor
from genomes_agentic_os.cli import main
from genomes_agentic_os.runtime_backend import apply_queue_mode, runtime_queue_items
from genomes_agentic_os.runtime_ops import runtime_doctor, runtime_run_latest_by_ref, runtime_run_next
from genomes_agentic_os.supervisor import supervise_tick

STEP_NAMES = {"heartbeats", "schedules", "watch_sources", "events", "priority_run_queue", "run_queue", "health"}


def _fresh_root(tmp_path: Path) -> Path:
    root = tmp_path / "agentic_os"
    assert main(["init", "--target", str(root)]) == 0
    assert main(["runtime", "init", "--root", str(root)]) == 0
    return root


def test_supervise_dry_run_reports_every_step(tmp_path: Path) -> None:
    root = _fresh_root(tmp_path)
    report = supervise_tick(root, dry_run=True)

    assert report["dry_run"] is True
    assert report["ok"] is True
    assert {step["step"] for step in report["steps"]} == STEP_NAMES
    # Health is always collected and is read-only.
    health = next(step for step in report["steps"] if step["step"] == "health")
    assert "ok" in health
    # The CLI command exits 0 on a clean tick.
    assert main(["runtime", "supervise", "--root", str(root)]) == 0


def test_supervise_apply_runs_the_tick(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _fresh_root(tmp_path)
    monkeypatch.setattr(
        runtime_ops,
        "_run_local_script",
        lambda _root, command, **_kwargs: {
            "supported": True,
            "ok": True,
            "command": command,
            "errors": [],
            "warnings": [],
            "external_effect": "stubbed local test dispatch",
        },
    )
    report = supervise_tick(root, dry_run=False)
    assert report["dry_run"] is False
    assert report["ok"] is True
    assert main(["runtime", "supervise", "--root", str(root), "--apply"]) == 0


def test_schedule_producer_materializes_provider_route_before_fabric_enqueue(tmp_path: Path) -> None:
    root = _fresh_root(tmp_path)
    wrapper = root / "automations/run-codex.sh"
    wrapper.parent.mkdir(parents=True)
    wrapper.write_text("#!/usr/bin/env bash\nexec codex exec 'scheduled work'\n", encoding="utf-8")
    registry_path = root / "harness/shared_factory/00-control-plane/runtime-registry.yml"
    registry = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    registry["schedules"].append(
        {
            "id": "provider_schedule",
            "display_name": "Provider schedule",
            "enabled": True,
            "cadence": "hourly",
            "timezone": "America/Chicago",
            "execution_target": "script",
            "supervisor_priority": True,
            "command": str(wrapper),
            "next_due_at": "2000-01-01T00:00:00Z",
            "last_queued_at": None,
        }
    )
    registry_path.write_text(yaml.safe_dump(registry, sort_keys=False), encoding="utf-8")
    apply_queue_mode(root, "execution_fabric", dry_run=False)

    result = runtime_ops.schedule_run_due(root, dry_run=False)
    queued = next(item for item in runtime_queue_items(root) if item.get("ref") == "provider_schedule")

    assert result["status"] == "queued"
    assert queued["queue_name"] == "codex"
    assert queued["worker_pool"] == "codex_workers"
    assert queued["priority"] == 100
    assert queued["provider_inferred_from_command"] is True


def test_runtime_dispatches_watch_source_poll_command(tmp_path: Path, capsys) -> None:
    root = _fresh_root(tmp_path)
    assert (
        main(
            [
                "watch-source",
                "create",
                "auto_dev_queue_start",
                "--root",
                str(root),
                "--enabled",
                "--display-name",
                "Auto Dev Queue Start",
            ]
        )
        == 0
    )
    queue_path = root / "harness" / "shared_factory" / "00-control-plane" / "run-queue.yml"
    queue = yaml.safe_load(queue_path.read_text(encoding="utf-8"))
    item = {
        "id": "queue_watch_source_poll",
        "kind": "schedule",
        "ref": "auto_dev_queue_watch",
        "status": "queued",
        "approval_state": "not_required",
        "created_at": "2026-06-19T00:00:00Z",
        "idempotency_key": "test:watch-source-poll",
        "execution_target": "script",
        "command": f"agentic-os watch-source poll auto_dev_queue_start --root {root} --apply",
    }
    queue.setdefault("items", []).append(item)
    queue["run_queue"] = queue["items"]
    queue_path.write_text(yaml.safe_dump(queue, sort_keys=False), encoding="utf-8")
    capsys.readouterr()

    assert (
        main(
            [
                "runtime",
                "run-next",
                "--root",
                str(root),
                "--item-id",
                "queue_watch_source_poll",
                "--apply",
            ]
        )
        == 0
    )
    dispatched = yaml.safe_load(capsys.readouterr().out)
    assert dispatched["status"] == "done"
    assert dispatched["queue_item"]["status"] == "done"
    source_events = list(
        (root / "harness" / "shared_factory" / "06-runs-and-logs" / "source-events").glob("*.yml")
    )
    assert source_events


def test_runtime_dispatches_registered_watcher_script(tmp_path: Path, capsys) -> None:
    root = _fresh_root(tmp_path)
    script = root / "watchers" / "notion_work_intake" / "scripts" / "watch.py"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text("print('watcher-ran')\n", encoding="utf-8")
    (script.parent.parent / "watcher.yml").write_text("id: notion_work_intake\n", encoding="utf-8")
    queue_path = root / "harness" / "shared_factory" / "00-control-plane" / "run-queue.yml"
    queue = yaml.safe_load(queue_path.read_text(encoding="utf-8"))
    item = {
        "id": "queue_notion_watcher",
        "kind": "schedule",
        "ref": "notion_work_intake_watcher",
        "status": "queued",
        "approval_state": "not_required",
        "created_at": "2026-06-19T00:00:00Z",
        "idempotency_key": "test:notion-work-intake",
        "execution_target": "script",
        "command": f"python3 {script} --once",
    }
    queue.setdefault("items", []).append(item)
    queue["run_queue"] = queue["items"]
    queue_path.write_text(yaml.safe_dump(queue, sort_keys=False), encoding="utf-8")
    capsys.readouterr()

    assert (
        main(
            [
                "runtime",
                "run-next",
                "--root",
                str(root),
                "--item-id",
                "queue_notion_watcher",
                "--apply",
            ]
        )
        == 0
    )
    dispatched = yaml.safe_load(capsys.readouterr().out)
    assert dispatched["status"] == "done"
    assert dispatched["queue_item"]["status"] == "done"
    dispatch_log = yaml.safe_load((root / dispatched["queue_item"]["dispatch_log"]).read_text(encoding="utf-8"))
    assert dispatch_log["evidence"]["stdout"] == "watcher-ran"


def test_registered_watcher_detached_worker_remains_inside_dispatch_capacity(tmp_path: Path) -> None:
    root = _fresh_root(tmp_path)
    watcher_dir = root / "watchers/notion_work_intake"
    script = watcher_dir / "scripts/watch.py"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(
        "\n".join(
            [
                "import json, subprocess",
                "from pathlib import Path",
                "worker = subprocess.Popen(['/bin/sleep', '0.4'], start_new_session=True)",
                f"Path({str(watcher_dir / 'worker.json')!r}).write_text(json.dumps({{'pid': worker.pid}}))",
            ]
        ),
        encoding="utf-8",
    )
    (watcher_dir / "watcher.yml").write_text(
        "id: notion_work_intake\nharness_run_timeout_sec: 5\nharness_run_outer_grace_sec: 1\n",
        encoding="utf-8",
    )
    started = time.monotonic()

    result = runtime_ops._run_registered_watcher_script(
        root,
        f"python3 {script} --once",
        timeout_seconds=5,
    )

    assert result is not None
    assert result["ok"] is True
    assert result["worker_pid"]
    assert time.monotonic() - started >= 0.35


def test_runtime_dispatches_general_python_script(tmp_path: Path, capsys) -> None:
    root = _fresh_root(tmp_path)
    script = root / "scripts" / "write_runtime_marker.py"
    output = root / "harness" / "shared_factory" / "06-runs-and-logs" / "runs" / "runtime-marker.txt"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(
        "\n".join(
            [
                "import os",
                "from pathlib import Path",
                f"path = Path({str(output)!r})",
                "path.parent.mkdir(parents=True, exist_ok=True)",
                "path.write_text(os.environ['AGENTIC_OS_ROOT'], encoding='utf-8')",
                "print('marker-written')",
            ]
        ),
        encoding="utf-8",
    )
    queue_path = root / "harness" / "shared_factory" / "00-control-plane" / "run-queue.yml"
    queue = yaml.safe_load(queue_path.read_text(encoding="utf-8"))
    item = {
        "id": "queue_general_python",
        "kind": "schedule",
        "ref": "general_python",
        "status": "queued",
        "approval_state": "not_required",
        "created_at": "2026-06-19T00:00:00Z",
        "idempotency_key": "test:general-python",
        "execution_target": "script",
        "command": f"{sys.executable} {script}",
        "runtime_policy": {"timeout_seconds": 30},
    }
    queue.setdefault("items", []).append(item)
    queue["run_queue"] = queue["items"]
    queue_path.write_text(yaml.safe_dump(queue, sort_keys=False), encoding="utf-8")
    capsys.readouterr()

    assert (
        main(
            [
                "runtime",
                "run-next",
                "--root",
                str(root),
                "--item-id",
                "queue_general_python",
                "--apply",
            ]
        )
        == 0
    )
    dispatched = yaml.safe_load(capsys.readouterr().out)
    assert dispatched["status"] == "done"
    assert dispatched["queue_item"]["status"] == "done"
    assert dispatched["queue_item"]["external_effect"] == "local script executed"
    assert output.read_text(encoding="utf-8") == str(root)
    dispatch_log = yaml.safe_load((root / dispatched["queue_item"]["dispatch_log"]).read_text(encoding="utf-8"))
    assert dispatch_log["evidence"]["returncode"] == 0
    assert dispatch_log["evidence"]["stdout"] == "marker-written\n"
    assert dispatch_log["external_effect"] == "local script executed"


def test_runtime_dispatch_over_two_minutes_uses_central_long_running_contract(tmp_path: Path) -> None:
    root = _fresh_root(tmp_path)
    command = f"{sys.executable} -c \"print('governed-dispatch')\""

    result = runtime_ops._run_local_script(root, command, timeout_seconds=121)

    assert result["ok"] is True
    assert result["governed_status"] == "success"
    assert Path(result["governed_run"]).is_dir()
    assert Path(result["terminal_receipt"]).is_file()
    registry = root / "harness/shared_factory/00-control-plane/long-running-runs.json"
    assert registry.is_file()
    assert "governed-dispatch" in result["stdout"]


@pytest.mark.parametrize("timeout_seconds", [30, 121])
def test_runtime_dispatch_repairs_unquoted_executable_path_with_spaces(
    tmp_path: Path,
    timeout_seconds: int,
) -> None:
    root = _fresh_root(tmp_path)
    interpreter = tmp_path / "runtime path with spaces" / "python"
    interpreter.parent.mkdir(parents=True)
    interpreter.symlink_to(sys.executable)

    result = runtime_ops._run_local_script(
        root,
        f"{interpreter} -c \"print('space-safe-dispatch')\"",
        timeout_seconds=timeout_seconds,
    )

    assert result["ok"] is True
    assert result["stdout"] == "space-safe-dispatch\n"
    if timeout_seconds > runtime_ops.LONG_RUNNING_THRESHOLD_SECONDS:
        assert result["governed_status"] == "success"
        assert Path(result["terminal_receipt"]).is_file()


def test_runtime_dispatches_quiet_run_start_command(tmp_path: Path, capsys) -> None:
    root = _fresh_root(tmp_path)
    quiet_run = root / "harness" / "bin" / "agentic-os-quiet-run"
    quiet_run.write_text("#!/usr/bin/env bash\necho quiet-run-started\n", encoding="utf-8")
    quiet_run.chmod(0o755)
    queue_path = root / "harness" / "shared_factory" / "00-control-plane" / "run-queue.yml"
    queue = yaml.safe_load(queue_path.read_text(encoding="utf-8"))
    item = {
        "id": "queue_quiet_run_start",
        "kind": "source_trigger",
        "ref": "auto_dev_queue_watch",
        "status": "queued",
        "approval_state": "not_required",
        "created_at": "2026-06-19T00:00:00Z",
        "idempotency_key": "test:quiet-run-start",
        "execution_target": "script",
        "command": f"{quiet_run} start --artifact-dir {root / 'logs'} --label auto-dev-queue-watch -- /bin/true",
    }
    queue.setdefault("items", []).append(item)
    queue["run_queue"] = queue["items"]
    queue_path.write_text(yaml.safe_dump(queue, sort_keys=False), encoding="utf-8")
    capsys.readouterr()

    assert (
        main(
            [
                "runtime",
                "run-next",
                "--root",
                str(root),
                "--item-id",
                "queue_quiet_run_start",
                "--apply",
            ]
        )
        == 0
    )
    dispatched = yaml.safe_load(capsys.readouterr().out)
    assert dispatched["status"] == "done"
    assert dispatched["queue_item"]["status"] == "done"


def test_runtime_dispatch_holds_capacity_until_quiet_run_finishes(tmp_path: Path) -> None:
    root = _fresh_root(tmp_path)
    quiet_run = root / "harness/bin/agentic-os-quiet-run"
    started = time.monotonic()

    result = runtime_ops._run_quiet_run_script(
        root,
        f"{quiet_run} start --artifact-dir {root / 'logs'} --timeout-minutes 1 -- /bin/sleep 0.4",
        timeout_seconds=10,
    )

    assert result is not None
    assert result["ok"] is True
    assert result["quiet_run_status"] == "success"
    assert time.monotonic() - started >= 0.35


def test_runtime_dispatch_resolves_relative_quiet_run_state_from_os_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _fresh_root(tmp_path)
    quiet_run = root / "harness/bin/agentic-os-quiet-run"
    relative_state = Path("logs/async-runs/relative-state/state.json")
    state_path = root / relative_state
    state_path.parent.mkdir(parents=True)
    state_path.write_text(
        '{"status":"failure","exit_code":2,"error":"command-exited"}',
        encoding="utf-8",
    )
    monkeypatch.setattr(
        runtime_ops.subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=f"state={relative_state}\n",
            stderr="",
        ),
    )

    result = runtime_ops._run_quiet_run_script(
        root,
        f"{quiet_run} start --artifact-dir logs -- /bin/false",
        timeout_seconds=1,
    )

    assert result is not None
    assert result["ok"] is False
    assert result["quiet_run_status"] == "failure"
    assert result["quiet_run_state"] == str(state_path.resolve())


def test_runtime_dispatch_adds_user_local_bin_to_quiet_run_path(
    tmp_path: Path, capsys, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _fresh_root(tmp_path)
    home = tmp_path / "service-home"
    home.mkdir()
    observed_path = root / "quiet-run-path.txt"
    quiet_run = root / "harness" / "bin" / "agentic-os-quiet-run"
    quiet_run.write_text(
        f"#!/bin/bash\nprintf '%s' \"$PATH\" > {observed_path}\n",
        encoding="utf-8",
    )
    quiet_run.chmod(0o755)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("PATH", "/usr/bin:/bin")

    queue_path = root / "harness" / "shared_factory" / "00-control-plane" / "run-queue.yml"
    queue = yaml.safe_load(queue_path.read_text(encoding="utf-8"))
    queue.setdefault("items", []).append(
        {
            "id": "queue_quiet_run_path",
            "kind": "source_trigger",
            "ref": "path_contract",
            "status": "queued",
            "approval_state": "not_required",
            "created_at": "2026-07-16T00:00:00Z",
            "idempotency_key": "test:quiet-run-path",
            "execution_target": "script",
            "command": f"{quiet_run} start -- /bin/true",
        }
    )
    queue["run_queue"] = queue["items"]
    queue_path.write_text(yaml.safe_dump(queue, sort_keys=False), encoding="utf-8")
    capsys.readouterr()

    dispatched = runtime_run_next(root, dry_run=False, item_id="queue_quiet_run_path")

    assert dispatched["status"] == "done"
    assert observed_path.read_text(encoding="utf-8").split(os.pathsep) == [
        str(home / ".local" / "bin"),
        "/usr/bin",
        "/bin",
    ]


def test_runtime_dispatch_does_not_duplicate_user_local_bin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "service-home"
    user_bin = home / ".local" / "bin"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("PATH", f"/usr/bin:{user_bin}:/bin")

    env = runtime_ops._runtime_subprocess_env(tmp_path / "agentic_os")

    assert env["PATH"].split(os.pathsep) == ["/usr/bin", str(user_bin), "/bin"]


def test_runtime_dispatch_adds_user_local_bin_to_general_script_path(
    tmp_path: Path, capsys, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _fresh_root(tmp_path)
    home = tmp_path / "service-home"
    home.mkdir()
    observed_path = root / "general-script-path.txt"
    worker = root / "record-path.sh"
    worker.write_text(f"#!/bin/bash\nprintf '%s' \"$PATH\" > {observed_path}\n", encoding="utf-8")
    worker.chmod(0o755)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("PATH", "/usr/bin:/bin")

    queue_path = root / "harness" / "shared_factory" / "00-control-plane" / "run-queue.yml"
    queue = yaml.safe_load(queue_path.read_text(encoding="utf-8"))
    queue.setdefault("items", []).append(
        {
            "id": "queue_general_path",
            "kind": "source_trigger",
            "ref": "path_contract",
            "status": "queued",
            "approval_state": "not_required",
            "created_at": "2026-07-16T00:00:00Z",
            "idempotency_key": "test:general-path",
            "execution_target": "script",
            "command": str(worker),
        }
    )
    queue["run_queue"] = queue["items"]
    queue_path.write_text(yaml.safe_dump(queue, sort_keys=False), encoding="utf-8")
    capsys.readouterr()

    dispatched = runtime_run_next(root, dry_run=False, item_id="queue_general_path")

    assert dispatched["status"] == "done"
    assert observed_path.read_text(encoding="utf-8").split(os.pathsep) == [
        str(home / ".local" / "bin"),
        "/usr/bin",
        "/bin",
    ]


def test_runtime_dispatches_latest_priority_ref_and_skips_older_duplicates(tmp_path: Path) -> None:
    root = _fresh_root(tmp_path)
    queue_path = root / "harness" / "shared_factory" / "00-control-plane" / "run-queue.yml"
    queue = yaml.safe_load(queue_path.read_text(encoding="utf-8"))
    queue["items"] = [
        {
            "id": "queue_old_pr_health",
            "kind": "schedule",
            "ref": "los_agentic_pr_health",
            "status": "queued",
            "approval_state": "not_required",
            "created_at": "2026-06-30T10:00:00Z",
            "due_at": "2026-06-30T10:00:00Z",
            "idempotency_key": "test:pr-health:old",
            "execution_target": "script",
            "command": "agentic-os validate --root <root>",
        },
        {
            "id": "queue_new_pr_health",
            "kind": "schedule",
            "ref": "los_agentic_pr_health",
            "status": "queued",
            "approval_state": "not_required",
            "created_at": "2026-06-30T10:10:00Z",
            "due_at": "2026-06-30T10:10:00Z",
            "idempotency_key": "test:pr-health:new",
            "execution_target": "script",
            "command": "agentic-os validate --root <root>",
        },
        {
            "id": "queue_pr_health_self_heal",
            "kind": "runtime_self_heal",
            "ref": "los_agentic_pr_health",
            "status": "queued",
            "approval_state": "not_required",
            "created_at": "2026-06-30T10:05:00Z",
            "idempotency_key": "test:pr-health:self-heal",
            "execution_target": "codex_harness",
            "command": "agentic-os validate --root <root>",
        },
    ]
    queue["run_queue"] = queue["items"]
    queue_path.write_text(yaml.safe_dump(queue, sort_keys=False), encoding="utf-8")

    result = runtime_run_latest_by_ref(root, "los_agentic_pr_health", dry_run=False)

    assert result["status"] == "done"
    assert result["queue_item"]["id"] == "queue_new_pr_health"
    assert result["superseded_count"] == 1
    queue_after = yaml.safe_load(queue_path.read_text(encoding="utf-8"))
    by_id = {item["id"]: item for item in queue_after["items"]}
    assert by_id["queue_old_pr_health"]["status"] == "skipped"
    assert by_id["queue_new_pr_health"]["status"] == "done"
    assert by_id["queue_pr_health_self_heal"]["status"] == "queued"


def test_runtime_doctor_reports_run_queue_health(tmp_path: Path) -> None:
    root = _fresh_root(tmp_path)
    queue_path = root / "harness" / "shared_factory" / "00-control-plane" / "run-queue.yml"
    queue = yaml.safe_load(queue_path.read_text(encoding="utf-8"))
    queue["items"] = [
        {
            "id": "queue_stale_daily_one",
            "kind": "schedule",
            "ref": "daily_agentic_os_doctor",
            "status": "queued",
            "approval_state": "not_required",
            "created_at": "2026-06-01T00:00:00Z",
            "due_at": "2026-06-01T00:00:00Z",
            "idempotency_key": "test:stale:one",
            "execution_target": "script",
            "command": "agentic-os validate --root <root>",
        },
        {
            "id": "queue_stale_daily_two",
            "kind": "schedule",
            "ref": "daily_agentic_os_doctor",
            "status": "queued",
            "approval_state": "not_required",
            "created_at": "2026-06-01T01:00:00Z",
            "due_at": "2026-06-01T01:00:00Z",
            "idempotency_key": "test:stale:two",
            "execution_target": "script",
            "command": "agentic-os validate --root <root>",
        },
        {
            "id": "queue_duplicate_a",
            "kind": "schedule",
            "ref": "daily_agentic_os_doctor",
            "status": "queued",
            "approval_state": "not_required",
            "created_at": "2026-06-01T02:00:00Z",
            "idempotency_key": "test:duplicate",
            "execution_target": "script",
            "command": "agentic-os validate --root <root>",
        },
        {
            "id": "queue_duplicate_b",
            "kind": "schedule",
            "ref": "daily_agentic_os_doctor",
            "status": "queued",
            "approval_state": "not_required",
            "created_at": "2026-06-01T02:30:00Z",
            "idempotency_key": "test:duplicate",
            "execution_target": "script",
            "command": "agentic-os validate --root <root>",
        },
        {
            "id": "queue_failed_dispatch",
            "kind": "schedule",
            "ref": "daily_agentic_os_doctor",
            "status": "failed",
            "approval_state": "not_required",
            "created_at": "2026-06-01T03:00:00Z",
            "idempotency_key": "test:failed",
            "execution_target": "script",
            "command": "agentic-os unsupported --root <root>",
            "error": "unsupported local script command",
        },
        {
            "id": "queue_unsupported_command",
            "kind": "schedule",
            "ref": "daily_agentic_os_doctor",
            "status": "queued",
            "approval_state": "not_required",
            "created_at": "2026-06-01T04:00:00Z",
            "idempotency_key": "test:unsupported",
            "execution_target": "script",
            "command": "agentic-os unsupported-active --root <root>",
        },
        {
            "id": "queue_unknown_schedule",
            "kind": "schedule",
            "ref": "missing_schedule",
            "status": "queued",
            "approval_state": "not_required",
            "created_at": "2026-06-01T05:00:00Z",
            "idempotency_key": "test:unknown-schedule",
            "execution_target": "script",
            "command": "agentic-os validate --root <root>",
        },
    ]
    queue["run_queue"] = queue["items"]
    queue_path.write_text(yaml.safe_dump(queue, sort_keys=False), encoding="utf-8")

    report = runtime_doctor(root)
    messages = "\n".join(finding["message"] for finding in report["findings"])
    assert report["ok"] is True
    assert "queued run queue items are stale: daily_agentic_os_doctor due_at_past_24h_grace" in messages
    assert "sample=queue_stale_daily_one" in messages
    assert "duplicate active run queue idempotency_key: test:duplicate" in messages
    assert "multiple active schedule queue items: daily_agentic_os_doctor" in messages
    assert "run queue items failed: unsupported local script command" in messages
    assert "sample=queue_failed_dispatch" in messages
    assert "schedule queue items reference unknown schedule: missing_schedule" in messages


def test_run_queue_prune_archives_stale_items_and_removes_old_backups(tmp_path: Path, capsys) -> None:
    root = _fresh_root(tmp_path)
    queue_path = root / "harness" / "shared_factory" / "00-control-plane" / "run-queue.yml"
    backup_path = queue_path.parent / "run-queue.yml.backup-old"
    backup_path.write_text("old backup\n", encoding="utf-8")
    os.utime(backup_path, (0, 0))
    queue = yaml.safe_load(queue_path.read_text(encoding="utf-8"))
    queue["items"] = [
        {
            "id": "stale_queued",
            "kind": "schedule",
            "ref": "daily_agentic_os_doctor",
            "status": "queued",
            "approval_state": "not_required",
            "created_at": "2000-01-01T00:00:00Z",
            "due_at": "2000-01-01T00:00:00Z",
            "idempotency_key": "test:stale-queued",
        },
        {
            "id": "old_done",
            "kind": "schedule",
            "ref": "daily_agentic_os_doctor",
            "status": "done",
            "approval_state": "not_required",
            "created_at": "2000-01-01T00:00:00Z",
            "finished_at": "2000-01-01T00:00:00Z",
            "idempotency_key": "test:old-done",
        },
        {
            "id": "old_failed",
            "kind": "schedule",
            "ref": "daily_agentic_os_doctor",
            "status": "failed",
            "approval_state": "not_required",
            "created_at": "2000-01-01T00:00:00Z",
            "finished_at": "2000-01-01T00:00:00Z",
            "idempotency_key": "test:old-failed",
        },
        {
            "id": "old_skipped",
            "kind": "schedule",
            "ref": "daily_agentic_os_doctor",
            "status": "skipped",
            "approval_state": "not_required",
            "created_at": "2000-01-01T00:00:00Z",
            "updated_at": "2000-01-01T00:00:00Z",
            "idempotency_key": "test:old-skipped",
        },
        {
            "id": "fresh_queued",
            "kind": "schedule",
            "ref": "daily_agentic_os_doctor",
            "status": "queued",
            "approval_state": "not_required",
            "created_at": "2999-01-01T00:00:00Z",
            "due_at": "2999-01-01T00:00:00Z",
            "idempotency_key": "test:fresh-queued",
        },
    ]
    queue["run_queue"] = queue["items"]
    queue_path.write_text(yaml.safe_dump(queue, sort_keys=False), encoding="utf-8")
    capsys.readouterr()

    assert main(["runtime", "prune", "--root", str(root)]) == 0
    dry_run = yaml.safe_load(capsys.readouterr().out)
    assert dry_run["status"] == "would-prune"
    assert dry_run["counts"] == {"before": 5, "after": 1, "pruned": 4}
    assert dry_run["stale_backup_files"]["count"] == 1
    assert backup_path.exists()
    assert len(yaml.safe_load(queue_path.read_text(encoding="utf-8"))["items"]) == 5

    assert main(["run-queue", "prune", "--root", str(root), "--apply"]) == 0
    applied = yaml.safe_load(capsys.readouterr().out)
    assert applied["status"] == "pruned"
    assert applied["counts"] == {"before": 5, "after": 1, "pruned": 4}
    assert not backup_path.exists()
    queue_after = yaml.safe_load(queue_path.read_text(encoding="utf-8"))
    assert [item["id"] for item in queue_after["items"]] == ["fresh_queued"]
    archive = yaml.safe_load(Path(applied["archive_log"]).read_text(encoding="utf-8"))
    assert [item["id"] for item in archive["pruned_items"]] == ["stale_queued", "old_done", "old_failed", "old_skipped"]


def test_supervise_isolates_a_failing_step(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """One broken subsystem must not abort the tick or silence the others."""
    root = _fresh_root(tmp_path)

    def _boom(*args, **kwargs):
        raise RuntimeError("simulated schedule failure")

    monkeypatch.setattr(supervisor, "schedule_run_due", _boom)
    report = supervise_tick(root, dry_run=True)

    schedules = next(step for step in report["steps"] if step["step"] == "schedules")
    assert schedules["ok"] is False
    assert "simulated schedule failure" in schedules["error"]
    # Later steps still ran, and overall ok is False.
    assert {step["step"] for step in report["steps"]} == STEP_NAMES
    assert report["ok"] is False
    # The CLI command surfaces the failure as exit 1.
    assert main(["runtime", "supervise", "--root", str(root)]) == 1


def test_registered_watcher_script_honors_item_timeout(tmp_path: Path) -> None:
    root = _fresh_root(tmp_path)
    script = root / "watchers" / "notion_work_intake" / "scripts" / "watch.py"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text("import time\ntime.sleep(5)\n", encoding="utf-8")
    (script.parent.parent / "watcher.yml").write_text("id: notion_work_intake\n", encoding="utf-8")
    queue_path = root / "harness" / "shared_factory" / "00-control-plane" / "run-queue.yml"
    queue = yaml.safe_load(queue_path.read_text(encoding="utf-8"))
    item = {
        "id": "queue_notion_watcher_timeout",
        "kind": "schedule",
        "ref": "notion_work_intake_watcher",
        "status": "queued",
        "approval_state": "not_required",
        "created_at": "2026-06-19T00:00:00Z",
        "idempotency_key": "test:notion-work-intake-timeout",
        "execution_target": "script",
        "command": f"python3 {script} --once",
        "timeout_seconds": 1,
    }
    queue.setdefault("items", []).append(item)
    queue["run_queue"] = queue["items"]
    queue_path.write_text(yaml.safe_dump(queue, sort_keys=False), encoding="utf-8")

    dispatched = runtime_run_next(root, dry_run=False, item_id="queue_notion_watcher_timeout")

    assert dispatched["status"] == "failed"
    assert dispatched["queue_item"]["status"] == "failed"
    dispatch_log = yaml.safe_load((root / dispatched["queue_item"]["dispatch_log"]).read_text(encoding="utf-8"))
    assert dispatch_log["evidence"]["timed_out"] is True
    assert dispatch_log["evidence"]["timeout_seconds"] == 1
    assert "timed out after 1s" in dispatch_log["evidence"]["errors"][0]


def test_run_next_preserves_items_appended_during_in_process_execution(tmp_path: Path, monkeypatch) -> None:
    """A dispatched command that appends queue items mid-execution must not
    have those appends clobbered by the dispatcher's terminal queue write."""
    root = _fresh_root(tmp_path)
    runtime_ops.append_run_queue_item(
        root,
        {
            "id": "queue_dispatch_me",
            "kind": "schedule",
            "ref": "race_probe",
            "status": "queued",
            "approval_state": "not_required",
            "dry_run": False,
            "idempotency_key": "race-probe:1",
            "execution_target": "script",
            "command": f"agentic-os validate --root {root}",
        },
    )

    def _appending_run_local_script(os_root, command, **kwargs):
        runtime_ops.append_run_queue_item(
            os_root,
            {
                "id": "queue_appended_mid_flight",
                "kind": "self_improvement_action",
                "ref": "si-race",
                "status": "queued",
                "approval_state": "not_required",
                "dry_run": False,
                "idempotency_key": "self-improvement-action:race",
                "execution_target": "script",
                "command": "echo noop",
            },
        )
        return {"supported": True, "ok": True, "command": command, "errors": [], "warnings": [], "external_effect": "probe"}

    monkeypatch.setattr(runtime_ops, "_run_local_script", _appending_run_local_script)
    outcome = runtime_run_next(root, dry_run=False, item_id="queue_dispatch_me")
    assert outcome["status"] == "done"

    queue = yaml.safe_load(
        (root / "harness/shared_factory/00-control-plane/run-queue.yml").read_text(encoding="utf-8")
    )
    by_id = {item.get("id"): item for item in queue.get("items") or []}
    assert by_id["queue_dispatch_me"]["status"] == "done"
    assert "queue_appended_mid_flight" in by_id, "mid-flight append was clobbered by the terminal queue write"
    assert by_id["queue_appended_mid_flight"]["status"] == "queued"
