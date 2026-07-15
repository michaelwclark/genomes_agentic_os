"""Codex config.toml installation helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
import difflib
import re
import shutil
from typing import Any
import yaml

from .capability_registry import HARNESS_DIRECTORY, command_entries, hook_entries, library_entries, plugin_entries, rule_entries, skill_entries
from .composio_catalog import composio_tools_markdown
from .mcp_catalog import MCP_SERVERS, config_mcp_ids, mcp_config_payload, mcp_tools_markdown


CONFIG_FILENAME = "config.toml"
SIDECAR_FILENAME = "codex-profile.yml"
ROOT_MARKER_FILENAME = ".agentic_root"
MANAGED_BY = "genomes_agentic_os"
MANAGED_FEATURE = "62-role-aware-codex-config-layers"
MANAGED_POLICY_VERSION = 1
PROJECT_DOC_FALLBACK_FILES = ("PROFILE.md", "ROUTER.md", "CONTEXT.md", "RULES.md", "TOOLS.md", "MEMORY.md")
AGENTS_PROFILE_BEGIN = "<!-- agentic-os-codex-profile:start -->"
AGENTS_PROFILE_END = "<!-- agentic-os-codex-profile:end -->"
PROFILE_MANAGED_MARKER = (
    "<!-- managed-by: genomes_agentic_os; feature: 62-role-aware-codex-config-layers; policy-version: 1 -->"
)
OTEL_ENV_VARS = (
    "AGENTIC_OS_OTEL_EXPORTER_OTLP_ENDPOINT",
    "AGENTIC_OS_OTEL_HEADERS",
)
MCP_REGISTRATION_POINTS = (
    "notion",
    "genomes_brain",
    "github",
    "context_mode",
    "sentry",
    "datadog",
    "supabase",
    "playwright",
    "filesystem_runtime",
)
BASE_PROMPT_FILES = ("AGENTS.md", "PROFILE.md", "CLAUDE.md", "ROUTER.md", "CONTEXT.md", "RULES.md", "TOOLS.md", "MEMORY.md")
COMPACT_OBJECT_PROMPT_FILES = ("AGENTS.md", "PROFILE.md", "CLAUDE.md")
COMPACT_OBJECT_AGENTS_TEMPLATE = """# Agent Entry Point

This workflow or automation inherits its route, rules, and tool registry through
`context-contract.yml`; do not copy parent contract catalogs into this folder.

## Required Loop

1. Read `context-contract.yml` and the canonical object document.
2. Resolve inherited context with `agentic-os context explain --path .` when provenance matters.
3. Load `read.first` now and `read.deferred` only when the task requires it.
4. Follow inherited approval and safety rules plus explicit local overrides.
5. Record validation and evidence before closeout.
"""


def expand_path(path: str | Path) -> Path:
    return Path(path).expanduser().resolve()


def markdown_table(headers: tuple[str, ...], rows: list[tuple[str, ...]]) -> str:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    lines.extend("| " + " | ".join(row) + " |" for row in rows)
    return "\n".join(lines)


def tools_prompt_template() -> str:
    skills = markdown_table(
        ("Skill", "Use When", "Source"),
        [
            (f"`{entry['id']}`", entry["description"], entry["source"])
            for entry in skill_entries()
        ],
    )
    commands = markdown_table(
        ("Command", "Use When", "Source"),
        [
            (f"`{entry['command']}`", entry["description"], entry["source"])
            for entry in command_entries()
        ],
    )
    libraries = markdown_table(
        ("Name", "Use When", "Source"),
        [
            (f"`{entry['id']}`", entry["description"], entry.get("source", ""))
            for entry in library_entries()
        ],
    )
    plugins = markdown_table(
        ("Plugin", "Use When", "Status"),
        [
            (f"`{entry['id']}`", entry["description"], entry["status"])
            for entry in plugin_entries()
        ],
    )
    hooks = markdown_table(
        ("Hook", "Use When", "Status"),
        [
            (f"`{entry['id']}`", entry["description"], entry["status"])
            for entry in hook_entries()
        ],
    )
    rules = markdown_table(
        ("Rule", "Use When", "Source"),
        [
            (f"`{entry['id']}`", entry["description"], entry["source"])
            for entry in rule_entries()
        ],
    )
    return f"""# Tools

List the visible capabilities intended for this layer. Registry-backed installs
mirror this file from `registries/*.yml`; harness-specific folders implement
the contract but do not replace it.

## Skills

{skills}

## Commands

{commands}

## MCP Servers

{mcp_tools_markdown()}

## Composio Tool Routes

{composio_tools_markdown()}

## Plugins And Libraries

### Plugins

{plugins}

### Libraries

{libraries}

## Local Wrappers

| Wrapper | Use When | Notes |
| --- | --- | --- |
| `host-tool-registry` | Shell, runtime, package-manager, and cleanup work. | Read the host registry before non-trivial host work. |

## Hooks

{hooks}

## Rules

{rules}

## Missing Or Disabled

Record missing or disabled capabilities here instead of silently falling back
to hidden harness-specific state.
"""


PROMPT_TEMPLATES = {
    "AGENTS.md": """# Agent Entry Point

This file is the harness-neutral entrypoint for this Agentic OS layer.

## Startup Loop

