"""Layer-aware MCP catalog for Agentic OS config and tool docs."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class McpServer:
    id: str
    display_name: str
    use_when: str
    boundary: str
    install_scope: str
    url: str | None = None
    command: str | None = None
    args: tuple[str, ...] = ()
    bearer_token_env_var: str | None = None
    secret_policy: str = "no inline secrets; env var names only"


CORE_MCP_IDS = ("notion", "genomes_brain", "github", "context_mode")
LOS_MCP_IDS = ("sentry", "datadog")
CLARKS_MCP_IDS = ("supabase",)
VISIBLE_ONLY_MCP_IDS = ("composio", "orgo", "playwright")

MCP_SERVERS: dict[str, McpServer] = {
    "notion": McpServer(
        id="notion",
        display_name="Notion",
        url="https://mcp.notion.com/mcp",
        use_when="Genome's Notion control-plane reads and approved writes.",
        boundary="Verify Genome's Notion before writing; do not use Michael Clark's personal workspace.",
        install_scope="every layer",
    ),
    "genomes_brain": McpServer(
        id="genomes_brain",
        display_name="Genome's Brain",
        url="http://127.0.0.1:3155/mcp",
        use_when="Durable cross-session memory reads and non-secret writes.",
        boundary="No secrets; use project rules and memory policy before writing.",
        install_scope="every layer",
    ),
    "github": McpServer(
        id="github",
        display_name="GitHub",
        url="https://api.githubcopilot.com/mcp/",
        bearer_token_env_var="GITHUB_PAT_TOKEN",
        use_when="GitHub repository, issue, pull request, and code-hosting work.",
        boundary="Use least-privilege `GITHUB_PAT_TOKEN`; never commit or print token values.",
        install_scope="every layer",
    ),
    "context_mode": McpServer(
        id="context_mode",
        display_name="Context Mode",
        command="/Users/genome/.local/bin/context-mode",
        use_when="Large-file, repo, and session-memory analysis without flooding prompt context.",
        boundary="Use for analysis and retrieval; do not use context-mode subprocesses for file writes.",
        install_scope="every layer",
    ),
    "sentry": McpServer(
        id="sentry",
        display_name="Sentry",
        url="https://mcp.sentry.dev/mcp",
        use_when="LOS error, trace, release, and production incident investigation.",
        boundary="LOS layers only; production/customer-visible changes still require approval.",
        install_scope="LOS layers only",
    ),
    "datadog": McpServer(
        id="datadog",
        display_name="Datadog",
        url="https://mcp.datadoghq.com/api/unstable/mcp-server/mcp",
        use_when="LOS observability, logs, metrics, traces, and monitor investigation.",
        boundary="LOS layers only; do not expose customer data outside approved observability workflows.",
        install_scope="LOS layers only",
    ),
    "supabase": McpServer(
        id="supabase",
        display_name="Supabase",
        url="https://mcp.supabase.com/mcp",
        use_when="Clark consulting Supabase project work.",
        boundary="`clarks_consulting` layers only unless a customer profile explicitly approves Supabase.",
        install_scope="clarks_consulting layers only",
    ),
    "composio": McpServer(
        id="composio",
        display_name="Composio",
        use_when="Federated SaaS tools, OAuth flows, triggers, and app actions.",
        boundary="Visible by default; install only after generating an approved Composio MCP server URL for the target layer.",
        install_scope="visible only until an approved generated MCP URL is available",
    ),
    "orgo": McpServer(
        id="orgo",
        display_name="Orgo.io",
        use_when="Isolated cloud desktop and computer-use execution targets.",
        boundary="Visible by default; install only through an approved Orgo MCP bridge or runtime execution target.",
        install_scope="visible only until an approved Orgo MCP bridge is available",
    ),
    "playwright": McpServer(
        id="playwright",
        display_name="Playwright",
        command="npx",
        args=("@playwright/mcp@latest",),
        use_when="Browser automation and UI validation workflows.",
        boundary="Visible by default; add to config only in layers that explicitly own browser automation.",
        install_scope="visible only until a browser automation layer opts in",
    ),
}


def _normalized_parts(path: str | Path | None) -> set[str]:
    if path is None:
        return set()
    return {part.lower().replace("-", "_") for part in Path(path).parts}


def active_domain_ids(path: str | Path | None = None, approved_domains: list[str] | tuple[str, ...] | None = None) -> set[str]:
    parts = _normalized_parts(path)
    domains = {str(domain).lower().replace("-", "_") for domain in approved_domains or ()}
    domains.update(parts)
    active: set[str] = set()
    if {"los", "lenders"} & domains:
        active.add("los")
    if {"clark", "clarks", "clarks_consulting", "clark_consulting"} & domains:
        active.add("clarks_consulting")
    return active


def config_mcp_ids(layer: str, path: str | Path | None = None) -> tuple[str, ...]:
    ids = list(CORE_MCP_IDS)
    domains = active_domain_ids(path)
    if "los" in domains:
        ids.extend(LOS_MCP_IDS)
    if "clarks_consulting" in domains:
        ids.extend(CLARKS_MCP_IDS)
    return tuple(dict.fromkeys(ids))


def all_visible_mcp_ids() -> tuple[str, ...]:
    return tuple(dict.fromkeys((*CORE_MCP_IDS, *LOS_MCP_IDS, *CLARKS_MCP_IDS, *VISIBLE_ONLY_MCP_IDS)))


def mcp_status(server_id: str, active_domains: set[str]) -> str:
    if server_id in CORE_MCP_IDS:
        return "installed at every layer"
    if server_id in LOS_MCP_IDS:
        return "installed here" if "los" in active_domains else "visible; LOS layers only"
    if server_id in CLARKS_MCP_IDS:
        return "installed here" if "clarks_consulting" in active_domains else "visible; clarks_consulting layers only"
    if server_id == "playwright":
        return "visible; opt in for browser automation layers"
    return "visible; endpoint or bridge approval required"


def mcp_tools_markdown(
    path: str | Path | None = None,
    approved_domains: list[str] | tuple[str, ...] | None = None,
    *,
    include_inactive: bool = True,
    public_customer: bool = False,
) -> str:
    active_domains = active_domain_ids(path, approved_domains)
    rows = []
    for server_id in all_visible_mcp_ids():
        if not include_inactive and server_id not in CORE_MCP_IDS:
            if server_id in LOS_MCP_IDS and "los" not in active_domains:
                continue
            if server_id in CLARKS_MCP_IDS and "clarks_consulting" not in active_domains:
                continue
            if server_id in VISIBLE_ONLY_MCP_IDS:
                continue
        server = MCP_SERVERS[server_id]
        display_name = server.display_name
        use_when = server.use_when
        boundary = server.boundary
        if public_customer and server_id == "notion":
            use_when = "Approved Notion control-plane reads and writes."
            boundary = "Verify the intended customer workspace before writing."
        if public_customer and server_id == "genomes_brain":
            display_name = "Agentic memory"
            use_when = "Durable cross-session memory reads and non-secret writes."
            boundary = "No secrets; follow customer memory policy before writing."
        rows.append(
            f"| `{server.id}` | {display_name} | {use_when} | {mcp_status(server_id, active_domains)} | {boundary} |"
        )
    return "\n".join(
        [
            "| Config ID | Server | Use When | Install Status | Boundary |",
            "| --- | --- | --- | --- | --- |",
            *rows,
        ]
    )


def mcp_config_payload(server: McpServer) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    if server.url:
        payload["url"] = server.url
    if server.command:
        payload["command"] = server.command
    if server.args:
        payload["args"] = list(server.args)
    if server.bearer_token_env_var:
        payload["bearer_token_env_var"] = server.bearer_token_env_var
    payload["secret_policy"] = server.secret_policy
    return payload
