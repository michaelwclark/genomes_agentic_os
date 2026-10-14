"""Actual native monitor admission and record-publication ownership regressions."""
from __future__ import annotations

from contextlib import contextmanager
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

import pytest

from genomes_agentic_os import long_run
from test_long_run import _wait_for


def _row(root, identifier):
    rows = [row for row in long_run.read_registry(root)["runs"] if row["id"] == identifier]
    assert len(rows) == 1
    return rows[0]


@contextmanager
def _live_owner(tmp_path):
    root = tmp_path / "os"; lock = tmp_path / "owner.lock"
    ready, finish = tmp_path / "ready", tmp_path / "finish"
    code = ("from pathlib import Path;import time;Path(" + repr(str(ready)) + ").write_text('ready');"
        "deadline=time.monotonic()+20;\n"
        "while not Path(" + repr(str(finish)) + ").exists() and time.monotonic()<deadline: time.sleep(.02)\n"
        "assert Path(" + repr(str(finish)) + ").exists();print('legitimate owner completed')")
    state = long_run.start_run(root, command=[sys.executable, "-c", code], label="live owner fixture",
        run_id="same-run-id", artifact_dir=str(tmp_path / "artifacts"), work_dir=str(tmp_path),
        mutation_lock=str(lock), budgets={"wall_clock_minutes": 1, "no_progress_minutes": 1})
    run = Path(state["run_dir"])
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if ready.exists() and long_run.status_for_run(run)["status"] == "running": break
        time.sleep(.02)
    assert ready.exists() and lock.exists()
    owner = json.loads(lock.read_text()); assert owner["pid"] == state["monitor_pid"]
    try: yield root, run, lock, owner
    finally:
        finish.write_text("finish")
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if long_run.status_for_run(run)["status"] == "success" and not lock.exists(): break
            time.sleep(.02)
        assert long_run.status_for_run(run)["status"] == "success" and not lock.exists()


def test_actual_same_run_directory_duplicate_preserves_all_owner_records(tmp_path):
    with _live_owner(tmp_path) as (root, run, lock, owner):
        before_state, before_registry = long_run.status_for_run(run), _row(root, "same-run-id")
        original_lock, original_preflight = lock.read_bytes(), (run / "preflight.json").read_bytes()
        assert not (run / "terminal-receipt.json").exists()
        duplicate = subprocess.run([sys.executable, "-m", "genomes_agentic_os.cli", "long-run", "_monitor", str(run)],
            capture_output=True, text=True, timeout=10)
        assert duplicate.returncode != 0
        os.kill(owner["pid"], 0)
        after_state, after_registry = long_run.status_for_run(run), _row(root, "same-run-id")
        stable = ("status", "phase", "monitor_pid", "pid", "run_dir", "started_at")
        assert {k: after_state.get(k) for k in stable} == {k: before_state.get(k) for k in stable}
        assert {k: after_registry.get(k) for k in stable} == {k: before_registry.get(k) for k in stable}
        assert not (run / "terminal-receipt.json").exists()
        assert lock.read_bytes() == original_lock and (run / "preflight.json").read_bytes() == original_preflight
        assert long_run.recover_run(run, mark_stale=True)["classification"] == "active"


def test_nonowner_terminal_publication_refuses_live_owner_and_restores_signals(tmp_path):
    with _live_owner(tmp_path) as (root, run, lock, owner):
        before_state, before_registry = long_run.status_for_run(run), _row(root, "same-run-id")
        command = json.loads((run / "command.json").read_text())
        handlers = {n: signal.getsignal(n) for n in (signal.SIGTERM, signal.SIGINT)}
        with pytest.raises(long_run.LongRunError): long_run.monitor_run(run)
        assert {n: signal.getsignal(n) for n in handlers} == handlers
        with pytest.raises(long_run.LongRunError):
            long_run._terminal(root, run, command, status="failure", exit_code=77,
                reason="synthetic unowned negative attempt", checks=[])
        assert long_run.status_for_run(run)["status"] == before_state["status"] == "running"
        assert _row(root, "same-run-id")["status"] == before_registry["status"] == "running"
        assert not (run / "terminal-receipt.json").exists()


