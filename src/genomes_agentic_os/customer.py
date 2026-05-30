"""Customer Agentic OS factory operations."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re
from typing import Any

import yaml

from .capability_registry import REGISTRY_FILES, VISIBLE_CAPABILITY_DIRECTORIES, inventory_markdown
from .scaffold import (
    AUTOMATION_FILES,
    ROOT_MARKER_FILENAME,
    WORKFLOW_FILES,
    agent_entrypoint,
    automation_logs_readme,
    automation_scaffold_content,
    claude_adapter,
    create_domain_structure,
    ensure_customer_update_contract,
    ensure_dir,
    ensure_update_metadata,
    expand_path,
    template_source_dir,
    validate_name,
    write_file_once,
    write_root_marker,
    workflow_examples_readme,
    workflow_runs_readme,
    workflow_scaffold_content,
)
from .mcp_catalog import mcp_tools_markdown
from .validate import ValidationResult, validate_domain


PRIVATE_TERMS = ("genome", "clark", "clarks_consulting", "los", "lenders")
CUSTOMER_CONFIG_PROFILES = {
    "customer_os_root": "customer_os_root",
    "domain_or_lane": "domain_or_lane",
    "workflow_or_task": "workflow_or_task",
    "automation": "automation",
}
CUSTOMER_ROOT_FILES = (
    ROOT_MARKER_FILENAME,
    "config.toml",
    "README.md",
    "ROUTER.md",
    "AGENTS.md",
    "CLAUDE.md",
    "CONTEXT.md",
    "RULES.md",
    "TOOLS.md",
    "MEMORY.md",
    "agentic-os.lock.json",
    "UPDATE_POLICY.md",
    "customer.yml",
)


@dataclass
class CustomerResult:
    created: list[Path] = field(default_factory=list)
    skipped: list[Path] = field(default_factory=list)
    updated: list[Path] = field(default_factory=list)

    def extend(self, other: Any) -> None:
        self.created.extend(getattr(other, "created", []))
        self.skipped.extend(getattr(other, "skipped", []))
        self.updated.extend(getattr(other, "updated", []))

    def as_dict(self) -> dict[str, list[str]]:
        return {
            "created": [str(path) for path in self.created],
            "updated": [str(path) for path in self.updated],
            "skipped": [str(path) for path in self.skipped],
        }


def load_profile(profile_path: str | Path) -> dict[str, Any]:
    path = expand_path(profile_path)
    if not path.is_file():
        raise ValueError(f"profile file is missing: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError("customer profile must be a YAML mapping")
    customer = data.get("customer")
    if not isinstance(customer, dict):
        raise ValueError("customer profile must include a customer mapping")
    return data


def profile_customer(data: dict[str, Any]) -> dict[str, Any]:
    customer = data.get("customer") or {}
    if not isinstance(customer, dict):
        raise ValueError("customer profile must include a customer mapping")
    return customer


def profile_value(data: dict[str, Any], key: str, default: Any = None) -> Any:
    customer = profile_customer(data)
    if key in customer:
        return customer[key]
    return data.get(key, default)


def normalize_profile(customer_slug: str, data: dict[str, Any]) -> dict[str, Any]:
    slug = validate_name(customer_slug, "customer_slug")
    customer = profile_customer(data)
    profile_slug = customer.get("slug")
    if profile_slug and not str(profile_slug).startswith("<"):
        profile_slug = validate_name(str(profile_slug), "customer.slug")
        if profile_slug != slug:
            raise ValueError(f"profile customer.slug {profile_slug!r} does not match {slug!r}")
    customer["slug"] = slug
    customer.setdefault("display_name", slug.replace("_", " ").title())
    customer.setdefault("owner", "Customer Owner")
    customer.setdefault("notion_workspace", "")

    approved_domains = profile_value(data, "approved_domains")
    if not approved_domains:
        approved_domains = [room["id"] for room in data.get("rooms", []) if isinstance(room, dict) and room.get("id")]
    if not approved_domains:
        approved_domains = ["operations"]
    customer["approved_domains"] = [validate_customer_name(str(domain), "approved domain") for domain in approved_domains]

    for list_key in ("source_systems", "default_workflows", "default_automations"):
        customer[list_key] = profile_value(data, list_key, []) or []
    customer["approval_policy"] = profile_value(data, "approval_policy", {}) or {}
    data["customer"] = customer
    data["content_boundary"] = {
        "public_customer_install": True,
        "source_owner_domains_excluded": True,
    }
    return data


def validate_customer_name(value: str, label: str) -> str:
    value = validate_name(value, label)
    lowered = value.lower()
    if lowered in PRIVATE_TERMS:
        raise ValueError(f"{label} uses a private Genome source name: {value!r}")
    return value


def render_customer_readme(profile: dict[str, Any]) -> str:
    customer = profile_customer(profile)
    return f"""# {customer['display_name']} Agentic OS

