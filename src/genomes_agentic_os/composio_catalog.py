"""Composio toolkit routing defaults for Agentic OS layers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ComposioToolRoute:
    id: str
    toolkit: str
    name: str
    route_when: str
    layer_scope: tuple[str, ...]
    provider_priority: tuple[str, ...]
    read_tools: tuple[str, ...] = ()
    write_tools: tuple[str, ...] = ()
    trigger_tools: tuple[str, ...] = ()
    approval_required_for: tuple[str, ...] = ("external_write", "customer_visible_output")
    boundary: str = "Verify the target workspace/account before writes; keep secrets in env vars only."
    status: str = "planned route"
    source_system: str = ""


LAYER_SCOPE = (
    "agentic_os_root",
    "domain_or_lane",
    "project",
    "workflow_or_task",
    "automation",
)


COMPOSIO_TOOL_ROUTES: tuple[ComposioToolRoute, ...] = (
    ComposioToolRoute(
        id="agentmail_genome",
        toolkit="agent_mail",
        name="Genome AgentMail",
        route_when="Inbox reads, message lookup, and approved agent email sends.",
        layer_scope=LAYER_SCOPE,
        provider_priority=("composio", "agentmail_api", "direct_api"),
        read_tools=("AGENT_MAIL_LIST_INBOXES", "AGENT_MAIL_LIST_MESSAGES", "AGENT_MAIL_GET_MESSAGE"),
        write_tools=("AGENT_MAIL_SEND_EMAIL",),
        boundary="Use for Genome AgentMail only; sending email requires explicit approval.",
        status="cached locally",
        source_system="connected-system:agentmail_genome",
    ),
    ComposioToolRoute(
        id="slack_genome",
        toolkit="slack",
        name="Genome Slack",
        route_when="Slack context lookup, DM/channel routing, and approved Slack notifications.",
        layer_scope=LAYER_SCOPE,
        provider_priority=("composio", "slack_mcp", "slack_connector", "direct_api"),
        write_tools=("SLACK_OPEN_DM", "SLACK_SEND_MESSAGE"),
        boundary="Verify Genome Slack workspace and channel/user target before sending.",
        status="cached locally",
        source_system="connected-system:slack_genome",
    ),
    ComposioToolRoute(
        id="notion_blocks",
        toolkit="notion",
        name="Notion block fallback",
        route_when="Fallback block-content reads when the Notion MCP/connector cannot fetch the needed page blocks.",
        layer_scope=LAYER_SCOPE,
        provider_priority=("notion_mcp", "notion_connector", "composio", "direct_api"),
        read_tools=("NOTION_FETCH_ALL_BLOCK_CONTENTS",),
        approval_required_for=("external_write", "customer_visible_output", "workspace_mismatch"),
        boundary="Prefer Notion MCP; verify Genome's Notion before any Notion write path.",
        status="cached locally",
        source_system="connected-system:notion_genome",
    ),
    ComposioToolRoute(
        id="jira_genome",
        toolkit="jira",
        name="Genome Jira",
        route_when="Jira issue/project reads and approved issue creation or updates.",
        layer_scope=LAYER_SCOPE,
        provider_priority=("composio", "jira_mcp", "jira_connector", "direct_api"),
        boundary="Use the configured Genome Jira workspace; writes require ticket-scope approval.",
        source_system="connected-system:jira_genome",
    ),
    ComposioToolRoute(
        id="linear_genome",
        toolkit="linear",
        name="Genome Linear",
        route_when="Linear issue/team reads and approved issue creation or updates.",
        layer_scope=LAYER_SCOPE,
        provider_priority=("composio", "linear_mcp", "linear_connector", "direct_api"),
        boundary="Use only for Genome Linear routes; external writes require approval.",
        source_system="connected-system:linear_genome",
    ),
    ComposioToolRoute(
        id="email_genome",
        toolkit="gmail",
        name="Genome Email",
        route_when="Email search/read and approved outbound mail.",
        layer_scope=LAYER_SCOPE,
        provider_priority=("composio", "gmail_mcp", "email_connector", "direct_api"),
        boundary="Read only by default; sending mail requires explicit approval and recipient verification.",
        source_system="connected-system:email_genome",
    ),
    ComposioToolRoute(
        id="github_genome",
        toolkit="github",
        name="Genome GitHub",
        route_when="GitHub issue, pull request, repo, and code-hosting actions when MCP/gh are unavailable or Composio is the approved route.",
        layer_scope=LAYER_SCOPE,
        provider_priority=("github_mcp", "github_cli", "composio", "direct_api"),
        boundary="Prefer GitHub MCP or gh for repo work; writes require repo/PR/issue scope verification.",
        source_system="connected-system:github_genome",
    ),
    ComposioToolRoute(
        id="granola_local",
        toolkit="granola",
        name="Granola Notes",
        route_when="Meeting-note lookup and approved notes ingestion when a Granola integration is configured.",
        layer_scope=("agentic_os_root", "domain_or_lane", "project", "workflow_or_task"),
        provider_priority=("composio", "granola_local", "direct_api"),
        approval_required_for=("customer_visible_output",),
        boundary="Read-only by default; do not expose private notes into customer-visible output without approval.",
        source_system="connected-system:granola_local",
    ),
    ComposioToolRoute(
        id="composio_discovery",
        toolkit="composio",
        name="Composio discovery and schema inspection",
        route_when="Unknown slug discovery, schema inspection, dry-run validation, proxy fallback, and multi-tool scripting.",
        layer_scope=LAYER_SCOPE,
        provider_priority=("composio_cli",),
        read_tools=(
            "composio search",
            "composio tools list",
            "composio tools info",
            "composio execute --get-schema",
            "composio execute --dry-run",
            "composio proxy",
            "composio run --dry-run",
        ),
        approval_required_for=("external_write", "destructive_action", "customer_visible_output"),
        boundary="Use execute before search when a slug is known; link accounts only after confirming the target toolkit/workspace.",
        status="available through CLI",
        source_system="composio-cli",
    ),
)


def composio_tool_entries() -> list[dict[str, Any]]:
    return [
        {
            "id": route.id,
            "toolkit": route.toolkit,
            "name": route.name,
            "route_when": route.route_when,
            "layer_scope": list(route.layer_scope),
            "provider_priority": list(route.provider_priority),
            "read_tools": list(route.read_tools),
            "write_tools": list(route.write_tools),
            "trigger_tools": list(route.trigger_tools),
            "approval_required_for": list(route.approval_required_for),
            "boundary": route.boundary,
            "status": route.status,
            "source_system": route.source_system,
        }
        for route in COMPOSIO_TOOL_ROUTES
    ]


def _tools(route: ComposioToolRoute) -> str:
    groups = []
    if route.read_tools:
        groups.append("read: " + ", ".join(f"`{tool}`" for tool in route.read_tools))
    if route.write_tools:
        groups.append("write: " + ", ".join(f"`{tool}`" for tool in route.write_tools))
    if route.trigger_tools:
        groups.append("trigger: " + ", ".join(f"`{tool}`" for tool in route.trigger_tools))
    return "; ".join(groups) if groups else "discover with `composio tools list <toolkit>`"


def composio_tools_markdown(*, public_customer: bool = False) -> str:
    if public_customer:
        return "\n".join(
            [
                "| Route ID | Toolkit | Use When | Layers | Boundary |",
                "| --- | --- | --- | --- | --- |",
                "| `customer_approved_only` | Composio | Use only when the customer profile explicitly approves the toolkit and workspace. | customer layers | Do not inherit Genome Composio routes into customer OS roots. |",
            ]
        )
    rows = [
        "| Route ID | Toolkit | Use When | Layers | Provider Order | Known Tools | Boundary |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for route in COMPOSIO_TOOL_ROUTES:
        rows.append(
            "| "
            f"`{route.id}` | `{route.toolkit}` | {route.route_when} | "
            f"{', '.join(route.layer_scope)} | "
            f"{' -> '.join(f'`{provider}`' for provider in route.provider_priority)} | "
            f"{_tools(route)} | {route.boundary} |"
        )
    return "\n".join(rows)
