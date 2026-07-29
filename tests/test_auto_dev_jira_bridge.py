"""Offline Auto-Dev acceptance tests for the shared Jira bridge adapter."""

from __future__ import annotations

import importlib.machinery
import importlib.util
import subprocess
import sys
from copy import deepcopy
from pathlib import Path
from types import ModuleType
from typing import Any

ROOT = Path(__file__).parents[1]
TRACKER = ROOT / "harness" / "skills" / "auto-dev" / "scripts" / "tracker"
PROJECTED_TRACKER = (
    ROOT
    / "harness"
    / "shared_factory"
    / "05-knowledge"
    / "skills"
    / "auto-dev"
    / "scripts"
    / "tracker"
)


def _load_jira_tracker() -> ModuleType:
    name = "auto_dev_jira_tracker_bridge_test"
    loader = importlib.machinery.SourceFileLoader(name, str(TRACKER / "jira.py"))
    spec = importlib.util.spec_from_loader(name, loader)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(TRACKER))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(str(TRACKER))
    return module


class FakeBridge:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.transitions = [
            {
                "id": "31",
                "name": "Start Progress",
                "available": True,
                "destination": {"name": "In Progress"},
            },
            {
                "id": "41",
                "name": "Complete",
                "available": True,
                "destination": {"name": "Done"},
            },
        ]
        self.issue = {
            "id": "131",
            "key": "APP-131",
            "url": "https://jira.invalid/browse/APP-131",
            "summary": "Bridge Auto Dev",
            "description": {
                "version": 1,
                "type": "doc",
                "content": [
                    {
                        "type": "paragraph",
                        "content": [
                            {
                                "type": "text",
                                "text": "Acceptance criteria\n- Shared bridge only",
                            }
                        ],
                    }
                ],
            },
            "status": {"id": "1", "name": "To Do"},
            "fields": {"labels": [], "assignee": None},
        }

    def request(self, operation: str, args: dict[str, Any]) -> Any:
        self.calls.append((operation, args))
        if operation == "preflightIdentity":
            return {"project": {"key": args["projectKey"]}}
        if operation == "getIssue":
            return deepcopy(self.issue)
        if operation == "updateIssue":
            self.issue["fields"].update(deepcopy(args["input"]["fields"]))
            return deepcopy(self.issue)
        if operation == "listTransitions":
            return deepcopy(self.transitions)
        if operation == "transitionIssue":
            states = {"31": "In Progress", "41": "Done"}
            self.issue["status"] = {
                "id": args["transitionId"],
                "name": states[args["transitionId"]],
            }
            return deepcopy(self.issue)
        if operation == "addComment":
            return {"id": "comment-1", "body": args["input"]["body"]}
        raise AssertionError(operation)


def _adapter(module: ModuleType, bridge: FakeBridge) -> Any:
    return module.JiraBridgeAdapter(
        bridge,
        {
            "siteUrl": "https://jira.invalid",
            "projectKey": "APP",
            "issueTypeId": "10001",
            "cloudId": "cloud-1",
            "accountId": "account-1",
        },
    )


def test_live_jira_tracker_claim_and_transition_are_preflighted_and_reread() -> None:
    module = _load_jira_tracker()
    bridge = FakeBridge()
    adapter = _adapter(module, bridge)

    claimed = adapter.claim("APP-131", "owner-1", "auto-dev", "In Progress")
    completed = adapter.transition("APP-131", "Done", note="Implementation complete")

    assert claimed.assignee == "owner-1"
    assert claimed.labels == ["auto-dev"]
    assert claimed.workflow_state == "In Progress"
    assert completed.workflow_state == "Done"
    assert completed.acceptance_criteria == ["Shared bridge only"]
    operations = [operation for operation, _ in bridge.calls]
    assert operations.count("preflightIdentity") == 2
    assert "updateIssue" in operations
    assert operations.count("transitionIssue") == 2
    comment = next(
        args for operation, args in bridge.calls if operation == "addComment"
    )
    marker = comment["input"]["reconciliationMarker"]
    assert marker.startswith("agentic-os:auto-dev:")
    assert marker in str(comment["input"]["body"])


def test_live_jira_tracker_reports_not_found_distinctly() -> None:
    module = _load_jira_tracker()
    bridge = FakeBridge()
    bridge.request = lambda _operation, _args: None  # type: ignore[method-assign]
    adapter = _adapter(module, bridge)
    try:
        adapter.fetch("APP-404")
    except module.TrackerError as exc:
        assert "APP-404 was not found" in str(exc)
    else:
        raise AssertionError("missing Jira issue was not reported as not found")


def test_transition_matches_available_destination_only() -> None:
    module = _load_jira_tracker()
    bridge = FakeBridge()
    bridge.transitions = [
        {
            "id": "wrong-name",
            "name": "Done",
            "available": True,
            "destination": {"name": "Resolved"},
        },
        {
            "id": "unavailable",
            "name": "Complete",
            "available": False,
            "destination": {"name": "Done"},
        },
        {
            "id": "41",
            "name": "Complete",
            "available": True,
            "destination": {"name": "Done"},
        },
    ]
    adapter = _adapter(module, bridge)

    completed = adapter.transition("APP-131", "Done")

    assert completed.workflow_state == "Done"
    transition = next(
        args for operation, args in bridge.calls if operation == "transitionIssue"
    )
    assert transition["transitionId"] == "41"


def test_fixture_and_live_adapter_projection_stays_byte_identical() -> None:
    assert (TRACKER / "jira.py").read_bytes() == (
        PROJECTED_TRACKER / "jira.py"
    ).read_bytes()


def test_fixture_adapter_import_remains_package_free_under_ambient_python() -> None:
    completed = subprocess.run(
        [
            "/usr/bin/python3",
            "-c",
            "from tracker.jira import JiraFixtureAdapter; print(JiraFixtureAdapter.kind)",
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=15,
        cwd=TRACKER.parent,
        env={"PATH": "/usr/bin:/bin", "PYTHONPATH": str(TRACKER.parent)},
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "jira"
