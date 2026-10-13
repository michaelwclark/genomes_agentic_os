"""Actual npm install/substitution and native locked-execution regressions."""
from __future__ import annotations

import json
from pathlib import Path
import os
import shlex
import sys
from contextlib import contextmanager

import pytest

from genomes_agentic_os import development_delivery as delivery
from genomes_agentic_os.long_run import start_run, control_run
from genomes_agentic_os.validation_node_provenance import dependency_closure, run_guard, LOCK, SNAPSHOT, _json
from test_development_validation_refresh import _fixture, _refresh, _bound, _write, _command_proof, _now
from test_development_delivery import _git
from test_long_run import _wait_for


def test_real_npm_ci_binds_full_closure_and_honest_frozen_deferral(tmp_path):
    f = _fixture(tmp_path, node_commands=True, legacy=True, deferred_successor=True, registered_metadata=True)
    old, before = f["predecessor"].read_bytes(), f["task"].read()
    result = _refresh(f)
    assert result["task"]["validation_head_sha"] == f["head"]
    assert result["task"]["receipts"][:len(before["receipts"])] == before["receipts"]
    assert f["predecessor"].read_bytes() == old
    request = json.loads(f["request"].read_text())
    assert request["status"] == "deferred_to_ci"
    rows = request["evidence"]["validation_runs"]
    assert [row["command"] for row in rows] == ["npm ci", "npx tsc --noEmit", "npx playwright test --list"]
    for row in rows:
        terminal = json.loads(Path(row["terminal"]["path"]).read_text())
        assert terminal["git_identity_pre"]["clean"] == terminal["git_identity_post"]["clean"] == "false"
        assert terminal["post_run_invariants_ok"] is True
        assert [check["phase"] for check in terminal["checks"]] == ["preflight", "post-run"]
    assert not (f["packet"] / "artifacts" / LOCK).exists()
    assert _refresh(f)["replayed"] is True


def test_real_post_install_green_noop_cannot_be_admitted(tmp_path):
    f = _fixture(tmp_path, node_commands=True)
    request = json.loads(f["request"].read_text()); rows = request["evidence"]["validation_runs"]
    binary = f["worktree"] / "node_modules/.bin/tsc"
    binary.unlink(); binary.write_text("#!/bin/sh\nexit 0\n"); binary.chmod(0o755)
    assert _git("status", "--porcelain", cwd=f["worktree"]) == ""
    # This is the actual reported bypass: genuine native execution of the
    # unchanged frozen argv returns green against a replaced ignored binary.
    green = _command_proof(f["root"], f["packet"], f["worktree"], "npx tsc --noEmit", f["head"],
        f["task"].read()["policy_fingerprint"], node_guards=False)
    green["node_install_closure"] = rows[0]["node_install_closure"]
    rows[1] = green; request["verified_at"] = _now(); _write(f["request"], request)
    before = f["task"].path.read_bytes()
    with pytest.raises(delivery.DevelopmentDeliveryError, match="closure changed"):
        _refresh(f)
    assert f["task"].path.read_bytes() == before
    # With the approved hooks the substituted command is stopped before launch.
    blocked = _command_proof(f["root"], f["packet"], f["worktree"], "npx tsc --noEmit", f["head"],
        f["task"].read()["policy_fingerprint"], expected_status="failure",
        node_install=Path(rows[0]["command_receipt"]["path"]).parent)
    terminal = json.loads(Path(blocked["terminal"]["path"]).read_text())
    assert terminal["exit_code"] is None and terminal["reason"] == "preflight-check-failed"
    assert not (f["packet"] / "artifacts" / LOCK).exists()


@pytest.mark.parametrize("change", ["contents", "mode", "added", "deleted", "outside", "dangling", "directory-link"])
def test_full_installed_dependency_closure_rejects_each_mutation(tmp_path, change):
    f = _fixture(tmp_path, node_commands=True)
    root = f["worktree"] / "node_modules"
    target = root / "synthetic-typescript/cli.js"
    if change == "contents": target.write_text("#!/usr/bin/env node\nprocess.exit(0)\n")
    elif change == "mode": target.chmod(0o644)
    elif change == "added": (root / "added.js").write_text("module.exports = 1\n")
    elif change == "deleted": target.unlink()
    else:
        binary = root / ".bin/tsc"; binary.unlink()
        destination = (tmp_path / "outside.js") if change == "outside" else root / "missing.js" if change == "dangling" else root
        if change == "outside": destination.write_text("#!/bin/sh\nexit 0\n"); destination.chmod(0o755)
        binary.symlink_to(destination)
    before = f["task"].path.read_bytes()
    with pytest.raises(delivery.DevelopmentDeliveryError, match="Node.*(closure|provenance)|installed Node"):
        _refresh(f)
    assert f["task"].path.read_bytes() == before


