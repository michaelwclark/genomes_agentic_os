"""Deterministic routing policy for the integration adapter ports.

This is a policy catalogue, not a provider client.  Provider clients keep
their authentication and wire details in their own modules; callers use this
catalogue to select the allowed adapter before invoking one.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AdapterRoute:
    """One reviewed adapter choice for a provider operation."""

    system: str
    operation: str
    primary: str
    fallbacks: tuple[str, ...]
    boundary: str
    limitation: str | None = None


_ROUTES: tuple[AdapterRoute, ...] = (
    AdapterRoute(
        "atlassian",
        "read",
        "acli",
        ("jira_bridge_rest", "jira_mcp"),
        "Use the configured Atlassian site and preserve the target issue/project scope.",
    ),
    AdapterRoute(
        "atlassian",
        "write",
        "acli",
        ("jira_bridge_rest", "jira_mcp"),
        "Writes require ticket-scope approval and provider readback.",
    ),
    AdapterRoute(
        "atlassian",
        "service_desk_comment",
        "jira_bridge_rest",
        (),
        "Service-desk comments default to internal and require explicit target verification.",
        "Only the REST adapter can set the internal-comment flag; never route this operation through acli or MCP.",
    ),
    AdapterRoute(
        "notion",
        "interactive_read",
        "notion_mcp",
        ("notion_bridge_rest",),
        "Reads must remain within the intended workspace/page scope.",
    ),
    AdapterRoute(
        "notion",
        "write",
        "notion_bridge_rest",
        (),
        "Writes require Genome's Notion workspace and an approved parent identity.",
        "MCP update_content cannot reliably match image blocks, so it is not a write fallback.",
    ),
    AdapterRoute(
        "slack",
        "channel_history",
        "slack_api_client",
        (),
        "The generic client returns trimmed messages with stable idempotency keys; workflows own polling and event persistence.",
    ),
    AdapterRoute(
        "valkey",
        "delivery",
        "bullmq_delivery",
        (),
        "Only the execution-fabric delivery port uses Valkey; producers and workers use the control-plane API.",
        "PostgreSQL remains canonical truth. BullMQ/Valkey is a reconstructable delivery signal, never the task ledger.",
    ),
)


def adapter_route(system: str, operation: str) -> AdapterRoute:
    """Return the one reviewed route, failing closed for undeclared operations."""
    normalized = (system.strip().lower(), operation.strip().lower())
    for route in _ROUTES:
        if (route.system, route.operation) == normalized:
            return route
    raise ValueError(f"No reviewed adapter route for {normalized[0]!r}/{normalized[1]!r}")


def adapter_routes() -> tuple[AdapterRoute, ...]:
    """Expose the complete immutable policy for registries and documentation."""
    return _ROUTES
