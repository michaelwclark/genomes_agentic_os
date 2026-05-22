"""Codex config.toml installation helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
import difflib
import re
import shutil
from typing import Any

from .scaffold import expand_path


CONFIG_FILENAME = "config.toml"
OTEL_ENV_VARS = (
    "AGENTIC_OS_OTEL_EXPORTER_OTLP_ENDPOINT",
    "AGENTIC_OS_OTEL_HEADERS",
)
MCP_REGISTRATION_POINTS = (
    "notion",
    "browser",
    "filesystem_runtime",
    "memory",
    "customer_integration",
)
PROMPT_POINTER = """# Agent Entry Point

Load `BRAIN.md`, `ROUTER.md`, `CONTEXT.md`, and `MEMORY.md` before acting.
This compatibility file exists for harness discovery.
"""

PROMPT_TEMPLATES = {
    "AGENTS.md": PROMPT_POINTER,
    "CLAUDE.md": PROMPT_POINTER,
    "BRAIN.md": """# Agent Brain

Shared operating behavior for this Agentic OS directory.

- Follow the strictest approval rule in the stitched context.
- Preserve source truth and validation evidence.
- Keep durable behavior here, not duplicated in harness entry files.
""",
    "ROUTER.md": """# Agent Router

Route work to the narrowest correct domain, workflow, automation, or run log
before creating or changing artifacts.
""",
    "CONTEXT.md": """# Local Context

Describe the local room, source systems, approval constraints, and output
expectations for this directory.
""",
    "MEMORY.md": """# Memory Policy

Record only durable, useful, non-secret learnings. Follow the strictest privacy
rule from the stitched context.
""",
}


LAYERS: dict[str, dict[str, Any]] = {
    "global_harness": {
        "profile": "global_user_harness",
        "prompt_files": ("AGENTS.md", "CLAUDE.md", "BRAIN.md", "ROUTER.md", "CONTEXT.md", "MEMORY.md"),
        "mcp": "user-approved only",
        "sandbox": "workspace-write",
    },
    "agentic_os_root": {
        "profile": "agentic_os_root",
        "prompt_files": ("AGENTS.md", "CLAUDE.md", "BRAIN.md", "ROUTER.md", "CONTEXT.md", "MEMORY.md"),
        "mcp": "source package and local filesystem tools",
        "sandbox": "workspace-write",
    },
    "customer_os_root": {
        "profile": "customer_os_root",
        "prompt_files": ("AGENTS.md", "CLAUDE.md", "BRAIN.md", "ROUTER.md", "CONTEXT.md", "MEMORY.md"),
        "mcp": "approved customer systems only",
        "sandbox": "workspace-write",
    },
    "domain_or_lane": {
        "profile": "domain_or_lane",
        "prompt_files": ("AGENTS.md", "CLAUDE.md", "ROUTER.md", "CONTEXT.md", "MEMORY.md"),
        "mcp": "domain-approved systems only",
        "sandbox": "workspace-write",
    },
    "workflow_or_task": {
        "profile": "workflow_or_task",
        "prompt_files": ("AGENTS.md", "CLAUDE.md", "CONTEXT.md", "MEMORY.md"),
        "mcp": "workflow-approved systems only",
        "sandbox": "workspace-write",
    },
    "automation": {
        "profile": "automation",
        "prompt_files": ("AGENTS.md", "CLAUDE.md", "CONTEXT.md", "MEMORY.md"),
        "mcp": "explicit automation contract only",
        "sandbox": "workspace-write",
    },
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


def config_template(layer: str) -> str:
    config = LAYERS[layer]
    profile = config["profile"]
    return f"""# Agentic OS Codex config template
# Layer: {layer}
# Local edits are preserved by the installer. Review diffs before applying.

model = "gpt-5.2"
approval_policy = "on-request"
sandbox_mode = "{config['sandbox']}"

[profiles.{profile}]
model = "gpt-5.2"
approval_policy = "on-request"
sandbox_mode = "{config['sandbox']}"

[profiles.{profile}.agentic_os]
layer = "{layer}"
prompt_files = {toml_array(config['prompt_files'])}
mcp_availability = "{config['mcp']}"
environment = "local filesystem"

