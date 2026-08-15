"""Focused offline guards for the opposing-model review transport."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
from types import SimpleNamespace
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
        "```json\n[]\n```\nAGENTIC_OS_REVIEW_VERDICT: CLEAN"
    )

    assert runner.parse_review_verdict(echoed_prompt) == ("clean", True)
    assert runner.parse_review_verdict(
        "```json\n[]\n```\nAGENTIC_OS_REVIEW_VERDICT: CLEAN\ntrailing text"
    ) == ("findings", False)
    assert runner.parse_review_verdict(
        "```json\n[{\"id\": \"F1\"}]\n```\nAGENTIC_OS_REVIEW_VERDICT: CLEAN"
    ) == ("clean", True)
    assert runner.parse_review_verdict(
        "```json\n[{\"id\": \"F1\", \"severity\": \"low\", "
        "\"blocking\": false}]\n```\nAGENTIC_OS_REVIEW_VERDICT: CLEAN"
    ) == ("clean", True)
    assert runner.parse_review_verdict(
        "```json\n[{\"id\": \"F1\", \"severity\": \"high\", "
        "\"blocking\": false}]\n```\nAGENTIC_OS_REVIEW_VERDICT: CLEAN"
    ) == ("clean", True)
    assert runner.parse_review_verdict(
        "```json\n[{\"id\": \"F1\", \"severity\": \"high\"}]\n```\n"
        "AGENTIC_OS_REVIEW_VERDICT: CLEAN"
    ) == ("findings", True)
    assert runner.parse_review_verdict(
        "```json\n[{\"id\": \"F1\", \"severity\": \"low\", "
        "\"blocking\": true}]\n```\nAGENTIC_OS_REVIEW_VERDICT: CLEAN"
    ) == ("findings", True)
    assert runner.parse_review_verdict(
        "```json\n[{\"id\": \"F1\", \"blocking\": true, "
        "\"status\": \"resolved\"}]\n```\nAGENTIC_OS_REVIEW_VERDICT: CLEAN"
    ) == ("clean", True)
    assert runner.parse_review_verdict(
        "```json\n[{\"id\": \"F1\", \"blocking\": true}]\n```\n"
        "```json\n[]\n```\nAGENTIC_OS_REVIEW_VERDICT: CLEAN"
    ) == ("findings", True)
    assert runner.parse_review_verdict(
        "```json\n[{\"id\": \"F1\", "
        "\"severity\": \"critical | high | medium | low\", "
        "\"category\": \"correctness | tests\", \"blocking\": true}]\n```\n"
        "```json\n[]\n```\nAGENTIC_OS_REVIEW_VERDICT: CLEAN"
    ) == ("clean", True)
    template = runner.TEMPLATE.read_text(encoding="utf-8")
    assert "AGENTIC_OS_REVIEW_VERDICT: CLEAN" in template
    assert "AGENTIC_OS_REVIEW_VERDICT: FINDINGS" in template
    assert "VERDICT: ready" not in template


def _installed_root(path: Path) -> Path:
    path.mkdir(parents=True)
    (path / ".agentic_root").write_text("installed\n", encoding="utf-8")
    (path / "harness").mkdir()
    (path / "domains").mkdir()
    return path


def test_runner_default_root_uses_environment_not_current_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runner = _load_runner()
    canonical = _installed_root(tmp_path / "canonical")
    private_cwd = tmp_path / "worktree"
    private_cwd.mkdir()
    monkeypatch.chdir(private_cwd)
    monkeypatch.setenv("AGENTIC_OS_ROOT", str(canonical))

    assert runner.resolve_os_root(None) == canonical.resolve()


def test_runner_default_root_fails_closed_instead_of_using_cwd(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runner = _load_runner()
    private_cwd = tmp_path / "worktree"
    private_cwd.mkdir()
    monkeypatch.chdir(private_cwd)
    monkeypatch.delenv("AGENTIC_OS_ROOT", raising=False)
    monkeypatch.setattr(runner, "INSTALLED_OS_ROOT", tmp_path / "missing-installed-root")

    with pytest.raises(runner.ReviewError, match="installed Agentic OS root"):
        runner.resolve_os_root(None)


def test_runner_explicit_root_must_match_configured_canonical_root(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runner = _load_runner()
    canonical = _installed_root(tmp_path / "canonical")
    other = _installed_root(tmp_path / "other")
    monkeypatch.setenv("AGENTIC_OS_ROOT", str(canonical))

    with pytest.raises(runner.ReviewCoordinationError, match="disagrees"):
        runner.resolve_os_root(other)


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


def test_runner_request_run_id_matches_created_artifact_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runner = _load_runner()
    work_item = tmp_path / "work-item"
    worktree = tmp_path / "worktree"
    work_item.mkdir()
    worktree.mkdir()
    head = "b" * 40
    review_key = "review-key"
    source = {
        "work_item_id": "AGE-196",
        "worktree": str(worktree),
        "repo_path": str(worktree),
        "implementation_summary": "Bind the review receipt to its artifact directory.",
        "spec_source": "AGE-196 acceptance criteria",
        "builder_model": "gpt-5.6",
        "reviewer_model": "opus",
        "selected_reviewer_model": "opus",
        "reviewer_selection_source": "project-policy",
        "target_branch": "main",
        "base_sha": "a" * 40,
        "head_sha": head,
        "diff_hash": "d" * 64,
        "pr_number": 42,
        "artifact_dir": "stale-artifact-dir",
        "mode": "post_pr",
    }
    provider = {
        "number": 42,
        "url": "https://example.test/acme/widgets/pull/42",
        "state": "OPEN",
        "headRefOid": head,
        "baseRefName": "main",
        "statusCheckRollup": [],
    }

    class FakeCoordinator:
        def __init__(self, _root: Path) -> None:
            pass

        def execute(self, _subject, execute_review, **_kwargs):
            review = execute_review()
            return SimpleNamespace(
                key=review_key,
                receipt={"review": review, "outcome": review["outcome"]},
                receipt_path=tmp_path / "coordination-receipt.json",
                reused=False,
            )

    monkeypatch.setattr(runner, "resolve_os_root", lambda _explicit: tmp_path)
    monkeypatch.setattr(runner, "prior_request", lambda *_args: source)
    monkeypatch.setattr(runner, "provider_pr", lambda *_args: provider)
    monkeypatch.setattr(runner, "git_head", lambda _worktree: head)
    monkeypatch.setattr(runner, "git_repository", lambda _worktree: "acme/widgets")
    monkeypatch.setattr(runner, "stable_review_key", lambda _subject: review_key)
    monkeypatch.setattr(runner, "diff_hash", lambda *_args: "d" * 64)
    monkeypatch.setattr(runner, "ReviewCoordinator", FakeCoordinator)
    monkeypatch.setattr(runner.shutil, "which", lambda _name: None)
    monkeypatch.setattr(runner, "decide", lambda _run_dir: {"decision": "blocked_model_identity"})
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_opposing_model_review.py",
            "AGE-196",
            "--os-root",
            str(tmp_path),
            "--work-item",
            str(work_item),
            "--worktree",
            str(worktree),
        ],
    )

    assert runner.main() == 2
    run_dir = work_item / "artifacts/finishing-touches/review-runs" / review_key
    request = json.loads((run_dir / "review-request.json").read_text(encoding="utf-8"))

    assert request["run_id"] == run_dir.name == review_key
    validation = subprocess.run(
        [sys.executable, str(runner.HELPER), "validate", "--run-dir", str(run_dir)],
        text=True,
        capture_output=True,
        check=False,
    )
    assert validation.returncode == 0, validation.stderr
