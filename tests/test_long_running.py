from __future__ import annotations

import json
import os
from pathlib import Path
import signal

import pytest

from genomes_agentic_os.long_running import (
    DurableRunProgress,
    MutationLock,
    RunInterrupted,
    SignalGuard,
)


def test_durable_progress_writes_atomic_snapshot_and_semantic_journal(
    tmp_path: Path,
) -> None:
    progress = DurableRunProgress(
        tmp_path / "progress.json",
        run_id="run-1",
        operation="fixture",
        items_total=3,
        metadata={"budget": {"wall_clock_seconds": 60}},
    )
    progress.event("phase_started", phase="copy")
    progress.update(phase="copy", items_completed=1, bytes_completed=128, force=True)

    snapshot = json.loads(progress.path.read_text(encoding="utf-8"))
    events = [
        json.loads(line) for line in progress.journal_path.read_text().splitlines()
    ]
    assert snapshot["operation"] == "fixture"
    assert snapshot["items_completed"] == 1
    assert snapshot["bytes_completed"] == 128
    assert snapshot["last_semantic_progress_at"] == snapshot["updated_at"]
    assert [event["event"] for event in events] == ["run_started", "phase_started"]


def test_mutation_lock_recovers_orphan_and_preserves_stale_receipt(
    tmp_path: Path,
) -> None:
    path = tmp_path / "operation.lock"
    path.write_text(
        json.dumps({"run_id": "orphan", "pid": 999_999_999}), encoding="utf-8"
    )
    lock = MutationLock(path, run_id="replacement", operation="fixture")

    lock.acquire()
    assert json.loads(path.read_text(encoding="utf-8"))["run_id"] == "replacement"
    assert len(list(tmp_path.glob("operation.lock.stale-*"))) == 1
    lock.release()
    assert not path.exists()


def test_mutation_lock_rejects_live_owner(tmp_path: Path) -> None:
    path = tmp_path / "operation.lock"
    path.write_text(
        json.dumps({"run_id": "live", "pid": os.getpid()}), encoding="utf-8"
    )

    with pytest.raises(RuntimeError, match="live PID"):
        MutationLock(path, run_id="other", operation="fixture").acquire()


def test_signal_guard_translates_sigterm_to_recoverable_interrupt() -> None:
    with pytest.raises(RunInterrupted, match="SIGTERM"):
        with SignalGuard():
            os.kill(os.getpid(), signal.SIGTERM)
