from __future__ import annotations

import json
import subprocess

import pytest

from genomes_agentic_os.notion_bridge import (
    BRIDGE_VERSION,
    REVIEWED_PLATFORM_BRIDGE_REVISION,
    NotionBridgeClient,
    NotionBridgeError,
    auth_from_environment,
    call_notion_bridge,
    client_from_environment,
    command_from_environment,
    identity_from_environment,
)


def _success(result: object):
    def runner(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
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
        REVIEWED_PLATFORM_BRIDGE_REVISION
        == "d6ab26c5fb5281467bf7ef695b6f33d385a86d69"
    )


def test_command_parses_without_shell() -> None:
    assert command_from_environment(
        {"GENOMES_NOTION_BRIDGE_COMMAND": "node '/tmp/notion bridge.js'"}
    ) == ["node", "/tmp/notion bridge.js"]
    assert command_from_environment({}) is None
    with pytest.raises(NotionBridgeError, match="command is invalid"):
        command_from_environment(
            {"GENOMES_NOTION_BRIDGE_COMMAND": "node 'unterminated"}
        )


def test_auth_and_environment_client_fail_closed() -> None:
    assert auth_from_environment({"GENOMES_NOTION_PAT": "token"}) == {
        "GENOMES_NOTION_PAT": "token"
    }
    with pytest.raises(NotionBridgeError, match="GENOMES_NOTION_PAT is required"):
        auth_from_environment({})
    with pytest.raises(NotionBridgeError, match="command is not configured"):
        client_from_environment({"GENOMES_NOTION_PAT": "token"})


def test_identity_defaults_to_genomes_notion() -> None:
    assert identity_from_environment(
        {"GENOMES_NOTION_PARENT_PAGE_ID": "parent"}
    ) == {"workspaceName": "Genome's Notion", "parentPageId": "parent"}


def test_mutation_requires_identity_before_runner() -> None:
    called = False

    def runner(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        nonlocal called
        called = True
        return subprocess.CompletedProcess([], 0, "{}", "")

    client = NotionBridgeClient(["node", "bridge.js"], {"GENOMES_NOTION_PAT": "secret"}, runner=runner)
    with pytest.raises(NotionBridgeError, match="exact workspace") as exc:
        client.request("trashPage", {"pageId": "page"}, mutation=True)
    assert exc.value.code == "IDENTITY_MISMATCH"
    assert called is False


def test_child_environment_and_payload_are_bounded() -> None:
    captured: dict[str, object] = {}

    def runner(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        captured.update(kwargs)
        return subprocess.CompletedProcess(
            [], 0, json.dumps({"version": 1, "ok": True, "result": {"id": "page"}}), ""
        )

    result = call_notion_bridge(
        ["node", "bridge.js"],
        "getPage",
        {"pageId": "page"},
        auth={"GENOMES_NOTION_PAT": "secret"},
        identity={"workspaceName": "Genome's Notion", "parentPageId": "parent"},
        runner=runner,
    )
    assert result == {"id": "page"}
    payload = json.loads(str(captured["input"]))
    assert payload["identity"]["parentPageId"] == "parent"
    assert "secret" not in str(captured["input"])
    child_env = captured["env"]
    assert isinstance(child_env, dict)
    assert child_env["GENOMES_NOTION_PAT"] == "secret"
    assert "GENOMES_NOTION_BRIDGE_COMMAND" not in child_env


def test_client_includes_identity_only_in_versioned_payload() -> None:
    captured: dict[str, object] = {}

    def runner(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        captured.update(kwargs)
        return _success({"values": [], "complete": True})(*args, **kwargs)

    identity = {
        "workspaceName": "Genome's Notion",
        "parentPageId": "3a8683b4-8dab-8111-bdc1-c2069129f031",
    }
    client = NotionBridgeClient(
        ["node", "bridge.js"],
        {"GENOMES_NOTION_PAT": "secret"},
        identity=identity,
        runner=runner,
    )
    assert client.request("listBlockChildren", {"blockId": "page"}) == {
        "values": [],
        "complete": True,
    }
    assert json.loads(str(captured["input"])) == {
        "version": 1,
        "operation": "listBlockChildren",
        "args": {"blockId": "page"},
        "identity": identity,
    }


def test_provider_errors_are_sanitized() -> None:
    def runner(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            [],
            0,
            json.dumps(
                {
                    "version": 1,
                    "ok": False,
                    "error": {
                        "code": "PERMISSION_ERROR",
                        "message": "raw provider body secret",
                    },
                }
            ),
            "",
        )

    with pytest.raises(NotionBridgeError) as exc:
        call_notion_bridge(
            ["node", "bridge.js"],
            "getPage",
            {"pageId": "page"},
            auth={"GENOMES_NOTION_PAT": "secret"},
            runner=runner,
        )
    assert exc.value.code == "PERMISSION_ERROR"
    assert exc.value.status is None
    assert "raw provider" not in str(exc.value)
    assert "secret" not in str(exc.value)


def test_unknown_provider_and_process_failures_are_sanitized() -> None:
    def unknown(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=args[0],
            returncode=0,
            stdout=json.dumps(
                {
                    "version": 1,
                    "ok": False,
                    "error": {
                        "code": "provider-secret-detail",
                        "message": "raw body",
                        "status": 500,
                    },
                }
            ),
            stderr="",
        )

    with pytest.raises(NotionBridgeError) as exc:
        call_notion_bridge(
            ["node", "bridge.js"],
            "getPage",
            {"pageId": "page"},
            auth={"GENOMES_NOTION_PAT": "secret"},
            runner=unknown,
        )
    assert exc.value.code == "BRIDGE_OPERATION_FAILED"
    assert exc.value.status == 500
    assert "provider-secret-detail" not in str(exc.value)

    with pytest.raises(NotionBridgeError, match="exited unsuccessfully") as exc:
        call_notion_bridge(
            ["node", "bridge.js"],
            "getPage",
            {"pageId": "page"},
            auth={"GENOMES_NOTION_PAT": "secret"},
            runner=lambda *args, **kwargs: subprocess.CompletedProcess(
                args=args[0], returncode=1, stdout="", stderr="secret raw body"
            ),
        )
    assert "secret" not in str(exc.value)


def test_timeout_and_invalid_response_fail_closed() -> None:
    def timeout(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(args[0], 1, stderr="secret")

    with pytest.raises(NotionBridgeError, match="could not be executed"):
        call_notion_bridge(
            ["node", "bridge.js"],
            "getPage",
            {"pageId": "page"},
            auth={"GENOMES_NOTION_PAT": "secret"},
            runner=timeout,
        )
    with pytest.raises(NotionBridgeError, match="unsupported response"):
        call_notion_bridge(
            ["node", "bridge.js"],
            "getPage",
            {"pageId": "page"},
            auth={"GENOMES_NOTION_PAT": "secret"},
            runner=lambda *args, **kwargs: subprocess.CompletedProcess(
                args=args[0],
                returncode=0,
                stdout='{"version":0,"ok":true}',
                stderr="",
            ),
        )
