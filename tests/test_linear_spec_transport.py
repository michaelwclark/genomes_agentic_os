"""Offline side-by-side tests for Spec Engine over the shared Linear port."""

from __future__ import annotations

from genomes_agentic_os.spec_adapters.linear import (
    LinearBridgeSpecTransport,
    LinearSpecAdapter,
    transport_from_environment,
)
from genomes_agentic_os.spec_engine import Spec


class FakeBridgeClient:
    def __init__(self, *, issues=None):
        self.issues = list(issues or [])
        self.calls = []

    def request(self, operation, args):
        self.calls.append((operation, args))
        if operation == "preflightIdentity":
            return {
                "team": {"id": args["teamId"], "key": "AGE", "name": "Agentic OS"},
                "workspace": {"id": "workspace"},
                "viewer": {"id": "viewer"},
            }
        if operation == "listIssuesByTeam":
            return self.issues
        if operation == "listWorkflowStates":
            return [{"id": "todo", "name": "Todo", "type": "unstarted"}]
        if operation == "listLabels":
            return [{"id": "blocked-label", "name": "blocked", "color": "#EB5757"}]
        if operation == "createIssue":
            issue = {
                "id": "issue-1",
                "identifier": "AGE-1",
                "url": "https://linear.app/genomes/issue/AGE-1/example",
                **args["input"],
            }
            self.issues.append(issue)
            return issue
        if operation == "updateIssue":
            return {
                "id": args["issue"],
                "identifier": "AGE-1",
                "url": "https://linear.app/genomes/issue/AGE-1/example",
                **args["input"],
            }
        if operation == "getIssue":
            return next((item for item in self.issues if item["id"] == args["issue"]), None)
        raise AssertionError((operation, args))


def adapter(client):
    return LinearSpecAdapter(
        {
            "enabled": True,
            "target": {"team_id": "team", "project_id": "project"},
            "status_map": {"ready": "Todo"},
        },
        LinearBridgeSpecTransport(client),
    )


def test_create_preserves_old_plan_shape_and_adds_marker_readback() -> None:
    client = FakeBridgeClient()
    spec = Spec(id="one", title="One", summary="Summary", status="ready")
    planned = adapter(client).create(spec, apply=False)
    applied = adapter(client).create(spec, apply=True)

    assert planned.plan["native_status"] == "Todo"
    assert applied.ok is True
    assert applied.provider_id == "issue-1"
    create = next(args for operation, args in client.calls if operation == "createIssue")
    assert create["input"]["teamId"] == "team"
    assert create["input"]["projectId"] == "project"
    assert create["input"]["stateId"] == "todo"
    assert "spec:::one" in create["input"]["description"]


def test_existing_exact_marker_updates_instead_of_creating() -> None:
    client = FakeBridgeClient(
        issues=[
            {
                "id": "issue-old",
                "identifier": "AGE-1",
                "url": "https://linear.app/genomes/issue/AGE-1/example",
                "description": "spec:::one",
            }
        ]
    )
    receipt = adapter(client).create(Spec(id="one", title="Revised", status="ready"), apply=True)
    assert receipt.ok is True
    assert receipt.provider_id == "issue-old"
    assert any(operation == "updateIssue" for operation, _ in client.calls)
    assert not any(operation == "createIssue" for operation, _ in client.calls)


def test_cli_transport_configuration_fails_closed_without_command() -> None:
    assert transport_from_environment({}) is None
    transport = transport_from_environment({"LINEAR_TOKEN": "token"})
    assert transport is not None
    receipt = LinearSpecAdapter(
        {"enabled": True, "target": {"team_id": "team"}}, transport
    ).doctor()
    assert receipt.ok is False
    assert receipt.status == "blocked"


def test_blocked_plan_uses_shared_label_capability() -> None:
    client = FakeBridgeClient()
    receipt = adapter(client).create(
        Spec(id="blocked", title="Blocked", status="blocked"), apply=True
    )
    assert receipt.ok is True
    create = next(args for operation, args in client.calls if operation == "createIssue")
    assert create["input"]["labelIds"] == ["blocked-label"]
