"""Offline contract tests for the Python-to-TypeScript Linear boundary."""

from __future__ import annotations

import json
import subprocess

import pytest

from genomes_agentic_os.linear_bridge import (
    BRIDGE_VERSION,
    REVIEWED_PLATFORM_BRIDGE_REVISION,
    LinearBridgeClient,
    LinearBridgeError,
    auth_from_environment,
    call_linear_bridge,
    command_from_environment,
)


def _success(result):
    def runner(*args, **kwargs):
        return subprocess.CompletedProcess(
            args=args[0],
            returncode=0,
            stdout=json.dumps({"version": BRIDGE_VERSION, "ok": True, "result": result}),
            stderr="",
        )

    return runner


def test_reviewed_platform_bridge_revision_is_exact() -> None:
    assert REVIEWED_PLATFORM_BRIDGE_REVISION == "9a4e34fb3b6120524877e117ac201ec0b46337eb"


def test_command_and_auth_modes_are_explicit() -> None:
    assert command_from_environment(
        {"GENOMES_LINEAR_BRIDGE_COMMAND": "node /tmp/linear.js"}
    ) == ["node", "/tmp/linear.js"]
    assert command_from_environment({}) is None
    assert auth_from_environment({"LINEAR_TOKEN": "token"}) == {"LINEAR_TOKEN": "token"}
    with pytest.raises(LinearBridgeError, match="Exactly one"):
        auth_from_environment({})
    with pytest.raises(LinearBridgeError, match="Exactly one"):
        auth_from_environment({"LINEAR_TOKEN": "one", "LINEAR_API_KEY": "two"})


def test_request_is_versioned_and_credentials_stay_out_of_payload() -> None:
    captured: dict[str, object] = {}

    def runner(*args, **kwargs):
        captured.update(kwargs)
        return _success({"viewer": {"id": "viewer"}})(*args, **kwargs)

    result = call_linear_bridge(
        ["node", "bridge.js"],
        "preflightIdentity",
        {"teamId": "team"},
        auth={"LINEAR_TOKEN": "secret-token"},
        runner=runner,
    )
    assert result == {"viewer": {"id": "viewer"}}
    assert json.loads(str(captured["input"])) == {
        "version": 1,
        "operation": "preflightIdentity",
        "args": {"teamId": "team"},
    }
    assert "secret-token" not in str(captured["input"])
    assert captured["env"]["LINEAR_TOKEN"] == "secret-token"
    assert "LINEAR_API_KEY" not in captured["env"]


def test_side_by_side_old_issue_shape_is_preserved() -> None:
    old = {
        "id": "issue-1",
        "identifier": "AGE-133",
        "url": "https://linear.app/genomes/issue/AGE-133/example",
        "state": {"id": "started", "name": "In Progress", "type": "started"},
        "priority": 2,
    }
    client = LinearBridgeClient(
        ["node", "bridge.js"], {"LINEAR_TOKEN": "secret"}, runner=_success(old)
    )
    assert client.request("getIssue", {"issue": "AGE-133"}) == old


def test_provider_and_process_failures_are_safe() -> None:
    def provider_failure(*args, **kwargs):
        return subprocess.CompletedProcess(
            args=args[0],
            returncode=0,
            stdout=json.dumps(
                {
                    "version": 1,
                    "ok": False,
                    "error": {"code": "PERMISSION_ERROR", "message": "raw body", "status": 403},
                }
            ),
            stderr="",
        )

    with pytest.raises(LinearBridgeError, match="operation failed") as error:
        call_linear_bridge(
            ["node", "bridge.js"],
            "getIssue",
            {"issue": "AGE-133"},
            auth={"LINEAR_TOKEN": "secret"},
            runner=provider_failure,
        )
    assert error.value.code == "PERMISSION_ERROR"
    assert "raw body" not in str(error.value)

    with pytest.raises(LinearBridgeError, match="exited unsuccessfully") as error:
        call_linear_bridge(
            ["node", "bridge.js"],
            "getIssue",
            {"issue": "AGE-133"},
            auth={"LINEAR_TOKEN": "secret"},
            runner=lambda *args, **kwargs: subprocess.CompletedProcess(
                args=args[0], returncode=1, stdout="", stderr="secret raw body"
            ),
        )
    assert "secret" not in str(error.value)


def test_timeout_and_invalid_response_fail_closed() -> None:
    with pytest.raises(LinearBridgeError, match="could not be executed"):
        call_linear_bridge(
            ["node", "bridge.js"],
            "getIssue",
            {"issue": "AGE-133"},
            auth={"LINEAR_TOKEN": "secret"},
            runner=lambda *args, **kwargs: (_ for _ in ()).throw(
                subprocess.TimeoutExpired(args[0], 1)
            ),
        )
    with pytest.raises(LinearBridgeError, match="unsupported response"):
        call_linear_bridge(
            ["node", "bridge.js"],
            "getIssue",
            {"issue": "AGE-133"},
            auth={"LINEAR_TOKEN": "secret"},
            runner=lambda *args, **kwargs: subprocess.CompletedProcess(
                args=args[0], returncode=0, stdout='{"version":0,"ok":true}', stderr=""
            ),
        )