1. Read `ROUTER.md`, `CONTEXT.md`, `RULES.md`, and `TOOLS.md` in this directory.
2. Classify the request against `ROUTER.md`.
3. If the router points to a narrower directory, `cd` there and repeat this loop.
4. Act only after loading the final routed layer.
5. Record routing gaps, missing tools, and durable next actions in the run log or closeout artifact.

## Adaptive Observe Receipt

When the installed adaptive observation config is enabled and `CODEX_THREAD_ID`
is available, run `agentic-os adaptive-routing observe --root <root> "<original
user request>"` once per substantive user task before its first action. This is local,
non-executing, text-free telemetry; duplicate turn correlations are no-ops.

## Precedence

- Active user instructions win.
- The final routed layer is the working context.
- The strictest safety, approval, privacy, and destructive-action rule wins across all loaded `RULES.md` files.
- Use `TOOLS.md` as the visible tool contract before assuming a skill, MCP server, command, plugin, wrapper, or library is available.

Read `MEMORY.md` when present before writing durable memory.
""",
    "CLAUDE.md": "@AGENTS.md\n",
    "ROUTER.md": """# Agent Router

Route work to the narrowest correct domain, workflow, automation, or run log
before creating or changing artifacts.

Read `CONTEXT.md`, `RULES.md`, and `TOOLS.md`; when this router points to a
narrower directory, change into that directory and repeat the same read-route
loop.
""",
    "CONTEXT.md": """# Local Context

Describe the local room, source systems, routing hints, and output expectations
for this directory. Keep constraints in `RULES.md` and available capabilities in
`TOOLS.md`.
""",
    "RULES.md": """# Rules

Record local constraints, approval gates, safety boundaries, coding rules, and
operating rules for this layer.

The strictest applicable rule wins across parent and child layers.
""",
    "TOOLS.md": tools_prompt_template(),
    "MEMORY.md": """# Memory Policy

