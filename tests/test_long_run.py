from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import time
from types import SimpleNamespace

import pytest

from genomes_agentic_os.cli import main
from genomes_agentic_os import long_run
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


def _wait_for(run_dir: Path, statuses: set[str], timeout: float = 90) -> dict[str, object]:
    # The terminal receipt lands via a detached monitor process, so loaded CI
    # runners need a generous deadline; the status is always re-read once after
    # the deadline expires so a write during the final sleep cannot be missed.
    deadline = time.monotonic() + timeout
    delay = 0.05
    while True:
        state = status_for_run(run_dir)
        if state.get("status") in statuses:
            return state
        if time.monotonic() >= deadline:
            raise AssertionError(
                f"run did not reach {statuses} within {timeout}s: {state}"
            )
        time.sleep(delay)
        delay = min(delay * 2, 1.0)


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


def test_long_run_persists_expected_and_observed_git_identity_at_both_boundaries(
    tmp_path: Path,
) -> None:
    root = tmp_path / "agentic_os"
    work_dir = tmp_path / "worktree"
    work_dir.mkdir()
    for command in (
        ["git", "init", "-q"],
        ["git", "config", "user.email", "test@example.com"],
        ["git", "config", "user.name", "Test User"],
        ["git", "remote", "add", "origin", "git@example.com:owner/repo.git"],
    ):
        subprocess.run(command, cwd=work_dir, check=True)
    (work_dir / "tracked.txt").write_text("tracked\n", encoding="utf-8")
    subprocess.run(["git", "add", "tracked.txt"], cwd=work_dir, check=True)
    subprocess.run(["git", "commit", "-qm", "initial"], cwd=work_dir, check=True)
    identity = {
        "repository": "git@example.com:owner/repo.git",
        "branch": subprocess.check_output(
            ["git", "branch", "--show-current"], cwd=work_dir, text=True
        ).strip(),
        "head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=work_dir, text=True).strip(),
        "clean": "true",
    }
    state = start_run(
        root,
        command=[sys.executable, "-c", "print('complete')"],
        label="guarded identity receipt",
        artifact_dir=str(tmp_path / "artifacts"),
        work_dir=str(work_dir),
        expected_git_identity=identity,
        budgets={"wall_clock_minutes": 1, "no_progress_minutes": 1},
    )
    run_dir = Path(state["run_dir"])
    terminal = _wait_for(run_dir, {"success", "failure", "error"})

    assert terminal["status"] == "success"
    receipt = json.loads((run_dir / "terminal-receipt.json").read_text(encoding="utf-8"))
    assert receipt["expected_git_identity"] == identity
    assert receipt["git_identity_pre"] == identity
    assert receipt["git_identity_post"] == identity


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


# AGE228 fixtures exercise the production admission and monitor boundaries with
# injected Git/worker/signal interfaces. They never inspect or signal real PIDs.
_AGE228_IDENTITY = {
    "repository": "git@example.com:owner/repo.git",
    "branch": "main", "head": "a" * 40, "clean": "true",
}


@pytest.fixture
def age228_signals(monkeypatch: pytest.MonkeyPatch):
    originals = {long_run.signal.SIGINT: object(), long_run.signal.SIGTERM: object()}
    current = dict(originals)

    def replace(number, handler):
        previous = current[number]
        current[number] = handler
        return previous

    monkeypatch.setattr(long_run.signal, "signal", replace)
    yield current
    assert current == originals


def _age228_admit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, **options):
    monkeypatch.setattr(long_run.subprocess, "Popen", lambda *a, **k: SimpleNamespace(pid=1234567))
    root = tmp_path / "private-os"
    state = start_run(root, command=["fixture-worker"], label="offline AGE228",
                      run_id="age228-fixture", artifact_dir=str(tmp_path / "receipts"),
                      work_dir=str(tmp_path), **options)
    run_dir = Path(state["run_dir"])

    def forbidden(*args, **kwargs):
        raise AssertionError("child dispatch must not occur")

    monkeypatch.setattr(long_run.subprocess, "Popen", forbidden)
    return root, run_dir


def _age228_git(monkeypatch: pytest.MonkeyPatch, *, changed=None, failing=None):
    outputs = {
        ("config", "--get", "remote.origin.url"): _AGE228_IDENTITY["repository"],
        ("branch", "--show-current"): _AGE228_IDENTITY["branch"],
        ("rev-parse", "HEAD"): _AGE228_IDENTITY["head"],
        ("status", "--porcelain"): "",
    }
    outputs.update(changed or {})
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        assert command[0] == "git"
        assert kwargs["timeout"] == 30
        key = tuple(command[1:])
        if key == ("branch", "--show-current") and failing is not None:
            if isinstance(failing, BaseException):
                raise failing
            return subprocess.CompletedProcess(command, failing, "", "private diagnostic canary")
        return subprocess.CompletedProcess(command, 0, outputs[key] + "\n", "")

    monkeypatch.setattr(long_run.subprocess, "run", run)
    return calls


