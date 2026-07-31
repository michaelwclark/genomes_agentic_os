"""Offline source-watch tests for the shared Jira bridge."""

from __future__ import annotations

from typing import Any

import genomes_agentic_os.source_providers as source_providers
from genomes_agentic_os.source_providers import poll_jira_source
from genomes_agentic_os.source_watch import (
    default_connected_systems,
    default_source_providers,
)


class FakeJiraBridge:
    def __init__(self, *, complete: bool = True) -> None:
        self.complete = complete
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def request(self, operation: str, args: dict[str, Any]) -> Any:
        self.calls.append((operation, args))
        assert operation == "searchIssues"
        return {
            "complete": self.complete,
            "values": [
                {
                    "id": "131",
                    "key": "APP-131",
                    "url": "https://jira.invalid/browse/APP-131",
                    "summary": "Shared Jira watcher",
                    "project": {"id": "1", "key": "APP", "name": "App"},
                    "issueType": {"id": "10001", "name": "Task"},
                    "status": {"id": "3", "name": "In Progress"},
                    "fields": {
                        "updated": "2026-07-29T18:00:00.000+0000",
                        "labels": ["rubicon"],
                    },
                }
            ],
        }


def test_jira_watch_uses_unbounded_shared_search_and_trimmed_events() -> None:
    bridge = FakeJiraBridge()
    result = poll_jira_source(
        {"external_ref": {"project_key": "APP"}},
        {"system": "jira"},
        client=bridge,  # type: ignore[arg-type]
    )

    assert result["ok"] and result["live"] and result["item_count"] == 1
    assert bridge.calls == [
        (
            "searchIssues",
            {
                "jql": 'project = "APP" ORDER BY updated DESC',
                "fields": ["updated", "labels"],
            },
        )
    ]
    item = result["items"][0]
    assert item["key"] == "APP-131"
    assert item["status"] == "In Progress"
    assert item["_idempotency_key"].endswith("2026-07-29T18:00:00.000+0000")
    assert "description" not in item


def test_jira_watch_rejects_incomplete_unbounded_search() -> None:
    result = poll_jira_source(
        {"external_ref": {"jql": "project = APP"}},
        {"system": "jira"},
        client=FakeJiraBridge(complete=False),  # type: ignore[arg-type]
    )
    assert result["ok"] is False
    assert result["findings"][0]["code"] == "BRIDGE_INVALID_RESPONSE"


def test_default_jira_registry_routes_polling_to_shared_bridge() -> None:
    jira = next(
        item
        for item in default_connected_systems()["connected_systems"]
        if item["id"] == "jira_genome"
    )
    assert jira["provider_priority"][0] == "jira_bridge"
    assert "JIRA_OAUTH_TOKEN" in jira["credential_refs"]["env_vars"]
    providers = default_source_providers()["source_providers"]
    bridge = next(item for item in providers if item["id"] == "jira_bridge")
    assert bridge["status"] == "available"
    assert "poll" in bridge["supports"]


def test_jira_watch_bearer_mode_uses_atlassian_gateway(monkeypatch: Any) -> None:
    bridge = FakeJiraBridge()
    captured: dict[str, Any] = {}

    def make_client(command: Any, base_url: str, auth: Any) -> FakeJiraBridge:
        captured.update(command=list(command), base_url=base_url, auth=dict(auth))
        return bridge

    monkeypatch.setattr(source_providers, "JiraBridgeClient", make_client)
    monkeypatch.setenv("GENOMES_JIRA_BRIDGE_COMMAND", "node bridge.js")
    monkeypatch.setenv("JIRA_BASE_URL", "https://tenant.invalid")
    monkeypatch.setenv("JIRA_OAUTH_TOKEN", "secret")
    monkeypatch.setenv("ATLASSIAN_JIRA_CLOUDID", "cloud-131")
    monkeypatch.delenv("JIRA_EMAIL", raising=False)
    monkeypatch.delenv("JIRA_API_TOKEN", raising=False)
    monkeypatch.delenv("ATLASSIAN_BASE_URL", raising=False)
    monkeypatch.delenv("JIRA_OAUTH_BASE_URL", raising=False)
    monkeypatch.delenv("JIRA_CLOUD_ID", raising=False)
    monkeypatch.delenv("ATLASSIAN_CLOUD_ID", raising=False)

    result = poll_jira_source(
        {"external_ref": {"project_key": "APP"}}, {"system": "jira"}
    )

    assert result["ok"] and result["live"]
    assert captured["command"] == ["node", "bridge.js"]
    assert captured["base_url"] == "https://api.atlassian.com/ex/jira/cloud-131"
    assert captured["auth"] == {"JIRA_OAUTH_TOKEN": "secret"}
