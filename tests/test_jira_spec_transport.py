"""Offline acceptance tests for Spec Engine composition over the Jira bridge."""

from __future__ import annotations

from typing import Any

from genomes_agentic_os.jira_bridge import JiraBridgeError
from genomes_agentic_os.spec_adapters.jira import (
    JiraBridgeSpecTransport,
    JiraSpecAdapter,
    transport_from_environment,
)
from genomes_agentic_os.spec_engine import Spec


class FakeBridgeClient:
    def __init__(
        self,
        *,
        duplicate_matches: int = 0,
        existing_labels: list[str] | None = None,
    ) -> None:
        self.duplicate_matches = duplicate_matches
        self.existing_labels = list(existing_labels or [])
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def request(self, operation: str, args: dict[str, Any]) -> Any:
        self.calls.append((operation, args))
        if operation == "preflightIdentity":
            return {"siteUrl": args["siteUrl"], "projectKey": args["projectKey"]}
        if operation == "searchIssues":
            values = [
                {
                    "key": f"APP-{index + 1}",
                    "url": f"https://jira.invalid/APP-{index + 1}",
                }
                for index in range(self.duplicate_matches)
            ]
            return {"values": values, "complete": True}
        if operation == "createIssue":
            return {"key": "APP-131", "url": "https://jira.invalid/APP-131"}
        if operation == "updateIssue":
            return {"key": args["key"], "url": f"https://jira.invalid/{args['key']}"}
        if operation == "getIssue":
            return {
                "key": args["key"],
                "url": f"https://jira.invalid/{args['key']}",
                "fields": {"labels": self.existing_labels},
            }
        raise AssertionError(operation)


def _adapter(client: FakeBridgeClient) -> JiraSpecAdapter:
    return JiraSpecAdapter(
        {
            "enabled": True,
            "target": {
                "site_url": "https://jira.invalid",
                "project_key": "APP",
                "issue_type_id": "10001",
            },
            "placement": {"default": "backlog"},
        },
        JiraBridgeSpecTransport(client),  # type: ignore[arg-type]
    )


def test_jira_spec_apply_uses_preflight_marker_native_adf_and_readback() -> None:
    client = FakeBridgeClient()
    spec = Spec(
        id="age_131",
        title="Bridge Jira",
        summary="Use the shared port",
        acceptance_criteria=["Native ADF", "Independent readback"],
        domain="acme",
        project="app",
    )

    receipt = _adapter(client).create(spec, apply=True)

    assert receipt.ok and receipt.readback_verified
    assert receipt.provider_id == "APP-131"
    assert [operation for operation, _ in client.calls] == [
        "preflightIdentity",
        "searchIssues",
        "createIssue",
        "getIssue",
    ]
    create = client.calls[2][1]
    assert create["issueType"] == "10001"
    assert create["reconciliationJql"].startswith(
        'project = APP AND labels = "agentic-os-spec-'
    )
    assert create["fields"]["labels"][0] == "agentic-os-spec"
    assert create["description"]["type"] == "doc"
    assert any(
        node["type"] == "bulletList" for node in create["description"]["content"]
    )
    rendered = str(create["description"])
    assert "spec:acme:app:age_131" in rendered
    assert "Native ADF" in rendered


def test_jira_spec_duplicate_marker_and_active_sprint_fail_closed() -> None:
    client = FakeBridgeClient(duplicate_matches=2)
    receipt = _adapter(client).create(Spec(id="one", title="One"), apply=True)
    assert receipt.ok is False
    assert receipt.status == "blocked"
    assert "multiple issues" in str(receipt.error)
    assert [operation for operation, _ in client.calls] == [
        "preflightIdentity",
        "searchIssues",
    ]

    sprint = _adapter(FakeBridgeClient()).create(
        Spec(id="two", title="Two"),
        apply=True,
        placement="active_sprint",
    )
    assert sprint.ok is False
    assert sprint.status == "blocked"
    assert "disabled" in str(sprint.error)


def test_jira_spec_update_preserves_existing_human_labels() -> None:
    client = FakeBridgeClient(
        duplicate_matches=1,
        existing_labels=["human-owned"],
    )
    receipt = _adapter(client).create(
        Spec(id="one", title="One", domain="acme", project="app"),
        apply=True,
    )
    assert receipt.ok and receipt.provider_id == "APP-1"
    update = next(
        args for operation, args in client.calls if operation == "updateIssue"
    )
    labels = update["input"]["fields"]["labels"]
    assert labels[:2] == ["human-owned", "agentic-os-spec"]
    assert labels[2].startswith("agentic-os-spec-")


def test_jira_spec_transport_environment_is_explicit_and_complete() -> None:
    assert transport_from_environment({}) is None
    incomplete = transport_from_environment(
        {"GENOMES_JIRA_BRIDGE_COMMAND": "node bridge.js"}
    )
    assert incomplete is not None
    try:
        incomplete.request("verify_target", {"target": {}})
    except JiraBridgeError as exc:
        assert exc.code == "CONFIGURATION_ERROR"
    else:
        raise AssertionError("incomplete Jira bridge configuration did not block")
    transport = transport_from_environment(
        {
            "GENOMES_JIRA_BRIDGE_COMMAND": "node bridge.js",
            "JIRA_BASE_URL": "https://jira.invalid",
            "JIRA_OAUTH_TOKEN": "secret",
        }
    )
    assert isinstance(transport, JiraBridgeSpecTransport)
    assert list(transport.client.command) == ["node", "bridge.js"]

    partial = transport_from_environment(
        {
            "GENOMES_JIRA_BRIDGE_COMMAND": "node bridge.js",
            "JIRA_BASE_URL": "https://jira.invalid",
            "JIRA_EMAIL": "only@example.com",
        }
    )
    assert partial is not None
    try:
        partial.request("verify_target", {"target": {}})
    except JiraBridgeError as exc:
        assert exc.code == "CONFIGURATION_ERROR"
    else:
        raise AssertionError("partial Jira authentication did not block")