def _age228_evidence(root: Path, run_dir: Path):
    receipt = json.loads((run_dir / "terminal-receipt.json").read_text())
    state = status_for_run(run_dir)
    row = next(row for row in read_registry(root)["runs"] if row["id"] == state["id"])
    assert receipt["status"] == state["status"] == row["status"]
    assert state["phase"] == row["phase"] == "terminal"
    assert any(json.loads(line)["event"] in {"terminal", "terminal-evidence-failed"}
               for line in (run_dir / "events.jsonl").read_text().splitlines())
    return receipt, state, row


@pytest.mark.parametrize("invalid", [
    [], "private diagnostic canary", True, 1,
    {"repository": "repo"}, {**_AGE228_IDENTITY, "unknown": "private diagnostic canary"},
    {**_AGE228_IDENTITY, "clean": 1}, {**_AGE228_IDENTITY, "clean": "True"},
    {**_AGE228_IDENTITY, "clean": "false "}, {**_AGE228_IDENTITY, "clean": []},
    {**_AGE228_IDENTITY, "repository": None}, {**_AGE228_IDENTITY, "head": ""},
    {**_AGE228_IDENTITY, "branch": "bad\nbranch"}, {**_AGE228_IDENTITY, "worktree": 3},
    {**_AGE228_IDENTITY, "repository": "r" * 4097},
])
def test_age228_admission_refuses_closed_identity_before_side_effects(tmp_path, monkeypatch, invalid):
    def forbidden(*a, **k):
        pytest.fail("invalid identity detached a monitor")
    monkeypatch.setattr(long_run.subprocess, "Popen", forbidden)
    with pytest.raises(LongRunError) as raised:
        start_run(tmp_path / "os", command=["fixture-worker"], label="invalid",
                  artifact_dir=str(tmp_path / "receipts"), expected_git_identity=invalid)
    assert "private diagnostic canary" not in str(raised.value)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("clean", [True, False, "true", "false"])
def test_age228_admission_normalizes_only_closed_clean_values(tmp_path, monkeypatch, clean):
    _, run_dir = _age228_admit(tmp_path, monkeypatch,
                              expected_git_identity={**_AGE228_IDENTITY, "clean": clean})
    command = json.loads((run_dir / "command.json").read_text())
    expected = "true" if clean is True else "false" if clean is False else clean
    assert command["expected_git_identity"] == {**_AGE228_IDENTITY, "clean": expected}


@pytest.mark.parametrize("failure", [1, OSError("private diagnostic canary"),
                                    subprocess.TimeoutExpired("private diagnostic canary", 30)])
def test_age228_git_failure_terminalizes_with_partial_observations(
    tmp_path, monkeypatch, age228_signals, failure
):
    root, run_dir = _age228_admit(tmp_path, monkeypatch, expected_git_identity=_AGE228_IDENTITY)
    _age228_git(monkeypatch, failing=failure)
    assert long_run.monitor_run(run_dir) == 0
    receipt, _, row = _age228_evidence(root, run_dir)
    assert receipt["status"] == "error"
    assert receipt["git_identity_pre"] == {"repository": _AGE228_IDENTITY["repository"]}
    assert receipt["failure_category"] == row["failure_category"] == "git-identity-collection"
    assert receipt["child_started"] is False
    assert receipt["post_run_invariants_ok"] is None
    assert "private diagnostic canary" not in "".join(p.read_text() for p in run_dir.iterdir())


@pytest.mark.parametrize("field,actual", [
    ("repository", "git@example.com:other/repo.git"), ("branch", "other"),
    ("head", "b" * 40), ("clean", " M tracked"), ("worktree", "different-root"),
])
def test_age228_each_exact_git_binding_mismatch_refuses_child(
    tmp_path, monkeypatch, age228_signals, field, actual
):
    expected = dict(_AGE228_IDENTITY)
    changed = {}
    keys = {"repository": ("config", "--get", "remote.origin.url"),
            "branch": ("branch", "--show-current"), "head": ("rev-parse", "HEAD"),
            "clean": ("status", "--porcelain")}
    if field == "worktree":
        expected[field] = str(tmp_path / actual)
    else:
        changed[keys[field]] = actual
    root, run_dir = _age228_admit(tmp_path, monkeypatch, expected_git_identity=expected)
    _age228_git(monkeypatch, changed=changed)
    assert long_run.monitor_run(run_dir) == 0
    receipt, _, _ = _age228_evidence(root, run_dir)
    assert receipt["status"] == "failure"
    assert receipt["failure_category"] == "git-identity-assertion"
    assert receipt["child_started"] is False
    assert not (run_dir / "preflight.json").exists()