@pytest.mark.parametrize("change", ["self-asserted", "missing-preflight", "wrong-check", "no-capture",
    "capture-output", "install-command-sha", "lockfile-sha", "wrong-lock", "foreign-snapshot"])
def test_native_install_capture_authority_cannot_be_substituted(tmp_path, change):
    f = _fixture(tmp_path, node_commands=True)
    request = json.loads(f["request"].read_text()); rows = request["evidence"]["validation_runs"]
    row = rows[0]; terminal_path = Path(row["terminal"]["path"]); terminal = json.loads(terminal_path.read_text())
    command_path = Path(row["command_receipt"]["path"]); command = json.loads(command_path.read_text())
    snapshot_path = Path(row["node_install_closure"]["path"]); snapshot = json.loads(snapshot_path.read_text())
    if change == "missing-preflight": row.pop("preflight")
    elif change == "wrong-check": command["preflight_checks"] = ["true"]
    elif change == "no-capture": terminal["checks"] = terminal["checks"][:1]
    elif change == "capture-output": terminal["checks"][1]["output_tail"] = '{"operation":"capture"}\n'
    elif change == "install-command-sha": snapshot["command_sha256"] = "0" * 64
    elif change == "lockfile-sha": snapshot["lockfile_sha256"] = "0" * 64
    elif change == "wrong-lock": command["mutation_lock"] = str(f["packet"] / "artifacts/other.lock")
    elif change == "foreign-snapshot":
        snapshot_path = _write(f["packet"] / "artifacts/self-asserted.json", snapshot)
    elif change == "self-asserted": snapshot["entries"] = []
    _write(command_path, command); _write(terminal_path, terminal); _write(snapshot_path, snapshot)
    row["command_receipt"], row["terminal"], row["node_install_closure"] = _bound(command_path), _bound(terminal_path), _bound(snapshot_path)
    _write(f["request"], request)
    before = f["task"].path.read_bytes()
    with pytest.raises(delivery.DevelopmentDeliveryError, match="Node|validation proof"):
        _refresh(f)
    assert f["task"].path.read_bytes() == before


def test_dependency_closure_is_rechecked_under_task_lock_before_authority(tmp_path, monkeypatch):
    f = _fixture(tmp_path, node_commands=True)
    original = delivery._file_lock
    @contextmanager
    def mutate_after_admission(path):
        with original(path):
            (f["worktree"] / "node_modules/added-after-preflight.js").write_text("module.exports = 0\n")
            yield
    monkeypatch.setattr(delivery, "_file_lock", mutate_after_admission)
    before = f["task"].path.read_bytes()
    with pytest.raises(delivery.DevelopmentDeliveryError, match="closure changed"):
        _refresh(f)
    assert f["task"].path.read_bytes() == before


def test_real_native_post_check_rejects_dependency_change_during_command(tmp_path):
    f = _fixture(tmp_path, node_commands=True)
    rows = json.loads(f["request"].read_text())["evidence"]["validation_runs"]
    install_run = Path(rows[0]["command_receipt"]["path"]).parent
    from genomes_agentic_os.validation_node_provenance import guard_checks
    identifier = "actual-post-mutation"
    run = f["packet"] / "artifacts/command-runs/async-runs" / identifier
    pre, post = guard_checks(install_run, run, f["worktree"], rows[0]["node_install_closure"]["sha256"])
    target = f["worktree"] / "node_modules/synthetic-typescript/cli.js"
    state = start_run(f["root"], command=[sys.executable, "-I", "-S", "-c",
            "from pathlib import Path;Path(" + repr(str(target)) + ").write_text('green no-op');print('command returned zero')"],
        label="actual change while governed command runs", run_id=identifier,
        artifact_dir=str(f["packet"] / "artifacts/command-runs"), work_dir=str(f["worktree"]),
        expected_git_identity=json.loads(Path(rows[0]["command_receipt"]["path"]).read_text())["expected_git_identity"],
        mutation_lock=str(f["packet"] / "artifacts" / LOCK), preflight_checks=[pre], post_run_checks=[post],
        budgets={"wall_clock_minutes": 1, "no_progress_minutes": 1})
    result = _wait_for(Path(state["run_dir"]), {"success", "failure", "error"})
    receipt = json.loads((run / "terminal-receipt.json").read_text())
    assert result["status"] == "failure" and receipt["exit_code"] == 0
    assert receipt["reason"] == "post-run-invariant-failed" and receipt["post_run_invariants_ok"] is False
    assert receipt["checks"][0]["ok"] is True and receipt["checks"][1]["ok"] is False
    assert not (f["packet"] / "artifacts" / LOCK).exists()


