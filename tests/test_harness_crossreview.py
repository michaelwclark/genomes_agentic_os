"""Offline tests for the cross-review command's shared GitHub read boundary."""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from importlib.machinery import SourceFileLoader
from pathlib import Path

import pytest

from genomes_agentic_os.github_bridge import GitHubBridgeError


def _load_crossreview():
    script = Path(__file__).parents[1] / "harness/bin/agentic-os-pr-crossreview"
    spec = importlib.util.spec_from_loader(
        "agentic_os_pr_crossreview_test", SourceFileLoader("agentic_os_pr_crossreview_test", str(script))
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_metadata_read_uses_the_shared_bridge_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    crossreview = _load_crossreview()
    monkeypatch.setattr(
        crossreview,
        "_bridge_pull_request",
        lambda repo, pr: {
            "title": "Bridge migration",
            "body": "Read only",
            "headBranch": "feature/read",
            "headSha": "exact-head",
            "author": "octocat",
        },
    )

    assert crossreview.get_pr_meta("acme/widgets", 42) == {
        "title": "Bridge migration",
        "body": "Read only",
        "head_branch": "feature/read",
        "head_sha": "exact-head",
        "author_login": "octocat",
    }


def test_metadata_read_rejects_an_absent_head_sha(monkeypatch: pytest.MonkeyPatch) -> None:
    crossreview = _load_crossreview()
    monkeypatch.setattr(crossreview, "_bridge_pull_request", lambda _repo, _pr: {"headSha": ""})

    with pytest.raises(SystemExit):
        crossreview.get_pr_meta("acme/widgets", 42)


def test_commit_read_is_bounded_and_keeps_the_legacy_message_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    crossreview = _load_crossreview()
    observed: dict[str, object] = {}
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    monkeypatch.setattr(crossreview, "github_command_from_environment", lambda: ["node", "bridge.mjs"])

    def list_commits(command, **kwargs):
        observed["command"] = command
        observed.update(kwargs)
        return [{"sha": "exact-commit", "message": "Subject\\n\\nCo-Authored-By: Claude"}]

    monkeypatch.setattr(crossreview, "bridge_list_pull_request_commits", list_commits)

    assert crossreview.get_pr_commits("acme/widgets", 42) == [
        {"sha": "exact-commit", "commit": {"message": "Subject\\n\\nCo-Authored-By: Claude"}}
    ]
    assert observed == {
        "command": ["node", "bridge.mjs"],
        "owner": "acme",
        "repo": "widgets",
        "number": 42,
        "token": "test-token",
        "limit": crossreview.MAX_COMMIT_SCAN,
    }


def test_diff_read_keeps_the_legacy_unavailable_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    crossreview = _load_crossreview()
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    monkeypatch.setattr(crossreview, "github_command_from_environment", lambda: ["node", "bridge.mjs"])

    def unavailable(*_args, **_kwargs):
        raise GitHubBridgeError("UPSTREAM_TIMEOUT", "safe timeout")

    monkeypatch.setattr(crossreview, "bridge_get_pull_request_diff", unavailable)

    assert crossreview.get_pr_diff("acme/widgets", 42) == "(diff unavailable)"


def test_consistent_input_read_guards_author_evidence_and_diff(monkeypatch: pytest.MonkeyPatch) -> None:
    crossreview = _load_crossreview()
    calls: list[str] = []
    metas = iter([
        {"head_sha": "first", "head_branch": "feature/read"},
        {"head_sha": "second", "head_branch": "feature/read"},
    ])
    monkeypatch.setattr(crossreview, "get_pr_meta", lambda _repo, _pr: (calls.append("meta"), next(metas))[1])
    monkeypatch.setattr(crossreview, "get_pr_commits", lambda _repo, _pr: calls.append("commits") or [])
    monkeypatch.setattr(crossreview, "get_pr_diff", lambda _repo, _pr: calls.append("diff") or "diff")

    assert crossreview.read_consistent_pr_inputs("acme/widgets", 42, include_commits=True) is None
    assert calls == ["meta", "commits", "diff", "meta"]


def test_commit_scan_fails_closed_at_the_explicit_bound(monkeypatch: pytest.MonkeyPatch) -> None:
    crossreview = _load_crossreview()
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    monkeypatch.setattr(crossreview, "github_command_from_environment", lambda: ["node", "bridge.mjs"])
    monkeypatch.setattr(
        crossreview,
        "bridge_list_pull_request_commits",
        lambda *_args, **_kwargs: [{"sha": str(i), "message": "message"} for i in range(crossreview.MAX_COMMIT_SCAN)],
    )

    with pytest.raises(SystemExit):
        crossreview.get_pr_commits("acme/widgets", 42)


def test_direct_script_help_bootstraps_the_source_package(tmp_path: Path) -> None:
    script = Path(__file__).parents[1] / "harness/bin/agentic-os-pr-crossreview"
    base_python = Path(sys.base_prefix) / "bin" / f"python{sys.version_info.major}.{sys.version_info.minor}"
    assert base_python.exists()
    (tmp_path / "yaml.py").write_text("def safe_load(_value):\n    return {}\n", encoding="utf-8")
    env = {**os.environ, "PYTHONPATH": str(tmp_path)}
    result = subprocess.run(
        [str(base_python), str(script), "--help"], capture_output=True, text=True, check=False, env=env
    )

    assert result.returncode == 0
    assert "Run a senior-engineer PR review" in result.stdout
