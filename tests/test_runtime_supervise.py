from __future__ import annotations

from pathlib import Path

import pytest

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