@pytest.mark.parametrize("operation", ["preflight-fails", "all-pass"])
def test_native_lock_covers_preflight_command_postflight_and_releases(tmp_path, operation):
    lock = tmp_path / "execution.lock"; trace = tmp_path / "ordered.jsonl"
    def code(phase, exit_code=0):
        return ("import json;from pathlib import Path; "
            f"lock=Path({str(lock)!r});trace=Path({str(trace)!r}); "
            "assert lock.is_file(); owner=json.loads(lock.read_text()); assert owner['run_id']=='locked-order'; "
            f"f=trace.open('a');f.write({phase!r}+'\\n');f.close();raise SystemExit({exit_code})")
    pre = shlex.join([sys.executable, "-c", code("preflight", 1 if operation == "preflight-fails" else 0)])
    post = shlex.join([sys.executable, "-c", code("post-run")])
    state = start_run(tmp_path / "os", command=[sys.executable, "-c", code("command")], label="locked actual ordering",
        run_id="locked-order", artifact_dir=str(tmp_path / "artifacts"), work_dir=str(tmp_path),
        mutation_lock=str(lock), preflight_checks=[pre], post_run_checks=[post],
        budgets={"wall_clock_minutes": 1, "no_progress_minutes": 1})
    result = _wait_for(Path(state["run_dir"]), {"success", "failure", "error"})
    assert result["status"] == ("failure" if operation == "preflight-fails" else "success")
    assert trace.read_text().splitlines() == (["preflight"] if operation == "preflight-fails" else ["preflight", "command", "post-run"])
    assert not lock.exists()


@pytest.mark.parametrize("failure", ["preflight-file", "output-log", "foreign-lock", "cancel-preflight"])
def test_actual_native_lock_cleanup_on_error_conflict_and_cancellation(tmp_path, failure):
    lock, ready = tmp_path / "execution.lock", tmp_path / "ready"
    identifier = "actual-lock-cleanup"
    run = tmp_path / "artifacts/async-runs" / identifier
    code = "from pathlib import Path;import time;Path(" + repr(str(ready)) + ").write_text('ready');"
    if failure == "preflight-file": code += "Path(" + repr(str(run / "preflight.json")) + ").mkdir()"
    elif failure == "output-log": code += "Path(" + repr(str(run / "output.log")) + ").mkdir()"
    elif failure == "cancel-preflight": code += "time.sleep(5)"
    else: code += "print('preflight')"
    if failure == "foreign-lock":
        _write(lock, {"run_id": "other-live-run", "pid": os.getpid()}); original = lock.read_bytes()
    start_run(tmp_path / "os", command=[sys.executable, "-c", "print('actual command')"],
        label="actual error and cancellation cleanup", run_id=identifier,
        artifact_dir=str(tmp_path / "artifacts"), work_dir=str(tmp_path), mutation_lock=str(lock),
        preflight_checks=[shlex.join([sys.executable, "-c", code])],
        budgets={"wall_clock_minutes": 1, "no_progress_minutes": 1})
    if failure == "cancel-preflight":
        import time
        deadline = time.monotonic() + 10
        while not ready.exists() and time.monotonic() < deadline: time.sleep(0.02)
        assert ready.exists() and lock.exists()
        try: control_run(run, "cancel", grace_seconds=5)
        except ProcessLookupError: pass  # Honest published cancellation can win this existing transport race.
    result = _wait_for(run, {"success", "failure", "error", "cancelled"})
    assert result["status"] == ("cancelled" if failure == "cancel-preflight" else "error")
    if failure == "foreign-lock":
        assert lock.read_bytes() == original and not ready.exists()
    else:
        assert not lock.exists()


