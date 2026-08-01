"""Offline tests for the cross-review command's shared GitHub read boundary."""

from __future__ import annotations

import importlib.util
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
    }


def test_diff_read_keeps_the_legacy_unavailable_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    crossreview = _load_crossreview()
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    monkeypatch.setattr(crossreview, "github_command_from_environment", lambda: ["node", "bridge.mjs"])

    def unavailable(*_args, **_kwargs):
        raise GitHubBridgeError("UPSTREAM_TIMEOUT", "safe timeout")

    monkeypatch.setattr(crossreview, "bridge_get_pull_request_diff", unavailable)

    assert crossreview.get_pr_diff("acme/widgets", 42) == "(diff unavailable)"
