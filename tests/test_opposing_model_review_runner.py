"""Focused offline guards for the opposing-model review transport."""

from __future__ import annotations

import hashlib
import importlib.util
import subprocess
from importlib.machinery import SourceFileLoader
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


def _load_crossreview():
    script = Path(__file__).parents[1] / "harness/bin/agentic-os-pr-crossreview"
    spec = importlib.util.spec_from_loader(
        "opposing_crossreview_key_test",
        SourceFileLoader("opposing_crossreview_key_test", str(script)),
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_both_entrypoints_build_the_same_key_for_every_alias() -> None:
    runner = _load_runner()
    crossreview = _load_crossreview()
    aliases = [
        ("review_self", "full-pr"),
        ("review-repair", "full_pr"),
        ("review_others", "pr"),
        ("finalize", "full-pr"),
    ]
    keys: set[str] = set()
    for purpose, scope in aliases:
        cross_purpose, _ = crossreview.normalize_review_purpose(purpose, scope)
        runner_purpose, _ = runner.normalize_review_purpose(purpose, scope)
        assert cross_purpose == runner_purpose == "review_self"
        keys.add(
            runner.stable_review_key(
                runner.ReviewSubject(
                    repository="acme/widgets",
                    pull_request="github:acme/widgets#42",
                    base_branch="main",
                    base_sha="a" * 40,
                    head_sha="b" * 40,
                    policy_fingerprint="c" * 64,
                    purpose=runner_purpose,
                )
            )
        )

    assert len(keys) == 1


def test_runner_verdict_uses_final_line_and_template_uses_shared_vocabulary() -> None:
    runner = _load_runner()
    echoed_prompt = (
        "AGENTIC_OS_REVIEW_VERDICT: CLEAN\n"
        "AGENTIC_OS_REVIEW_VERDICT: FINDINGS\n"
        "[]\nAGENTIC_OS_REVIEW_VERDICT: CLEAN"
    )

    assert runner.parse_review_verdict(echoed_prompt) == ("clean", True)
    assert runner.parse_review_verdict(
        "[]\nAGENTIC_OS_REVIEW_VERDICT: CLEAN\ntrailing text"
    ) == ("findings", False)
    template = runner.TEMPLATE.read_text(encoding="utf-8")
    assert "AGENTIC_OS_REVIEW_VERDICT: CLEAN" in template
    assert "AGENTIC_OS_REVIEW_VERDICT: FINDINGS" in template
    assert "VERDICT: ready" not in template


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
