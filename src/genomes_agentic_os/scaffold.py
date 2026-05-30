"""Filesystem scaffolding for installed Agentic OS roots."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import shutil

import yaml

from .capability_registry import (
    HARNESS_DIRECTORY,
    REGISTRY_FILES,
    VISIBLE_CAPABILITY_DIRECTORIES,
    hook_entries,
    inventory_markdown,
    registry_file_payloads,
)
from .config_ops import install_config
from .mcp_catalog import mcp_tools_markdown


DEFAULT_DOMAINS = (
    "personal",
    "clarks_consulting",
    "los",
    "archive",
)

ROOT_MARKER_FILENAME = ".agentic_root"
SHARED_FACTORY_DOMAIN = "shared_factory"
# Backward-compatible default for the deprecated --projects-source flag.
DEFAULT_PROJECTS_SOURCE = "~/projects"
SOURCE_PACKAGE_VERSION = "0.1.0"
DEFAULT_UPDATE_CHANNEL = "stable"
DEFAULT_UPDATE_POLICY = "operator_approved"

DOMAIN_ALIASES = {
    "lenders": "los",
}

STANDARD_LANES = (
    "engineering",
    "marketing",
    "sales",
    "support",
    "operations",
    "finance",
    "personal_admin",
    "learning",
)

PROJECT_STATUSES = (
    "active",
    "waiting",
    "blocked",
    "done",
)

PROJECT_CONFIG_FILES = (
    "project-profile.yml",
    "workflows.yml",
    "output-artifacts.yml",
    "validation.yml",
    "worktrees.yml",
    "memory.yml",
    "mcps.yml",
    "tools.yml",
)

CONTROL_PLANE_FILES = (
    "README.md",
    "active-work.md",
    "state-index.md",
    "decisions.md",
    "routing-rules.md",
    "approval-rules.md",
)

INBOX_FILES = (
    "raw-ideas.md",
    "triage.md",
)

KNOWLEDGE_FILES = (
    "source-map.md",
    "glossary.md",
    "memory-policy.md",
)

METRIC_FILES = (
    "baselines.md",
    "scorecards.md",
)

DOMAIN_DIRECTORIES = (
    "00-control-plane",
    "01-inbox",
    "02-projects",
    "03-workflows",
    "04-automations",
    "05-knowledge",
    "06-runs-and-logs",
    "06-runs-and-logs/runs",
    "06-runs-and-logs/failures",
    "07-metrics",
    "08-archive",
)

WORKFLOW_FILES = (
    "workflow.md",
    "outcome-brief.md",
    "alignment-questions.md",
    "prd.md",
    "implementation-plan.md",
    "dispatch-handoff.md",
    "progress.md",
    "quick-reference.md",
    "state-machine.md",
    "context-pack.md",
    "approval-rules.md",
    "output-contract.md",
    "runbook.md",
)

AUTOMATION_FILES = (
    "automation.md",
    "inputs.md",
    "outputs.md",
    "permissions.md",
    "failure-modes.md",
    "runbook.md",
    "tests.md",
)

NAME_PATTERN = re.compile(r"^[a-z0-9_]+$")


@dataclass
class ScaffoldResult:
    created: list[Path] = field(default_factory=list)
    skipped: list[Path] = field(default_factory=list)
    updated: list[Path] = field(default_factory=list)

    def extend(self, other: "ScaffoldResult") -> None:
        self.created.extend(other.created)
        self.skipped.extend(other.skipped)
        self.updated.extend(other.updated)

    def messages(self) -> list[str]:
        lines: list[str] = []
        for label, paths in (
            ("created", self.created),
            ("updated", self.updated),
        ):
            for path in paths:
                lines.append(f"{label}: {path}")
        return lines


def expand_path(path: str | Path) -> Path:
    return Path(path).expanduser().resolve()


def harness_path(root: str | Path, *parts: str) -> Path:
    return expand_path(root) / HARNESS_DIRECTORY / Path(*parts)


def shared_factory_path(root: str | Path, *parts: str) -> Path:
    return harness_path(root, SHARED_FACTORY_DOMAIN, *parts)


def domain_path(root: str | Path, domain: str) -> Path:
    normalized = normalize_domain(domain)
    if normalized == SHARED_FACTORY_DOMAIN:
        return shared_factory_path(root)
    return expand_path(root) / normalized


def validate_name(value: str, label: str = "name") -> str:
    if not NAME_PATTERN.fullmatch(value):
        raise ValueError(f"{label} must use lowercase letters, numbers, and underscores only: {value!r}")
    return value


def normalize_domain(value: str) -> str:
    domain = validate_name(value, "domain")
    return DOMAIN_ALIASES.get(domain, domain)


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def template_source_dir() -> Path:
    candidate = repo_root() / "templates"
    if candidate.is_dir():
        return candidate
    raise FileNotFoundError("Could not find repository templates directory")


def operating_manual_source_dir() -> Path:
    candidate = repo_root() / "operating-manual"
    if candidate.is_dir():
        return candidate
    raise FileNotFoundError("Could not find repository operating-manual directory")


def harness_source_dir() -> Path:
    candidate = repo_root() / "harness"
    if candidate.is_dir():
        return candidate
    raise FileNotFoundError("Could not find repository harness directory")


def plans_source_dir() -> Path:
    candidate = repo_root() / "PLANS"
    if candidate.is_dir():
        return candidate
    raise FileNotFoundError("Could not find repository PLANS directory")


def ensure_dir(path: Path, result: ScaffoldResult) -> None:
    if path.is_dir():
        result.skipped.append(path)
        return
    path.mkdir(parents=True, exist_ok=True)
    result.created.append(path)


def write_file_once(path: Path, content: str, result: ScaffoldResult) -> None:
    if path.exists():
        result.skipped.append(path)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    result.created.append(path)


def ensure_codex_config(root: Path, layer: str, result: ScaffoldResult) -> None:
    config_result = install_config(root, layer=layer, dry_run=False, confirm_conflicts=True)
    result.created.extend(config_result.created)
    result.updated.extend(config_result.updated)
    result.skipped.extend(config_result.skipped)


def root_marker_content(_projects_source: str | Path = DEFAULT_PROJECTS_SOURCE) -> str:
    return f"""# Agentic OS root marker

kind = "genomes_agentic_os_root"
version = "1"
source_package_version = "{SOURCE_PACKAGE_VERSION}"
project_link_scope = "domain_project_src"
harness_entrypoint = "harness/AGENTS.md"
update_channel = "{DEFAULT_UPDATE_CHANNEL}"
update_policy = "{DEFAULT_UPDATE_POLICY}"
update_registry = "harness/registries/updates.yml"
"""


def write_root_marker(root: Path, result: ScaffoldResult, projects_source: str | Path = DEFAULT_PROJECTS_SOURCE) -> None:
    write_file_once(root / ROOT_MARKER_FILENAME, root_marker_content(projects_source), result)


def update_lock_payload() -> dict[str, object]:
    return {
        "schema_version": 1,
        "source_package": "genomes-agentic-os",
        "installed_version": SOURCE_PACKAGE_VERSION,
        "update_channel": DEFAULT_UPDATE_CHANNEL,
        "update_policy": DEFAULT_UPDATE_POLICY,
        "status": "installed",
    }


def update_policy_markdown() -> str:
    return """# Update Policy

Updates are additive by default. Local edits, customer files, prompts, source
code, logs, and secrets are not collected or overwritten by automated update
commands.

## Approval Required

- Executable changes
- Hook changes
- MCP server registration changes
- Rule or permission changes
- Any destructive operation

## Safe Without Additional Approval

- Missing templates
- Missing docs
- Missing registry entries
- Missing command definitions
"""


def updates_registry_payload() -> dict[str, object]:
    return {
        "updates": {
            "installed_version": SOURCE_PACKAGE_VERSION,
            "channel": DEFAULT_UPDATE_CHANNEL,
            "policy": DEFAULT_UPDATE_POLICY,
            "latest_known_version": SOURCE_PACKAGE_VERSION,
            "status_ref": "harness/registries/update-status.yml",
        }
    }


def ensure_update_metadata(root: Path, result: ScaffoldResult) -> None:
    write_file_once(harness_path(root, "agentic-os.lock.json"), json.dumps(update_lock_payload(), indent=2) + "\n", result)
    write_file_once(harness_path(root, "UPDATE_POLICY.md"), update_policy_markdown(), result)
    write_file_once(harness_path(root, "registries", "updates.yml"), yaml.safe_dump(updates_registry_payload(), sort_keys=False), result)


def customer_identity_payload() -> dict[str, object]:
    return {
        "schema_version": 1,
        "install_id": "local",
        "license": {
            "status": "inactive",
            "activated_at": "",
            "key_hash": "",
        },
        "update_grant": {
            "status": "not_registered",
            "path": "harness/registries/update-grant.json",
        },
    }


def backup_policy_payload() -> dict[str, object]:
    return {
        "backup_policy": {
            "enabled": True,
            "include": [
                ".agentic_root",
                "harness/AGENTS.md",
                "harness/ROUTER.md",
                "harness/CONTEXT.md",
                "harness/RULES.md",
                "harness/TOOLS.md",
                "harness/registries/",
                "harness/shared_factory/00-control-plane/",
            ],
            "exclude": [
                "projects/",
                "harness/logs/",
                "harness/security/ssh/*",
                "**/.env",
                "**/*secret*",
                "**/*token*",
            ],
            "remote": {
                "name": "agentic-os-backup",
                "url": "",
            },
        }
    }


def ensure_customer_update_contract(root: Path, result: ScaffoldResult) -> None:
    ensure_dir(harness_path(root, "security"), result)
    ensure_dir(harness_path(root, "security", "ssh"), result)
    ensure_dir(harness_path(root, "logs"), result)
    ensure_dir(harness_path(root, "logs", "updates"), result)
    ensure_dir(harness_path(root, "logs", "backups"), result)
    write_file_once(harness_path(root, "registries", "customer-identity.json"), json.dumps(customer_identity_payload(), indent=2) + "\n", result)
    write_file_once(
        harness_path(root, "registries", "backup-policy.yml"),
        yaml.safe_dump(backup_policy_payload(), sort_keys=False),
        result,
    )


def append_once(path: Path, content: str, result: ScaffoldResult) -> None:
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    if content in existing:
        result.skipped.append(path)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    separator = "" if not existing or existing.endswith("\n") else "\n"
    path.write_text(f"{existing}{separator}{content}", encoding="utf-8")
    result.updated.append(path)


def copy_file(source: Path, destination: Path, result: ScaffoldResult) -> None:
    if destination.exists():
        result.skipped.append(destination)
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    result.created.append(destination)


def copy_file_once(source: Path, destination: Path, result: ScaffoldResult) -> None:
    copy_file(source, destination, result)


def copy_tree(source: Path, destination: Path) -> ScaffoldResult:
    result = ScaffoldResult()
    for item in sorted(source.rglob("*")):
        relative = item.relative_to(source)
        target = destination / relative
        if item.is_dir():
            ensure_dir(target, result)
        else:
            copy_file(item, target, result)
    return result


def copy_tree_missing(source: Path, destination: Path) -> ScaffoldResult:
    return copy_tree(source, destination)


def ensure_visible_capability_directories(root: Path, result: ScaffoldResult) -> None:
    for directory in VISIBLE_CAPABILITY_DIRECTORIES:
        ensure_dir(root / directory, result)


def ensure_capability_registries(root: Path, result: ScaffoldResult) -> None:
    for relative_path, payload in registry_file_payloads().items():
        write_file_once(root / relative_path, yaml.safe_dump(payload, sort_keys=False), result)
    write_file_once(harness_path(root, "INVENTORY.md"), inventory_markdown(), result)


def ensure_visible_capability_surface(root: Path, result: ScaffoldResult) -> None:
    ensure_visible_capability_directories(root, result)
    ensure_capability_registries(root, result)
    hooks_root = harness_source_dir() / "hooks"
    if hooks_root.is_dir():
        result.extend(copy_tree_missing(hooks_root, harness_path(root, "hooks")))


def mirror_visible_commands_and_skills(root: Path) -> ScaffoldResult:
    result = ScaffoldResult()
    harness_root = harness_source_dir()
    result.extend(copy_tree_missing(harness_root / "commands", harness_path(root, "commands")))
    result.extend(copy_tree_missing(harness_root / "skills", harness_path(root, "skills")))
    hooks_root = harness_root / "hooks"
    if hooks_root.is_dir():
        result.extend(copy_tree_missing(hooks_root, harness_path(root, "hooks")))
    return result


def titleize_name(name: str) -> str:
    known_names = {
        "personal": "Personal",
        "clarks_consulting": "Clark's Consulting",
        "los": "LOS",
        "shared_factory": "Shared Factory",
        "archive": "Archive",
    }
    return known_names.get(name, name.replace("_", " ").title())


def domain_purpose(domain: str) -> str:
    purposes = {
        "personal": "Personal administration, household operations, learning, planning, and life logistics.",
        "clarks_consulting": "Client delivery, consulting operations, sales, marketing, and reusable service workflows.",
        "los": "Loan origination system and lender-related product work, support, releases, implementation, and operational knowledge.",
        "shared_factory": "Shared patterns, templates, routers, reusable automations, schemas, and cross-domain tools.",
        "archive": "Inactive work, retired projects, historical runs, and preserved decisions.",
    }
    return purposes.get(domain, "Describe the operating boundary this domain owns.")


def root_readme() -> str:
    domains = "\n".join(f"- `{domain}/` - {domain_purpose(domain)}" for domain in DEFAULT_DOMAINS)
    return f"""# Installed Agentic OS

