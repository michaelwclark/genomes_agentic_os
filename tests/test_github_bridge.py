"""Offline contract tests for the Python-to-TypeScript GitHub port boundary."""

from __future__ import annotations

import json
import subprocess

import pytest

from genomes_agentic_os.github_bridge import (
    BRIDGE_VERSION,
    GitHubBridgeError,
    REVIEWED_PLATFORM_BRIDGE_REVISION,
    call_github_bridge,
    command_from_environment,
    list_issues,
    list_pull_requests,
)


def test_reviewed_platform_bridge_revision_is_exact() -> None:
    assert REVIEWED_PLATFORM_BRIDGE_REVISION == "448cd722d7feb8eb32c86b886627ade0346fdf4a"


def _runner(*args, **kwargs):
    return subprocess.CompletedProcess(args=args[0], returncode=0, stdout=json.dumps({
        "version": BRIDGE_VERSION,
        "ok": True,
        "result": {"pullRequests": [{"number": 42, "updatedAt": "2026-07-28T00:00:00.000Z"}]},
    }), stderr="")


def test_command_from_environment_uses_argv_not_a_shell() -> None:
    assert command_from_environment({"GENOMES_GITHUB_BRIDGE_COMMAND": "node /tmp/bridge.mjs"}) == ["node", "/tmp/bridge.mjs"]
    assert command_from_environment({}) is None


def test_list_pull_requests_sends_versioned_request_and_keeps_token_out_of_payload() -> None:
    captured: dict[str, object] = {}

    def runner(*args, **kwargs):
        captured.update(kwargs)
        return _runner(*args, **kwargs)

    result = list_pull_requests(["node", "bridge.mjs"], owner="genome", repo="os", token="secret-token", runner=runner)

    assert result == [{"number": 42, "updatedAt": "2026-07-28T00:00:00.000Z"}]
    request = json.loads(str(captured["input"]))
    assert request == {
        "version": 1,
        "operation": "listPullRequests",
        "repo": {"owner": "genome", "repo": "os"},
        "filter": {"state": "all", "limit": 30},
    }
    assert "secret-token" not in str(captured["input"])
    assert captured["env"]["GITHUB_TOKEN"] == "secret-token"


def test_list_issues_sends_incremental_filter_and_keeps_token_out_of_payload() -> None:
    captured: dict[str, object] = {}

    def runner(*args, **kwargs):
        captured.update(kwargs)
        return subprocess.CompletedProcess(
            args=args[0],
            returncode=0,
            stdout=json.dumps({
                "version": BRIDGE_VERSION,
                "ok": True,
                "result": {"issues": [{"number": 77, "pullRequest": False}]},
            }),
            stderr="",
        )

    result = list_issues(
        ["node", "bridge.mjs"],
        owner="genome",
        repo="os",
        token="secret-token",
        since="2026-07-28T00:00:00Z",
        runner=runner,
    )

    assert result == [{"number": 77, "pullRequest": False}]
    request = json.loads(str(captured["input"]))
    assert request == {
        "version": 1,
        "operation": "listIssues",
        "repo": {"owner": "genome", "repo": "os"},
        "filter": {
            "state": "all",
            "limit": 30,
            "since": "2026-07-28T00:00:00Z",
        },
    }
    assert "secret-token" not in str(captured["input"])
    assert captured["env"]["GITHUB_TOKEN"] == "secret-token"


def test_list_issues_omits_absent_since_and_rejects_invalid_result() -> None:
    captured: dict[str, object] = {}

    def runner(*args, **kwargs):
        captured.update(kwargs)
        return subprocess.CompletedProcess(
            args=args[0],
            returncode=0,
            stdout=json.dumps({"version": BRIDGE_VERSION, "ok": True, "result": {"issues": {}}}),
            stderr="",
        )

    with pytest.raises(GitHubBridgeError, match="invalid issues"):
        list_issues(
            ["node", "bridge.mjs"],
            owner="genome",
            repo="os",
            token="secret-token",
            runner=runner,
        )
    assert "since" not in json.loads(str(captured["input"]))["filter"]


def test_bridge_failure_does_not_echo_stderr_or_token() -> None:
    def failing(*args, **kwargs):
        return subprocess.CompletedProcess(args=args[0], returncode=1, stdout="", stderr="secret-token diagnostic")

    with pytest.raises(GitHubBridgeError, match="exited unsuccessfully") as error:
        call_github_bridge(["node", "bridge.mjs"], {"operation": "listPullRequests"}, token="secret-token", runner=failing)
    assert "secret-token" not in str(error.value)


def test_bridge_rejects_unknown_response_version() -> None:
    def old_version(*args, **kwargs):
        return subprocess.CompletedProcess(args=args[0], returncode=0, stdout=json.dumps({"version": 0, "ok": True, "result": {}}), stderr="")

    with pytest.raises(GitHubBridgeError, match="unsupported response"):
        call_github_bridge(["node", "bridge.mjs"], {"operation": "listPullRequests"}, token="secret-token", runner=old_version)
