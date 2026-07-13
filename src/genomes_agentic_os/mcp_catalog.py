"""Layer-aware MCP catalog for Agentic OS config and tool docs.

Optional (non-core) servers are never keyed to built-in domain names.
A domain opts into a gated server through the installed OS registry at
``harness/registries/mcp-domain-gating.yml``::

    domains:
      alpha_ops:
        - sentry
        - datadog

Layers resolve their gating by walking up from the target path to the
OS root marker; roots without the registry get core servers only.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import yaml


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
# Servers a domain can opt into via the mcp-domain-gating registry.
DOMAIN_GATED_MCP_IDS = ("sentry", "datadog", "supabase")
VISIBLE_ONLY_MCP_IDS = ("composio", "orgo", "playwright")

# Installed-OS registry that maps domain slug -> gated server ids.
DOMAIN_GATING_REGISTRY = "harness/registries/mcp-domain-gating.yml"
# Duplicated from scaffold.ROOT_MARKER_FILENAME to avoid a circular import
# (scaffold imports this module).
_ROOT_MARKER_FILENAME = ".agentic_root"

MCP_SERVERS: dict[str, McpServer] = {
    "notion": McpServer(
        id="notion",
        display_name="Notion",
        url="https://mcp.notion.com/mcp",
        use_when="Notion control-plane reads and approved writes.",
        boundary="Verify the intended control-plane workspace before writing.",
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
        command="context-mode",
        use_when="Large-file, repo, and session-memory analysis without flooding prompt context.",
        boundary="Use for analysis and retrieval; do not use context-mode subprocesses for file writes.",
        install_scope="every layer",
    ),
    "sentry": McpServer(
        id="sentry",
        display_name="Sentry",
        url="https://mcp.sentry.dev/mcp",
        use_when="Error, trace, release, and production incident investigation.",
        boundary="Domain-gated; production/customer-visible changes still require approval.",
        install_scope="domain-gated via mcp-domain-gating registry",
    ),
    "datadog": McpServer(
        id="datadog",
        display_name="Datadog",
        url="https://mcp.datadoghq.com/api/unstable/mcp-server/mcp",
        use_when="Observability, logs, metrics, traces, and monitor investigation.",
        boundary="Domain-gated; do not expose customer data outside approved observability workflows.",
        install_scope="domain-gated via mcp-domain-gating registry",
    ),
    "supabase": McpServer(
        id="supabase",
        display_name="Supabase",
        url="https://mcp.supabase.com/mcp",
        use_when="Supabase project work in domains that opt in.",
        boundary="Domain-gated; install only in layers the gating registry approves.",
        install_scope="domain-gated via mcp-domain-gating registry",
    ),
    "composio": McpServer(
        id="composio",
        display_name="Composio",
        use_when="Federated SaaS tools, OAuth flows, triggers, and app actions routed through `harness/registries/composio-tools.yml`.",
        boundary="Visible by default; install only after generating an approved Composio MCP server URL for the target layer and matching the requested toolkit to the route registry.",
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


def _normalized(value: str) -> str:
    return value.lower().replace("-", "_")


def _normalized_parts(path: str | Path | None) -> set[str]:
    if path is None:
        return set()
    return {_normalized(part) for part in Path(path).parts}


def _find_os_root(path: str | Path | None) -> Path | None:
    if path is None:
        return None
    candidate = Path(path).expanduser()
    try:
        candidate = candidate.resolve()
    except OSError:
        return None
    for current in (candidate, *candidate.parents):
        if (current / _ROOT_MARKER_FILENAME).is_file():
            return current
    return None


def load_domain_mcp_gating(path: str | Path | None = None) -> dict[str, tuple[str, ...]]:
    """Load the domain -> gated-server mapping for the OS root above *path*.

    Returns an empty mapping when no OS root or registry file exists, or
    when the registry is malformed. Unknown server ids are ignored so a
    typo can never install an undeclared server.
    """
    os_root = _find_os_root(path)
    if os_root is None:
        return {}
    registry = os_root / DOMAIN_GATING_REGISTRY
    if not registry.is_file():
        return {}
    try:
        data = yaml.safe_load(registry.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return {}
    raw = data.get("domains") if isinstance(data, dict) else None
    if not isinstance(raw, dict):
        return {}
    gating: dict[str, tuple[str, ...]] = {}
    for domain, server_ids in raw.items():
        if not isinstance(server_ids, (list, tuple)):
            continue
        cleaned = tuple(
            server_id
            for server_id in (str(item) for item in server_ids)
            if server_id in DOMAIN_GATED_MCP_IDS
        )
        if cleaned:
            gating[_normalized(str(domain))] = cleaned
    return gating


def active_domain_ids(
    path: str | Path | None = None,
    approved_domains: list[str] | tuple[str, ...] | None = None,
) -> set[str]:
    domains = {_normalized(str(domain)) for domain in approved_domains or ()}
    domains.update(_normalized_parts(path))
    return domains


def _gated_ids(
    active_domains: set[str],
    gating: Mapping[str, Sequence[str]],
) -> tuple[str, ...]:
    activated = {
        server_id
        for domain, server_ids in gating.items()
        if domain in active_domains
        for server_id in server_ids
    }
    return tuple(server_id for server_id in DOMAIN_GATED_MCP_IDS if server_id in activated)


def config_mcp_ids(
    layer: str,
    path: str | Path | None = None,
    gating: Mapping[str, Sequence[str]] | None = None,
) -> tuple[str, ...]:
    resolved_gating = load_domain_mcp_gating(path) if gating is None else gating
    ids = list(CORE_MCP_IDS)
    ids.extend(_gated_ids(active_domain_ids(path), resolved_gating))
    return tuple(dict.fromkeys(ids))


def all_visible_mcp_ids() -> tuple[str, ...]:
    return tuple(dict.fromkeys((*CORE_MCP_IDS, *DOMAIN_GATED_MCP_IDS, *VISIBLE_ONLY_MCP_IDS)))


def mcp_status(
    server_id: str,
    active_domains: set[str],
    gating: Mapping[str, Sequence[str]] | None = None,
) -> str:
    if server_id in CORE_MCP_IDS:
        return "installed at every layer"
    if server_id in DOMAIN_GATED_MCP_IDS:
        if server_id in _gated_ids(active_domains, gating or {}):
            return "installed here"
        return "visible; domain-gated via mcp-domain-gating registry"
    if server_id == "playwright":
        return "visible; opt in for browser automation layers"
    return "visible; endpoint or bridge approval required"


def mcp_tools_markdown(
    path: str | Path | None = None,
    approved_domains: list[str] | tuple[str, ...] | None = None,
    *,
    include_inactive: bool = True,
    public_customer: bool = False,
    gating: Mapping[str, Sequence[str]] | None = None,
) -> str:
    active_domains = active_domain_ids(path, approved_domains)
    resolved_gating = load_domain_mcp_gating(path) if gating is None else gating
    active_gated = set(_gated_ids(active_domains, resolved_gating))
    rows = []
    for server_id in all_visible_mcp_ids():
        if not include_inactive and server_id not in CORE_MCP_IDS:
            if server_id in DOMAIN_GATED_MCP_IDS and server_id not in active_gated:
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
            f"| `{server.id}` | {display_name} | {use_when} | {mcp_status(server_id, active_domains, resolved_gating)} | {boundary} |"
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
