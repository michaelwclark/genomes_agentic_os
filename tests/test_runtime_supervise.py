from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from genomes_agentic_os import supervisor
from genomes_agentic_os.cli import main
from genomes_agentic_os.supervisor import supervise_tick

STEP_NAMES = {"heartbeats", "schedules", "watch_sources", "events", "run_queue", "health"}


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


def test_supervise_apply_runs_the_tick(tmp_path: Path) -> None:
    root = _fresh_root(tmp_path)
    report = supervise_tick(root, dry_run=False)
    assert report["dry_run"] is False
    assert report["ok"] is True
    assert main(["runtime", "supervise", "--root", str(root), "--apply"]) == 0


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
