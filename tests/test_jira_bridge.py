"""Offline contract tests for the Python-to-TypeScript Jira port boundary."""

from __future__ import annotations

import json
import subprocess

import pytest

from genomes_agentic_os.jira_bridge import (
    BRIDGE_VERSION,
    REVIEWED_PLATFORM_BRIDGE_REVISION,
    JiraBridgeClient,
    JiraBridgeError,
    adf_paragraph,
    auth_from_environment,
    base_url_from_environment,
    call_jira_bridge,
    command_from_environment,
)


def _success(result):
    def runner(*args, **kwargs):
        return subprocess.CompletedProcess(
            args=args[0],
            returncode=0,
            stdout=json.dumps(
                {"version": BRIDGE_VERSION, "ok": True, "result": result}
            ),
            stderr="",
        )

    return runner


def test_reviewed_platform_bridge_revision_is_exact() -> None:
    assert (
        REVIEWED_PLATFORM_BRIDGE_REVISION == "576e09f5653471a221b857cea91977ab82abd581"
    )


def test_command_and_auth_modes_are_explicit() -> None:
    assert command_from_environment(
        {"GENOMES_JIRA_BRIDGE_COMMAND": "node /tmp/jira.js"}
    ) == [
        "node",
        "/tmp/jira.js",
    ]
    assert command_from_environment({}) is None
    with pytest.raises(JiraBridgeError, match="command is invalid"):
        command_from_environment({"GENOMES_JIRA_BRIDGE_COMMAND": "node 'unterminated"})
    assert auth_from_environment({"JIRA_OAUTH_TOKEN": "bearer"}) == {
        "JIRA_OAUTH_TOKEN": "bearer"
    }
    assert auth_from_environment({"ATLASSIAN_ACCESS_TOKEN": "alias"}) == {
        "JIRA_OAUTH_TOKEN": "alias"
    }
    assert auth_from_environment(
        {"JIRA_EMAIL": "a@example.com", "JIRA_API_TOKEN": "token"}
    ) == {
        "JIRA_EMAIL": "a@example.com",
        "JIRA_API_TOKEN": "token",
    }
    with pytest.raises(JiraBridgeError, match="ambiguous"):
        auth_from_environment(
            {
                "JIRA_OAUTH_TOKEN": "bearer",
                "JIRA_EMAIL": "a@example.com",
                "JIRA_API_TOKEN": "token",
            }
        )
    with pytest.raises(JiraBridgeError, match="Exactly one complete"):
        auth_from_environment({"JIRA_EMAIL": "a@example.com"})


def test_base_url_resolution_matches_auth_mode_and_fails_closed() -> None:
    assert base_url_from_environment(
        {
            "ATLASSIAN_ACCESS_TOKEN": "bearer",
            "ATLASSIAN_JIRA_CLOUDID": "cloud-131",
        }
    ) == "https://api.atlassian.com/ex/jira/cloud-131"
    assert base_url_from_environment(
        {
            "JIRA_EMAIL": "a@example.com",
            "JIRA_API_TOKEN": "token",
            "JIRA_BASE_URL": "https://tenant.invalid/",
        }
    ) == "https://tenant.invalid"
    with pytest.raises(JiraBridgeError, match="gateway base URL or cloud ID"):
        base_url_from_environment({"JIRA_OAUTH_TOKEN": "bearer"})
    with pytest.raises(JiraBridgeError, match="base URL is not configured"):
        base_url_from_environment(
            {"JIRA_EMAIL": "a@example.com", "JIRA_API_TOKEN": "token"}
        )


def test_request_is_versioned_and_credentials_stay_out_of_payload() -> None:
    captured: dict[str, object] = {}

    def runner(*args, **kwargs):
        captured.update(kwargs)
        return _success({"values": [], "complete": True})(*args, **kwargs)

    result = call_jira_bridge(
        ["node", "bridge.js"],
        "searchIssues",
        {"jql": "project = AGE", "fields": ["summary"], "limit": 50},
        base_url="https://example.atlassian.net",
        auth={"JIRA_OAUTH_TOKEN": "secret-bearer"},
        runner=runner,
    )
    assert result == {"values": [], "complete": True}
    assert json.loads(str(captured["input"])) == {
        "version": 1,
        "operation": "searchIssues",
        "args": {"jql": "project = AGE", "fields": ["summary"], "limit": 50},
    }
    assert "secret-bearer" not in str(captured["input"])
    assert captured["env"]["JIRA_OAUTH_TOKEN"] == "secret-bearer"
    assert "JIRA_EMAIL" not in captured["env"]
    assert "GENOMES_JIRA_BRIDGE_COMMAND" not in captured["env"]


