from __future__ import annotations

import importlib
from pathlib import Path
import time
from typing import Any

from genomes_agentic_os.cli import main


cli_validate = importlib.import_module("genomes_agentic_os.cli.validate")


def _silent_worker(queue: Any, root: str, scope: str, strict: bool) -> None:
    del queue, root, scope, strict
    time.sleep(10)


def _failed_worker(queue: Any, root: str, scope: str, strict: bool) -> None:
    del root, scope, strict
    queue.put(("error", {"type": "RuntimeError", "message": "synthetic failure"}))


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