This install contains the customer-approved operating domains, templates, workflows, automations, run logs, and update contract.

## Customer

| Field | Value |
| --- | --- |
| Slug | `{customer['slug']}` |
| Owner | {customer.get('owner', '')} |
| Notion Workspace | {customer.get('notion_workspace', '')} |

## Approved Domains

{chr(10).join(f'- `{domain}`' for domain in customer['approved_domains'])}

## Update Contract

Updates are additive and non-destructive. Local customer edits are preserved unless an operator explicitly replaces them.
"""


def render_customer_router(profile: dict[str, Any]) -> str:
    customer = profile_customer(profile)
    rows = "\n".join(f"| `{domain}` | `{domain}/ROUTER.md` |" for domain in customer["approved_domains"])
    return f"""# Customer Router

Read this file first, then load only the domain router and context files needed
for the request. After routing to a domain, read that domain's `ROUTER.md`,
`CONTEXT.md`, `RULES.md`, and `TOOLS.md`, then repeat the routing decision.

## Routing Table

| Domain | Router |
| --- | --- |
{rows}

## Operating Rules

- Use only customer-approved domains and source systems.
- Stop before external writes, customer-visible output, production changes, destructive actions, billing, legal, or credential changes unless approval is explicit.
- Record material runs in the domain run log.
"""


def render_agent_router() -> str:
    return agent_entrypoint("this customer Agentic OS root")


def render_customer_context(profile: dict[str, Any]) -> str:
    customer = profile_customer(profile)
    domains = "\n".join(f"- `{domain}`" for domain in customer["approved_domains"])
    return f"""# Customer Context

This root is a customer-specific Agentic OS install. Use only the approved
domains, source systems, and approval rules in this install.

## Customer

| Field | Value |
| --- | --- |
| Slug | `{customer['slug']}` |
| Display Name | {customer['display_name']} |
| Notion Workspace | {customer.get('notion_workspace', '')} |

## Approved Domains

{domains}

## What To Load

| Need | Read First | Read When Needed | Skip By Default |
| --- | --- | --- | --- |
| Route work | `ROUTER.md`, `CONTEXT.md`, `RULES.md`, `TOOLS.md` | selected domain router | unapproved domains |
| Domain work | selected domain context files | source maps, project status, run logs | unrelated domains |
| Customer-visible output | `RULES.md`, approval policy, source map | human approval record | private source packages |

## Done Means

- Work stays inside customer-approved domains and systems.
- Approval gates are followed before external or customer-visible actions.
- Source evidence and validation are recorded.
"""


def render_customer_rules(profile: dict[str, Any]) -> str:
    customer = profile_customer(profile)
    return f"""# Rules

These rules apply to the customer OS root for `{customer['display_name']}` unless a narrower layer provides a stricter rule.

## Approval Gates

- External writes require explicit approval.
- Customer-visible output requires explicit approval.
- Production changes require explicit approval.
- Destructive actions require explicit approval.
- Secrets, billing, and legal records require explicit approval.

## Operating Rules

- This install is for `{customer['display_name']}` only.
- Use only customer-approved domains and source systems.
- Do not copy private source-package terms, internal client names, or unrelated tenant data into customer artifacts.
- Route before acting.
- Preserve source links and validation evidence.
- Keep secrets out of prompts, logs, docs, generated config, and run artifacts.

## Precedence

Narrower rules override these rules unless this file is stricter for safety, privacy, production, billing, legal, or customer-visible work.
"""


def render_customer_tools(profile: dict[str, Any]) -> str:
    customer = profile_customer(profile)
    return f"""# Tools

