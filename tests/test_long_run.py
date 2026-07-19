from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import time

import pytest

from genomes_agentic_os.cli import main
from genomes_agentic_os.long_run import (
    _sample_collateral,
    LongRunError,
    control_run,
    read_registry,
    recover_run,
    start_run,
    status_for_run,
    update_registry,
)


def _wait_for(run_dir: Path, statuses: set[str], timeout: float = 15) -> dict[str, object]:
    deadline = time.monotonic() + timeout
    state: dict[str, object] = {}
    while time.monotonic() < deadline:
        state = status_for_run(run_dir)
        if state.get("status") in statuses:
            return state
        time.sleep(0.05)
    raise AssertionError(f"run did not reach {statuses}: {state}")


def test_long_run_success_registers_progress_log_and_terminal_receipt(tmp_path: Path) -> None:
    root = tmp_path / "agentic_os"
    state = start_run(
        root,
        command=[sys.executable, "-c", "print('complete')"],
        label="contract smoke",
        artifact_dir=str(tmp_path / "artifacts"),
        work_dir=str(tmp_path),
        budgets={"wall_clock_minutes": 1, "no_progress_minutes": 1},
    )
    run_dir = Path(state["run_dir"])
    terminal = _wait_for(run_dir, {"success", "failure", "error"})

    assert terminal["status"] == "success"
    receipt = json.loads((run_dir / "terminal-receipt.json").read_text(encoding="utf-8"))
    assert receipt["status"] == "success"
    assert receipt["post_run_invariants_ok"] is True
    assert receipt["budgets"]["wall_clock_minutes"] == 1
    assert receipt["progress"]["items_completed"] == 0
    assert (run_dir / "output.log").read_text(encoding="utf-8") == "complete\n"
    assert (run_dir / "summary.md").is_file()
    registry = read_registry(root)
    assert registry["runs"][0]["id"] == terminal["id"]
    assert registry["runs"][0]["status"] == "success"


