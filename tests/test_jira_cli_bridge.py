"""Offline contract tests for the agentic-os-jira bridge facade."""

from __future__ import annotations

import argparse
import importlib.machinery
import importlib.util
import subprocess
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest


def _load_cli() -> ModuleType:
    path = Path(__file__).parents[1] / "harness" / "bin" / "agentic-os-jira"
    name = "agentic_os_jira_cli"
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeBridge:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def request(self, operation: str, args: dict[str, Any]) -> Any:
        self.calls.append((operation, args))
        if operation == "preflightIdentity":
            return {"project": {"key": args["projectKey"]}}
        if operation == "addComment":
            return {"id": "100", "body": args["input"]["body"]}
        if operation == "listComments":
            return {
                "values": [
                    {"id": "1", "body": {"type": "doc"}},
                    {"id": "2", "body": {"type": "doc"}},
                ],
                "total": 2,
                "complete": True,
            }
        raise AssertionError(operation)


def _facade(module: ModuleType, *, issue_type_id: str = "10001") -> Any:
    client = module.JiraBridgeFacade(
        {
            "mode": "bearer",
            "base": "https://api.atlassian.invalid/ex/jira/cloud-1",
            "browse_base": "https://jira.invalid",
            "bridge_command": ["node", "bridge.js"],
            "bridge_auth": {"JIRA_OAUTH_TOKEN": "secret"},
            "cloud_id": "cloud-1",
            "account_id": "account-1",
            "issue_type_id": issue_type_id,
        }
    )
    client.bridge = FakeBridge()
    return client


def test_mutation_facade_requires_identity_preflight_and_keeps_native_adf() -> None:
    module = _load_cli()
    client = _facade(module)

    client.preflight_issue("APP-131")
    result = client.add_comment("APP-131", "Provider-safe comment")

    assert result["id"] == "100"
    assert [operation for operation, _ in client.bridge.calls] == [
        "preflightIdentity",
        "addComment",
    ]
    preflight = client.bridge.calls[0][1]
    assert preflight == {
        "siteUrl": "https://jira.invalid",
        "projectKey": "APP",
        "issueTypeId": "10001",
        "cloudId": "cloud-1",
        "accountId": "account-1",
    }
    assert client.bridge.calls[1][1]["input"]["body"]["type"] == "doc"


def test_mutation_preflight_blocks_when_issue_type_identity_is_missing() -> None:
    module = _load_cli()
    client = _facade(module, issue_type_id="")
    with pytest.raises(module.JiraCliError, match="JIRA_DEFAULT_ISSUE_TYPE_ID"):
        client.preflight_issue("APP-131")
    assert client.bridge.calls == []


def test_comment_dry_run_never_resolves_auth_or_invokes_bridge(monkeypatch) -> None:
    module = _load_cli()

    def unexpected_auth() -> None:
        raise AssertionError("dry-run resolved Jira credentials")

    monkeypatch.setattr(module, "resolve_auth", unexpected_auth)
    args = argparse.Namespace(issue_key="APP-131", body="No write", execute=False)
    assert module.cmd_comment(args) == 0


def test_comments_preserve_legacy_key_newest_first_and_limit() -> None:
    module = _load_cli()
    client = _facade(module)
    result = client.comments("APP-131", limit=1)
    assert result == {
        "comments": [{"id": "2", "body": {"type": "doc"}}],
        "total": 2,
        "maxResults": 1,
    }


def test_source_checkout_wrapper_bootstraps_under_ambient_python() -> None:
    path = Path(__file__).parents[1] / "harness" / "bin" / "agentic-os-jira"
    completed = subprocess.run(
        ["/usr/bin/python3", str(path), "--help"],
        check=False,
        capture_output=True,
        text=True,
        timeout=15,
        env={"PATH": "/usr/bin:/bin"},
    )
    assert completed.returncode == 0, completed.stderr
    assert "Jira helper" in completed.stdout