This registry names the visible tool surface for `{customer['display_name']}`.

## Skills

| Skill | Use When | Source |
| --- | --- | --- |
| `os-navigator` | Route customer work to the correct domain, workflow, automation, or run log. | shared skill registry |
| `workflow-builder` | Create or improve reusable workflows. | shared skill registry |
| `automation-qualifier` | Decide whether a process is safe to automate. | shared skill registry |
| `context-pack-builder` | Assemble focused customer-safe context packs. | shared skill registry |
| `run-logger` | Capture execution evidence. | shared skill registry |

## Commands

| Command | Use When | Notes |
| --- | --- | --- |
| `agentic-os customer validate` | Validate this customer OS. | Run before handoff after structural changes. |
| `agentic-os route` | Route a request to a domain or workflow. | Use before creating new work. |
| `agentic-os context build` | Build a deterministic context packet. | Use for handoffs and repeatable runs. |

## MCP Servers

{mcp_tools_markdown(approved_domains=customer["approved_domains"], include_inactive=False, public_customer=True)}

## Plugins And Libraries

| Name | Use When | Notes |
| --- | --- | --- |
|  |  |  |

## Local Wrappers

| Wrapper | Use When | Path |
| --- | --- | --- |
| host tool registry | Shell, terminal, runtime, package-manager, and cleanup work. | inherited from the installed OS when present |

## When To Use What

- Use skills for repeatable customer-safe workflows.
- Use commands for deterministic filesystem or runtime operations.
- Use MCP servers only when the current layer's rules and source boundaries allow them.

## Missing Or Disabled

Only list or use tools approved for `{customer['display_name']}`. Record missing
customer tools in this file instead of silently falling back to another
workspace.
"""


def customer_layer_tools() -> str:
    return f"""# Tools

This registry names the visible tool surface for this customer-approved layer.

## Skills

| Skill | Use When | Source |
| --- | --- | --- |
| `os-navigator` | Route customer work to the correct local layer. | shared skill registry |
| `workflow-builder` | Create or improve reusable workflows. | shared skill registry |
| `automation-qualifier` | Decide whether a process is safe to automate. | shared skill registry |

## Commands

| Command | Use When | Notes |
| --- | --- | --- |
| `agentic-os customer validate` | Validate this customer OS. | Run before handoff after structural changes. |
| `agentic-os route` | Route a request to a domain or workflow. | Use before creating new work. |

## MCP Servers

{mcp_tools_markdown(approved_domains=(), include_inactive=False, public_customer=True)}

## Missing Or Disabled

Record missing customer-approved tools here instead of falling back to another workspace.
"""


def customer_layer_config(layer: str) -> str:
    profile = CUSTOMER_CONFIG_PROFILES[layer]
    return f"""# Agentic OS Codex config template
# Layer: {layer}
# Customer-safe local layer. Do not inline secrets.

model = "gpt-5.2"
approval_policy = "on-request"
sandbox_mode = "workspace-write"
project_root_markers = [".agentic_root", ".git", "agentic-os.package.json", "pyproject.toml", "package.json"]
project_doc_fallback_filenames = ["ROUTER.md", "CONTEXT.md", "RULES.md", "TOOLS.md", "MEMORY.md"]

[profiles.{profile}]
model = "gpt-5.2"
approval_policy = "on-request"
sandbox_mode = "workspace-write"

[profiles.{profile}.agentic_os]
layer = "{layer}"
prompt_files = ["AGENTS.md", "CLAUDE.md", "ROUTER.md", "CONTEXT.md", "RULES.md", "TOOLS.md", "MEMORY.md"]
context_contract = "route-read-cd-repeat"
rules_file = "RULES.md"
tool_registry_file = "TOOLS.md"
mcp_availability = "approved customer systems only"
environment = "local filesystem"

[otel]
log_user_prompt = false
exporter_otlp_endpoint_env_var = "AGENTIC_OS_OTEL_EXPORTER_OTLP_ENDPOINT"
headers_env_var = "AGENTIC_OS_OTEL_HEADERS"