This is the live operating system root for agentic work. It is domain-first: choose the domain, then use that domain's control plane, inbox, projects, workflows, automations, knowledge, runs, metrics, and archive. OS brains and harness-visible capabilities live under `harness/`.

## Domains

{domains}

## Harness Brain

- `harness/` - root router, tools, commands, skills, hooks, MCP declarations, registries, logs, update metadata, and the shared factory.
- `harness/shared_factory/` - reusable patterns, templates, workflow and automation building blocks, runtime registries, and cross-domain knowledge.

## Standard Domain Shape

Each domain uses the same numbered operating lanes:

- `00-control-plane/` - active work, routing, approvals, and decisions.
- `01-inbox/` - raw capture and triage.
- `02-projects/` - active project folders.
- `03-workflows/` - repeatable human-and-agent workflow specs.
- `04-automations/` - trigger-driven automation specs and logs.
- `05-knowledge/` - source maps, glossary, memory policy, and reference material.
- `06-runs-and-logs/` - execution records, artifacts, failures, and activity logs.
- `07-metrics/` - baselines and scorecards.
- `08-archive/` - closed or inactive material.

## Agent Entry Point

Start with `harness/AGENTS.md`. It tells every harness to read
`ROUTER.md`, `CONTEXT.md`, `RULES.md`, and `TOOLS.md`, route to the narrowest
directory, and repeat the same local read loop before acting.

`CLAUDE.md` is a Claude adapter that includes `AGENTS.md`. `AGENT.md` is not
generated by default; create it only for a compatibility harness that proves it
needs that exact filename.
"""


def root_router() -> str:
    routing_rows = "\n".join(
        f"| `{domain}` | {domain_purpose(domain)} | `{domain}/01-inbox/` |"
        for domain in DEFAULT_DOMAINS
    )
    return f"""# Agent Router

Use this file before touching work inside the installed Agentic OS.
After choosing a domain or narrower layer, change to that directory and read its
`ROUTER.md`, `CONTEXT.md`, `RULES.md`, and `TOOLS.md` before acting.

## Routing Table

| Domain | Use For | Intake Path |
| --- | --- | --- |
{routing_rows}
| `harness/shared_factory` | Shared OS templates, schemas, routers, reusable automations, runtime registries, cross-domain tools, and installed harness capabilities. | `harness/shared_factory/01-inbox/` |

## Domain Classification

- First identify the project, product, client, or life area named in the request.
- Route explicit project or product names to their domain before deciding whether the work is an idea, project, workflow, automation, run, or knowledge update.
- Examples: requests mentioning `LOS`, loan origination, lender operations, or LOS engineering route to `los/`; requests mentioning Clark's Consulting route to `clarks_consulting/`.
- If a request says `add an idea`, `capture an idea`, `idea for`, or similar, route to the matching domain's `01-inbox/` unless the user explicitly asks to create a project, workflow, automation, Jira, or implementation branch.

## Operating Rules

- Pick a domain before creating projects, workflows, automations, or run logs.
- Repeat the route-read-cd loop after changing directories.
- Do not create new root-level work folders for active work.
- Put workflow specs in `<domain>/03-workflows/<lane>/<workflow>/`.
- Put automation specs in `<domain>/04-automations/<lane>/<automation>/`.
- Put execution records in `<domain>/06-runs-and-logs/runs/`.
- Use `harness/shared_factory` for reusable templates, schemas, and cross-domain operating patterns.
- Before non-trivial shell, terminal, package-manager, runtime, or cleanup work, read `harness/shared_factory/05-knowledge/host-tool-registry.<host>.yml` when it exists.
- Use `archive` only for inactive or historical material.

## Standard Lanes

{chr(10).join(f"- `{lane}`" for lane in STANDARD_LANES)}

## Approval Defaults

External writes, customer-visible output, production changes, destructive actions, secrets, billing, and legal records require explicit human approval unless a domain rule narrows the restriction further.
"""


def agent_entrypoint(scope: str = "this Agentic OS layer") -> str:
    return f"""# Agent Entry Point

This is the harness-neutral entry point for {scope}.

## Required Loop

1. Read `ROUTER.md`, `CONTEXT.md`, `RULES.md`, and `TOOLS.md` in this directory.
2. Classify the request against `ROUTER.md`.
3. If the router points to a narrower directory, change to that directory.
4. Repeat the local read and routing loop until no narrower route applies.
5. Act only after loading the final layer's context, rules, and tool registry.
6. Record unclear routes, missing tools, and durable follow-up in the run log or closeout artifact.

## Context Precedence

- User instructions override local defaults.
- Narrower `RULES.md` files override broader rules unless the broader rule is stricter for safety, privacy, production, billing, legal, or customer-visible work.
- `TOOLS.md` is the visible tool contract. Harness-specific install folders only implement that contract.
"""


def claude_adapter() -> str:
    return "@AGENTS.md\n"


def legacy_agent_adapter() -> str:
    return """# Legacy Agent Adapter

Load `AGENTS.md` first, then follow the local route-read-cd loop.
"""


def root_context() -> str:
    domains = "\n".join(f"- `{domain}/` - {domain_purpose(domain)}" for domain in DEFAULT_DOMAINS)
    return f"""# Local Context

This installed harness directory is the entry layer for Genome's Agentic OS runtime. It
routes work into domain rooms, shared factory materials, workflows,
automations, projects, run logs, and archived material.

## Domains

{domains}

## What To Load

| Need | Read First | Read When Needed | Skip By Default |
| --- | --- | --- | --- |
| Route new work | `AGENTS.md`, `ROUTER.md`, `CONTEXT.md`, `RULES.md`, `TOOLS.md` | domain router | unrelated domains |
| Shared template or skill work | `shared_factory/05-knowledge/` index files | relevant template, command, skill, or plan | active domain state |
| Shell or runtime work | host tool registry under `shared_factory/05-knowledge/` | installed command docs | customer data |
| Resume active domain work | routed domain `CONTEXT.md` and active work files | project status, workflow context pack, run logs | unrelated projects |

## Done Means

- Work was routed to the narrowest correct layer.
- Source evidence and validation are recorded.
- Approval gates in `RULES.md` were followed.
- Missing route or tool information was recorded before handoff.
"""


def root_rules() -> str:
    return """# Rules

These root rules apply unless a narrower layer provides a stricter rule.

## Approval Gates

- External writes require explicit approval.
- Customer-visible output requires explicit approval.
- Production changes require explicit approval.
- Destructive actions require explicit approval.
- Secrets, billing, and legal records require explicit approval.

## Operating Rules

- Route before acting.
- Prefer the narrowest applicable domain, project, workflow, automation, or run log.
- Preserve source links and validation evidence.
- Keep secrets out of prompts, logs, docs, generated config, and run artifacts.
- Before non-trivial shell, terminal, package-manager, runtime, or cleanup work, read the host tool registry when it exists.

## Precedence

Narrower rules override broader rules unless the broader rule is stricter for
safety, privacy, production, billing, legal, or customer-visible work.
"""


def root_tools() -> str:
    hooks = "\n".join(
        f"| `{entry['id']}` | {entry['description']} | `{entry.get('source', '')}` |"
        for entry in hook_entries()
    )
    return f"""# Tools

This harness registry names the visible tool surface for the installed Agentic OS.
Folders under `harness/` and config files implement this contract; they are not
the source of truth by themselves.

## Skills

| Skill | Use When | Source |
| --- | --- | --- |
| `os-navigator` | Route work through installed OS rooms. | `shared_factory/05-knowledge/skills/os-navigator/` |
| `workflow-builder` | Create or improve reusable workflows. | `shared_factory/05-knowledge/skills/workflow-builder/` |
| `automation-qualifier` | Decide whether a process is safe to automate. | `shared_factory/05-knowledge/skills/automation-qualifier/` |
| `os-doctor` | Audit installed OS structure and contracts. | `shared_factory/05-knowledge/skills/os-doctor/` |

## Commands