[otel]
log_user_prompt = false
exporter_otlp_endpoint_env_var = "AGENTIC_OS_OTEL_EXPORTER_OTLP_ENDPOINT"
headers_env_var = "AGENTIC_OS_OTEL_HEADERS"

[mcp_servers.filesystem_runtime]
command = "agentic-os"
args = ["config", "doctor"]
secret_policy = "no inline secrets"
"""


def toml_array(values: tuple[str, ...]) -> str:
    return "[" + ", ".join(f'"{value}"' for value in values) + "]"


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
    inserts: list[tuple[int, list[str]]] = []
    for section, section_additions in additions.items():
        if section in ranges:
            insert_at = ranges[section][1]
            payload = ["", "# Agentic OS managed additions", *section_additions]
        else:
            header = [] if section is None else [f"[{section}]"]
            insert_at = len(lines)
            payload = ["", "# Agentic OS managed additions", *header, *section_additions]
        inserts.append((insert_at, payload))

    for insert_at, payload in sorted(inserts, key=lambda item: item[0], reverse=True):
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


def install_config(
    root: str | Path,
    *,
    layer: str,
    dry_run: bool = True,
    backup: bool = False,
    confirm_conflicts: bool = False,
) -> ConfigInstallResult:
    if layer not in LAYERS:
        raise ValueError(f"layer must be one of {', '.join(sorted(LAYERS))}: {layer!r}")

    root_path = expand_path(root)
    config_path = root_path / CONFIG_FILENAME
    template = config_template(layer)
    existing = config_path.read_text(encoding="utf-8") if config_path.exists() else ""
    planned, conflicts = merge_config(existing, template)
    result = ConfigInstallResult(root=root_path, layer=layer, dry_run=dry_run, conflicts=conflicts)
    result.diff = diff_text(existing, planned, config_path)

    prompt_files = LAYERS[layer]["prompt_files"]
    if dry_run:
        if not root_path.exists():
            result.created.append(root_path)
        if not config_path.exists() or planned != existing:
            result.updated.append(config_path) if config_path.exists() else result.created.append(config_path)
        for filename in prompt_files:
            prompt_path = root_path / filename
            if not prompt_path.exists():
                result.created.append(prompt_path)
        return result

    if conflicts and not confirm_conflicts:
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

    for filename in prompt_files:
        prompt_path = root_path / filename
        if prompt_path.exists():
            result.skipped.append(prompt_path)
            continue
        prompt_path.write_text(PROMPT_TEMPLATES[filename], encoding="utf-8")
        result.created.append(prompt_path)

    return result


def doctor_config(root: str | Path, *, layer: str) -> dict[str, Any]:
    if layer not in LAYERS:
        raise ValueError(f"layer must be one of {', '.join(sorted(LAYERS))}: {layer!r}")

    root_path = expand_path(root)
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
    profile = LAYERS[layer]["profile"]
    required = [
        (None, "approval_policy", "Add an approval_policy matching the layer contract."),
        (None, "sandbox_mode", "Add a sandbox_mode matching the layer contract."),
        ("otel", "log_user_prompt", "Add [otel] log_user_prompt = false unless explicit approval allows prompt logging."),
        (
            "otel",
            "exporter_otlp_endpoint_env_var",
            "Reference AGENTIC_OS_OTEL_EXPORTER_OTLP_ENDPOINT by name; do not inline endpoint secrets.",
        ),
        ("otel", "headers_env_var", "Reference AGENTIC_OS_OTEL_HEADERS by name; do not inline header values."),
        (
            f"profiles.{profile}.agentic_os",
            "mcp_availability",
            "Declare the MCP availability boundary for this layer.",
        ),
        (
            "mcp_servers.filesystem_runtime",
            "secret_policy",
            "Declare secret_policy = \"no inline secrets\" for MCP registration blocks.",
        ),
    ]
    for section, key, remediation in required:
        if (section, key) not in keys:
            label = f"[{section}] {key}" if section else key
            findings.append(ConfigDoctorFinding("blocker", config_path, f"missing required config key: {label}", remediation))

    secret_markers = ("secret=", "token=", "password=", "GENOMES_NOTION_PAT=", "GENOMES_NOTION_CONNECTOR=")
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