[mcp_servers.filesystem_runtime]
command = "agentic-os"
args = ["customer", "validate"]
secret_policy = "no inline secrets"
"""


def has_private_marker(content: str) -> bool:
    lowered = content.lower()
    return any(re.search(rf"(?<![a-z0-9_]){re.escape(term)}(?![a-z0-9_])", lowered) for term in PRIVATE_TERMS)


def write_customer_safe_file(path: Path, content: str, result: CustomerResult) -> None:
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        result.created.append(path)
        return
    if existing == content:
        result.skipped.append(path)
        return
    if has_private_marker(existing):
        path.write_text(content, encoding="utf-8")
        result.updated.append(path)
        return
    result.skipped.append(path)


def ensure_customer_codex_layer(root: Path, layer: str, result: CustomerResult) -> None:
    write_customer_safe_file(root / "config.toml", customer_layer_config(layer), result)
    write_customer_safe_file(root / "AGENTS.md", agent_entrypoint("this customer-approved Agentic OS layer"), result)
    write_customer_safe_file(root / "CLAUDE.md", claude_adapter(), result)
    write_customer_safe_file(root / "ROUTER.md", "# Agent Router\n\nRoute to the narrowest customer-approved local layer before acting.\n", result)
    write_customer_safe_file(root / "CONTEXT.md", "# Local Context\n\nUse only customer-approved local context and source systems for this layer.\n", result)
    write_customer_safe_file(root / "RULES.md", render_customer_rules({"customer": {"display_name": "this customer", "approved_domains": []}}), result)
    write_customer_safe_file(root / "TOOLS.md", customer_layer_tools(), result)
    write_customer_safe_file(root / "MEMORY.md", "# Memory Policy\n\nRecord only durable, non-secret, customer-approved learnings.\n", result)


def render_customer_asset(template_name: str, profile: dict[str, Any]) -> str:
    customer = profile_customer(profile)
    template = (template_source_dir() / "customer" / template_name).read_text(encoding="utf-8")
    return (
        template.replace("<customer_or_project>", customer["display_name"])
        .replace("<workflow_or_outcome>", f"{customer['display_name']} automation candidate")
        .replace("<input>", "customer-approved input")
        .replace("<output>", "customer-approved output")
        .replace("<criterion>", "Pilot output is reviewed and approved before external use.")
    )


def write_customer_assets(root: Path, profile: dict[str, Any], result: CustomerResult) -> None:
    customer_dir = root / "customer"
    write_file_once(customer_dir / "README.md", "# Customer Operating Package\n", result)
    write_file_once(customer_dir / "handoff-checklist.md", render_customer_asset("customer-handoff-checklist.md", profile), result)
    write_file_once(customer_dir / "automation-fit-matrix.md", render_customer_asset("automation-fit-matrix.md", profile), result)
    write_file_once(customer_dir / "client-automation-brief.md", render_customer_asset("client-automation-brief.md", profile), result)
    write_file_once(
        customer_dir / "update-contract.md",
        """# Customer Update Contract

Updates add missing standards, templates, domains, workflows, and automations. They do not overwrite local edits.

## Operator Review