| Command | Use When | Notes |
| --- | --- | --- |
| `/make-skill` | Create or improve a reusable skill. | Declared in `registries/commands.yml`. |
| `/make-domain` | Create a routed OS domain or room. | Declared in `registries/commands.yml`. |
| `/make-automation` | Create a guarded automation spec. | Declared in `registries/commands.yml`. |
| `/make-workflow` | Create a reusable workflow contract. | Declared in `registries/commands.yml`. |
| `/orchestrate` | Decompose, delegate, verify, and merge feature work. | Declared in `registries/commands.yml`. |
| `agentic-os validate` | Validate the installed root. | Run before handoff after structural changes. |
| `agentic-os route` | Route a request to a domain or workflow. | Use before creating new work. |
| `agentic-os context build` | Build a deterministic context packet. | Use for handoffs and repeatable runs. |
| `agentic-os project onboard` | Create or repair a project-local agent/config surface. | Additive by default. |
| `agentic-os project worktree add` | Register a visible worktree link inside a project. | Keeps the real checkout outside the OS. |
| `agentic-os config doctor` | Check Codex config contracts. | Does not store secrets. |
| `agentic-os config install-tree` | Install Codex config across routed OS layers. | Dry-run by default. |

## MCP Servers

{mcp_tools_markdown()}

## Plugins And Libraries

| Name | Use When | Notes |
| --- | --- | --- |
|  |  |  |

## Local Wrappers

| Wrapper | Use When | Path |
| --- | --- | --- |
| host tool registry | Shell, terminal, runtime, package-manager, and cleanup work. | `shared_factory/05-knowledge/host-tool-registry.<host>.yml` |

## Hooks

| Hook | Use When | Source |
| --- | --- | --- |
{hooks}

## When To Use What

- Use skills for repeatable agent workflows.
- Use commands for deterministic filesystem or runtime operations.
- Use MCP servers only when the current layer's rules and source boundaries allow them.

## Missing Or Disabled

| Capability | Needed For | Status |
| --- | --- | --- |
|  |  |  |
"""


def domain_config(domain: str) -> str:
    lanes = "\n".join(f"  - {lane}" for lane in STANDARD_LANES)
    return f"""id: {domain}
name: {titleize_name(domain)}
owner: OS Owner
status: active

purpose: >
  {domain_purpose(domain)}

lanes:
{lanes}

directories:
  control_plane: 00-control-plane
  inbox: 01-inbox
  projects: 02-projects
  workflows: 03-workflows
  automations: 04-automations
  knowledge: 05-knowledge
  runs_and_logs: 06-runs-and-logs
  metrics: 07-metrics
  archive: 08-archive

source_systems:
  - name: Notion
    role: control_plane
    url: ""
  - name: GitHub
    role: code_and_prs
    url: ""

approval_policy:
  external_writes_require_approval: true
  customer_visible_output_requires_approval: true
  production_changes_require_approval: true
  destructive_actions_require_approval: true

notion:
  domain_home_page_id: ""
  inbox_database_id: ""
  work_items_database_id: ""
  runs_database_id: ""
  approvals_database_id: ""

storage:
  active_state: filesystem
  artifacts: filesystem
  cockpit: notion
  memory: agent_memory

context_loading:
  map_file: ROUTER.md
  room_file: CONTEXT.md
  rules_file: RULES.md
  tools_file: TOOLS.md
  reference_file: REFERENCES.md
  default_rule: read the map, context, rules, and tools first, then load only task-specific references
  skip_by_default:
    - unrelated domains
    - unrelated projects
    - workflow internals unless running that workflow
    - automation logs unless reviewing that automation
"""


def domain_readme(domain: str) -> str:
    display_name = titleize_name(domain)
    return f"""# {display_name}

## Purpose

{domain_purpose(domain)}

## Context Files

- `CONTEXT.md` defines how this domain works and what good output looks like.
- `RULES.md` defines safety, approval, and local operating constraints.
- `TOOLS.md` lists intended local and inherited skills, commands, MCP servers, plugins, and wrappers.
- `REFERENCES.md` points to source systems, docs, repos, tools, and recurring examples.

## Active Outcomes

-

## Main Systems

| System | Role | Link |
| --- | --- | --- |
| Notion | Control plane |  |
| GitHub | Code and pull requests |  |

## Repositories / Notion / Jira

- Repositories:
- Notion:
- Jira:

## Approval Rules

See `00-control-plane/approval-rules.md`.

## Sensitive Data Rules

- Record what can be read.
- Record what can be written.
- Require approval for external writes, production changes, secrets, billing, and legal records.

## Common Workflows

Workflows live under `03-workflows/<lane>/<workflow>/`.

## Active Automations

Automations live under `04-automations/<lane>/<automation>/`.

## Source Map

See `05-knowledge/source-map.md`.

## Current Risks

-
"""


def domain_router(domain: str) -> str:
    display_name = titleize_name(domain)
    return f"""# Agent Router: {display_name}

## First Decision

Classify the request into one of this domain's operating lanes, then choose the narrowest matching project, workflow, or automation.

## Where To Put Work

| Work Type | Path |
| --- | --- |
| Idea spec or rough idea capture | `01-inbox/<idea-slug>.md` |
| Raw capture | `01-inbox/raw-ideas.md` |
| Triage notes | `01-inbox/triage.md` |
| Domain context | `CONTEXT.md` |
| Domain references | `REFERENCES.md` |
| Active project | `02-projects/<project>/` |
| Workflow spec | `03-workflows/<lane>/<workflow>/workflow.md` |
| Automation spec | `04-automations/<lane>/<automation>/automation.md` |
| Knowledge | `05-knowledge/` |
| Run log | `06-runs-and-logs/runs/<run-id>/run-log.md` |
| Failure record | `06-runs-and-logs/failures/` |
| Metrics | `07-metrics/` |
| Archive | `08-archive/` |

## Routing Rules

- Read `AGENTS.md`, then `ROUTER.md`, `CONTEXT.md`, `RULES.md`, and `TOOLS.md`.
- If the prompt says `add an idea`, `capture an idea`, `idea for`, `rough idea`, or similar, write the idea to `01-inbox/` first. Do not route it directly to `02-projects`, `03-workflows`, `04-automations`, Jira, or a code repository unless the user explicitly asks for that escalation.
- Treat ideas as pre-routing inputs. A systems idea is different from a code feature, Jira implementation task, or active project.
- If a project, workflow, automation, or run-log directory narrows the route, change there and repeat the local context-file load before acting.
- Read `00-control-plane/routing-rules.md` before creating a new workflow or automation.
- Read `CONTEXT.md`, `RULES.md`, `TOOLS.md`, and `REFERENCES.md` before doing domain-specific work.
- Use `03-workflows` when judgment, context assembly, or approval gates are central.
- Use `04-automations` when a trigger can safely run a repeatable action with declared permissions.
- Use `shared_factory` when a pattern should be reused by multiple domains.

## Context Loading

| Need | Load | Skip By Default |
| --- | --- | --- |
| Understand the room | `CONTEXT.md`, `domain.yml` | Other domains |
| Find source truth | `REFERENCES.md`, `05-knowledge/source-map.md` | Full private docs unless needed |
| Resume active work | `00-control-plane/active-work.md`, matching project status | Unrelated project folders |
| Run a workflow | Matching workflow `quick-reference.md`, `context-pack.md`, `runbook.md` | Automation logs |
| Review an automation | Matching automation spec, permissions, tests, logs | Workflow internals outside the linked process |

## Approval Rules

- Follow `00-control-plane/approval-rules.md`.
- Escalate before external writes, customer-visible output, production changes, destructive actions, secrets, billing, and legal records.
- Write a run log before ending any non-trivial execution.
"""


def domain_context(domain: str) -> str:
    display_name = titleize_name(domain)
    return f"""# Context: {display_name}

This file teaches agents how work inside `{domain}` should be understood before they execute a task. Treat this domain as a room: load the room guide, route to the right object, then read only the sources the task requires.

## Purpose

{domain_purpose(domain)}

## Inputs

- Raw requests, notes, tickets, messages, or ideas.
- Existing project state under `02-projects/`.
- Workflow and automation specs under `03-workflows/` and `04-automations/`.
- Source systems listed in `REFERENCES.md` and `05-knowledge/source-map.md`.

## Process

1. Read `ROUTER.md`, this file, `RULES.md`, `TOOLS.md`, and the matching row in `## What To Load`.
2. Check `00-control-plane/active-work.md` before creating new work.
3. Reuse an existing project, workflow, automation, or run log when one fits.
4. Read only the references required for the routed task.
5. Record validation, next action, and durable learning before ending.
6. When a new idea, workflow opportunity, automation state, project feature, bug fix, or research thread appears, update `00-control-plane/state-index.md` and `MEMORY.md`.

## Output Folders

- `00-control-plane/` - routing, approvals, active work, and decisions.
- `01-inbox/` - untriaged capture and routing notes.
- `02-projects/` - project-specific state, source maps, status, and artifacts.
- `03-workflows/` - repeatable judgment-heavy processes.
- `04-automations/` - triggerable processes with declared permissions and logs.
- `05-knowledge/` - source maps, glossary, memory policy, and reference material.
- `06-runs-and-logs/` - execution records, failures, and activity history.
- `07-metrics/` - baselines and scorecards.
- `08-archive/` - inactive or historical material.

## What To Load

| Task Type | Read First | Read When Needed | Do Not Load By Default | Output Path |
| --- | --- | --- | --- | --- |
| Raw capture | `01-inbox/raw-ideas.md` | `REFERENCES.md` | workflow internals | `01-inbox/raw-ideas.md` |
| Route work | `ROUTER.md`, `00-control-plane/routing-rules.md` | `00-control-plane/active-work.md` | unrelated domain folders | `01-inbox/triage.md` or target object |
| Project work | `02-projects/<project>/status.md`, `source-map.md` | linked repo, linked Notion/Jira | unrelated projects | `02-projects/<project>/` |
| Workflow run | `03-workflows/<lane>/<workflow>/quick-reference.md`, `context-pack.md` | runbook, examples, source maps | automations unless the workflow says so | `06-runs-and-logs/runs/` |
| Automation review | `04-automations/<lane>/<automation>/automation.md`, `permissions.md` | tests, logs, failure modes | unrelated workflows | `04-automations/<lane>/<automation>/` |

## Tools And Skills

| Tool Or Skill | Use When | Notes |
| --- | --- | --- |
|  |  |  |

## Done Means

- It routes work to the correct project, workflow, automation, or run log.
- It preserves source links and evidence.
- It follows approval rules before external, production, destructive, billing, legal, or customer-visible action.
- It updates active state or records a next action before the session ends.

## Standing Context

- Main people:
- Main systems:
- Main repositories:
- Main Notion pages:
- Main Jira or issue trackers:

## Work Style

- Preferred level of detail:
- Required terminology:
- Formatting expectations:
- Things to avoid:

## Common Tasks

| Task Type | Route | Read First | Output |
| --- | --- | --- | --- |
|  |  |  |  |

## Update Rule

Update this file when a stable domain rule, source system, work style preference, routing pattern, tool trigger, or repeated failure mode becomes durable.
"""


def domain_rules(domain: str) -> str:
    display_name = titleize_name(domain)
    return f"""# Rules: {display_name}