@pytest.mark.parametrize("failure,expected_status", [(1, "failure"),
    (OSError("private diagnostic canary"), "error"),
    (subprocess.TimeoutExpired("private diagnostic canary", 120), "failure")])
def test_age228_production_checker_boundary_failure(tmp_path, monkeypatch, age228_signals, failure, expected_status):
    root, run_dir = _age228_admit(tmp_path, monkeypatch, preflight_checks=["fixture-check"])
    def run(command, **kwargs):
        assert command == "fixture-check" and kwargs["timeout"] == 120
        if isinstance(failure, Exception):
            raise failure
        return subprocess.CompletedProcess(command, failure, "", "")
    monkeypatch.setattr(long_run.subprocess, "run", run)
    assert long_run.monitor_run(run_dir) == 0
    receipt, _, _ = _age228_evidence(root, run_dir)
    assert receipt["status"] == expected_status
    assert receipt["failure_category"] == "preflight-checker"
    assert receipt["child_started"] is False
    assert "private diagnostic canary" not in (run_dir / "terminal-receipt.json").read_text()


def test_age228_completed_checker_evidence_survives_later_checker_exception(tmp_path, monkeypatch, age228_signals):
    root, run_dir = _age228_admit(tmp_path, monkeypatch, preflight_checks=["first-check", "later-check"])
    def run(command, **kwargs):
        if command == "later-check":
            raise OSError("private diagnostic canary")
        return subprocess.CompletedProcess(command, 0, "first-check-result", "")
    monkeypatch.setattr(long_run.subprocess, "run", run)
    assert long_run.monitor_run(run_dir) == 0
    receipt, _, _ = _age228_evidence(root, run_dir)
    assert receipt["status"] == "error"
    assert len(receipt["checks"]) == 1 and receipt["checks"][0]["ok"] is True
    assert receipt["checks"][0]["output_tail"] == "first-check-result"


@pytest.mark.parametrize("channel", ["state", "registry", "preflight"])
def test_age228_preflight_write_failure_is_terminal_not_queued(tmp_path, monkeypatch, age228_signals, channel):
    root, run_dir = _age228_admit(tmp_path, monkeypatch, expected_git_identity=_AGE228_IDENTITY)
    _age228_git(monkeypatch)
    original = long_run.atomic_json
    failed = []
    target = {"state": run_dir / "state.json", "registry": long_run.registry_path(root),
              "preflight": run_dir / "preflight.json"}[channel]
    def write(path, payload):
        if path == target and not failed:
            failed.append(path)
            raise OSError("private diagnostic canary")
        return original(path, payload)
    monkeypatch.setattr(long_run, "atomic_json", write)
    assert long_run.monitor_run(run_dir) == 0
    receipt, _, _ = _age228_evidence(root, run_dir)
    assert receipt["status"] == "error" and receipt["child_started"] is False
    assert receipt["git_identity_pre"] == _AGE228_IDENTITY
    assert receipt["failure_category"] == ("preflight-evidence-write" if channel == "preflight" else "preflight-state-write")


@pytest.mark.parametrize("cancelled", [False, True])
def test_age228_preflight_signal_restores_handlers_without_child(tmp_path, monkeypatch, age228_signals, cancelled):
    root, run_dir = _age228_admit(tmp_path, monkeypatch, preflight_checks=["fixture-check"])
    def check(command, **kwargs):
        if cancelled:
            long_run._atomic_state(run_dir, {"status": "cancelling"})
        age228_signals[long_run.signal.SIGTERM](long_run.signal.SIGTERM, None)
        return subprocess.CompletedProcess(command, 0, "", "")
    monkeypatch.setattr(long_run.subprocess, "run", check)
    assert long_run.monitor_run(run_dir) == 0
    receipt, _, _ = _age228_evidence(root, run_dir)
    assert receipt["status"] == ("cancelled" if cancelled else "interrupted")
    assert receipt["child_started"] is False


