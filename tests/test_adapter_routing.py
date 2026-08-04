"""Offline contract tests for reviewed integration-adapter routing."""

from __future__ import annotations

import pytest

from genomes_agentic_os.adapter_routing import adapter_route, adapter_routes


def test_every_route_has_one_concrete_primary_adapter_and_boundary() -> None:
    for route in adapter_routes():
        assert route.primary
        assert route.boundary
        assert adapter_route(route.system, route.operation) is route


def test_atlassian_service_desk_comments_fail_closed_to_rest() -> None:
    route = adapter_route("atlassian", "service_desk_comment")

    assert route.primary == "jira_bridge_rest"
    assert route.fallbacks == ()
    assert "internal" in route.boundary.lower()


def test_notion_routes_reads_to_mcp_and_writes_to_rest() -> None:
    assert adapter_route("notion", "interactive_read").primary == "notion_mcp"
    write = adapter_route("notion", "write")
    assert write.primary == "notion_bridge_rest"
    assert write.fallbacks == ()
    assert "image blocks" in (write.limitation or "")


def test_slack_client_is_a_generic_port_and_valkey_is_delivery_only() -> None:
    assert adapter_route("slack", "channel_history").primary == "slack_api_client"
    valkey = adapter_route("valkey", "delivery")
    assert valkey.primary == "bullmq_delivery"
    assert "never the task ledger" in (valkey.limitation or "")


def test_unknown_operations_are_rejected_instead_of_falling_back() -> None:
    with pytest.raises(ValueError, match="No reviewed adapter route"):
        adapter_route("notion", "delete_workspace")