These rules apply to work routed into `{domain}` unless a narrower project,
workflow, or automation defines a stricter rule.

## Approval Gates

- External writes require explicit approval.
- Customer-visible output requires explicit approval.
- Production changes require explicit approval.
- Destructive actions require explicit approval.
- Secrets, billing, and legal records require explicit approval.

## Operating Rules

- Read `ROUTER.md`, `CONTEXT.md`, `RULES.md`, and `TOOLS.md` before acting in this domain.
- Check `00-control-plane/active-work.md` before creating new active work.
- Keep `00-control-plane/state-index.md` current for ideas, workflow opportunities, automation states, project features, bug fixes, and research threads.
- Update `MEMORY.md` for durable, non-secret routing and operating learnings.
- Record material execution in `06-runs-and-logs/`.
- Preserve source links and validation evidence.
- Keep secrets out of run logs, docs, prompts, and generated config.

## Precedence

Narrower rules override these rules unless this file is stricter for safety,
privacy, production, billing, legal, or customer-visible work.
"""


def domain_tools(domain: str, *, public_customer: bool = False) -> str:
    display_name = titleize_name(domain)
    mcp_markdown = mcp_tools_markdown(domain, include_inactive=not public_customer, public_customer=public_customer)
    return f"""# Tools: {display_name}

This registry names the intended skills, commands, MCP servers, plugins,
libraries, and wrappers for `{domain}`.

## Skills

| Skill | Use When | Source |
| --- | --- | --- |
| `os-navigator` | Route domain work to the correct project, workflow, automation, or run log. | inherited from `harness/shared_factory` |
| `workflow-builder` | Create or refine repeatable workflows. | inherited from `harness/shared_factory` |
| `automation-qualifier` | Decide whether a repeatable process should become an automation. | inherited from `harness/shared_factory` |

## Commands

| Command | Use When | Notes |
| --- | --- | --- |
| `agentic-os project create` | Create a domain project. | Use after checking active work. |
| `agentic-os workflow create` | Create a reusable workflow. | Use when the pattern should repeat. |
| `agentic-os automation create` | Create a guarded automation spec. | Start in observe or prepare mode. |
| `agentic-os validate` | Validate domain and root structure. | Run before handoff after structural changes. |

## MCP Servers

{mcp_markdown}

## Plugins And Libraries

| Name | Use When | Notes |
| --- | --- | --- |
|  |  |  |

## Local Wrappers

| Wrapper | Use When | Path |
| --- | --- | --- |
|  |  |  |

## Missing Or Disabled

| Capability | Needed For | Status |
| --- | --- | --- |
|  |  |  |
"""


def domain_references(domain: str) -> str:
    display_name = titleize_name(domain)
    return f"""# References: {display_name}

Use this file as the domain's durable source map. Link to the source; do not paste whole private documents unless they are intentionally part of this OS.

## Source Systems

| Source | Location | What It Contains | When To Use |
| --- | --- | --- | --- |
| Notion |  | Control plane, docs, status |  |
| GitHub |  | Repositories, PRs, issues |  |
| Local files |  | Working artifacts and installed OS state |  |

## Example Outputs

| Example | Location | Why It Is Useful |
| --- | --- | --- |
|  |  |  |

## Reusable Prompts Or Briefs

| Name | Location | Use For |
| --- | --- | --- |
|  |  |  |

## Known Gaps

-
"""


def control_file_content(domain: str, filename: str) -> str:
    display_name = titleize_name(domain)
    headings = {
        "README.md": f"""# {display_name} Control Plane

This folder owns routing, approvals, active work, and durable decisions for `{domain}`.
""",
        "active-work.md": f"""# Active Work: {display_name}

| Work | Status | Owner | Next Action | Link |
| --- | --- | --- | --- | --- |
""",
        "state-index.md": f"""# State Index: {display_name}

Use this file as the domain control-plane ledger. Update it whenever an idea is captured, a workflow opportunity appears, an automation is running or disabled, a project feature or bug changes state, or research starts or closes.

## Ideas

| Date | Item | Status | Link | Notes |
| --- | --- | --- | --- | --- |

## Workflow Opportunities

| Date | Workflow Or Pattern | Status | Link | Notes |
| --- | --- | --- | --- | --- |

## Automation Status

| Date | Automation | Status | Link | Notes |
| --- | --- | --- | --- | --- |

## Project Activity

| Date | Project Or Work | Status | Link | Notes |
| --- | --- | --- | --- | --- |

## Research

| Date | Topic | Status | Link | Notes |
| --- | --- | --- | --- | --- |
""",
        "decisions.md": f"""# Decisions: {display_name}

| Date | Decision | Why | Impact | Link |
| --- | --- | --- | --- | --- |
""",
        "routing-rules.md": f"""# Routing Rules: {display_name}

## Default Route

1. Identify the domain.
2. If the request is an idea capture, write it to `01-inbox/` before routing it further.
3. Identify the lane.
4. Check active projects.
5. Reuse an existing workflow or automation when one fits.
6. Create a new workflow only when the process should be repeated.

## Idea Capture

- Treat `add an idea`, `capture an idea`, `idea for`, `rough idea`, and similar phrasing as inbox work.
- Keep the first artifact in `01-inbox/` as a markdown idea/spec unless the user asks for a table-only capture.
- Do not promote an idea into a project, workflow, automation, Jira, or repository feature until the user asks to route or escalate it.
- When capturing an idea, update `01-inbox/raw-ideas.md`, `01-inbox/triage.md`, `00-control-plane/state-index.md`, and `MEMORY.md` in the same pass.

## Control-Plane Writeback

- Update `00-control-plane/state-index.md` for ideas, workflow opportunities, automation enabled/disabled/running states, project features, bug fixes, and research.
- Update `00-control-plane/active-work.md` when work is active, waiting, blocked, or ready for owner review.
- Update `MEMORY.md` for durable, non-secret routing decisions, repeated patterns, source maps, and stable project/domain learnings.

## Lane Hints

{chr(10).join(f"- `{lane}` -" for lane in STANDARD_LANES)}
""",
        "approval-rules.md": f"""# Approval Rules: {display_name}

## Default Rule

External writes, customer-visible output, production changes, destructive actions, secrets, billing, and legal records require explicit human approval.

## Approval Matrix

| Action | Approval Required | Approver | Notes |
| --- | --- | --- | --- |
| Read source systems | no |  |  |
| Draft internal summary | no |  |  |
| Create internal work item | no |  |  |
| Send external message | yes |  |  |
| Comment on customer-visible ticket | yes |  |  |
| Merge PR | yes |  |  |
| Deploy production change | yes |  |  |

## Never Allowed Without Explicit Human Instruction

- Delete customer data.
- Rotate or expose secrets.
- Merge or deploy production code.
- Send customer-visible messages.
- Modify billing or legal records.
""",
    }
    return headings[filename]


def inbox_file_content(domain: str, filename: str) -> str:
    display_name = titleize_name(domain)
    if filename == "raw-ideas.md":
        return f"""# Raw Ideas: {display_name}

Capture untriaged ideas, notes, messages, and prompts here before routing them.

| Date | Source | Raw Input | Next Step |
| --- | --- | --- | --- |
"""
    return f"""# Triage: {display_name}

| Date | Input | Domain | Lane | Intent | Risk | Confidence | Routed To |
| --- | --- | --- | --- | --- | --- | --- | --- |
"""


def knowledge_file_content(domain: str, filename: str) -> str:
    display_name = titleize_name(domain)
    if filename == "source-map.md":
        return f"""# Source Map: {display_name}

| Source | Location | Purpose | Owner | Notes |
| --- | --- | --- | --- | --- |
| Notion |  | Control plane |  |  |
| GitHub |  | Source and PRs |  |  |
| Local files |  | Working artifacts |  |  |
"""
    if filename == "glossary.md":
        return f"""# Glossary: {display_name}

| Term | Meaning | Source |
| --- | --- | --- |
"""
    return f"""# Memory Policy: {display_name}

## Record In Memory

- Durable preferences.
- Repeated workflow decisions.
- Stable source maps.

## Do Not Record In Memory

- Secrets.
- Temporary credentials.
- Sensitive customer data unless explicitly approved and sanitized.

## Refresh Rules

- Verify drift-prone facts before acting.
- Cite source files, tickets, pages, or run logs when recording durable facts.
"""


def metric_file_content(domain: str, filename: str) -> str:
    display_name = titleize_name(domain)
    if filename == "baselines.md":
        return f"""# Baselines: {display_name}

| Metric | Current Baseline | Source | Date |
| --- | --- | --- | --- |
"""
    return f"""# Scorecards: {display_name}

| Period | Workflow / Automation | Result | Notes |
| --- | --- | --- | --- |
"""


def workflows_readme(domain: str) -> str:
    return f"""# Workflows: {titleize_name(domain)}

Workflow specs live here when the work needs judgment, context assembly, validation, or approval gates.

## Lane Directories

{chr(10).join(f"- `{lane}/`" for lane in STANDARD_LANES)}

## Workflow Folder Format

```text
<lane>/<workflow>/
  workflow.md
  outcome-brief.md
  alignment-questions.md
  prd.md
  implementation-plan.md
  dispatch-handoff.md
  progress.md
  quick-reference.md
  state-machine.md
  context-pack.md
  approval-rules.md
  output-contract.md
  runbook.md
  examples/
  runs/
```

## Creation Rule

Use `agentic-os workflow create {domain} <lane> <workflow> --root ~/agentic_os`.
"""


def workflow_lane_readme(domain: str, lane: str) -> str:
    return f"""# Workflow Lane: {lane}

## Domain

`{domain}`

## Purpose

Create reusable workflow folders here for `{lane}` work inside `{domain}`.

## Workflow Folder Format

```text
<workflow>/
  workflow.md
  outcome-brief.md
  alignment-questions.md
  prd.md
  implementation-plan.md
  dispatch-handoff.md
  progress.md
  quick-reference.md
  state-machine.md
  context-pack.md
  approval-rules.md
  output-contract.md
  runbook.md
  examples/
  runs/
```

## Routing Rule

If the work can be repeated and still needs judgment, create a workflow. If the trigger and action are stable enough to run unattended, create an automation under `04-automations/{lane}/`.
"""


def automations_readme(domain: str) -> str:
    return f"""# Automations: {titleize_name(domain)}

Automation specs live here when a trigger can safely run a guarded process with declared permissions, idempotency, logs, and approval gates.

## Lane Directories

{chr(10).join(f"- `{lane}/`" for lane in STANDARD_LANES)}

## Automation Folder Format

```text
<lane>/<automation>/
  automation.md
  inputs.md
  outputs.md
  permissions.md
  failure-modes.md
  runbook.md
  tests.md
  logs/
```

## Creation Rule

Use `agentic-os automation create {domain} <lane> <automation> --root ~/agentic_os`.
"""


def automation_lane_readme(domain: str, lane: str) -> str:
    return f"""# Automation Lane: {lane}

## Domain