def test_age228_malformed_persisted_identity_is_sanitized(tmp_path, monkeypatch, age228_signals):
    root, run_dir = _age228_admit(tmp_path, monkeypatch)
    path = run_dir / "command.json"
    command = json.loads(path.read_text())
    command["expected_git_identity"] = {"unknown": "private diagnostic canary"}
    path.write_text(json.dumps(command))
    assert long_run.monitor_run(run_dir) == 0
    receipt, _, _ = _age228_evidence(root, run_dir)
    assert receipt["status"] == "failure" and receipt["expected_git_identity"] == {}
    assert receipt["failure_category"] == "expected-git-identity-validation"
    assert "private diagnostic canary" not in (run_dir / "terminal-receipt.json").read_text()


@pytest.mark.parametrize("channel", ["receipt", "state", "registry", "event", "summary"])
def test_age228_terminal_publication_has_finite_independent_fallback(
    tmp_path, monkeypatch, age228_signals, channel
):
    root, run_dir = _age228_admit(tmp_path, monkeypatch, expected_git_identity=_AGE228_IDENTITY)
    _age228_git(monkeypatch, changed={("branch", "--show-current"): "mismatch"})
    failures = []
    if channel in {"receipt", "state", "registry"}:
        original = long_run.atomic_json
        target = {"receipt": run_dir / "terminal-receipt.json", "state": run_dir / "state.json",
                  "registry": long_run.registry_path(root)}[channel]
        def write(path, payload):
            if path == target and payload.get("status") in {"failure", "error"} and not failures:
                failures.append(channel)
                raise OSError("private diagnostic canary")
            return original(path, payload)
        if channel == "registry":
            def write(path, payload):
                terminal = any(row.get("status") in {"failure", "error"} for row in payload.get("runs", []))
                if path == target and terminal and not failures:
                    failures.append(channel)
                    raise OSError("private diagnostic canary")
                return original(path, payload)
        monkeypatch.setattr(long_run, "atomic_json", write)
    else:
        name = "_append_event" if channel == "event" else "_write_summary"
        original = getattr(long_run, name)
        def publish(*args, **kwargs):
            if not failures:
                failures.append(channel)
                raise OSError("private diagnostic canary")
            return original(*args, **kwargs)
        monkeypatch.setattr(long_run, name, publish)
    assert long_run.monitor_run(run_dir) == 2
    receipt, _, row = _age228_evidence(root, run_dir)
    assert failures == [channel]
    assert receipt["status"] == "error" and receipt["original_outcome_status"] == "failure"
    assert receipt["terminal_evidence_incomplete"] is row["terminal_evidence_incomplete"] is True
    assert receipt["child_started"] is False
    assert "private diagnostic canary" not in "".join(p.read_text() for p in run_dir.iterdir())


def test_age228_permanently_unwritable_terminal_evidence_does_not_recurse(tmp_path, monkeypatch, age228_signals):
    root, run_dir = _age228_admit(tmp_path, monkeypatch, expected_git_identity=_AGE228_IDENTITY)
    _age228_git(monkeypatch, failing=OSError("private diagnostic canary"))
    calls = []
    def fail(*args, **kwargs):
        calls.append(args)
        raise OSError("private diagnostic canary")
    for name in ("atomic_json", "update_registry", "_append_event", "_write_summary"):
        monkeypatch.setattr(long_run, name, fail)
    assert long_run.monitor_run(run_dir) == 2
    assert len(calls) == 6  # one normal write plus five independent fallback channels
    assert not (run_dir / "terminal-receipt.json").exists()
    assert status_for_run(run_dir)["status"] == "queued"


@pytest.mark.parametrize("identity_kind", ["legacy", "boolean", "boolean-dirty", "worktree", "empty", "omitted"])
def test_age228_success_uses_production_dispatch_and_compatible_receipt_shape(
    tmp_path, monkeypatch, age228_signals, identity_kind
):
    expected = dict(_AGE228_IDENTITY)
    if identity_kind == "boolean":
        expected["clean"] = True
    elif identity_kind == "boolean-dirty":
        expected["clean"] = False
    elif identity_kind == "worktree":
        expected["worktree"] = str(tmp_path / ".")
    elif identity_kind == "empty":
        expected = {}
    elif identity_kind == "omitted":
        expected = None
    root, run_dir = _age228_admit(tmp_path, monkeypatch, expected_git_identity=expected)
    git_calls = _age228_git(monkeypatch, changed={
        ("status", "--porcelain"): " M tracked"
    } if identity_kind == "boolean-dirty" else None)
    _age228_worker(monkeypatch)
    assert long_run.monitor_run(run_dir) == 0
    receipt, _, _ = _age228_evidence(root, run_dir)
    normalized = dict(_AGE228_IDENTITY)
    if identity_kind == "boolean-dirty":
        normalized["clean"] = "false"
    if identity_kind == "worktree":
        normalized["worktree"] = str(tmp_path.resolve())
    if identity_kind in {"empty", "omitted"}:
        assert receipt["expected_git_identity"] == {}
        assert receipt["git_identity_pre"] is receipt["git_identity_post"] is None
        assert git_calls == []
    else:
        assert receipt["expected_git_identity"] == receipt["git_identity_pre"] == receipt["git_identity_post"] == normalized
        assert len(git_calls) == 8
    assert receipt["status"] == "success" and receipt["child_started"] is True