Record only durable, useful, non-secret learnings. Follow the strictest privacy
rule from the stitched context.
""",
}


@dataclass(frozen=True)
class CodexLayerPolicy:
    layer_token: str
    profile: str
    legacy_profiles: tuple[str, ...]
    role: str
    role_summary: str
    model: str
    model_reasoning_effort: str
    model_verbosity: str
    model_reasoning_summary: str
    approval_policy: str
    sandbox_mode: str
    prompt_files: tuple[str, ...]
    mcp_scope: str
    customer_safe: bool

    @property
    def profile_names(self) -> tuple[str, ...]:
        return (self.profile, *self.legacy_profiles)


LAYER_POLICIES: dict[str, CodexLayerPolicy] = {
    "global_harness": CodexLayerPolicy(
        layer_token="global_harness",
        profile="global_user_harness",
        legacy_profiles=(),
        role="navigator",
        role_summary="Route personal work, gather lightweight context, and hand off to the narrowest useful layer.",
        model="gpt-5.4-mini",
        model_reasoning_effort="medium",
        model_verbosity="low",
        model_reasoning_summary="concise",
        approval_policy="on-request",
        sandbox_mode="workspace-write",
        prompt_files=BASE_PROMPT_FILES,
        mcp_scope="user-approved only",
        customer_safe=True,
    ),
    "agentic_os_root": CodexLayerPolicy(
        layer_token="agentic_os_root",
        profile="agentic_os_root",
        legacy_profiles=(),
        role="os_navigator",
        role_summary="Navigate the installed OS, read shared rules, and prepare context before routing work deeper.",
        model="gpt-5.4-mini",
        model_reasoning_effort="medium",
        model_verbosity="low",
        model_reasoning_summary="concise",
        approval_policy="on-request",
        sandbox_mode="workspace-write",
        prompt_files=BASE_PROMPT_FILES,
        mcp_scope="source package and local filesystem tools",
        customer_safe=False,
    ),
    "customer_os_root": CodexLayerPolicy(
        layer_token="customer_os_root",
        profile="customer_os_root",
        legacy_profiles=(),
        role="customer_navigator",
        role_summary="Stay inside the customer boundary, route to approved customer surfaces, and avoid cross-customer context.",
        model="gpt-5.4-mini",
        model_reasoning_effort="medium",
        model_verbosity="low",
        model_reasoning_summary="concise",
        approval_policy="on-request",
        sandbox_mode="workspace-write",
        prompt_files=BASE_PROMPT_FILES,
        mcp_scope="approved customer systems only",
        customer_safe=True,
    ),
    "domain_or_lane": CodexLayerPolicy(
        layer_token="domain_or_lane",
        profile="domain_or_lane",
        legacy_profiles=(),
        role="domain_navigator",
        role_summary="Classify work for this domain and route to the correct project, workflow, or automation layer.",
        model="gpt-5.4-mini",
        model_reasoning_effort="medium",
        model_verbosity="low",
        model_reasoning_summary="concise",
        approval_policy="on-request",
        sandbox_mode="workspace-write",
        prompt_files=BASE_PROMPT_FILES,
        mcp_scope="domain-approved systems only",
        customer_safe=True,
    ),
    "project": CodexLayerPolicy(
        layer_token="project",
        profile="project_orchestrator",
        legacy_profiles=("project",),
        role="orchestrator",
        role_summary=(
            "You plan, decompose, delegate, verify, and integrate project work. If the request is only navigation or "
            "routing, route to the narrowest layer and avoid broad implementation. If you spawn subagents, verify their "
            "results before declaring the work complete."
        ),
        model="gpt-5.5",
        model_reasoning_effort="high",
        model_verbosity="low",
        model_reasoning_summary="concise",
        approval_policy="on-request",
        sandbox_mode="workspace-write",
        prompt_files=BASE_PROMPT_FILES,
        mcp_scope="project-approved systems only",
        customer_safe=True,
    ),
    "workflow_or_task": CodexLayerPolicy(
        layer_token="workflow_or_task",
        profile="workflow_orchestrator",
        legacy_profiles=("workflow_or_task",),
        role="orchestrator",
        role_summary="Run workflow-scoped heavy work, track acceptance criteria, verify delegated outputs, and record evidence.",
        model="gpt-5.5",
        model_reasoning_effort="high",
        model_verbosity="low",
        model_reasoning_summary="concise",
        approval_policy="on-request",
        sandbox_mode="workspace-write",
        prompt_files=BASE_PROMPT_FILES,
        mcp_scope="workflow-approved systems only",
        customer_safe=True,
    ),
    "automation": CodexLayerPolicy(
        layer_token="automation",
        profile="automation_guard",
        legacy_profiles=("automation",),
        role="automation_guard",
        role_summary="Execute only within the automation contract, preserve evidence, and stop when approvals or safety gates are missing.",
        model="gpt-5.5",
        model_reasoning_effort="high",
        model_verbosity="low",
        model_reasoning_summary="concise",
        approval_policy="on-request",
        sandbox_mode="workspace-write",
        prompt_files=BASE_PROMPT_FILES,
        mcp_scope="explicit automation contract only",
        customer_safe=True,
    ),
}


LAYERS: dict[str, dict[str, Any]] = {
    layer: {
        "profile": policy.profile,
        "legacy_profiles": policy.legacy_profiles,
        "prompt_files": policy.prompt_files,
        "mcp": policy.mcp_scope,
        "sandbox": policy.sandbox_mode,
    }
    for layer, policy in LAYER_POLICIES.items()
}

KEY_PATTERN = re.compile(r"^\s*([A-Za-z0-9_.-]+)\s*=\s*(.*?)\s*(?:#.*)?$")
SECTION_PATTERN = re.compile(r"^\s*\[([A-Za-z0-9_.-]+)]\s*$")


@dataclass
class ConfigInstallResult:
    root: Path
    layer: str
    dry_run: bool
    created: list[Path] = field(default_factory=list)
    updated: list[Path] = field(default_factory=list)
    skipped: list[Path] = field(default_factory=list)
    backups: list[Path] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    diff: str = ""
    blocked: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "root": str(self.root),
            "layer": self.layer,
            "dry_run": self.dry_run,
            "created": [str(path) for path in self.created],
            "updated": [str(path) for path in self.updated],
            "skipped": [str(path) for path in self.skipped],
            "backups": [str(path) for path in self.backups],
            "conflicts": self.conflicts,
            "blocked": self.blocked,
            "diff": self.diff,
        }


@dataclass(frozen=True)
class ConfigTreeTarget:
    root: Path
    layer: str
    reason: str

    def as_dict(self) -> dict[str, str]:
        return {"root": str(self.root), "layer": self.layer, "reason": self.reason}


@dataclass
class ConfigTreeInstallResult:
    root: Path
    dry_run: bool
    targets: list[ConfigTreeTarget] = field(default_factory=list)
    installations: list[ConfigInstallResult] = field(default_factory=list)

    @property
    def blocked(self) -> bool:
        return any(installation.blocked for installation in self.installations)

    def as_dict(self) -> dict[str, Any]:
        return {
            "root": str(self.root),
            "dry_run": self.dry_run,
            "blocked": self.blocked,
            "targets": [target.as_dict() for target in self.targets],
            "installations": [installation.as_dict() for installation in self.installations],
        }


@dataclass
class ConfigDoctorFinding:
    severity: str
    path: Path
    message: str
    remediation: str

    def as_dict(self) -> dict[str, str]:
        return {
            "severity": self.severity,
            "path": str(self.path),
            "message": self.message,
            "remediation": self.remediation,
        }


def toml_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(toml_value(item) for item in value) + "]"
    if isinstance(value, str):
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return str(value)


def mcp_server_template(server_id: str) -> str:
    server = MCP_SERVERS[server_id]
    lines = [f"[mcp_servers.{server.id}]"]
    for key, value in mcp_config_payload(server).items():
        lines.append(f"{key} = {toml_value(value)}")
    return "\n".join(lines)


def mcp_servers_template(layer: str, root: str | Path | None = None) -> str:
    return "\n\n".join(mcp_server_template(server_id) for server_id in config_mcp_ids(layer, root))


def policy_for_layer(layer: str) -> CodexLayerPolicy:
    if layer not in LAYER_POLICIES:
        raise ValueError(f"layer must be one of {', '.join(sorted(LAYER_POLICIES))}: {layer!r}")
    return LAYER_POLICIES[layer]


def profile_toml_block(policy: CodexLayerPolicy, profile_name: str, *, compact_context: bool = False) -> str:
    context_contract = "context-contract.yml" if compact_context else "route-read-cd-repeat"
    rules_file = "inherited" if compact_context else "RULES.md"
    tool_registry_file = "inherited" if compact_context else "TOOLS.md"
    prompt_files = COMPACT_OBJECT_PROMPT_FILES if compact_context else policy.prompt_files
    return f"""[profiles.{profile_name}]