- Review generated diffs before sharing customer-visible material.
- Keep secrets out of customer docs and run logs.
- Re-run customer validation after updates.
""",
        result,
    )
    shared = root / "shared_factory" / "05-knowledge" / "templates"
    write_file_once(
        shared / "profile" / "customer-os-profile.yml",
        (template_source_dir() / "profile" / "customer-os-profile.yml").read_text(encoding="utf-8"),
        result,
    )
    for filename in ("client-automation-brief.md", "automation-fit-matrix.md", "customer-handoff-checklist.md"):
        write_file_once(shared / "customer" / filename, (template_source_dir() / "customer" / filename).read_text(encoding="utf-8"), result)


def public_customer_registry_payloads() -> dict[str, dict[str, Any]]:
    commands = [
        {"id": "customer-validate", "command": "agentic-os customer validate", "description": "Validate this customer OS.", "source": "agentic-os customer validate"},
        {"id": "route", "command": "agentic-os route", "description": "Route a request to the right customer-approved domain.", "source": "agentic-os route"},
        {"id": "context-build", "command": "agentic-os context build", "description": "Build a focused context packet.", "source": "agentic-os context build"},
        {"id": "update-register", "command": "agentic-os update register", "description": "Register local public keys for approved updates and backups.", "source": "agentic-os update register"},
        {"id": "backup-run", "command": "agentic-os backup run", "description": "Plan or record a customer OS backup.", "source": "agentic-os backup run"},
    ]
    skills = [
        {"id": "os-navigator", "name": "OS Navigator", "description": "Route customer work to the right local domain.", "source": "shared skill registry"},
        {"id": "workflow-builder", "name": "Workflow Builder", "description": "Create or improve customer-approved workflows.", "source": "shared skill registry"},
        {"id": "automation-qualifier", "name": "Automation Qualifier", "description": "Check whether a customer process is safe to automate.", "source": "shared skill registry"},
    ]
    mcp_servers = [
        {
            "id": "notion",
            "name": "Notion",
            "use_when": "Approved customer control-plane reads and writes.",
            "boundary": "Verify the intended customer workspace before writing.",
            "install_scope": "approved customer layers only",
        },
        {
            "id": "agentic_memory",
            "name": "Agentic Memory",
            "use_when": "Durable non-secret memory reads and writes approved by local policy.",
            "boundary": "No secrets or unapproved customer data.",
            "install_scope": "approved customer layers only",
        },
        {
            "id": "github",
            "name": "GitHub",
            "use_when": "Approved repository, issue, and backup/update remote operations.",
            "boundary": "Use least-privilege credentials; never store token values in the OS.",
            "install_scope": "approved customer layers only",
        },
    ]
    libraries = [
        {"id": "context_mode", "name": "Context Mode", "description": "Large-output and file analysis without overloading context.", "source": "local analysis tool"},
        {"id": "unified_memory", "name": "Unified Memory", "description": "Durable non-secret memory plane.", "source": "approved memory service"},
    ]
    hooks = [
        {"id": "memory-write-router", "name": "Memory Write Router", "description": "Routes non-secret memory writes through policy.", "status": "available"},
        {"id": "quiet-pr-watch", "name": "Quiet PR Watch", "description": "Writes PR check status artifacts instead of chat polling.", "status": "available"},
    ]
    plugins = [
        {"id": "browser", "name": "Browser", "description": "Browser automation for approved local or customer-visible validation.", "status": "visible"},
    ]
    rules = [
        {"id": "route-read-cd-repeat", "name": "Route, read, cd, repeat", "description": "Read local routing, context, rules, and tools before acting.", "source": "AGENTS.md"},
        {"id": "strictest-rule-wins", "name": "Strictest rule wins", "description": "The strictest applicable safety rule wins.", "source": "RULES.md"},
        {"id": "no-secret-registry-values", "name": "No secret registry values", "description": "Reference secret environment variable names only.", "source": "RULES.md"},
    ]
    collections = {
        "commands": commands,
        "skills": skills,
        "mcp_servers": mcp_servers,
        "libraries": libraries,
        "hooks": hooks,
        "plugins": plugins,
        "rules": rules,
    }
    capabilities = []
    type_map = {
        "commands": "command",
        "skills": "skill",
        "mcp_servers": "mcp_server",
        "libraries": "library",
        "hooks": "hook",
        "plugins": "plugin",
        "rules": "rule",
    }
    for collection, entries in collections.items():
        for entry in entries:
            capabilities.append(
                {
                    "id": f"{type_map[collection]}:{entry['id']}",
                    "type": type_map[collection],
                    "ref": entry["id"],
                    "name": entry.get("name") or entry.get("command") or entry["id"],
                    "description": entry.get("description") or entry.get("use_when") or "",
                }
            )
    return {
        "capabilities": {"capabilities": capabilities},
        "commands": {"commands": commands},
        "skills": {"skills": skills},
        "mcp_servers": {"mcp_servers": mcp_servers},
        "libraries": {"libraries": libraries},
        "hooks": {"hooks": hooks},
        "plugins": {"plugins": plugins},
        "rules": {"rules": rules},
    }


def ensure_public_customer_capability_surface(root: Path, result: CustomerResult) -> None:
    for directory in VISIBLE_CAPABILITY_DIRECTORIES:
        ensure_dir(root / directory, result)
    payloads = public_customer_registry_payloads()
    for registry_name, relative_path in REGISTRY_FILES.items():
        write_file_once(root / relative_path, yaml.safe_dump(payloads[registry_name], sort_keys=False), result)
    write_file_once(root / "INVENTORY.md", inventory_markdown(payloads), result)


def parse_bundle_item(item: Any, default_domain: str) -> tuple[str, str, str]:
    if isinstance(item, str):
        parts = item.split("/")
        if len(parts) == 3:
            domain, lane, name = parts
        elif len(parts) == 2:
            domain = default_domain
            lane, name = parts
        else:
            raise ValueError(f"bundle item must be domain/lane/name or lane/name: {item!r}")
    elif isinstance(item, dict):
        domain = str(item.get("domain") or default_domain)
        lane = str(item.get("lane") or "operations")
        name = str(item.get("name") or item.get("id") or "")
    else:
        raise ValueError(f"unsupported bundle item: {item!r}")
    return (
        validate_customer_name(domain, "bundle domain"),
        validate_name(lane, "bundle lane"),
        validate_name(name, "bundle name"),
    )


def create_customer_domain(root: Path, domain: str) -> CustomerResult:
    result = CustomerResult()
    create_domain_structure(root, domain, result, public_customer_tools=True)
    ensure_customer_codex_layer(root / domain, "domain_or_lane", result)
    return result


def create_customer_workflow(root: Path, domain: str, lane: str, name: str) -> CustomerResult:
    result = create_customer_domain(root, domain)
    workflow_root = root / domain / "03-workflows" / lane / name
    ensure_dir(workflow_root, result)
    ensure_dir(workflow_root / "examples", result)
    ensure_dir(workflow_root / "runs", result)
    write_file_once(workflow_root / "examples" / "README.md", workflow_examples_readme(domain, lane, name), result)
    write_file_once(workflow_root / "runs" / "README.md", workflow_runs_readme(domain, lane, name), result)
    for filename in WORKFLOW_FILES:
        write_file_once(workflow_root / filename, workflow_scaffold_content(domain, lane, name, filename), result)
    ensure_customer_codex_layer(workflow_root, "workflow_or_task", result)
    return result


def create_customer_automation(root: Path, domain: str, lane: str, name: str) -> CustomerResult:
    result = create_customer_domain(root, domain)
    automation_root = root / domain / "04-automations" / lane / name
    ensure_dir(automation_root, result)
    ensure_dir(automation_root / "logs", result)
    write_file_once(automation_root / "logs" / "README.md", automation_logs_readme(domain, lane, name), result)
    for filename in AUTOMATION_FILES:
        write_file_once(automation_root / filename, automation_scaffold_content(domain, lane, name, filename), result)
    ensure_customer_codex_layer(automation_root, "automation", result)
    return result


def apply_customer_profile(root: Path, profile: dict[str, Any], result: CustomerResult) -> None:
    customer = profile_customer(profile)
    for domain in customer["approved_domains"]:
        result.extend(create_customer_domain(root, domain))
    default_domain = customer["approved_domains"][0]
    for item in customer.get("default_workflows", []):
        domain, lane, name = parse_bundle_item(item, default_domain)
        result.extend(create_customer_workflow(root, domain, lane, name))
    for item in customer.get("default_automations", []):
        domain, lane, name = parse_bundle_item(item, default_domain)
        result.extend(create_customer_automation(root, domain, lane, name))


def customer_init(customer_slug: str, profile_path: str | Path, target: str | Path) -> dict[str, Any]:
    profile = normalize_profile(customer_slug, load_profile(profile_path))
    root = expand_path(target)
    result = CustomerResult()
    root.mkdir(parents=True, exist_ok=True)
    write_root_marker(root, result)
    ensure_public_customer_capability_surface(root, result)
    ensure_update_metadata(root, result)
    ensure_customer_update_contract(root, result)
    write_file_once(root / "README.md", render_customer_readme(profile), result)
    write_file_once(root / "ROUTER.md", render_customer_router(profile), result)
    write_file_once(root / "AGENTS.md", render_agent_router(), result)
    write_file_once(root / "CLAUDE.md", claude_adapter(), result)
    write_file_once(root / "CONTEXT.md", render_customer_context(profile), result)
    write_file_once(root / "RULES.md", render_customer_rules(profile), result)
    write_file_once(root / "TOOLS.md", render_customer_tools(profile), result)
    ensure_customer_codex_layer(root, "customer_os_root", result)
    write_file_once(root / "customer.yml", yaml.safe_dump(profile, sort_keys=False), result)
    write_customer_assets(root, profile, result)
    apply_customer_profile(root, profile, result)
    return {"root": str(root), "customer": profile_customer(profile)["slug"], **result.as_dict()}


def customer_update(customer_slug: str, root: str | Path) -> dict[str, Any]:
    os_root = expand_path(root)
    profile_path = os_root / "customer.yml"
    if not profile_path.is_file():
        raise ValueError(f"customer.yml is missing: {profile_path}")
    profile = normalize_profile(customer_slug, yaml.safe_load(profile_path.read_text(encoding="utf-8")) or {})
    result = CustomerResult()
    write_root_marker(os_root, result)
    ensure_public_customer_capability_surface(os_root, result)
    ensure_update_metadata(os_root, result)
    ensure_customer_update_contract(os_root, result)
    write_file_once(os_root / "AGENTS.md", render_agent_router(), result)
    write_file_once(os_root / "CLAUDE.md", claude_adapter(), result)
    write_file_once(os_root / "CONTEXT.md", render_customer_context(profile), result)
    write_file_once(os_root / "RULES.md", render_customer_rules(profile), result)
    write_file_once(os_root / "TOOLS.md", render_customer_tools(profile), result)
    ensure_customer_codex_layer(os_root, "customer_os_root", result)
    write_customer_assets(os_root, profile, result)
    apply_customer_profile(os_root, profile, result)
    return {"root": str(os_root), "customer": profile_customer(profile)["slug"], **result.as_dict()}


def private_term_warnings(root: Path) -> list[str]:
    warnings = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in {".md", ".yml", ".yaml"}:
            continue
        text = path.read_text(encoding="utf-8").lower()
        for term in PRIVATE_TERMS:
            if re.search(rf"(?<![a-z0-9_]){re.escape(term)}(?![a-z0-9_])", text):
                warnings.append(f"private source term {term!r} appears in {path}")
                break
    return warnings


def customer_validate(root: str | Path) -> dict[str, Any]:
    os_root = expand_path(root)
    core_errors: list[str] = []
    profile_warnings: list[str] = []
    if not os_root.is_dir():
        return {"root": str(os_root), "ok": False, "core_errors": [f"missing root: {os_root}"], "profile_warnings": []}
    for filename in CUSTOMER_ROOT_FILES:
        if not (os_root / filename).is_file():
            core_errors.append(f"missing customer root file: {os_root / filename}")
    for filename in ("customer-identity.json", "backup-policy.yml"):
        if not (os_root / "registries" / filename).is_file():
            core_errors.append(f"missing customer registry file: {os_root / 'registries' / filename}")
    for directory in ("security/ssh", "logs/updates", "logs/backups"):
        if not (os_root / directory).is_dir():
            core_errors.append(f"missing customer runtime folder: {os_root / directory}")
    profile_path = os_root / "customer.yml"
    profile: dict[str, Any] = {}
    if profile_path.is_file():
        try:
            profile = yaml.safe_load(profile_path.read_text(encoding="utf-8")) or {}
            profile = normalize_profile(str(profile_customer(profile).get("slug", "")), profile)
        except (ValueError, yaml.YAMLError) as exc:
            core_errors.append(f"invalid customer profile: {exc}")
    if profile:
        customer = profile_customer(profile)
        if not customer.get("notion_workspace"):
            profile_warnings.append("customer.notion_workspace is empty")
        if not customer.get("source_systems"):
            profile_warnings.append("customer.source_systems is empty")
        if not customer.get("default_workflows"):
            profile_warnings.append("customer.default_workflows is empty")
        if not customer.get("default_automations"):
            profile_warnings.append("customer.default_automations is empty")
        domain_result = ValidationResult(root=os_root)
        for domain in customer["approved_domains"]:
            validate_domain(os_root / domain, domain_result)
        core_errors.extend(domain_result.errors)
        profile_warnings.extend(domain_result.warnings)
    profile_warnings.extend(private_term_warnings(os_root))
    return {"root": str(os_root), "ok": not core_errors, "core_errors": core_errors, "profile_warnings": profile_warnings}


def format_customer_result(result: dict[str, Any]) -> str:
    return yaml.safe_dump(result, sort_keys=False).strip()
