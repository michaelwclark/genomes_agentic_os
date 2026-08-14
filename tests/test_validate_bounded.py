from __future__ import annotations

import importlib
import multiprocessing
import os
from pathlib import Path
import signal
import threading
import time
from typing import Any

from genomes_agentic_os.cli import main
from genomes_agentic_os.validate import ValidationResult


cli_validate = importlib.import_module("genomes_agentic_os.cli.validate")


def _silent_worker(queue: Any, root: str, scope: str, strict: bool) -> None:
    del queue, root, scope, strict
    time.sleep(10)


def _failed_worker(queue: Any, root: str, scope: str, strict: bool) -> None:
    del root, scope, strict
    queue.put(("error", {"type": "RuntimeError", "message": "synthetic failure"}))


def _progressing_scope(
    root: str,
    scope: str,
    *,
    progress: Any = None,
) -> ValidationResult:
    for index in range(6):
        time.sleep(0.04)
        progress(f"{scope}:batch-{index}")
    return ValidationResult(root=Path(root))


def _interruptible_worker(queue: Any, root: str, scope: str, strict: bool) -> None:
    del strict
    pid_path = Path(root) / "validation-worker.pid"
    pid_path.write_text(str(os.getpid()), encoding="utf-8")
    queue.put(("progress", {"scope": scope, "stage": scope, "status": "started"}))
    time.sleep(10)


def test_scoped_validation_reports_scope_and_progress(tmp_path: Path, capsys: Any) -> None:
    root = tmp_path / "agentic_os"
    assert main(["init", "--target", str(root)]) == 0
    capsys.readouterr()

    exit_code = main(
        [
            "validate",
            "--root",
            str(root),
            "--scope",
            "registries",
            "--timeout-seconds",
            "10",
            "--no-progress-seconds",
            "5",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert f"valid: {root} (scope=registries)" in captured.out
    assert "progress: scope=registries stage=registries status=started" in captured.err
    assert "progress: scope=registries stage=registries status=completed" in captured.err
    assert "progress: scope=registries stage=registries:capabilities status=running" in captured.err


def test_slow_but_progressing_validation_is_not_misclassified_as_stalled(
    tmp_path: Path,
    capsys: Any,
    monkeypatch: Any,
) -> None:
    monkeypatch.setattr(cli_validate, "validate_scope", _progressing_scope)

    exit_code = main(
        [
            "validate",
            "--root",
            str(tmp_path),
            "--timeout-seconds",
            "2",
            "--no-progress-seconds",
            "0.08",
            "--progress-interval-seconds",
            "0.02",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "valid:" in captured.out
    assert "stage=root:batch-5 status=running" in captured.err


def test_no_progress_root_is_terminated_with_deterministic_status(
    tmp_path: Path,
    capsys: Any,
    monkeypatch: Any,
) -> None:
    monkeypatch.setattr(cli_validate, "_validation_worker", _silent_worker)
    started = time.monotonic()

    exit_code = main(
        [
            "validate",
            "--root",
            str(tmp_path),
            "--timeout-seconds",
            "2",
            "--no-progress-seconds",
            "0.1",
            "--progress-interval-seconds",
            "0.02",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 124
    assert time.monotonic() - started < 1.5
    assert "progress: scope=root stage=root status=running" in captured.err
    assert "validation scope=root terminated: no progress for 0.1s" in captured.err


def test_worker_failure_returns_concise_terminal_diagnostic(
    tmp_path: Path,
    capsys: Any,
    monkeypatch: Any,
) -> None:
    monkeypatch.setattr(cli_validate, "_validation_worker", _failed_worker)

    exit_code = main(["validate", "--root", str(tmp_path)])

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "validation scope=root terminated: worker failed: RuntimeError: synthetic failure" in captured.err


def test_keyboard_interrupt_returns_130_and_reaps_validation_worker(
    tmp_path: Path,
    capsys: Any,
    monkeypatch: Any,
) -> None:
    monkeypatch.setattr(cli_validate, "_validation_worker", _interruptible_worker)
    pid_path = tmp_path / "validation-worker.pid"

    def interrupt_after_worker_starts() -> None:
        deadline = time.monotonic() + 2
        while not pid_path.is_file() and time.monotonic() < deadline:
            time.sleep(0.005)
        os.kill(os.getpid(), signal.SIGINT)

    interrupter = threading.Thread(target=interrupt_after_worker_starts)
    interrupter.start()
    exit_code = main(["validate", "--root", str(tmp_path)])
    interrupter.join(timeout=2)

    captured = capsys.readouterr()
    worker_pid = int(pid_path.read_text(encoding="utf-8"))
    assert exit_code == 130
    assert "validation scope=root terminated: cancelled safely" in captured.err
    assert worker_pid not in {child.pid for child in multiprocessing.active_children()}
    try:
        os.kill(worker_pid, 0)
    except ProcessLookupError:
        pass
    else:  # pragma: no cover - diagnostic if a child ever leaks
        raise AssertionError(f"validation worker {worker_pid} was not reaped")