model = "{policy.model}"
model_reasoning_effort = "{policy.model_reasoning_effort}"
model_verbosity = "{policy.model_verbosity}"
model_reasoning_summary = "{policy.model_reasoning_summary}"
approval_policy = "{policy.approval_policy}"
sandbox_mode = "{policy.sandbox_mode}"

[profiles.{profile_name}.agentic_os]
layer = "{policy.layer_token}"
prompt_files = {toml_array(prompt_files)}
context_contract = "{context_contract}"
rules_file = "{rules_file}"
tool_registry_file = "{tool_registry_file}"
mcp_availability = "{policy.mcp_scope}"
environment = "local filesystem"
"""


def config_template(layer: str, root: str | Path | None = None, *, compact_context: bool = False) -> str:
    policy = policy_for_layer(layer)
    profile_blocks = "\n\n".join(
        profile_toml_block(policy, profile_name, compact_context=compact_context)
        for profile_name in policy.profile_names
    )
    return f"""# Agentic OS Codex config template
# Layer: {layer}
# Local edits are preserved by the installer. Review diffs before applying.

model = "{policy.model}"
model_reasoning_effort = "{policy.model_reasoning_effort}"
model_verbosity = "{policy.model_verbosity}"
model_reasoning_summary = "{policy.model_reasoning_summary}"
approval_policy = "{policy.approval_policy}"
sandbox_mode = "{policy.sandbox_mode}"
project_root_markers = [".agentic_root", ".git", "agentic-os.package.json", "pyproject.toml", "package.json"]
project_doc_fallback_filenames = {toml_array(COMPACT_OBJECT_PROMPT_FILES if compact_context else PROJECT_DOC_FALLBACK_FILES)}

{profile_blocks}

[otel]
log_user_prompt = false
exporter_otlp_endpoint_env_var = "AGENTIC_OS_OTEL_EXPORTER_OTLP_ENDPOINT"
headers_env_var = "AGENTIC_OS_OTEL_HEADERS"

[mcp_servers.filesystem_runtime]
command = "agentic-os"
args = ["config", "doctor"]
secret_policy = "no inline secrets"

{mcp_servers_template(layer, root)}
"""


def profile_markdown_template(policy: CodexLayerPolicy) -> str:
    return f"""{PROFILE_MANAGED_MARKER}

# Codex Profile

Role: {policy.role}
Layer: {policy.layer_token}
Profile: {policy.profile}
Default model: {policy.model}
Reasoning effort: {policy.model_reasoning_effort}

{policy.role_summary}
"""


def agents_role_block(policy: CodexLayerPolicy) -> str:
    return f"""{AGENTS_PROFILE_BEGIN}
## Codex Profile

Role: {policy.role}
Layer: {policy.layer_token}
Profile: {policy.profile}
Default model: {policy.model}
Reasoning effort: {policy.model_reasoning_effort}