def test_actual_native_same_run_id_different_live_pid_conflict_preserves_owner(tmp_path):
    import time
    lock, ready, finish = tmp_path / "shared.lock", tmp_path / "owner-ready", tmp_path / "finish-owner"
    code = ("from pathlib import Path;import time;Path(" + repr(str(ready)) + ").write_text('ready');"
            "deadline=time.monotonic()+15;\n"
            "while not Path(" + repr(str(finish)) + ").exists() and time.monotonic()<deadline: time.sleep(.02)\n"
            "assert Path(" + repr(str(finish)) + ").exists();print('owner finished')")
    first = start_run(tmp_path / "owner-os", command=[sys.executable, "-c", code],
        label="first actual monitor holds lock", run_id="same-run-id",
        artifact_dir=str(tmp_path / "owner-artifacts"), work_dir=str(tmp_path), mutation_lock=str(lock),
        budgets={"wall_clock_minutes": 1, "no_progress_minutes": 1})
    deadline = time.monotonic() + 10
    while not ready.exists() and time.monotonic() < deadline: time.sleep(.02)
    assert ready.exists() and lock.exists()
    original = lock.read_bytes(); owner = json.loads(original)
    assert owner["run_id"] == "same-run-id" and owner["pid"] == first["monitor_pid"]
    try:
        second = start_run(tmp_path / "contender-os", command=[sys.executable, "-c", "print('must not execute')"],
            label="second actual monitor same ID different PID", run_id="same-run-id",
            artifact_dir=str(tmp_path / "contender-artifacts"), work_dir=str(tmp_path), mutation_lock=str(lock),
            budgets={"wall_clock_minutes": 1, "no_progress_minutes": 1})
        assert second["monitor_pid"] != owner["pid"]
        outcome = _wait_for(Path(second["run_dir"]), {"success", "failure", "error"})
        assert outcome["status"] == "error" and "mutation-lock-acquire-failed" in outcome["terminal_reason"]
        os.kill(owner["pid"], 0)
        assert lock.is_file() and lock.read_bytes() == original
        assert not (Path(second["run_dir"]) / "output.log").exists()
        # Actual continued exclusivity: a third native monitor still cannot
        # enter the first monitor's preflight/command/post-check window.
        third = start_run(tmp_path / "third-os", command=[sys.executable, "-c", "print('must not execute')"],
            label="third actual monitor cannot enter", run_id="other-run-id",
            artifact_dir=str(tmp_path / "third-artifacts"), work_dir=str(tmp_path), mutation_lock=str(lock),
            budgets={"wall_clock_minutes": 1, "no_progress_minutes": 1})
        assert _wait_for(Path(third["run_dir"]), {"success", "failure", "error"})["status"] == "error"
        assert lock.read_bytes() == original
    finally:
        finish.write_text("finish")
        assert _wait_for(Path(first["run_dir"]), {"success", "failure", "error"})["status"] == "success"
    deadline = time.monotonic() + 2
    while lock.exists() and time.monotonic() < deadline: time.sleep(.02)
    assert not lock.exists()


@pytest.mark.parametrize("change", ["missing", "redirected-root", "fifo", "group-write", "symlink-directory"])
def test_unqualified_closure_is_refused(tmp_path, change):
    root = tmp_path / "node_modules"; root.mkdir()
    if change == "missing": root.rmdir()
    elif change == "redirected-root":
        root.rmdir(); other = tmp_path / "other"; other.mkdir(); root.symlink_to(other, target_is_directory=True)
    elif change == "fifo": os.mkfifo(root / "pipe")
    elif change == "group-write": (root / "package.js").write_text("1"); (root / "package.js").chmod(0o666)
    else: (root / "recursive").symlink_to(root, target_is_directory=True)
    with pytest.raises((ValueError, OSError)):
        dependency_closure(tmp_path)


