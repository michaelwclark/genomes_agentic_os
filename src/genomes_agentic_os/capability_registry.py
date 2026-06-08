"""Visible capability registry defaults for installed Agentic OS roots."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .mcp_catalog import MCP_SERVERS, all_visible_mcp_ids


HARNESS_DIRECTORY = "harness"

VISIBLE_CAPABILITY_DIRECTORIES = (
    "harness/bin",
    "harness/commands",
    "harness/skills",
    "harness/mcp",
    "harness/plugins",
    "harness/libraries",
    "harness/hooks",
    "harness/rules",
    "harness/registries",
)

REGISTRY_FILES = {
    "capabilities": "harness/registries/capabilities.yml",
    "commands": "harness/registries/commands.yml",
    "skills": "harness/registries/skills.yml",
    "mcp_servers": "harness/registries/mcp-servers.yml",
    "libraries": "harness/registries/libraries.yml",
    "hooks": "harness/registries/hooks.yml",
    "plugins": "harness/registries/plugins.yml",
    "rules": "harness/registries/rules.yml",
}

CAPABILITY_COLLECTIONS = {
    "command": "commands",
    "skill": "skills",
    "mcp_server": "mcp_servers",
    "library": "libraries",
    "hook": "hooks",
    "plugin": "plugins",
    "rule": "rules",
}


def command_entries() -> list[dict[str, str]]:
    return [
        {
            "id": "make-skill",
            "command": "/make-skill",
            "description": "Create or update a reusable Agentic OS skill.",
            "source": "harness/commands/os-create-workflow.md",
        },
        {
            "id": "make-domain",
            "command": "/make-domain",
            "description": "Create a routed Agentic OS domain or room.",
            "source": "agentic-os domain create",
        },
        {
            "id": "make-automation",
            "command": "/make-automation",
            "description": "Create a guarded automation spec and supporting files.",
            "source": "harness/commands/os-create-automation.md",
        },
        {
            "id": "make-workflow",
            "command": "/make-workflow",
            "description": "Create a reusable workflow spec and run contract.",
            "source": "harness/commands/os-create-workflow.md",
        },
        {
            "id": "orchestrate",
            "command": "/orchestrate",
            "description": "Plan, decompose, delegate, verify, and merge feature work.",
            "source": "harness/skills/orchestrate/SKILL.md",
        },
        {
            "id": "validate",
            "command": "agentic-os validate",
            "description": "Validate an installed OS root against the source package contract.",
            "source": "agentic-os validate",
        },
        {
            "id": "project-onboard",
            "command": "agentic-os project onboard",
            "description": "Create or repair a project-local agent, config, ideas, and worktree surface.",
            "source": "agentic-os project onboard",
        },
        {
            "id": "project-worktree-add",
            "command": "agentic-os project worktree add",
            "description": "Register a visible project worktree symlink and routing index entry.",
            "source": "agentic-os project worktree add",
        },
        {
            "id": "config-doctor",
            "command": "agentic-os config doctor",
            "description": "Validate Codex config and MCP registration contracts.",
            "source": "agentic-os config doctor",
        },
        {
            "id": "config-install-tree",
            "command": "agentic-os config install-tree",
            "description": "Install Codex config.toml files across the OS routing tree.",
            "source": "agentic-os config install-tree",
        },
        {
            "id": "hook-sync",
            "command": "agentic-os hook sync",
            "description": "Point active Claude/Codex hook settings at the installed OS hook source of truth.",
            "source": "agentic-os hook sync",
        },
        {
            "id": "self-improvement-run",
            "command": "agentic-os self-improvement run --dry-run",
            "description": "Review durable local evidence for proposal-only OS improvement opportunities.",
            "source": "harness/commands/os-self-improvement.md",
        },
    ]


def skill_entries() -> list[dict[str, str]]:
    return [
        {
            "id": "os-navigator",
            "name": "OS Navigator",
            "description": "Route work through installed Agentic OS rooms.",
            "source": "harness/skills/os-navigator/SKILL.md",
        },
        {
            "id": "workflow-builder",
            "name": "Workflow Builder",
            "description": "Create or refine reusable workflow contracts.",
            "source": "harness/skills/workflow-builder/SKILL.md",
        },
        {
            "id": "automation-qualifier",
            "name": "Automation Qualifier",
            "description": "Decide whether a process is safe to automate.",
            "source": "harness/skills/automation-qualifier/SKILL.md",
        },
        {
            "id": "orchestrate",
            "name": "Orchestrate",
            "description": "Coordinate subagents, verification, and integration.",
            "source": "harness/skills/orchestrate/SKILL.md",
        },
        {
            "id": "toolsmith-reviewer",
            "name": "Toolsmith Reviewer",
            "description": "Review redacted evidence bundles and propose draft-only OS improvements.",
            "source": "harness/skills/toolsmith-reviewer/SKILL.md",
        },
    ]


def mcp_server_entries() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for server_id in all_visible_mcp_ids():
        server = MCP_SERVERS[server_id]
        rows.append(
            {
                "id": server.id,
                "name": server.display_name,
                "use_when": server.use_when,
                "boundary": server.boundary,
                "install_scope": server.install_scope,
            }
        )
    return rows


def library_entries() -> list[dict[str, str]]:
    return [
        {
            "id": "context_mode",
            "name": "Context Mode",
            "description": "Large-output and file analysis without flooding agent context.",
            "source": "context-mode MCP and CLI",
        },
        {
            "id": "unified_memory",
            "name": "Unified Memory",
            "description": "Durable cross-session memory plane backed by losmon-memory, CoCoIndex, and MemPalace.",
            "source": "losmon-memory MCP",
        },
        {
            "id": "pyyaml",
            "name": "PyYAML",
            "description": "Structured YAML parsing for registries, runtime state, and templates.",
            "source": "pyproject.toml",
        },
    ]


def hook_entries() -> list[dict[str, str]]:
    return [
        {
            "id": "memory-write-router",
            "name": "Memory Write Router",
            "description": "Routes durable memory writes to the correct substrate without writing CLAUDE.md.",
            "status": "available",
            "source": "harness/hooks/memory-session-start.sh",
            "events": "SessionStart, Stop",
        },
        {
            "id": "memory-session-start",
            "name": "Memory Session Start",
            "description": "Injects losmon-memory discipline at session start, resume, or clear.",
            "status": "available",
            "source": "harness/hooks/memory-session-start.sh",
            "events": "SessionStart",
        },
        {
            "id": "memory-stop",
            "name": "Memory Stop Reminder",
            "description": "Reminds agents to write durable memory before ending substantive turns.",
            "status": "available",
            "source": "harness/hooks/memory-stop.sh",
            "events": "Stop",
        },
        {
            "id": "harness-trace-emitter",
            "name": "Harness Trace Emitter",
            "description": "Emits non-blocking AGENT_TRACE memory records from Stop hook payloads.",
            "status": "available",
            "source": "harness/hooks/harness-emit-trace.sh",
            "events": "Stop",
        },
        {
            "id": "conversation-auto-log",
            "name": "Conversation Auto Log",
            "description": "Writes redacted conversation transcripts and tool-call sidecars to the routed project or work item.",
            "status": "available",
            "source": "harness/hooks/conversation-auto-log.py",
            "events": "Stop",
        },
        {
            "id": "context-mode-cache-heal",
            "name": "Context Mode Cache Heal",
            "description": "Repairs stale Claude context-mode plugin cache symlinks after auto-updates.",
            "status": "available",
            "source": "harness/hooks/context-mode-cache-heal.mjs",
            "events": "SessionStart",
        },
        {
            "id": "quiet-pr-watch",
            "name": "Quiet PR Watch",
            "description": "Writes PR check status artifacts instead of long-polling in chat.",
            "status": "available",
        },
    ]


def plugin_entries() -> list[dict[str, str]]:
    return [
        {
            "id": "browser",
            "name": "Browser",
            "description": "In-app browser automation for local targets and screenshots.",
            "status": "visible",
        },
        {
            "id": "chrome",
            "name": "Chrome",
            "description": "Chrome automation when user cookies or existing profile state are required.",
            "status": "visible",
        },
        {
            "id": "computer-use",
            "name": "Computer Use",
            "description": "Local desktop app operation through Computer Use.",
            "status": "visible",
        },
    ]


def rule_entries() -> list[dict[str, str]]:
    return [
        {
            "id": "route-read-cd-repeat",
            "name": "Route, read, cd, repeat",
            "description": "Read local routing, context, rules, and tools before acting at each layer.",
            "source": "AGENTS.md",
        },
        {
            "id": "strictest-rule-wins",
            "name": "Strictest rule wins",
            "description": "Narrower rules override broader rules unless the broader rule is stricter for safety.",
            "source": "RULES.md",
        },
        {
            "id": "no-secret-registry-values",
            "name": "No secret registry values",
            "description": "Registry and config files reference secret environment variable names only.",
            "source": "RULES.md",
        },
    ]


def capability_entries() -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    for collection_type, getter in (
        ("command", command_entries),
        ("skill", skill_entries),
        ("mcp_server", mcp_server_entries),
        ("library", library_entries),
        ("hook", hook_entries),
        ("plugin", plugin_entries),
        ("rule", rule_entries),
    ):
        for entry in getter():
            entries.append(
                {
                    "id": f"{collection_type}:{entry['id']}",
                    "type": collection_type,
                    "ref": entry["id"],
                    "name": entry.get("name") or entry.get("command") or entry["id"],
                    "description": entry.get("description") or entry.get("use_when") or "",
                }
            )
    return entries


def registry_payloads() -> dict[str, dict[str, Any]]:
    return {
        "capabilities": {"capabilities": capability_entries()},
        "commands": {"commands": command_entries()},
        "skills": {"skills": skill_entries()},
        "mcp_servers": {"mcp_servers": mcp_server_entries()},
        "libraries": {"libraries": library_entries()},
        "hooks": {"hooks": hook_entries()},
        "plugins": {"plugins": plugin_entries()},
        "rules": {"rules": rule_entries()},
    }


def registry_file_payloads() -> dict[str, dict[str, Any]]:
    payloads = registry_payloads()
    return {REGISTRY_FILES[name]: payload for name, payload in payloads.items()}


def registry_yaml(name: str) -> str:
    return yaml.safe_dump(registry_payloads()[name], sort_keys=False)


def inventory_markdown(payloads: dict[str, dict[str, Any]] | None = None) -> str:
    payloads = payloads or registry_payloads()
    sections = ["# Agentic OS Inventory", "", "Generated from visible capability registries.", ""]
    for registry_name, payload in payloads.items():
        collection = payload.get(registry_name) or []
        title = registry_name.replace("_", " ").title()
        sections.extend([f"## {title}", "", "| ID | Name | Description |", "| --- | --- | --- |"])
        for entry in collection:
            name = entry.get("name") or entry.get("command") or entry.get("id") or ""
            description = entry.get("description") or entry.get("use_when") or ""
            sections.append(f"| `{entry.get('id', '')}` | {name} | {description} |")
        sections.append("")
    return "\n".join(sections).rstrip() + "\n"


def load_registry(path: Path, collection: str) -> list[dict[str, Any]]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        return []
    values = data.get(collection) or []
    return [entry for entry in values if isinstance(entry, dict)]
