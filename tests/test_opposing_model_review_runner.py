"""Focused offline guards for the opposing-model review transport."""

from __future__ import annotations

import hashlib
import importlib.util
import subprocess
from pathlib import Path

import pytest


def _load_runner():
    script = (
        Path(__file__).parents[1]
        / "harness/skills/auto-dev-review-self-opposing-model/scripts/run_opposing_model_review.py"
    )
    spec = importlib.util.spec_from_file_location("opposing_model_review_runner_test", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _completed(returncode: int, stdout: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess([], returncode, stdout, "")


def test_delta_validation_requires_parent_ancestry(monkeypatch: pytest.MonkeyPatch) -> None:
    runner = _load_runner()
    monkeypatch.setattr(runner, "run", lambda *_args, **_kwargs: _completed(1))

    with pytest.raises(runner.ReviewError, match="not an ancestor"):
        runner.validated_delta_hash(Path("/tmp/repo"), "a" * 40, "b" * 40)


def test_delta_validation_hashes_complete_oversized_descendant_diff(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _load_runner()
    results = iter(
        [_completed(0), _completed(0, "x" * (runner.MAX_DIFF_CHARS + 1))]
    )
    monkeypatch.setattr(runner, "run", lambda *_args, **_kwargs: next(results))

    assert runner.validated_delta_hash(
        Path("/tmp/repo"), "a" * 40, "b" * 40
    ) == runner.hashlib.sha256(
        ("x" * (runner.MAX_DIFF_CHARS + 1)).encode()
    ).hexdigest()


def test_delta_validation_returns_hash_for_one_bounded_descendant_diff(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _load_runner()
    delta = "diff --git a/file b/file\n+fixed\n"
    results = iter([_completed(0), _completed(0, delta)])
    monkeypatch.setattr(runner, "run", lambda *_args, **_kwargs: next(results))

    assert runner.validated_delta_hash(
        Path("/tmp/repo"), "a" * 40, "b" * 40
    ) == hashlib.sha256(delta.encode()).hexdigest()