`{domain}`

## Purpose

Create guarded automation folders here for `{lane}` work inside `{domain}`.

## Automation Folder Format

```text
<automation>/
  automation.md
  inputs.md
  outputs.md
  permissions.md
  failure-modes.md
  runbook.md
  tests.md
  logs/
```

## Safety Rule

Start automations at `observe` or `prepare`. External writes, customer-visible output, production changes, destructive actions, secrets, billing, and legal records require approval.
"""


def runs_readme(domain: str) -> str:
    return f"""# Runs: {titleize_name(domain)}

Each folder records one workflow, automation, or skill execution.

## Run Folder Format

```text
<run-id>/
  run-log.md
  artifacts/
```

## Required Run Evidence

- Input reference.
- Context loaded.
- Actions taken.
- Validation performed.
- Artifacts created or changed.
- Final state and next action.
"""


def failures_readme(domain: str) -> str:
    return f"""# Failures: {titleize_name(domain)}

Use this folder for failed runs, recovery notes, and repeated failure modes that need redesign.

## Failure Record Format

```text
<date>-<short-name>.md
```

Each record should include the source run, failure mode, impact, attempted recovery, and next action.
"""


def simple_readme(title: str, body: str) -> str:
    return f"# {title}\n\n{body}\n"


def render_template(content: str, replacements: dict[str, str]) -> str:
    for key, value in replacements.items():
        content = content.replace(key, value)
    return content


def ensure_root_files(
    root: Path,
    result: ScaffoldResult,
    projects_source: str | Path = DEFAULT_PROJECTS_SOURCE,
    *,
    include_legacy_agent: bool = False,
) -> None:
    ensure_dir(root, result)
    write_root_marker(root, result, projects_source)
    ensure_dir(harness_path(root), result)
    ensure_visible_capability_surface(root, result)
    ensure_update_metadata(root, result)
    ensure_customer_update_contract(root, result)
    harness_root = harness_path(root)
    write_file_once(harness_root / "README.md", root_readme(), result)
    router = root_router()
    write_file_once(harness_root / "ROUTER.md", router, result)
    write_file_once(harness_root / "AGENTS.md", agent_entrypoint("the installed Agentic OS root harness"), result)
    write_file_once(harness_root / "CLAUDE.md", claude_adapter(), result)
    write_file_once(harness_root / "CONTEXT.md", root_context(), result)
    write_file_once(harness_root / "RULES.md", root_rules(), result)
    write_file_once(harness_root / "TOOLS.md", root_tools(), result)
    if include_legacy_agent:
        write_file_once(harness_root / "AGENT.md", legacy_agent_adapter(), result)
    ensure_codex_config(harness_root, "agentic_os_root", result)


def create_domain_structure(
    os_root: Path,
    domain: str,
    result: ScaffoldResult,
    *,
    include_legacy_agent: bool = False,
    public_customer_tools: bool = False,
) -> None:
    domain = validate_name(domain, "domain")
    domain_root = domain_path(os_root, domain)
    ensure_dir(domain_root, result)
    write_file_once(domain_root / "README.md", domain_readme(domain), result)
    router = domain_router(domain)
    write_file_once(domain_root / "ROUTER.md", router, result)
    write_file_once(domain_root / "AGENTS.md", agent_entrypoint(f"the `{domain}` domain"), result)
    write_file_once(domain_root / "CLAUDE.md", claude_adapter(), result)
    write_file_once(domain_root / "CONTEXT.md", domain_context(domain), result)
    write_file_once(domain_root / "RULES.md", domain_rules(domain), result)
    write_file_once(domain_root / "TOOLS.md", domain_tools(domain, public_customer=public_customer_tools), result)
    if include_legacy_agent:
        write_file_once(domain_root / "AGENT.md", legacy_agent_adapter(), result)
    write_file_once(domain_root / "REFERENCES.md", domain_references(domain), result)
    write_file_once(domain_root / "domain.yml", domain_config(domain), result)
    ensure_codex_config(domain_root, "domain_or_lane", result)

    for directory in DOMAIN_DIRECTORIES:
        ensure_dir(domain_root / directory, result)

    for filename in CONTROL_PLANE_FILES:
        write_file_once(domain_root / "00-control-plane" / filename, control_file_content(domain, filename), result)

    for filename in INBOX_FILES:
        write_file_once(domain_root / "01-inbox" / filename, inbox_file_content(domain, filename), result)

    write_file_once(
        domain_root / "02-projects" / "README.md",
        simple_readme(
            f"Projects: {titleize_name(domain)}",
            "Create one folder per active project. Project folders should link back to workflows, automations, source systems, and run logs.",
        ),
        result,
    )

    write_file_once(domain_root / "03-workflows" / "README.md", workflows_readme(domain), result)
    write_file_once(domain_root / "04-automations" / "README.md", automations_readme(domain), result)

    for lane in STANDARD_LANES:
        ensure_dir(domain_root / "03-workflows" / lane, result)
        ensure_dir(domain_root / "04-automations" / lane, result)
        write_file_once(domain_root / "03-workflows" / lane / "README.md", workflow_lane_readme(domain, lane), result)
        write_file_once(domain_root / "04-automations" / lane / "README.md", automation_lane_readme(domain, lane), result)

    for filename in KNOWLEDGE_FILES:
        write_file_once(domain_root / "05-knowledge" / filename, knowledge_file_content(domain, filename), result)

    write_file_once(
        domain_root / "06-runs-and-logs" / "activity-log.md",
        simple_readme(
            f"Activity Log: {titleize_name(domain)}",
            "| Date | Actor | Action | Result | Link |\n| --- | --- | --- | --- | --- |",
        ),
        result,
    )
    write_file_once(domain_root / "06-runs-and-logs" / "runs" / "README.md", runs_readme(domain), result)
    write_file_once(domain_root / "06-runs-and-logs" / "failures" / "README.md", failures_readme(domain), result)

    for filename in METRIC_FILES:
        write_file_once(domain_root / "07-metrics" / filename, metric_file_content(domain, filename), result)

    write_file_once(
        domain_root / "08-archive" / "README.md",
        simple_readme(
            f"Archive: {titleize_name(domain)}",
            "Move inactive or historical material here when it should no longer appear in active routing.",
        ),
        result,
    )


def ensure_default_domains(os_root: Path, result: ScaffoldResult, *, include_legacy_agent: bool = False) -> None:
    for domain in DEFAULT_DOMAINS:
        create_domain_structure(os_root, domain, result, include_legacy_agent=include_legacy_agent)
    create_domain_structure(os_root, SHARED_FACTORY_DOMAIN, result, include_legacy_agent=include_legacy_agent)
    result.extend(copy_tree_missing(template_source_dir(), shared_factory_path(os_root, "05-knowledge", "templates")))
    result.extend(install_docs(os_root))


def init_os(
    target: str | Path,
    *,
    projects_source: str | Path = DEFAULT_PROJECTS_SOURCE,
    include_legacy_agent: bool = False,
) -> ScaffoldResult:
    root = expand_path(target)
    result = ScaffoldResult()
    ensure_root_files(root, result, projects_source, include_legacy_agent=include_legacy_agent)
    ensure_default_domains(root, result, include_legacy_agent=include_legacy_agent)
    return result


def install_docs(root: str | Path) -> ScaffoldResult:
    os_root = expand_path(root)
    result = ScaffoldResult()
    result.extend(mirror_visible_commands_and_skills(os_root))
    result.extend(
        copy_tree(
            template_source_dir(),
            shared_factory_path(os_root, "05-knowledge", "templates"),
        )
    )
    result.extend(
        copy_tree(
            operating_manual_source_dir(),
            shared_factory_path(os_root, "05-knowledge", "operating-manual"),
        )
    )
    result.extend(
        copy_tree(
            harness_source_dir() / "commands",
            shared_factory_path(os_root, "05-knowledge", "commands"),
        )
    )
    result.extend(
        copy_tree(
            harness_source_dir() / "skills",
            shared_factory_path(os_root, "05-knowledge", "skills"),
        )
    )
    hooks_root = harness_source_dir() / "hooks"
    if hooks_root.is_dir():
        result.extend(
            copy_tree(
                hooks_root,
                shared_factory_path(os_root, "05-knowledge", "hooks"),
            )
        )
    result.extend(
        copy_tree(
            plans_source_dir(),
            shared_factory_path(os_root, "05-knowledge", "plans"),
        )
    )
    result.extend(
        copy_tree(
            template_source_dir() / "reference",
            shared_factory_path(os_root, "05-knowledge", "references"),
        )
    )
    return result


def create_domain(root: str | Path, domain: str, *, include_legacy_agent: bool = False) -> ScaffoldResult:
    domain = normalize_domain(domain)
    os_root = expand_path(root)
    result = init_os(os_root, include_legacy_agent=include_legacy_agent)
    if domain not in DEFAULT_DOMAINS:
        create_domain_structure(os_root, domain, result, include_legacy_agent=include_legacy_agent)
    return result


def project_readme(domain: str, project: str, status: str, lane: str | None) -> str:
    lane_label = lane or ""
    return f"""# Project: {project}

## Metadata

| Field | Value |
| --- | --- |
| Domain | `{domain}` |
| Status | `{status}` |
| Lane | `{lane_label}` |

## Purpose

Describe the project outcome, boundaries, source systems, and active workflows.

## Start Here

- `status.md` records current state and next action.
- `source-map.md` records repos, Notion pages, Jira projects, and other source links.
- `src/` points to the local repository when `--repo` is a local path.
- `decisions.md` records durable project decisions.
- `artifacts/` stores project-specific outputs that do not belong in a workflow run.
"""


def project_config(
    domain: str,
    project: str,
    status: str,
    lane: str | None,
    repo: str | None,
    notion: str | None,
    jira: str | None,
) -> str:
    return f"""id: {project}
name: {project}
domain: {domain}
status: {status}
lane: {lane or ""}

sources:
  repo: {repo or ""}
  notion: {notion or ""}
  jira: {jira or ""}

routing:
  project_root: 02-projects/{project}
  status_file: status.md
  source_map: source-map.md
  decisions: decisions.md
"""


def project_status(project: str, status: str) -> str:
    return f"""# Status: {project}

| Field | Value |
| --- | --- |
| Status | `{status}` |
| Owner | OS Owner |
| Next Action |  |

## Current State

-

## Recent Activity

| Date | Update | Link |
| --- | --- | --- |
"""


def project_decisions(project: str) -> str:
    return f"""# Decisions: {project}

| Date | Decision | Why | Impact | Link |
| --- | --- | --- | --- | --- |
"""


def project_source_map(project: str, repo: str | None, notion: str | None, jira: str | None) -> str:
    rows = ["| Source | Location | Purpose | Notes |", "| --- | --- | --- | --- |"]
    if repo:
        rows.append(f"| Repo | {repo} | Code and working tree |  |")
    if notion:
        rows.append(f"| Notion | {notion} | Control plane or docs |  |")
    if jira:
        rows.append(f"| Jira | {jira} | Issues, roadmap, or delivery tracking |  |")
    if len(rows) == 2:
        rows.append("|  |  |  |  |")
    return f"""# Source Map: {project}