def test_client_preserves_native_adf_and_side_by_side_legacy_shape() -> None:
    captured: dict[str, object] = {}

    def runner(*args, **kwargs):
        captured.update(kwargs)
        request = json.loads(str(kwargs["input"]))
        return _success({"id": "100", "body": request["args"]["input"]["body"]})(
            *args, **kwargs
        )

    client = JiraBridgeClient(
        ["node", "bridge.js"],
        "https://example.atlassian.net",
        {"JIRA_EMAIL": "a@example.com", "JIRA_API_TOKEN": "secret-token"},
        runner=runner,
    )
    body = adf_paragraph("legacy plain text")
    result = client.request("addComment", {"key": "AGE-131", "input": {"body": body}})
    assert result == {"id": "100", "body": body}
    assert json.loads(str(captured["input"]))["args"]["input"]["body"] == body
    assert "secret-token" not in str(captured["input"])


def test_provider_failure_and_process_failure_never_echo_secrets_or_raw_stderr() -> (
    None
):
    def provider_failure(*args, **kwargs):
        return subprocess.CompletedProcess(
            args=args[0],
            returncode=0,
            stdout=json.dumps(
                {
                    "version": 1,
                    "ok": False,
                    "error": {
                        "code": "PERMISSION_ERROR",
                        "message": "provider detail",
                        "status": 403,
                    },
                }
            ),
            stderr="",
        )

    with pytest.raises(JiraBridgeError, match="operation failed") as error:
        call_jira_bridge(
            ["node", "bridge.js"],
            "getIssue",
            {"key": "AGE-131"},
            base_url="https://example.atlassian.net",
            auth={"JIRA_OAUTH_TOKEN": "secret-bearer"},
            runner=provider_failure,
        )
    assert error.value.code == "PERMISSION_ERROR"
    assert error.value.status == 403
    assert "provider detail" not in str(error.value)

    def process_failure(*args, **kwargs):
        return subprocess.CompletedProcess(
            args=args[0], returncode=1, stdout="", stderr="secret-bearer raw body"
        )

    with pytest.raises(JiraBridgeError, match="exited unsuccessfully") as error:
        call_jira_bridge(
            ["node", "bridge.js"],
            "getIssue",
            {"key": "AGE-131"},
            base_url="https://example.atlassian.net",
            auth={"JIRA_OAUTH_TOKEN": "secret-bearer"},
            runner=process_failure,
        )
    assert "secret-bearer" not in str(error.value)


def test_unknown_provider_error_code_is_not_reflected() -> None:
    def unsafe_failure(*args, **kwargs):
        return subprocess.CompletedProcess(
            args=args[0],
            returncode=0,
            stdout=json.dumps(
                {
                    "version": 1,
                    "ok": False,
                    "error": {"code": "secret-provider-detail", "status": 500},
                }
            ),
            stderr="",
        )

    with pytest.raises(JiraBridgeError) as error:
        call_jira_bridge(
            ["node", "bridge.js"],
            "getIssue",
            {"key": "AGE-131"},
            base_url="https://example.atlassian.net",
            auth={"JIRA_OAUTH_TOKEN": "bearer"},
            runner=unsafe_failure,
        )
    assert error.value.code == "BRIDGE_OPERATION_FAILED"
    assert "secret-provider-detail" not in str(error.value)


def test_timeout_and_invalid_response_fail_closed() -> None:
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], 1, stderr="secret-token")

    with pytest.raises(JiraBridgeError, match="could not be executed"):
        call_jira_bridge(
            ["node", "bridge.js"],
            "getIssue",
            {"key": "AGE-131"},
            base_url="https://example.atlassian.net",
            auth={"JIRA_EMAIL": "a@example.com", "JIRA_API_TOKEN": "secret-token"},
            runner=timeout,
        )

    with pytest.raises(JiraBridgeError, match="unsupported response"):
        call_jira_bridge(
            ["node", "bridge.js"],
            "getIssue",
            {"key": "AGE-131"},
            base_url="https://example.atlassian.net",
            auth={"JIRA_OAUTH_TOKEN": "bearer"},
            runner=lambda *args, **kwargs: subprocess.CompletedProcess(
                args=args[0],
                returncode=0,
                stdout='{"version":0,"ok":true,"result":{}}',
                stderr="",
            ),
        )