def _age228_worker(monkeypatch):
    worker = SimpleNamespace(pid=1234568, stdout=SimpleNamespace(fileno=lambda: 123), poll=lambda: 0)
    monkeypatch.setattr(long_run.subprocess, "Popen", lambda *a, **k: worker)
    monkeypatch.setattr(long_run.os, "set_blocking", lambda *a: None)
    monkeypatch.setattr(long_run.os, "read", lambda *a: b"")
    monkeypatch.setattr(long_run.select, "select", lambda *a: ([], [], []))
    monkeypatch.setattr(long_run, "_sample_process", lambda pid: {"cpu_percent": 0, "rss_mb": 1, "process_count": 1})
    monkeypatch.setattr(long_run, "_sample_collateral", lambda specs: [])
    monkeypatch.setattr(long_run, "_terminate_group", lambda *a, **k: None)


def test_age228_post_dispatch_git_mismatch_still_refuses_success(tmp_path, monkeypatch, age228_signals):
    root, run_dir = _age228_admit(tmp_path, monkeypatch, expected_git_identity=_AGE228_IDENTITY)
    calls = _age228_git(monkeypatch)
    original = long_run.subprocess.run
    def run(command, **kwargs):
        result = original(command, **kwargs)
        if len(calls) > 4 and command[1:] == ["rev-parse", "HEAD"]:
            result.stdout = "b" * 40
        return result
    monkeypatch.setattr(long_run.subprocess, "run", run)
    _age228_worker(monkeypatch)
    assert long_run.monitor_run(run_dir) == 0
    receipt, _, _ = _age228_evidence(root, run_dir)
    assert receipt["status"] == "error" and receipt["child_started"] is True
    assert receipt["git_identity_pre"] == _AGE228_IDENTITY
    assert receipt["git_identity_post"]["head"] == "b" * 40


def test_age228_cli_json_boolean_reaches_normalized_admission(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(long_run.subprocess, "Popen", lambda *a, **k: SimpleNamespace(pid=1234567))
    assert main(["long-run", "start", "--root", str(tmp_path / "os"),
                 "--artifact-dir", str(tmp_path / "receipts"), "--work-dir", str(tmp_path),
                 "--run-id", "cli-age228", "--json", "--expected-git-identity",
                 json.dumps({**_AGE228_IDENTITY, "clean": True}), "--", "fixture-worker"]) == 0
    state = json.loads(capsys.readouterr().out)
    command = json.loads((Path(state["run_dir"]) / "command.json").read_text())
    assert command["expected_git_identity"] == _AGE228_IDENTITY


@pytest.mark.parametrize("failure_at", ["construction", "close"])
def test_age228_log_boundary_failure_keeps_child_and_lock_evidence_truthful(
    tmp_path, monkeypatch, age228_signals, failure_at
):
    root, run_dir = _age228_admit(tmp_path, monkeypatch, mutation_lock="fixture-lock")
    lock_events = []
    class Lock:
        def __init__(self, *a, **k):
            pass
        def acquire(self):
            lock_events.append("acquire")
        def release(self):
            lock_events.append("release")
    original = long_run._BoundedLog
    class Log(original):
        def __init__(self, *a, **k):
            if failure_at == "construction":
                raise OSError("private diagnostic canary")
            super().__init__(*a, **k)
        def close(self):
            super().close()
            raise OSError("private diagnostic canary")
    monkeypatch.setattr(long_run, "MutationLock", Lock)
    monkeypatch.setattr(long_run, "_BoundedLog", Log)
    if failure_at == "close":
        _age228_worker(monkeypatch)
    assert long_run.monitor_run(run_dir) == 0
    receipt, _, _ = _age228_evidence(root, run_dir)
    assert receipt["status"] == "error"
    assert receipt["child_started"] is (failure_at == "close")
    assert lock_events == ["acquire", "release"]
    assert "private diagnostic canary" not in (run_dir / "terminal-receipt.json").read_text()