@pytest.mark.parametrize("delayed", ["state-pid", "registry-pid"])
def test_actual_native_start_waits_for_complete_parent_pid_registration(tmp_path, monkeypatch, delayed):
    original_write, original_registry = long_run._write_state, long_run.update_registry
    observed = []
    root = tmp_path / "os"
    def check_queued(run):
        time.sleep(.8)  # Let the real child reach admission before its parent publishes.
        current, registry = long_run.status_for_run(run), _row(root, "registered-start")
        observed.append((current["status"], registry["status"], current.get("monitor_pid"), registry.get("monitor_pid")))
        assert current["status"] == registry["status"] == "queued"
        assert not registry.get("monitor_pid") and not (run / "terminal-receipt.json").exists()
    def delayed_write(os_root, run, changes):
        if delayed == "state-pid" and "monitor_pid" in changes: check_queued(run)
        return original_write(os_root, run, changes)
    def delayed_registry(os_root, current):
        if delayed == "registry-pid" and current.get("monitor_pid") and current["status"] == "queued":
            check_queued(Path(current["run_dir"]))
        return original_registry(os_root, current)
    monkeypatch.setattr(long_run, "_write_state", delayed_write)
    monkeypatch.setattr(long_run, "update_registry", delayed_registry)
    state = long_run.start_run(root, command=[sys.executable, "-c", "print('registered command')"], label="native startup ordering",
        run_id="registered-start", artifact_dir=str(tmp_path / "artifacts"), work_dir=str(tmp_path),
        budgets={"wall_clock_minutes": 1, "no_progress_minutes": 1})
    run = Path(state["run_dir"])
    assert observed and _wait_for(run, {"success", "failure", "error"})["status"] == "success"
    assert long_run.status_for_run(run)["monitor_pid"] == state["monitor_pid"]


def _legacy(root, run, monitor):
    root.mkdir(); run.mkdir()
    command = {"id": "legacy", "root": str(root), "kind": "test", "label": "synthetic legacy orphan",
        "command": [sys.executable, "-c", "print('not admitted')"], "command_display": "unused",
        "work_dir": str(run), "created_at": "2026-07-19T00:00:00Z", "checkpoint_strategy": "restart-from-command-receipt",
        "budgets": {}, "preflight_checks": [], "post_run_checks": []}
    state = {"id": "legacy", "run_dir": str(run), "status": "running", "phase": "execute",
        "pid": 99999999, "monitor_pid": monitor}
    (run / "command.json").write_text(json.dumps(command)); (run / "state.json").write_text(json.dumps(state))
    long_run.update_registry(root, state)
    return command


@pytest.mark.parametrize("monitor", [None, "", 0, 99999998])
def test_legacy_or_dead_pid_cannot_be_adopted_but_honest_orphan_recovery_remains(tmp_path, monitor):
    root, run = tmp_path / "os", tmp_path / "legacy"
    command = _legacy(root, run, monitor)
    state, registry = (run / "state.json").read_bytes(), long_run.registry_path(root).read_bytes()
    handlers = {n: signal.getsignal(n) for n in (signal.SIGTERM, signal.SIGINT)}
    with pytest.raises(long_run.LongRunError): long_run.monitor_run(run)
    assert {n: signal.getsignal(n) for n in handlers} == handlers
    with pytest.raises(long_run.LongRunError):
        long_run._terminal(root, run, command, status="success", exit_code=0, reason="unowned negative attempt", checks=[])
    assert (run / "state.json").read_bytes() == state and long_run.registry_path(root).read_bytes() == registry
    assert not (run / "terminal-receipt.json").exists()
    recovered = long_run.recover_run(run, mark_stale=True)
    assert recovered["classification"] == "stale" and recovered["marked_stale"] is True
    assert json.loads((run / "terminal-receipt.json").read_text())["status"] == "stale"


def test_actual_unregistered_legacy_queue_times_out_without_borrowing_ownership(tmp_path):
    root, run = tmp_path / "os", tmp_path / "legacy"
    _legacy(root, run, None)
    state = json.loads((run / "state.json").read_text()); state["status"] = "queued"
    (run / "state.json").write_text(json.dumps(state)); long_run.update_registry(root, state)
    before_state, before_registry = (run / "state.json").read_bytes(), long_run.registry_path(root).read_bytes()
    result = subprocess.run([sys.executable, "-m", "genomes_agentic_os.cli", "long-run", "_monitor", str(run)],
        capture_output=True, text=True, timeout=10)
    assert result.returncode != 0
    assert (run / "state.json").read_bytes() == before_state
    assert long_run.registry_path(root).read_bytes() == before_registry
    assert not (run / "terminal-receipt.json").exists()
    assert long_run.recover_run(run, mark_stale=True)["marked_stale"] is True