{policy.role_summary}
{AGENTS_PROFILE_END}"""


def agents_markdown_template(policy: CodexLayerPolicy, base: str | None = None) -> str:
    block = agents_role_block(policy)
    content = (base or PROMPT_TEMPLATES["AGENTS.md"]).rstrip()
    if content.startswith("# "):
        first_line, _, rest = content.partition("\n")
        return f"{first_line}\n\n{block}\n\n{rest.lstrip()}\n"
    return f"{block}\n\n{content}\n"


def content_looks_generated_agents(content: str) -> bool:
    return content.startswith("# Agent Entry Point") and ("## Startup Loop" in content or "## Required Loop" in content)


def merge_agents_role_block(existing: str, policy: CodexLayerPolicy) -> str:
    if not existing.strip():
        return agents_markdown_template(policy).rstrip() + "\n"
    if AGENTS_PROFILE_BEGIN in existing and AGENTS_PROFILE_END in existing:
        pattern = re.compile(
            rf"{re.escape(AGENTS_PROFILE_BEGIN)}.*?{re.escape(AGENTS_PROFILE_END)}",
            re.DOTALL,
        )
        stripped = pattern.sub("", existing, count=1).lstrip()
        return agents_markdown_template(policy, stripped).rstrip() + "\n"
    if content_looks_generated_agents(existing):
        return agents_markdown_template(policy, existing).rstrip() + "\n"
    return existing if existing.endswith("\n") else existing + "\n"


def sidecar_payload(policy: CodexLayerPolicy, *, prompt_files: tuple[str, ...] | None = None) -> dict[str, Any]:
    return {
        "layer": policy.layer_token,
        "profile": policy.profile,
        "legacy_profiles": list(policy.legacy_profiles),
        "role": policy.role,
        "role_summary": policy.role_summary,
        "model": policy.model,
        "model_reasoning_effort": policy.model_reasoning_effort,
        "model_verbosity": policy.model_verbosity,
        "model_reasoning_summary": policy.model_reasoning_summary,
        "prompt_files": list(prompt_files or policy.prompt_files),
        "mcp_availability": policy.mcp_scope,
        "customer_safe": policy.customer_safe,
        "managed_by": MANAGED_BY,
        "managed_feature": MANAGED_FEATURE,
        "managed_policy_version": MANAGED_POLICY_VERSION,
    }


def sidecar_template(policy: CodexLayerPolicy, *, prompt_files: tuple[str, ...] | None = None) -> str:
    return yaml.safe_dump(sidecar_payload(policy, prompt_files=prompt_files), sort_keys=False)


def prompt_file_template(policy: CodexLayerPolicy, filename: str) -> str:
    if filename == "AGENTS.md":
        return agents_markdown_template(policy)
    if filename == "PROFILE.md":
        return profile_markdown_template(policy)
    return PROMPT_TEMPLATES[filename]


def toml_array(values: tuple[str, ...]) -> str:
    return toml_value(values)


def parse_toml_keys(content: str) -> dict[tuple[str | None, str], str]:
    keys: dict[tuple[str | None, str], str] = {}
    section: str | None = None
    for line in content.splitlines():
        section_match = SECTION_PATTERN.match(line)
        if section_match:
            section = section_match.group(1)
            continue
        key_match = KEY_PATTERN.match(line)
        if key_match:
            keys[(section, key_match.group(1))] = key_match.group(2).strip()
    return keys


def section_ranges(lines: list[str]) -> dict[str | None, tuple[int, int]]:
    starts: list[tuple[str | None, int]] = [(None, 0)]
    for index, line in enumerate(lines):
        section_match = SECTION_PATTERN.match(line)
        if section_match:
            starts.append((section_match.group(1), index + 1))
    ranges: dict[str | None, tuple[int, int]] = {}
    for offset, (section, start) in enumerate(starts):
        end = starts[offset + 1][1] - 1 if offset + 1 < len(starts) else len(lines)
        ranges[section] = (start, end)
    return ranges


def template_keys_by_section(template: str) -> dict[str | None, list[tuple[str, str]]]:
    sections: dict[str | None, list[tuple[str, str]]] = {}
    section: str | None = None
    for line in template.splitlines():
        section_match = SECTION_PATTERN.match(line)
        if section_match:
            section = section_match.group(1)
            sections.setdefault(section, [])
            continue
        key_match = KEY_PATTERN.match(line)
        if key_match:
            sections.setdefault(section, []).append((key_match.group(1), key_match.group(2).strip()))
    return sections


def merge_config(existing: str, template: str) -> tuple[str, list[str]]:
    if not existing.strip():
        return template.rstrip() + "\n", []

    existing_keys = parse_toml_keys(existing)
    template_sections = template_keys_by_section(template)
    conflicts: list[str] = []
    additions: dict[str | None, list[str]] = {}

    for section, pairs in template_sections.items():
        for key, value in pairs:
            existing_value = existing_keys.get((section, key))
            if existing_value is None:
                additions.setdefault(section, []).append(f"{key} = {value}")
            elif existing_value != value:
                label = f"{section}.{key}" if section else key
                conflicts.append(f"{label}: existing {existing_value} differs from managed {value}")

    if not additions:
        return existing if existing.endswith("\n") else existing + "\n", conflicts

    lines = existing.splitlines()
    ranges = section_ranges(lines)
    inserts: list[tuple[int, int, list[str]]] = []
    for section, section_additions in additions.items():
        if section in ranges:
            insert_at = ranges[section][1]
            payload = ["", "# Agentic OS managed additions", *section_additions]
            priority = 0 if section is None else 1
        else:
            header = [] if section is None else [f"[{section}]"]
            insert_at = len(lines)
            payload = ["", "# Agentic OS managed additions", *header, *section_additions]
            priority = 0 if section is None else 1
        inserts.append((insert_at, priority, payload))

    for insert_at, _priority, payload in sorted(inserts, key=lambda item: (item[0], item[1]), reverse=True):
        lines[insert_at:insert_at] = payload
    return "\n".join(lines).rstrip() + "\n", conflicts


def diff_text(before: str, after: str, path: Path) -> str:
    if before == after:
        return ""
    return "".join(
        difflib.unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile=f"{path}:before",
            tofile=f"{path}:after",
        )
    )


def backup_path(path: Path) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    return path.with_name(f"{path.name}.bak-{stamp}")


def sidecar_path(root: Path) -> Path:
    return root / "config" / SIDECAR_FILENAME


def artifact_is_managed(path: Path, content: str) -> bool:
    if path.name == "PROFILE.md":
        return PROFILE_MANAGED_MARKER in content
    if path.name == SIDECAR_FILENAME:
        try:
            data = yaml.safe_load(content) or {}
        except yaml.YAMLError:
            return False
        return (
            data.get("managed_by") == MANAGED_BY
            and data.get("managed_feature") == MANAGED_FEATURE
            and data.get("managed_policy_version") == MANAGED_POLICY_VERSION
        )
    return False


def plan_managed_artifact(path: Path, planned: str) -> tuple[str, str, str]:
    """Return action, existing content, and conflict message for a managed whole-file artifact."""
    if not path.exists():
        return "create", "", ""
    existing = path.read_text(encoding="utf-8")
    if existing == planned:
        return "skip", existing, ""
    if artifact_is_managed(path, existing):
        return "update", existing, f"{path}: managed content differs from policy"
    return "update", existing, f"{path}: pre_existing_unmanaged_file"


def install_config(
    root: str | Path,
    *,
    layer: str,
    dry_run: bool = True,
    backup: bool = False,
    confirm_conflicts: bool = False,
    compact_context: bool | None = None,
) -> ConfigInstallResult:
    policy = policy_for_layer(layer)

    root_path = expand_path(root)
    if compact_context is None:
        compact_context = (
            layer in {"workflow_or_task", "automation"}
            and (root_path / "context-contract.yml").is_file()
        )
    config_path = root_path / CONFIG_FILENAME
    template = config_template(layer, root_path, compact_context=compact_context)
    existing = config_path.read_text(encoding="utf-8") if config_path.exists() else ""
    planned, conflicts = merge_config(existing, template)
    result = ConfigInstallResult(root=root_path, layer=layer, dry_run=dry_run, conflicts=conflicts)
    result.diff = diff_text(existing, planned, config_path)

    profile_path = root_path / "PROFILE.md"
    sidecar = sidecar_path(root_path)
    profile_content = profile_markdown_template(policy)
    prompt_files = COMPACT_OBJECT_PROMPT_FILES if compact_context else policy.prompt_files
    sidecar_content = sidecar_template(policy, prompt_files=prompt_files)
    managed_artifacts = (
        (profile_path, profile_content),
        (sidecar, sidecar_content),
    )
    artifact_plans: list[tuple[Path, str, str, str, str]] = []
    for path, content in managed_artifacts:
        action, artifact_existing, artifact_conflict = plan_managed_artifact(path, content)
        if artifact_conflict:
            result.conflicts.append(artifact_conflict)
        artifact_diff = diff_text(artifact_existing, content, path)
        if artifact_diff:
            result.diff = f"{result.diff.rstrip()}\n{artifact_diff}".lstrip()
        artifact_plans.append((path, action, artifact_existing, content, artifact_conflict))

    agents_path = root_path / "AGENTS.md"
    agents_existing = agents_path.read_text(encoding="utf-8") if agents_path.exists() else ""
    agents_planned = (
        agents_markdown_template(policy, COMPACT_OBJECT_AGENTS_TEMPLATE)
        if compact_context and not agents_existing.strip()
        else merge_agents_role_block(agents_existing, policy)
    )
    agents_diff = diff_text(agents_existing, agents_planned, agents_path)
    if agents_diff:
        result.diff = f"{result.diff.rstrip()}\n{agents_diff}".lstrip()

    if dry_run:
        if not root_path.exists():
            result.created.append(root_path)
        if not config_path.exists() or planned != existing:
            result.updated.append(config_path) if config_path.exists() else result.created.append(config_path)
        if not agents_path.exists():
            result.created.append(agents_path)
        elif agents_planned != agents_existing:
            result.updated.append(agents_path)
        for filename in prompt_files:
            if filename in {"AGENTS.md", "PROFILE.md"}:
                continue
            prompt_path = root_path / filename
            if not prompt_path.exists():
                result.created.append(prompt_path)
        if not sidecar.parent.exists():
            result.created.append(sidecar.parent)
        for path, action, _artifact_existing, _content, _artifact_conflict in artifact_plans:
            if action == "create":
                result.created.append(path)
            elif action == "update":
                result.updated.append(path)
        return result

    if result.conflicts and not confirm_conflicts:
        result.blocked = True
        return result

    root_path.mkdir(parents=True, exist_ok=True)
    if config_path.exists() and planned != existing and backup:
        destination = backup_path(config_path)
        shutil.copy2(config_path, destination)
        result.backups.append(destination)
    if planned != existing:
        config_path.write_text(planned, encoding="utf-8")
        result.updated.append(config_path) if existing else result.created.append(config_path)
    else:
        result.skipped.append(config_path)

    if agents_planned != agents_existing:
        if agents_path.exists() and backup:
            destination = backup_path(agents_path)
            shutil.copy2(agents_path, destination)
            result.backups.append(destination)
        agents_path.write_text(agents_planned, encoding="utf-8")
        result.updated.append(agents_path) if agents_existing else result.created.append(agents_path)
    else:
        result.skipped.append(agents_path)

    for filename in prompt_files:
        prompt_path = root_path / filename
        if filename in {"AGENTS.md", "PROFILE.md"}:
            continue
        if prompt_path.exists():
            result.skipped.append(prompt_path)
            continue
        prompt_path.write_text(prompt_file_template(policy, filename), encoding="utf-8")
        result.created.append(prompt_path)

    sidecar.parent.mkdir(parents=True, exist_ok=True)
    for path, action, _artifact_existing, content, _artifact_conflict in artifact_plans:
        if action == "skip":
            result.skipped.append(path)
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and backup:
            destination = backup_path(path)
            shutil.copy2(path, destination)
            result.backups.append(destination)
        path.write_text(content, encoding="utf-8")
        result.created.append(path) if action == "create" else result.updated.append(path)

    return result


def discover_config_tree_targets(root: str | Path) -> list[ConfigTreeTarget]:
    root_path = expand_path(root)
    if not (root_path / ROOT_MARKER_FILENAME).is_file():
        raise ValueError(f"config install-tree requires an installed OS root with {ROOT_MARKER_FILENAME}: {root_path}")

    harness_root = root_path / HARNESS_DIRECTORY
    agentic_root = harness_root if harness_root.is_dir() else root_path
    candidates: list[ConfigTreeTarget] = [
        ConfigTreeTarget(agentic_root, "agentic_os_root", ".agentic_root harness layer"),
    ]
    if root_path.exists():
        domain_roots = {domain_config_path.parent for domain_config_path in root_path.glob("*/domain.yml")}
        shared_factory_root = harness_root / "shared_factory"
        if (shared_factory_root / "domain.yml").is_file():
            domain_roots.add(shared_factory_root)
        for domain_root in sorted(domain_roots):
            candidates.append(ConfigTreeTarget(domain_root, "domain_or_lane", "domain.yml"))
            for project_config_path in sorted(domain_root.glob("02-projects/*/project.yml")):
                candidates.append(ConfigTreeTarget(project_config_path.parent, "project", "project.yml"))
            for workflow_path in sorted(domain_root.glob("03-workflows/*/*/workflow.md")):
                candidates.append(ConfigTreeTarget(workflow_path.parent, "workflow_or_task", "workflow.md"))
            for automation_path in sorted(domain_root.glob("04-automations/*/*/automation.md")):
                candidates.append(ConfigTreeTarget(automation_path.parent, "automation", "automation.md"))

    targets: list[ConfigTreeTarget] = []
    seen: set[Path] = set()
    for candidate in candidates:
        if candidate.root in seen:
            continue
        seen.add(candidate.root)
        targets.append(candidate)
    return targets


def install_config_tree(
    root: str | Path,
    *,
    dry_run: bool = True,
    backup: bool = False,
    confirm_conflicts: bool = False,
) -> ConfigTreeInstallResult:
    root_path = expand_path(root)
    targets = discover_config_tree_targets(root_path)
    result = ConfigTreeInstallResult(root=root_path, dry_run=dry_run, targets=targets)
    for target in targets:
        compact_context = (
            target.layer in {"workflow_or_task", "automation"}
            and (target.root / "context-contract.yml").is_file()
        )
        result.installations.append(
            install_config(
                target.root,
                layer=target.layer,
                dry_run=dry_run,
                backup=backup,
                confirm_conflicts=confirm_conflicts,
                compact_context=compact_context,
            )
        )
    return result


def doctor_config(root: str | Path, *, layer: str) -> dict[str, Any]:
    policy = policy_for_layer(layer)

    root_path = expand_path(root)
    compact_context = (
        layer in {"workflow_or_task", "automation"}
        and (root_path / "context-contract.yml").is_file()
    )
    config_path = root_path / CONFIG_FILENAME
    findings: list[ConfigDoctorFinding] = []
    if not config_path.is_file():
        findings.append(
            ConfigDoctorFinding(
                "blocker",
                config_path,
                "config.toml is missing",
                f"Run agentic-os config install --root {root_path} --layer {layer} --dry-run, review the diff, then rerun with --apply.",
            )
        )
        return {"ok": False, "root": str(root_path), "layer": layer, "findings": [finding.as_dict() for finding in findings]}

    content = config_path.read_text(encoding="utf-8")
    keys = parse_toml_keys(content)
    expected_mcp_ids = ("filesystem_runtime", *config_mcp_ids(layer, root_path))
    required = [
        (None, "model", "Add a model matching the layer policy."),
        (None, "model_reasoning_effort", "Add model_reasoning_effort matching the layer policy."),
        (None, "model_verbosity", "Add model_verbosity matching the layer policy."),
        (None, "model_reasoning_summary", "Add model_reasoning_summary matching the layer policy."),
        (None, "approval_policy", "Add an approval_policy matching the layer contract."),
        (None, "sandbox_mode", "Add a sandbox_mode matching the layer contract."),
        (None, "project_root_markers", "Add project_root_markers with .agentic_root so the installed OS root is discoverable."),
        (
            None,
            "project_doc_fallback_filenames",
            "Add fallback filenames for ROUTER.md, CONTEXT.md, RULES.md, TOOLS.md, and MEMORY.md.",
        ),
        ("otel", "log_user_prompt", "Add [otel] log_user_prompt = false unless explicit approval allows prompt logging."),
        (
            "otel",
            "exporter_otlp_endpoint_env_var",
            "Reference AGENTIC_OS_OTEL_EXPORTER_OTLP_ENDPOINT by name; do not inline endpoint secrets.",
        ),
        ("otel", "headers_env_var", "Reference AGENTIC_OS_OTEL_HEADERS by name; do not inline header values."),
        (
            "mcp_servers.filesystem_runtime",
            "secret_policy",
            "Declare secret_policy = \"no inline secrets\" for MCP registration blocks.",
        ),
    ]
    for profile_name in policy.profile_names:
        required.extend(
            [
                (f"profiles.{profile_name}", "model", f"Add model for profile {profile_name}."),
                (
                    f"profiles.{profile_name}",
                    "model_reasoning_effort",
                    f"Add model_reasoning_effort for profile {profile_name}.",
                ),
                (f"profiles.{profile_name}", "model_verbosity", f"Add model_verbosity for profile {profile_name}."),
                (
                    f"profiles.{profile_name}",
                    "model_reasoning_summary",
                    f"Add model_reasoning_summary for profile {profile_name}.",
                ),
                (f"profiles.{profile_name}", "approval_policy", f"Add approval_policy for profile {profile_name}."),
                (f"profiles.{profile_name}", "sandbox_mode", f"Add sandbox_mode for profile {profile_name}."),
                (
                    f"profiles.{profile_name}.agentic_os",
                    "mcp_availability",
                    "Declare the MCP availability boundary for this layer.",
                ),
                (
                    f"profiles.{profile_name}.agentic_os",
                    "context_contract",
                    "Declare context_contract = \"route-read-cd-repeat\" for the shared harness contract.",
                ),
                (
                    f"profiles.{profile_name}.agentic_os",
                    "rules_file",
                    "Point the layer profile at RULES.md.",
                ),
                (
                    f"profiles.{profile_name}.agentic_os",
                    "tool_registry_file",
                    "Point the layer profile at TOOLS.md.",
                ),
            ]
        )
    for server_id in expected_mcp_ids:
        section = f"mcp_servers.{server_id}"
        if server_id == "filesystem_runtime":
            continue
        server = MCP_SERVERS[server_id]
        if server.url:
            required.append((section, "url", f"Register the {server.display_name} MCP URL for this layer."))
        if server.command:
            required.append((section, "command", f"Register the {server.display_name} MCP command for this layer."))
        if server.bearer_token_env_var:
            required.append(
                (
                    section,
                    "bearer_token_env_var",
                    f"Reference {server.bearer_token_env_var} by name; do not inline bearer tokens.",
                )
            )
        required.append((section, "secret_policy", "Declare secret_policy for MCP registration blocks."))
    for section, key, remediation in required:
        if (section, key) not in keys:
            label = f"[{section}] {key}" if section else key
            findings.append(ConfigDoctorFinding("blocker", config_path, f"missing required config key: {label}", remediation))

    markers = keys.get((None, "project_root_markers"), "")
    if markers and ".agentic_root" not in markers:
        findings.append(
            ConfigDoctorFinding(
                "blocker",
                config_path,
                "project_root_markers does not include .agentic_root",
                "Add .agentic_root to project_root_markers so Codex can discover the installed OS root.",
            )
        )

    profile_path = root_path / "PROFILE.md"
    if not profile_path.is_file():
        findings.append(
            ConfigDoctorFinding(
                "blocker",
                profile_path,
                "PROFILE.md is missing",
                "Run agentic-os config install to generate the prompt-visible Codex role artifact.",
            )
        )
    else:
        profile_content = profile_path.read_text(encoding="utf-8")
        expected_profile_lines = (
            PROFILE_MANAGED_MARKER,
            f"Role: {policy.role}",
            f"Layer: {policy.layer_token}",
            f"Profile: {policy.profile}",
            f"Default model: {policy.model}",
            f"Reasoning effort: {policy.model_reasoning_effort}",
        )
        for expected in expected_profile_lines:
            if expected not in profile_content:
                findings.append(
                    ConfigDoctorFinding(
                        "blocker",
                        profile_path,
                        f"PROFILE.md missing expected policy line: {expected}",
                        "Regenerate PROFILE.md with agentic-os config install.",
                    )
                )

    sidecar = sidecar_path(root_path)
    if not sidecar.is_file():
        findings.append(
            ConfigDoctorFinding(
                "blocker",
                sidecar,
                "config/codex-profile.yml is missing",
                "Run agentic-os config install to generate Codex profile sidecar metadata.",
            )
        )
    else:
        try:
            sidecar_data = yaml.safe_load(sidecar.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as error:
            findings.append(
                ConfigDoctorFinding(
                    "blocker",
                    sidecar,
                    f"config/codex-profile.yml is not valid YAML: {error}",
                    "Regenerate the sidecar with agentic-os config install.",
                )
            )
            sidecar_data = {}
        expected_sidecar = sidecar_payload(
            policy,
            prompt_files=COMPACT_OBJECT_PROMPT_FILES if compact_context else None,
        )
        for key, expected_value in expected_sidecar.items():
            if sidecar_data.get(key) != expected_value:
                findings.append(
                    ConfigDoctorFinding(
                        "blocker",
                        sidecar,
                        f"config/codex-profile.yml has {key!r}={sidecar_data.get(key)!r}, expected {expected_value!r}",
                        "Regenerate the sidecar with agentic-os config install.",
                    )
                )

    secret_markers = (
        "secret=",
        "token=",
        "password=",
        "GENOMES_NOTION_PAT=",
        "GENOMES_NOTION_CONNECTOR=",
        "GITHUB_PAT_TOKEN=",
        "SENTRY_AUTH_TOKEN=",
        "DATADOG_API_KEY=",
        "SUPABASE_ACCESS_TOKEN=",
        "COMPOSIO_API_KEY=",
        "COMPOSIO_MCP_URL=",
        "ORGO_API_KEY=",
    )
    lowered = content.lower()
    for marker in secret_markers:
        if marker.lower() in lowered:
            findings.append(
                ConfigDoctorFinding(
                    "blocker",
                    config_path,
                    f"possible inline secret marker found: {marker}",
                    "Replace secret values with environment variable names only.",
                )
            )

    return {"ok": not findings, "root": str(root_path), "layer": layer, "findings": [finding.as_dict() for finding in findings]}
