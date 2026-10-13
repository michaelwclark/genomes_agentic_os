from __future__ import annotations

import json
import os
from pathlib import Path
import signal
import subprocess
import sys

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


def test_unacquired_same_id_instance_cannot_release_another_owner(tmp_path: Path) -> None:
    path = tmp_path / "operation.lock"
    owner = MutationLock(path, run_id="same-id", operation="fixture")
    owner.acquire()
    original = path.read_bytes()
    contender = MutationLock(path, run_id="same-id", operation="fixture")
    try:
        with pytest.raises(RuntimeError, match="live PID"):
            contender.acquire()
        contender.release()
        assert path.is_file() and path.read_bytes() == original
    finally:
        owner.release()
    assert not path.exists()


def test_release_does_not_remove_a_replacement_owned_file(tmp_path: Path) -> None:
    path = tmp_path / "operation.lock"
    first = MutationLock(path, run_id="same-id", operation="fixture")
    first.acquire()
    path.rename(tmp_path / "prior-owner-receipt.json")
    replacement = MutationLock(path, run_id="same-id", operation="fixture")
    replacement.acquire()
    original = path.read_bytes()
    try:
        first.release()
        assert path.is_file() and path.read_bytes() == original
    finally:
        replacement.release()
    assert not path.exists()


def test_acquired_lock_requires_its_actual_owning_pid_on_release(tmp_path: Path) -> None:
    path = tmp_path / "operation.lock"
    lock = MutationLock(path, run_id="same-id", operation="fixture")
    lock.acquire()
    original = path.read_bytes()
    sleeper = subprocess.Popen([sys.executable, "-c", "import time;time.sleep(10)"])
    try:
        payload = json.loads(original); payload["pid"] = sleeper.pid
        path.write_text(json.dumps(payload))
        changed = path.read_bytes()
        lock.release()
        assert path.is_file() and path.read_bytes() == changed
    finally:
        sleeper.terminate(); sleeper.wait(timeout=5)
        # Remove only this deliberately altered synthetic fixture. Production
        # orphan recovery stays in acquire(); release is not force-unlock.
        path.unlink()


def test_standalone_acquired_release_remains_idempotent(tmp_path: Path) -> None:
    path = tmp_path / "operation.lock"
    lock = MutationLock(path, run_id="standalone", operation="fixture")
    lock.acquire(); lock.release(); lock.release()
    assert not path.exists()


def test_signal_guard_translates_sigterm_to_recoverable_interrupt() -> None:
    with pytest.raises(RunInterrupted, match="SIGTERM"):
        with SignalGuard():
            os.kill(os.getpid(), signal.SIGTERM)