{chr(10).join(rows)}
"""


def project_agents(domain: str, project: str) -> str:
    return f"""# Agent Entry Point: {project}

This is the project-local entrypoint for `{domain}/02-projects/{project}`.

## Required Loop

1. Read `ROUTER.md`, `CONTEXT.md`, `RULES.md`, `TOOLS.md`, `project.yml`, and `config/*.yml`.
2. Decide whether the request belongs in project state, `src/`, a registered worktree, `ideas/`, or `artifacts/`.
3. If source work is required, use `src/` for the canonical checkout or `worktrees/<name>` for an active branch-specific checkout.
4. Follow local `RULES.md` and tool boundaries before touching source files.
5. Record durable ideas in `ideas/`, outputs in `artifacts/`, and execution evidence in the domain run log.

## Source Priority

- `project.yml` and `source-map.md` identify the project and canonical sources.
- `config/output-artifacts.yml` declares feature artifact roots such as `src/.features/{{ticket_or_slug}}`.
- `worktrees/index.yml` lists visible worktrees and their real filesystem targets.
"""


def project_router(domain: str, project: str) -> str:
    return f"""# Agent Router: {project}

Route project work to the narrowest local surface before acting.

| Request Type | Route |
| --- | --- |
| New idea, product thought, rough note | `ideas/raw-ideas.md` |
| Project status or next action | `status.md` |
| Source map, repo, Notion, Jira, or MCP setup | `source-map.md` and `config/*.yml` |
| Feature implementation | `src/` or a registered `worktrees/<name>` link |
| Feature artifact or generated output | `artifacts/` or configured source artifact root |
| Durable decision | `decisions.md` |

## Worktree Rule

Use `worktrees/index.yml` before assuming where active branch checkouts live.
Register visible worktrees with `agentic-os project worktree add {domain} {project} <name> --path <path>`.
"""


def project_context(domain: str, project: str) -> str:
    return f"""# Context: {project}

This project layer is the operating surface for `{domain}/02-projects/{project}`.
It connects project state, source links, worktrees, ideas, output artifacts, and local rules.

## Load Order

1. `project.yml`
2. `source-map.md`
3. `config/project-profile.yml`
4. `config/workflows.yml`, `config/output-artifacts.yml`, and `config/validation.yml`
5. `worktrees/index.yml` when source work may use a branch checkout

## Markdown vs YAML

- Markdown files explain intent, decisions, source maps, and human-readable context.
- YAML files under `config/` are for parsed defaults, paths, validation commands, MCP boundaries, and tool declarations.
- Use Markdown with YAML front matter for hybrid specs, ideas, and ticket drafts when both narrative and machine-readable metadata are needed.
"""


def project_rules(domain: str, project: str) -> str:
    return f"""# Rules: {project}

These rules apply to `{domain}/02-projects/{project}` unless a narrower source
checkout or feature artifact defines a stricter rule.

## Operating Rules

- Do not move source repositories into the OS; keep `src` and `worktrees/*` as links unless the operator explicitly requests otherwise.
- Preserve `project.yml`, `source-map.md`, `config/*.yml`, and `worktrees/index.yml` as the project control surface.
- Use `ideas/` for project-scoped idea capture before promoting work into a workflow, ticket, or feature artifact.
- Keep secrets out of markdown, YAML, generated config, logs, and artifacts.
- Follow the strictest applicable parent, project, source-repo, and workflow rule.
"""


def project_tools(domain: str, project: str) -> str:
    return f"""# Tools: {project}

This registry names project-local capabilities for `{domain}/02-projects/{project}`.

## Commands

| Command | Use When | Notes |
| --- | --- | --- |
| `agentic-os project src` | Create or repair the canonical `src` link. | The link stays scoped inside this project folder. |
| `agentic-os project onboard` | Repair missing project layer files. | Additive; preserves local edits. |
| `agentic-os project worktree add` | Register a visible worktree symlink and index entry. | Use for active branch-specific source checkouts. |
| `agentic-os context build --project {project}` | Build a deterministic project context packet. | Use for handoffs. |
| `agentic-os validate` | Validate OS and project layer structure. | Run before handoff after scaffold changes. |

## Local Paths

| Path | Use When |
| --- | --- |
| `src/` | Canonical source checkout for this project. |
| `worktrees/` | Visible links to active worktrees. |
| `config/` | Parsed project defaults and tool/workflow configuration. |
| `ideas/` | Project-scoped idea capture. |
| `artifacts/` | Project outputs that do not belong in a run log. |
"""


def project_memory_policy(project: str) -> str:
    return f"""# Memory Policy: {project}

Record durable, non-secret project learnings here when they are useful for
future work in this project. Keep temporary branch status in `status.md` or
`worktrees/index.yml`.
"""


def domain_memory_policy(domain: str) -> str:
    return f"""# Memory: {titleize_name(domain)}

Record durable, non-secret domain learnings here. Use this for routing decisions,
stable source maps, repeated workflow findings, project-level conventions, and
control-plane changes that future sessions should not rediscover.
"""


def project_config_file_content(domain: str, project: str, status: str, lane: str | None, filename: str) -> str:
    lane_value = lane or ""
    if filename == "project-profile.yml":
        return yaml.safe_dump(
            {
                "project": {
                    "id": project,
                    "domain": domain,
                    "status": status,
                    "lane": lane_value,
                    "entrypoint": "AGENTS.md",
                    "canonical_source": "src",
                    "ideas": "ideas",
                    "artifacts": "artifacts",
                }
            },
            sort_keys=False,
        )
    if filename == "workflows.yml":
        return yaml.safe_dump(
            {
                "workflows": {
                    "default_lane": lane_value,
                    "feature_development": {
                        "artifacts_ref": "config/output-artifacts.yml",
                        "validation_ref": "config/validation.yml",
                    },
                }
            },
            sort_keys=False,
        )
    if filename == "output-artifacts.yml":
        return yaml.safe_dump(
            {
                "output_artifacts": {
                    "feature_root": "src/.features/{ticket_or_slug}",
                    "project_artifacts": "artifacts",
                    "run_logs": "../../06-runs-and-logs/runs",
                    "front_matter": True,
                }
            },
            sort_keys=False,
        )
    if filename == "validation.yml":
        return yaml.safe_dump(
            {
                "validation": {
                    "source_root": "src",
                    "commands": [],
                    "required_before_handoff": ["agentic-os validate --root <os-root>"],
                }
            },
            sort_keys=False,
        )
    if filename == "worktrees.yml":
        return yaml.safe_dump(
            {
                "worktrees": {
                    "directory": "worktrees",
                    "index": "worktrees/index.yml",
                    "link_policy": "symlink_to_external_worktree",
                }
            },
            sort_keys=False,
        )
    if filename == "memory.yml":
        return yaml.safe_dump(
            {
                "memory": {
                    "local_file": "MEMORY.md",
                    "policy": "non_secret_durable_project_learnings_only",
                }
            },
            sort_keys=False,
        )
    if filename == "mcps.yml":
        return yaml.safe_dump(
            {
                "mcps": {
                    "availability": "project-approved systems only",
                    "declared_in": "TOOLS.md",
                    "codex_config": "config.toml",
                }
            },
            sort_keys=False,
        )
    if filename == "tools.yml":
        return yaml.safe_dump(
            {
                "tools": {
                    "registry": "TOOLS.md",
                    "commands": [
                        "agentic-os project src",
                        "agentic-os project onboard",
                        "agentic-os project worktree add",
                        "agentic-os context build",
                        "agentic-os validate",
                    ],
                }
            },
            sort_keys=False,
        )
    raise ValueError(f"unknown project config file: {filename}")


def worktrees_readme(project: str) -> str:
    return f"""# Worktrees: {project}

This folder contains visible links to active project worktrees. The source
checkouts stay where they already live; this folder makes them discoverable from
the project operating surface.

Register a worktree:

```bash
agentic-os project worktree add <domain> {project} <name> --path <path>
```

`index.yml` is the machine-readable list used by routing.
"""


def worktrees_index(project: str) -> str:
    return yaml.safe_dump({"project": project, "worktrees": []}, sort_keys=False)


def ideas_readme(project: str) -> str:
    return f"""# Ideas: {project}

Capture project-scoped ideas here before promoting them into tickets, workflows,
feature artifacts, or implementation plans.
"""


def ideas_raw(project: str) -> str:
    return f"""# Raw Ideas: {project}