def test_legacy_quiet_run_start_shape_remains_compatible(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "agentic_os"
    assert main(
        [
            "long-run",
            "start",
            "--root",
            str(root),
            "--artifact-dir",
            str(tmp_path / "legacy"),
            "--timeout-minutes",
            "1",
            "--",
            sys.executable,
            "-c",
            "raise SystemExit(0)",
        ]
    ) == 0
    output = capsys.readouterr().out.splitlines()
    state_path = Path(next(line.removeprefix("state=") for line in output if line.startswith("state=")))
    terminal = _wait_for(state_path.parent, {"success", "failure", "error"})
    assert terminal["status"] == "success"


def test_long_run_refuses_unsafe_mutations_and_secret_arguments(tmp_path: Path) -> None:
    root = tmp_path / "agentic_os"
    with pytest.raises(LongRunError, match="checkpoint-strategy"):
        start_run(root, command=["/bin/true"], label="unsafe", kind="migration")
    with pytest.raises(LongRunError, match="complexity and performance"):
        start_run(
            root,
            command=["/bin/true"],
            label="unsafe",
            kind="migration",
            checkpoint_strategy="restore backup",
            post_run_checks=["true"],
        )
    with pytest.raises(LongRunError, match="secret-looking"):
        start_run(root, command=["tool", "--token", "not-for-logs"], label="secret")
    with pytest.raises(LongRunError, match="budgets must be positive"):
        start_run(
            root,
            command=["/bin/true"],
            label="zero budget",
            budgets={"wall_clock_minutes": 0},
        )


def test_long_run_rotates_logs_and_supports_pause_resume_cancel(tmp_path: Path) -> None:
    root = tmp_path / "agentic_os"
    noisy = start_run(
        root,
        command=[sys.executable, "-c", "print('x' * 5000)"],
        label="bounded output",
        artifact_dir=str(tmp_path / "noisy"),
        work_dir=str(tmp_path),
        budgets={
            "wall_clock_minutes": 1,
            "no_progress_minutes": 1,
            "max_log_mb": 0.001,
            "log_rotations": 2,
        },
    )
    noisy_dir = Path(noisy["run_dir"])
    noisy_terminal = _wait_for(noisy_dir, {"success", "failure", "error"})
    assert noisy_terminal["status"] == "success"
    assert int(noisy_terminal["log_rotations"]) >= 1
    assert (noisy_dir / "output.log.1").is_file()
    assert len(list(noisy_dir.glob("output.log*"))) <= 3

    controlled = start_run(
        root,
        command=[sys.executable, "-c", "import time; time.sleep(30)"],
        label="operator controls",
        artifact_dir=str(tmp_path / "controlled"),
        work_dir=str(tmp_path),
        budgets={"wall_clock_minutes": 1, "no_progress_minutes": 1},
    )
    controlled_dir = Path(controlled["run_dir"])
    _wait_for(controlled_dir, {"running"})
    assert control_run(controlled_dir, "pause")["status"] == "paused"
    assert control_run(controlled_dir, "resume")["status"] == "running"
    cancelling = control_run(controlled_dir, "cancel", grace_seconds=1)
    assert cancelling["status"] == "cancelling"
    assert cancelling["cancel_grace_seconds"] == 1
    cancelled = _wait_for(controlled_dir, {"cancelled", "failure", "error"})
    assert cancelled["status"] == "cancelled"
    assert (controlled_dir / "terminal-receipt.json").is_file()


def test_watchdogs_stop_no_progress_and_resource_budget_violations(tmp_path: Path) -> None:
    root = tmp_path / "agentic_os"
    no_progress = start_run(
        root,
        command=[sys.executable, "-c", "import time; time.sleep(30)"],
        label="no progress watchdog",
        artifact_dir=str(tmp_path / "no-progress"),
        work_dir=str(tmp_path),
        budgets={"wall_clock_minutes": 1, "no_progress_minutes": 0.001},
    )
    no_progress_dir = Path(no_progress["run_dir"])
    no_progress_terminal = _wait_for(
        no_progress_dir,
        {"no-progress-timeout", "failure", "error"},
    )
    assert no_progress_terminal["status"] == "no-progress-timeout"

    config = root / "harness/config/long-running-execution.yml"
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(
        """long_running_execution:
  budgets:
    resource_violation_samples: 1
    sample_seconds: 0.05
""",
        encoding="utf-8",
    )
    resource = start_run(
        root,
        command=[sys.executable, "-c", "import time; time.sleep(30)"],
        label="resource watchdog",
        artifact_dir=str(tmp_path / "resource"),
        work_dir=str(tmp_path),
        budgets={
            "wall_clock_minutes": 1,
            "no_progress_minutes": 1,
            "max_rss_mb": 0.001,
        },
    )
    resource_dir = Path(resource["run_dir"])
    resource_terminal = _wait_for(
        resource_dir,
        {"resource-budget-exceeded", "failure", "error"},
    )
    assert resource_terminal["status"] == "resource-budget-exceeded"
    assert int(resource_terminal["resource_sample"]["process_count"]) >= 1
    resource_receipt = json.loads(
        (resource_dir / "terminal-receipt.json").read_text(encoding="utf-8")
    )
    assert float(resource_receipt["resource_peak"]["rss_mb"]) > 0


def test_collateral_sampler_uses_exact_process_names_without_truncated_paths() -> None:
    sleeper = subprocess.Popen(["/bin/sleep", "5"])
    try:
        rows = _sample_collateral(["sleep:9999:9999"])
    finally:
        sleeper.terminate()
        sleeper.wait(timeout=5)

    assert rows[0]["name"] == "sleep"
    assert rows[0]["exceeded"] is False
    assert rows[0]["rss_mb"] > 0


def test_orphan_recovery_marks_stale_and_writes_terminal_receipt(tmp_path: Path) -> None:
    root = tmp_path / "agentic_os"
    run_dir = tmp_path / "orphan"
    run_dir.mkdir()
    created = "2026-07-19T00:00:00Z"
    command = {
        "id": "071926-orphan",
        "kind": "scan",
        "label": "orphan fixture",
        "command": ["/bin/true"],
        "command_display": "/bin/true",
        "created_at": created,
        "checkpoint_strategy": "restart from receipt",
        "root": str(root),
    }
    state = {
        "id": command["id"],
        "kind": command["kind"],
        "label": command["label"],
        "status": "running",
        "phase": "execute",
        "created_at": created,
        "updated_at": created,
        "run_dir": str(run_dir),
        "root": str(root),
        "pid": 99999999,
        "monitor_pid": 99999998,
    }
    (run_dir / "command.json").write_text(json.dumps(command), encoding="utf-8")
    (run_dir / "state.json").write_text(json.dumps(state), encoding="utf-8")
    update_registry(root, state)

    report = recover_run(run_dir, mark_stale=True)

    assert report["classification"] == "stale"
    assert report["marked_stale"] is True
    receipt = json.loads((run_dir / "terminal-receipt.json").read_text(encoding="utf-8"))
    assert receipt["status"] == "stale"
    assert status_for_run(run_dir)["status"] == "stale"