def _guard_context(tmp_path):
    """Synthetic helper-unit context only; never offered as native admission proof."""
    worktree = tmp_path / "worktree"; worktree.mkdir()
    (worktree / "package-lock.json").write_text('{}\n')
    root = worktree / "node_modules"; (root / ".bin").mkdir(parents=True)
    for name in ("tsc", "playwright"):
        path = root / (name + ".js"); path.write_text("#!/usr/bin/env node\nprocess.exit(0)\n"); path.chmod(0o755)
        (root / ".bin" / name).symlink_to("../" + path.name)
    base = tmp_path / "packet/artifacts/command-runs/async-runs"
    install, dependent = base / "install", base / "dependent"
    identity = {"head": "1" * 40, "clean": "false"}
    lock = install.parents[2] / LOCK
    for run, command in ((install, ["npm", "ci"]), (dependent, ["npx", "playwright", "test", "--list"])):
        _write(run / "command.json", {"id": run.name, "run_dir": str(run), "work_dir": str(worktree),
            "expected_git_identity": identity, "mutation_lock": str(lock), "command": command,
            "environment_overrides": {"PWTEST_CACHE_DIR": str(run / "playwright-cache")}})
    _write(lock, {"run_id": install.name, "pid": os.getpid()})
    return install, dependent, worktree, lock


def test_helper_library_refuses_replay_stale_capture_and_cached_generated_code(tmp_path):
    install, dependent, worktree, lock = _guard_context(tmp_path)
    run_guard("prepare", install, install, worktree, "preflight", "-")
    capture = run_guard("capture", install, install, worktree, "post-run", "-")
    with pytest.raises(ValueError, match="existing snapshot"):
        run_guard("prepare", install, install, worktree, "preflight", "-")
    with pytest.raises(FileExistsError):
        run_guard("capture", install, install, worktree, "post-run", "-")
    _write(lock, {"run_id": dependent.name, "pid": os.getpid()})
    digest = capture["snapshot_sha256"]
    run_guard("verify", install, dependent, worktree, "preflight", digest)
    cache = dependent / "playwright-cache"; (cache / "generated.js").write_text("module.exports=0\n")
    run_guard("verify", install, dependent, worktree, "post-run", digest)
    with pytest.raises(FileExistsError):
        run_guard("verify", install, dependent, worktree, "preflight", digest)
    with pytest.raises(ValueError, match="SHA changed"):
        run_guard("verify", install, dependent, worktree, "post-run", "0" * 64)


@pytest.mark.parametrize("change", ["redirected-run", "identity", "wrong-lock", "lock-owner", "dead-owner",
    "capture-phase", "verify-install", "unsupported", "stale-identity", "cache-outside"])
def test_helper_refuses_unqualified_context_or_cache(tmp_path, change):
    install, dependent, worktree, lock = _guard_context(tmp_path)
    capsule = run_guard("capture", install, install, worktree, "post-run", "-")
    _write(lock, {"run_id": dependent.name, "pid": os.getpid()})
    command_path = dependent / "command.json"; command = json.loads(command_path.read_text())
    operation, phase, actual_run = "verify", "preflight", dependent
    if change == "redirected-run":
        linked = tmp_path / "link"; linked.symlink_to(dependent, target_is_directory=True); actual_run = linked
    elif change == "identity": command["expected_git_identity"]["head"] = "2" * 40
    elif change == "wrong-lock": command["mutation_lock"] = str(tmp_path / "foreign.lock")
    elif change == "lock-owner": _write(lock, {"run_id": "foreign", "pid": os.getpid()})
    elif change == "dead-owner": _write(lock, {"run_id": dependent.name, "pid": -1})
    elif change == "capture-phase": operation, phase = "capture", "preflight"
    elif change == "verify-install":
        actual_run = install; _write(lock, {"run_id": install.name, "pid": os.getpid()})
    elif change == "unsupported": operation = "unsupported"
    elif change == "stale-identity":
        snapshot = json.loads((install / SNAPSHOT).read_text()); snapshot["identity"]["head"] = "2" * 40
        _write(install / SNAPSHOT, snapshot); capsule["snapshot_sha256"] = _bound(install / SNAPSHOT)["sha256"]
    elif change == "cache-outside": command["environment_overrides"]["PWTEST_CACHE_DIR"] = str(tmp_path / "shared-cache")
    _write(command_path, command)
    with pytest.raises(ValueError):
        run_guard(operation, install, actual_run, worktree, phase, capsule["snapshot_sha256"])


@pytest.mark.parametrize("payload", ['{"id":1,"id":2}', '[]'])
def test_helper_json_rejects_ambiguous_authority(tmp_path, payload):
    path = tmp_path / "invalid.json"; path.write_text(payload)
    with pytest.raises(ValueError): _json(path)