| Date | Source | Idea | Next Step |
| --- | --- | --- | --- |
"""


def ensure_project_index(projects_readme: Path, domain: str, project: str, status: str, result: ScaffoldResult) -> None:
    table = "\n## Project Index\n\n| Project | Status | Folder |\n| --- | --- | --- |\n"
    if "## Project Index" not in projects_readme.read_text(encoding="utf-8"):
        append_once(projects_readme, table, result)
    append_once(projects_readme, f"| `{project}` | `{status}` | `{project}/` |\n", result)


def ensure_active_work(active_work: Path, project: str, status: str, result: ScaffoldResult) -> None:
    append_once(
        active_work,
        f"| `{project}` | `{status}` | OS Owner | Define next action. | `02-projects/{project}/` |\n",
        result,
    )


def append_control_signal(
    domain_root: Path,
    section: str,
    item: str,
    status: str,
    link: str,
    notes: str,
    result: ScaffoldResult,
) -> None:
    state_index = domain_root / "00-control-plane" / "state-index.md"
    if not state_index.exists():
        write_file_once(state_index, control_file_content(domain_root.name, "state-index.md"), result)
    row = (
        f"| {datetime.now(timezone.utc).date().isoformat()} | {item} | `{status}` | "
        f"{link} | {notes} |\n"
    )
    content = state_index.read_text(encoding="utf-8") if state_index.exists() else ""
    if row in content:
        result.skipped.append(state_index)
        return
    marker = f"## {section}"
    start = content.find(marker)
    if start == -1:
        append_once(state_index, f"\n{marker}\n\n| Date | Item | Status | Link | Notes |\n| --- | --- | --- | --- | --- |\n{row}", result)
        return
    next_section = content.find("\n## ", start + len(marker))
    insert_at = len(content) if next_section == -1 else next_section
    prefix = content[:insert_at]
    suffix = content[insert_at:]
    separator = "" if prefix.endswith("\n") else "\n"
    state_index.write_text(f"{prefix}{separator}{row}{suffix}", encoding="utf-8")
    result.updated.append(state_index)


def append_domain_memory(domain_root: Path, entry: str, result: ScaffoldResult) -> None:
    memory_file = domain_root / "MEMORY.md"
    if not memory_file.exists():
        write_file_once(memory_file, domain_memory_policy(domain_root.name), result)
    append_once(
        memory_file,
        f"\n## {datetime.now(timezone.utc).date().isoformat()}\n\n- {entry}\n",
        result,
    )


def append_project_source_refs(source_map: Path, repo: str | None, notion: str | None, jira: str | None, result: ScaffoldResult) -> None:
    rows = []
    if repo:
        rows.append(f"| Repo | {repo} | Code and working tree |  |\n")
    if notion:
        rows.append(f"| Notion | {notion} | Control plane or docs |  |\n")
    if jira:
        rows.append(f"| Jira | {jira} | Issues, roadmap, or delivery tracking |  |\n")
    for row in rows:
        append_once(source_map, row, result)


def write_project_file(path: Path, content: str, result: ScaffoldResult, *, replace_markers: tuple[str, ...] = ()) -> None:
    if not path.exists():
        write_file_once(path, content, result)
        return
    existing = path.read_text(encoding="utf-8")
    if existing == content:
        result.skipped.append(path)
        return
    if replace_markers and any(marker in existing for marker in replace_markers):
        path.write_text(content, encoding="utf-8")
        result.updated.append(path)
        return
    result.skipped.append(path)


def ensure_project_operating_surface(
    project_root: Path,
    domain: str,
    project: str,
    status: str,
    lane: str | None,
    result: ScaffoldResult,
) -> None:
    ensure_dir(project_root / "artifacts", result)
    ensure_dir(project_root / "config", result)
    ensure_dir(project_root / "ideas", result)
    ensure_dir(project_root / "worktrees", result)
    write_project_file(
        project_root / "AGENTS.md",
        project_agents(domain, project),
        result,
        replace_markers=("This file is the harness-neutral entrypoint for this Agentic OS layer",),
    )
    write_project_file(
        project_root / "ROUTER.md",
        project_router(domain, project),
        result,
        replace_markers=("Route work to the narrowest correct domain, workflow, automation, or run log",),
    )
    write_project_file(
        project_root / "CONTEXT.md",
        project_context(domain, project),
        result,
        replace_markers=("Describe the local room, source systems, routing hints",),
    )
    write_project_file(
        project_root / "RULES.md",
        project_rules(domain, project),
        result,
        replace_markers=("Record local constraints, approval gates, safety boundaries",),
    )
    write_project_file(
        project_root / "TOOLS.md",
        project_tools(domain, project),
        result,
        replace_markers=("List the visible capabilities intended for this layer",),
    )
    write_project_file(
        project_root / "MEMORY.md",
        project_memory_policy(project),
        result,
        replace_markers=("Record only durable, useful, non-secret learnings",),
    )
    write_file_once(project_root / "worktrees" / "README.md", worktrees_readme(project), result)
    write_file_once(project_root / "worktrees" / "index.yml", worktrees_index(project), result)
    write_file_once(project_root / "ideas" / "README.md", ideas_readme(project), result)
    write_file_once(project_root / "ideas" / "raw-ideas.md", ideas_raw(project), result)
    for filename in PROJECT_CONFIG_FILES:
        write_file_once(
            project_root / "config" / filename,
            project_config_file_content(domain, project, status, lane, filename),
            result,
        )
    ensure_codex_config(project_root, "project", result)


def is_remote_repo_reference(repo: str) -> bool:
    return "://" in repo or repo.startswith("git@")


def local_repo_link_target(repo: str | None) -> Path | None:
    if not repo or is_remote_repo_reference(repo):
        return None
    candidate = Path(repo).expanduser()
    if not candidate.is_absolute() and not candidate.exists() and not str(repo).startswith("."):
        return None
    return expand_path(repo)


def ensure_project_source_link(
    project_root: Path,
    repo: str | None,
    result: ScaffoldResult,
    *,
    replace: bool = False,
    fail_on_conflict: bool = False,
) -> None:
    target = local_repo_link_target(repo)
    if target is None:
        return
    link_path = project_root / "src"
    if link_path.is_symlink():
        if link_path.resolve() == target:
            result.skipped.append(link_path)
            return
        if not replace:
            if fail_on_conflict:
                raise ValueError(f"project src already points elsewhere: {link_path}")
            result.skipped.append(link_path)
            return
        link_path.unlink()
        link_path.symlink_to(target, target_is_directory=True)
        result.updated.append(link_path)
        return
    if link_path.exists():
        if fail_on_conflict:
            raise ValueError(f"project src exists and is not a symlink: {link_path}")
        result.skipped.append(link_path)
        return
    link_path.symlink_to(target, target_is_directory=True)
    result.created.append(link_path)


def project_repo_from_config(project_root: Path) -> str:
    config = project_root / "project.yml"
    data = yaml.safe_load(config.read_text(encoding="utf-8")) or {}
    sources = data.get("sources") if isinstance(data.get("sources"), dict) else {}
    return str(sources.get("repo") or "")


def set_project_repo(project_root: Path, repo: str, result: ScaffoldResult) -> None:
    config = project_root / "project.yml"
    data = yaml.safe_load(config.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"project config must be a YAML mapping: {config}")
    sources = data.get("sources")
    if not isinstance(sources, dict):
        sources = {}
        data["sources"] = sources
    if sources.get("repo") == repo:
        result.skipped.append(config)
        return
    sources["repo"] = repo
    config.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    result.updated.append(config)


def link_project_source(
    root: str | Path,
    domain: str,
    project: str,
    *,
    repo: str | None = None,
    force: bool = False,
) -> ScaffoldResult:
    domain = normalize_domain(domain)
    project = validate_name(project, "project")
    os_root = expand_path(root)
    project_root = domain_path(os_root, domain) / "02-projects" / project
    if not (project_root / "project.yml").is_file():
        raise ValueError(f"project not found: {domain}/{project}")

    result = ScaffoldResult()
    repo = repo or project_repo_from_config(project_root)
    if not repo:
        raise ValueError("repo is required because project.yml has no sources.repo")
    if local_repo_link_target(repo) is None:
        raise ValueError(f"repo must be a local path to create a project src symlink: {repo}")

    ensure_project_source_link(project_root, repo, result, replace=force, fail_on_conflict=True)
    set_project_repo(project_root, repo, result)
    append_project_source_refs(project_root / "source-map.md", repo, None, None, result)
    data = yaml.safe_load((project_root / "project.yml").read_text(encoding="utf-8")) or {}
    ensure_project_operating_surface(
        project_root,
        domain,
        project,
        str(data.get("status") or "active"),
        str(data.get("lane") or "") or None,
        result,
    )
    return result


def onboard_project(root: str | Path, domain: str, project: str) -> ScaffoldResult:
    domain = normalize_domain(domain)
    project = validate_name(project, "project")
    os_root = expand_path(root)
    project_root = domain_path(os_root, domain) / "02-projects" / project
    if not (project_root / "project.yml").is_file():
        raise ValueError(f"project not found: {domain}/{project}")
    data = yaml.safe_load((project_root / "project.yml").read_text(encoding="utf-8")) or {}
    result = ScaffoldResult()
    ensure_project_operating_surface(
        project_root,
        domain,
        project,
        str(data.get("status") or "active"),
        str(data.get("lane") or "") or None,
        result,
    )
    return result


def project_worktree_index_path(project_root: Path) -> Path:
    return project_root / "worktrees" / "index.yml"


def load_project_worktree_index(project_root: Path, project: str) -> dict[str, object]:
    index_path = project_worktree_index_path(project_root)
    if not index_path.is_file():
        return {"project": project, "worktrees": []}
    data = yaml.safe_load(index_path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        return {"project": project, "worktrees": []}
    worktrees = data.get("worktrees")
    if not isinstance(worktrees, list):
        data["worktrees"] = []
    data.setdefault("project", project)
    return data


def write_project_worktree_index(project_root: Path, data: dict[str, object], result: ScaffoldResult) -> None:
    index_path = project_worktree_index_path(project_root)
    before = index_path.read_text(encoding="utf-8") if index_path.exists() else ""
    after = yaml.safe_dump(data, sort_keys=False)
    if before == after:
        result.skipped.append(index_path)
        return
    index_path.write_text(after, encoding="utf-8")
    result.updated.append(index_path) if before else result.created.append(index_path)


def sync_project_worktree_config(project_root: Path, index_data: dict[str, object], result: ScaffoldResult) -> None:
    config_path = project_root / "config" / "worktrees.yml"
    before = config_path.read_text(encoding="utf-8") if config_path.exists() else ""
    after = yaml.safe_dump(
        {
            "worktrees": {
                "directory": "worktrees",
                "index": "worktrees/index.yml",
                "link_policy": "symlink_to_external_worktree",
                "registered": index_data.get("worktrees") or [],
            }
        },
        sort_keys=False,
    )
    if before == after:
        result.skipped.append(config_path)
        return
    config_path.write_text(after, encoding="utf-8")
    result.updated.append(config_path) if before else result.created.append(config_path)


def register_project_worktree(
    root: str | Path,
    domain: str,
    project: str,
    name: str,
    *,
    path: str | Path,
    force: bool = False,
) -> ScaffoldResult:
    domain = normalize_domain(domain)
    project = validate_name(project, "project")
    name = validate_name(name, "worktree")
    os_root = expand_path(root)
    project_root = domain_path(os_root, domain) / "02-projects" / project
    if not (project_root / "project.yml").is_file():
        raise ValueError(f"project not found: {domain}/{project}")
    target = expand_path(path)
    if not target.is_dir():
        raise ValueError(f"worktree path must be an existing directory: {target}")

    result = onboard_project(os_root, domain, project)
    link_path = project_root / "worktrees" / name
    if link_path.is_symlink():
        if link_path.resolve() == target:
            result.skipped.append(link_path)
        elif force:
            link_path.unlink()
            link_path.symlink_to(target, target_is_directory=True)
            result.updated.append(link_path)
        else:
            raise ValueError(f"worktree link already points elsewhere: {link_path}")
    elif link_path.exists():
        raise ValueError(f"worktree link exists and is not a symlink: {link_path}")
    else:
        link_path.symlink_to(target, target_is_directory=True)
        result.created.append(link_path)

    index_data = load_project_worktree_index(project_root, project)
    entries = [entry for entry in index_data.get("worktrees", []) if isinstance(entry, dict)]
    entry = {
        "id": name,
        "path": str(target),
        "link": f"worktrees/{name}",
        "status": "active",
    }
    replaced = False
    for offset, existing in enumerate(entries):
        if existing.get("id") == name:
            if existing != entry:
                entries[offset] = entry
            replaced = True
            break
    if not replaced:
        entries.append(entry)
    index_data["worktrees"] = entries
    write_project_worktree_index(project_root, index_data, result)
    sync_project_worktree_config(project_root, index_data, result)
    return result


def create_project(
    root: str | Path,
    domain: str,
    project: str,
    *,
    repo: str | None = None,
    notion: str | None = None,
    jira: str | None = None,
    status: str = "active",
    lane: str | None = None,
) -> ScaffoldResult:
    domain = normalize_domain(domain)
    project = validate_name(project, "project")
    if status not in PROJECT_STATUSES:
        raise ValueError(f"status must be one of {', '.join(PROJECT_STATUSES)}: {status!r}")
    if lane is not None:
        lane = validate_name(lane, "lane")

    result = create_domain(root, domain)
    domain_root = domain_path(root, domain)
    project_root = domain_root / "02-projects" / project
    ensure_dir(project_root, result)
    write_file_once(project_root / "README.md", project_readme(domain, project, status, lane), result)
    write_file_once(project_root / "project.yml", project_config(domain, project, status, lane, repo, notion, jira), result)
    write_file_once(project_root / "status.md", project_status(project, status), result)
    write_file_once(project_root / "decisions.md", project_decisions(project), result)
    write_file_once(project_root / "source-map.md", project_source_map(project, repo, notion, jira), result)
    ensure_project_source_link(project_root, repo, result)
    ensure_project_operating_surface(project_root, domain, project, status, lane, result)

    ensure_project_index(domain_root / "02-projects" / "README.md", domain, project, status, result)
    ensure_active_work(domain_root / "00-control-plane" / "active-work.md", project, status, result)
    append_control_signal(
        domain_root,
        "Project Activity",
        f"`{project}`",
        status,
        f"`02-projects/{project}/`",
        "Project scaffold created or repaired.",
        result,
    )
    append_project_source_refs(project_root / "source-map.md", repo, notion, jira, result)
    return result


def workflow_scaffold_content(domain: str, lane: str, name: str, filename: str) -> str:
    replacements = {
        "<workflow_name>": name,
        "<domain>": domain,
        "<lane>": lane,
        "<owner>": "OS Owner",
        "<yyyy-mm-dd>": datetime.now(timezone.utc).date().isoformat(),
        "<work_item_or_run>": name,
        "<workflow>": name,
        "<work_item_id>": "",
        "<workflow_or_domain>": name,
    }
    template_dir = template_source_dir() / "workflow"
    if filename == "workflow.md":
        return render_template((template_dir / "workflow.md").read_text(encoding="utf-8"), replacements)
    if filename == "outcome-brief.md":
        return render_template((template_dir / "outcome-brief.md").read_text(encoding="utf-8"), replacements)
    if filename == "alignment-questions.md":
        return render_template((template_dir / "alignment-questions.md").read_text(encoding="utf-8"), replacements)
    if filename == "prd.md":
        return render_template((template_dir / "prd.md").read_text(encoding="utf-8"), replacements)
    if filename == "implementation-plan.md":
        return render_template((template_dir / "implementation-plan.md").read_text(encoding="utf-8"), replacements)
    if filename == "dispatch-handoff.md":
        return render_template((template_dir / "dispatch-handoff.md").read_text(encoding="utf-8"), replacements)
    if filename == "progress.md":
        return render_template((template_dir / "progress.md").read_text(encoding="utf-8"), replacements)
    if filename == "quick-reference.md":
        return render_template((template_dir / "quick-reference.md").read_text(encoding="utf-8"), replacements)
    if filename == "context-pack.md":
        return render_template((template_dir / "context-pack.md").read_text(encoding="utf-8"), replacements)
    if filename == "approval-rules.md":
        return render_template((template_dir / "approval-rules.md").read_text(encoding="utf-8"), replacements)
    if filename == "state-machine.md":
        return f"""# State Machine: {name}

