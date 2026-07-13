"""Tests for genomes_agentic_os.composio_catalog: the static Composio
tool-route catalog and its rendered markdown table.

Unlike mcp_catalog, this module has no file-backed registry — "gating" here
is the `public_customer` flag on composio_tools_markdown(), which swaps the
full internal route table for a single customer-safe placeholder row. These
tests cover the catalog's structural invariants (unique ids, safety-relevant
approval defaults) and both branches of that gate.
"""

from __future__ import annotations

from genomes_agentic_os.composio_catalog import (
    COMPOSIO_TOOL_ROUTES,
    LAYER_SCOPE,
    ComposioToolRoute,
    composio_tool_entries,
    composio_tools_markdown,
)


# ---------------------------------------------------------------------------
# Catalog shape
# ---------------------------------------------------------------------------


def test_route_ids_are_unique():
    ids = [route.id for route in COMPOSIO_TOOL_ROUTES]
    assert len(ids) == len(set(ids))


def test_every_route_layer_scope_is_a_subset_of_known_layers():
    known = set(LAYER_SCOPE)
    for route in COMPOSIO_TOOL_ROUTES:
        assert set(route.layer_scope) <= known, route.id


def test_default_approval_required_for_covers_external_write_and_customer_output():
    route = ComposioToolRoute(
        id="test_route",
        toolkit="test",
        name="Test",
        route_when="testing",
        layer_scope=LAYER_SCOPE,
        provider_priority=("composio",),
    )
    assert route.approval_required_for == ("external_write", "customer_visible_output")


def test_routes_with_write_tools_still_require_external_write_approval():
    for route in COMPOSIO_TOOL_ROUTES:
        if route.write_tools:
            assert "external_write" in route.approval_required_for, route.id


def test_default_boundary_mentions_secrets_policy():
    route = ComposioToolRoute(
        id="test_route",
        toolkit="test",
        name="Test",
        route_when="testing",
        layer_scope=LAYER_SCOPE,
        provider_priority=("composio",),
    )
    assert "env vars" in route.boundary


# ---------------------------------------------------------------------------
# composio_tool_entries
# ---------------------------------------------------------------------------


def test_composio_tool_entries_returns_one_dict_per_route():
    entries = composio_tool_entries()
    assert len(entries) == len(COMPOSIO_TOOL_ROUTES)


def test_composio_tool_entries_converts_tuples_to_lists():
    entries = composio_tool_entries()
    agentmail = next(e for e in entries if e["id"] == "agentmail_genome")
    assert isinstance(agentmail["read_tools"], list)
    assert agentmail["read_tools"] == [
        "AGENT_MAIL_LIST_INBOXES",
        "AGENT_MAIL_LIST_MESSAGES",
        "AGENT_MAIL_GET_MESSAGE",
    ]
    assert isinstance(agentmail["layer_scope"], list)


def test_composio_tool_entries_preserves_declared_fields_and_defaults():
    entries = composio_tool_entries()
    jira = next(e for e in entries if e["id"] == "jira_genome")
    assert jira["toolkit"] == "jira"
    assert jira["status"] == "planned route"
    assert jira["read_tools"] == []
    assert jira["write_tools"] == []


# ---------------------------------------------------------------------------
# composio_tools_markdown: internal table vs. public_customer gate
# ---------------------------------------------------------------------------


def test_internal_markdown_lists_every_route():
    markdown = composio_tools_markdown(public_customer=False)
    for route in COMPOSIO_TOOL_ROUTES:
        assert f"`{route.id}`" in markdown


def test_internal_markdown_uses_seven_column_header():
    markdown = composio_tools_markdown(public_customer=False)
    header = markdown.splitlines()[0]
    assert header.count("|") == 8  # 7 columns -> 8 pipe delimiters


def test_internal_markdown_route_without_typed_tools_falls_back_to_discovery_hint():
    # The fallback text is a literal "<toolkit>" placeholder, not an
    # interpolated value -- assert the exact string _tools() emits so a
    # future switch to real interpolation is a visible, intentional change.
    markdown = composio_tools_markdown(public_customer=False)
    jira_line = next(line for line in markdown.splitlines() if line.startswith("| `jira_genome`"))
    assert "discover with `composio tools list <toolkit>`" in jira_line


def test_internal_markdown_route_with_read_and_write_tools_groups_them():
    markdown = composio_tools_markdown(public_customer=False)
    agentmail_line = next(
        line for line in markdown.splitlines() if line.startswith("| `agentmail_genome`")
    )
    assert "read:" in agentmail_line
    assert "write:" in agentmail_line
    assert "AGENT_MAIL_SEND_EMAIL" in agentmail_line


def test_public_customer_markdown_hides_every_internal_route():
    markdown = composio_tools_markdown(public_customer=True)
    for route in COMPOSIO_TOOL_ROUTES:
        assert f"`{route.id}`" not in markdown


def test_public_customer_markdown_is_a_single_placeholder_row():
    lines = [line for line in composio_tools_markdown(public_customer=True).splitlines() if line.strip()]
    assert len(lines) == 3  # header, separator, one data row
    assert "customer_approved_only" in lines[2]


def test_public_customer_markdown_warns_against_inheriting_genome_routes():
    markdown = composio_tools_markdown(public_customer=True)
    assert "Do not inherit Genome Composio routes into customer OS roots." in markdown