| From | To | Condition |
| --- | --- | --- |
| `new` | `triaged` | Domain and lane selected. |
| `triaged` | `ready` | Required context is present. |
| `ready` | `running` | Agent starts execution. |
| `running` | `needs_approval` | Output crosses an approval gate. |
| `running` | `done` | Output validated and recorded. |
| `running` | `failed` | Execution cannot safely continue. |
"""
    if filename == "output-contract.md":
        return f"""# Output Contract: {name}

## Required Outputs

- Run log.
- Links to artifacts.
- State update.
- Next action or closure reason.

## Quality Bar

- Source links are preserved.
- Approval gates are followed.
- The output can be resumed by another agent or human.
"""
    return f"""# Runbook: {name}

## Before Running

- Confirm the request belongs to `{domain}`.
- Confirm the lane is `{lane}`.
- Load the workflow spec, context pack, and approval rules.

## During The Run

- Record material actions.
- Preserve evidence links.
- Stop at approval gates.

## After Running

- Write or update the run log.
- Store artifacts in the run folder.
- Update active work or project state.
"""


def workflow_examples_readme(domain: str, lane: str, name: str) -> str:
    return f"""# Examples: {name}

## Domain

`{domain}`

## Lane

`{lane}`

## Purpose

Store sanitized example inputs, expected outputs, and edge cases for this workflow.

## Example Format

```text
<short-case-name>.md
```

Each example should include input, expected routing, required context, approval behavior, and expected output.
"""


def workflow_runs_readme(domain: str, lane: str, name: str) -> str:
    return f"""# Workflow Runs: {name}

## Domain

`{domain}`

## Lane

`{lane}`

## Purpose

Use this folder for workflow-local run notes when they are useful. The audit record still belongs under `{domain}/06-runs-and-logs/runs/`.
"""


def create_workflow(root: str | Path, domain: str, lane: str, name: str) -> ScaffoldResult:
    domain = normalize_domain(domain)
    lane = validate_name(lane, "lane")
    name = validate_name(name, "workflow")
    result = create_domain(root, domain)
    workflow_root = domain_path(root, domain) / "03-workflows" / lane / name
    ensure_dir(workflow_root, result)
    ensure_dir(workflow_root / "examples", result)
    ensure_dir(workflow_root / "runs", result)
    write_file_once(workflow_root / "examples" / "README.md", workflow_examples_readme(domain, lane, name), result)
    write_file_once(workflow_root / "runs" / "README.md", workflow_runs_readme(domain, lane, name), result)
    for filename in WORKFLOW_FILES:
        write_file_once(workflow_root / filename, workflow_scaffold_content(domain, lane, name, filename), result)
    ensure_codex_config(workflow_root, "workflow_or_task", result)
    append_control_signal(
        domain_path(root, domain),
        "Workflow Opportunities",
        f"`{name}`",
        "scaffolded",
        f"`03-workflows/{lane}/{name}/`",
        "Workflow opportunity now has a reusable spec scaffold.",
        result,
    )
    return result


def automation_scaffold_content(domain: str, lane: str, name: str, filename: str) -> str:
    replacements = {
        "<automation_name>": name,
        "<domain>": domain,
        "<lane>": lane,
        "<owner>": "OS Owner",
        "<yyyy-mm-dd>": datetime.now(timezone.utc).date().isoformat(),
    }
    template_dir = template_source_dir() / "automation"
    if filename == "automation.md":
        return render_template((template_dir / "automation.md").read_text(encoding="utf-8"), replacements)
    if filename == "permissions.md":
        return (template_dir / "permissions.md").read_text(encoding="utf-8")
    if filename == "failure-modes.md":
        return (template_dir / "failure-modes.md").read_text(encoding="utf-8")
    if filename == "inputs.md":
        return f"""# Inputs: {name}

| Input | Required | Source | Validation |
| --- | --- | --- | --- |
| Trigger payload | yes |  |  |
| Domain | yes | `{domain}` | Must match this automation's domain. |
| Lane | yes | `{lane}` | Must match this automation's lane. |
"""
    if filename == "outputs.md":
        return f"""# Outputs: {name}

| Output | Destination | Required | Notes |
| --- | --- | --- | --- |
| Run log | `logs/` and domain runs folder | yes |  |
| State update | Control plane or project | yes |  |
| Artifact |  | no |  |
"""
    if filename == "tests.md":
        return f"""# Tests: {name}

## Dry Run

- Confirm the automation can classify input without writing externally.
- Confirm idempotency behavior.
- Confirm approval-required actions stop before write.

## Failure Tests

- Missing input.
- Duplicate input.
- Unavailable source system.
- Permission denied.
"""
    return f"""# Runbook: {name}

## Start

- Confirm trigger source.
- Confirm declared permissions.
- Run in dry-run mode before enabling writes.

## Operate

- Validate inputs.
- Execute only safe actions.
- Stop at approval gates.

## Recover

- Preserve the failing input reference.
- Write a failure log.
- Route to manual review or retry.
"""


def automation_logs_readme(domain: str, lane: str, name: str) -> str:
    return f"""# Automation Logs: {name}

## Domain

`{domain}`

## Lane

`{lane}`

## Purpose

Store automation-local logs, dry-run outputs, and failure snapshots here. Durable audit records still belong under `{domain}/06-runs-and-logs/runs/`.

## Log Format

```text
<timestamp>-<result>.md
```

Each log should include trigger reference, idempotency key, action level, validation result, and next action.
"""


def create_automation(root: str | Path, domain: str, lane: str, name: str) -> ScaffoldResult:
    domain = normalize_domain(domain)
    lane = validate_name(lane, "lane")
    name = validate_name(name, "automation")
    result = create_domain(root, domain)
    automation_root = domain_path(root, domain) / "04-automations" / lane / name
    ensure_dir(automation_root, result)
    ensure_dir(automation_root / "logs", result)
    write_file_once(automation_root / "logs" / "README.md", automation_logs_readme(domain, lane, name), result)
    for filename in AUTOMATION_FILES:
        write_file_once(automation_root / filename, automation_scaffold_content(domain, lane, name, filename), result)
    ensure_codex_config(automation_root, "automation", result)
    append_control_signal(
        domain_path(root, domain),
        "Automation Status",
        f"`{name}`",
        "observe",
        f"`04-automations/{lane}/{name}/`",
        "Automation scaffold starts in observe mode until explicitly advanced.",
        result,
    )
    return result


def unique_run_log_dir(runs_dir: Path, run_id: str) -> Path:
    candidate = runs_dir / run_id
    if not candidate.exists():
        return candidate
    counter = 2
    while True:
        candidate = runs_dir / f"{run_id}-{counter}"
        if not candidate.exists():
            return candidate
        counter += 1


def create_run_log(root: str | Path, domain: str, workflow_or_automation: str) -> ScaffoldResult:
    domain = normalize_domain(domain)
    workflow_or_automation = validate_name(workflow_or_automation, "workflow_or_automation")
    result = create_domain(root, domain)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_id = f"{timestamp}-{domain}-{workflow_or_automation}"
    iso_timestamp = datetime.now(timezone.utc).isoformat()
    template = template_source_dir() / "workflow" / "run-log.md"
    content = render_template(
        template.read_text(encoding="utf-8"),
        {
            "<run_id>": run_id,
            "<domain>": domain,
            "<name>": workflow_or_automation,
            "<codex_or_claude_or_automation>": "codex",
            "<timestamp>": iso_timestamp,
            "<done_waiting_failed_needs_approval>": "running",
        },
    )
    run_root = unique_run_log_dir(domain_path(root, domain) / "06-runs-and-logs" / "runs", run_id)
    ensure_dir(run_root, result)
    ensure_dir(run_root / "artifacts", result)
    write_file_once(run_root / "run-log.md", content, result)
    return result
