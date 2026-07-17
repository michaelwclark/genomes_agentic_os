"""Filesystem scaffolding for installed Agentic OS roots."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess

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
from .composio_catalog import composio_tools_markdown
from .hosts import load_hosts
from .mcp_catalog import mcp_tools_markdown


DEFAULT_DOMAINS = (
    "personal",
    "work",
    "archive",
)

ROOT_MARKER_FILENAME = ".agentic_root"
SHARED_FACTORY_DOMAIN = "shared_factory"
# Backward-compatible default for the deprecated --projects-source flag.
DEFAULT_PROJECTS_SOURCE = "~/projects"
SOURCE_PACKAGE_VERSION = "0.1.0"
DEFAULT_UPDATE_CHANNEL = "stable"
DEFAULT_UPDATE_POLICY = "operator_approved"

# Optional alias map: alternate spellings that normalize to an installed
# domain slug. Intentionally empty in the generic product; operators can
# extend it in a fork or downstream configuration.
DOMAIN_ALIASES: dict[str, str] = {}

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

MANAGED_RUNTIME_FILES = (
    (
        "templates/runtime/activity-sources.yml",
        "harness/shared_factory/00-control-plane/activity-sources.yml",
        "replace_if_managed_unchanged",
    ),
    (
        "templates/runtime/analytics-metrics.yml",
        "harness/registries/analytics-metrics.yml",
        "replace_if_managed_unchanged",
    ),
    (
        "templates/runtime/spec-engine.yml",
        "harness/shared_factory/00-control-plane/spec-engine.yml",
        "replace_if_managed_unchanged",
    ),
    (
        "templates/runtime/spec-intake-workflow.md",
        "harness/shared_factory/04-workflows/spec-intake.md",
        "replace_if_managed_unchanged",
    ),
    (
        "templates/runtime/feature-intake-workflow.md",
        "harness/shared_factory/04-workflows/feature-intake.md",
        "replace_if_managed_unchanged",
    ),
    (
        "templates/runtime/bug-intake-workflow.md",
        "harness/shared_factory/04-workflows/bug-intake.md",
        "replace_if_managed_unchanged",
    ),
    (
        "templates/runtime/self-improvement.yml",
        "harness/shared_factory/00-control-plane/self-improvement.yml",
        "create_if_missing",
    ),
    (
        "templates/runtime/self-improvement-workflow.md",
        "harness/shared_factory/04-workflows/self-improvement-review.md",
        "create_if_missing",
    ),
    (
        "templates/runtime/self-improvement-review.yml",
        "harness/shared_factory/05-knowledge/templates/runtime/self-improvement-review.yml",
        "replace_if_managed_unchanged",
    ),
    (
        "templates/runtime/self-improvement-proposal.yml",
        "harness/shared_factory/05-knowledge/templates/runtime/self-improvement-proposal.yml",
        "replace_if_managed_unchanged",
    ),
    (
        "templates/runtime/self-improvement-usage-sidecar.json",
        "harness/shared_factory/05-knowledge/templates/runtime/self-improvement-usage-sidecar.json",
        "replace_if_managed_unchanged",
    ),
    (
        "harness/commands/os-self-improvement.md",
        "harness/shared_factory/05-knowledge/commands/os-self-improvement.md",
        "replace_if_managed_unchanged",
    ),
    (
        "harness/commands/os-quiet-run.md",
        "harness/shared_factory/05-knowledge/commands/os-quiet-run.md",
        "replace_if_managed_unchanged",
    ),
    (
        "harness/commands/os-groom-spec.md",
        "harness/shared_factory/05-knowledge/commands/os-groom-spec.md",
        "replace_if_managed_unchanged",
    ),
    (
        "harness/commands/os-add-spec.md",
        "harness/shared_factory/05-knowledge/commands/os-add-spec.md",
        "replace_if_managed_unchanged",
    ),
    (
        "templates/runtime/notion-organization.yml",
        "harness/shared_factory/00-control-plane/notion-organization.yml",
        "replace_if_managed_unchanged",
    ),
    (
        "harness/commands/os-notion-org.md",
        "harness/shared_factory/05-knowledge/commands/os-notion-org.md",
        "replace_if_managed_unchanged",
    ),
    (
        "harness/skills/toolsmith-reviewer/SKILL.md",
        "harness/shared_factory/05-knowledge/skills/toolsmith-reviewer/SKILL.md",
        "replace_if_managed_unchanged",
    ),
    (
        "harness/skills/quiet-async-runner/SKILL.md",
        "harness/shared_factory/05-knowledge/skills/quiet-async-runner/SKILL.md",
        "replace_if_managed_unchanged",
    ),
    (
        "harness/skills/spec-groomer/SKILL.md",
        "harness/shared_factory/05-knowledge/skills/spec-groomer/SKILL.md",
        "replace_if_managed_unchanged",
    ),
    (
        "harness/skills/spec-engine/SKILL.md",
        "harness/shared_factory/05-knowledge/skills/spec-engine/SKILL.md",
        "replace_if_managed_unchanged",
    ),
    (
        "harness/commands/project-domain-investigate.md",
        "harness/shared_factory/05-knowledge/commands/project-domain-investigate.md",
        "replace_if_managed_unchanged",
    ),
    (
        "harness/skills/project-domain-investigate/SKILL.md",
        "harness/shared_factory/05-knowledge/skills/project-domain-investigate/SKILL.md",
        "replace_if_managed_unchanged",
    ),
)

# Source-owned first-class resources are copied additively into an installed
# root.  Unlike run state and operator configuration, these directories are
# product definitions: a fresh install must be able to discover and execute
# them without reaching back into the source checkout.  ``copy_tree`` and
# ``copy_file`` deliberately preserve an existing destination so upgrades do
# not overwrite operator-owned changes.
MANAGED_RESOURCE_TREES = (
    (
        "harness/shared_factory/00-programs/project_domain_intelligence",
        "harness/shared_factory/00-programs/project_domain_intelligence",
    ),
    (
        "harness/shared_factory/05-knowledge/toolkits/project-domain-analysis",
        "harness/shared_factory/05-knowledge/toolkits/project-domain-analysis",
    ),
    (
        "harness/shared_factory/04-workflows/project-domain-architecture-analysis",
        "harness/shared_factory/04-workflows/project-domain-architecture-analysis",
    ),
)

PROJECT_STATUSES = (
    "active",
    "waiting",
    "blocked",
    "done",
)

PROJECT_CONFIG_FILES = (
    "project-profile.yml",
    "development.yml",
    "workflows.yml",
    "work-lifecycle.yml",
    "spec-engine.yml",
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
    "00-programs",
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
    "context-contract.yml",
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
    "context-contract.yml",
    "automation.md",
    "inputs.md",
    "outputs.md",
    "permissions.md",
    "failure-modes.md",
    "runbook.md",
    "tests.md",
)

PROGRAM_FILES = (
    "program.md",
    "components.yml",
    "context-pack.md",
    "crud.md",
    "documentation.md",
    "runbook.md",
    "tests.md",
    "worklog.md",
)

NAME_PATTERN = re.compile(r"^[a-z0-9_]+$")
WORKTREE_NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
SPOTLIGHT_NEVER_INDEX_FILENAME = ".metadata_never_index"


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


def installed_domain_names(root: str | Path) -> list[str]:
    """Return the domain slugs actually installed under *root*.

    A domain is any top-level directory carrying a ``domain.yml`` marker.
    Structural roots (``harness/``, and ``shared_factory`` inside it) never
    appear here because they do not live at the top level of the OS root.
    This keeps validation and routing keyed to the operator's real tree
    instead of any built-in default domain list.
    """
    os_root = expand_path(root)
    if not os_root.is_dir():
        return []
    return sorted(
        path.name
        for path in os_root.iterdir()
        if path.is_dir() and (path / "domain.yml").is_file()
    )


def validate_name(value: str, label: str = "name") -> str:
    if not NAME_PATTERN.fullmatch(value):
        # If the only problem is hyphens, suggest the snake_case form.
        snake = value.replace("-", "_")
        if NAME_PATTERN.fullmatch(snake):
            raise ValueError(
                f"{label} must use lowercase letters, numbers, and underscores only: {value!r}"
                f" — did you mean {snake!r}?"
            )
        raise ValueError(f"{label} must use lowercase letters, numbers, and underscores only: {value!r}")
    return value


def validate_worktree_name(value: str) -> str:
    if not WORKTREE_NAME_PATTERN.fullmatch(value):
        raise ValueError(
            "worktree name must start with a lowercase letter or number and use lowercase letters, "
            f"numbers, dots, hyphens, and underscores only: {value!r}"
        )
    return value


def worktree_name_from_branch(branch: str) -> str:
    name = re.sub(r"[^a-z0-9._-]+", "-", branch.lower()).strip("-.")
    if not name:
        raise ValueError(f"cannot derive a worktree name from branch: {branch!r}")
    return validate_worktree_name(name)


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


def ensure_spotlight_never_index(directory: Path, result: ScaffoldResult) -> None:
    write_file_once(directory / SPOTLIGHT_NEVER_INDEX_FILENAME, "", result)


def ensure_codex_config(
    root: Path,
    layer: str,
    result: ScaffoldResult,
    *,
    compact_context: bool = False,
) -> None:
    config_result = install_config(
        root,
        layer=layer,
        dry_run=False,
        confirm_conflicts=True,
        compact_context=compact_context,
    )
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
                "harness/bin/",
                "harness/commands/",
                "harness/registries/",
                "harness/reports/",
                "harness/rules/",
                "harness/skills/",
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


def ensure_schemas_dir(root: Path, result: ScaffoldResult) -> None:
    """Copy the repo schemas/ JSON files into harness/schemas/ so that
    installed roots are self-contained for strict validation and work even
    when the source repository is not available (e.g. pip-installed packages
    or customer machines).  Only JSON schemas are copied; the YAML
    customer-profile schema is not a SCHEMA_TARGETS target.
    """
    try:
        schemas_source = repo_root() / "schemas"
    except FileNotFoundError:
        # Running from a non-editable pip install that has no repo checkout;
        # ship the schemas from the package data directory instead.
        schemas_source = Path(__file__).parent.parent.parent / "schemas"
    if not schemas_source.is_dir():
        return
    dest = harness_path(root, "schemas")
    ensure_dir(dest, result)
    for schema_file in sorted(schemas_source.glob("*.json")):
        copy_file(schema_file, dest / schema_file.name, result)


def ensure_report_engine_contract(root: Path, result: ScaffoldResult) -> None:
    """Install additive, empty first-class report registries.

    Report content belongs to the installed OS, so source-package upgrades must
    never overwrite these registries after their first creation.
    """
    registries = {
        "report-definitions.yml": {"api_version": "report-registry/v1", "definitions": []},
        "report-runs.yml": {"api_version": "report-run-registry/v1", "runs": []},
        "report-artifacts.yml": {"api_version": "report-artifact-registry/v1", "artifacts": []},
    }
    for filename, payload in registries.items():
        write_file_once(
            harness_path(root, "registries", filename),
            yaml.safe_dump(payload, sort_keys=False),
            result,
        )


def ensure_context_migration_contract(root: Path, result: ScaffoldResult) -> None:
    """Install the empty operator-owned named context migration registry."""
    write_file_once(
        shared_factory_path(root, "00-control-plane", "context-migrations.yml"),
        yaml.safe_dump({"schema_version": 1, "migrations": []}, sort_keys=False),
        result,
    )


def copy_file_once(source: Path, destination: Path, result: ScaffoldResult) -> None:
    copy_file(source, destination, result)


def source_relative_path(relative_path: str) -> Path:
    return repo_root() / relative_path


def file_sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def managed_templates_payload() -> dict[str, object]:
    entries = []
    for source, destination, merge_policy in MANAGED_RUNTIME_FILES:
        source_path = source_relative_path(source)
        checksum = file_sha256(source_path) if source_path.is_file() else "sha256:missing"
        entries.append(
            {
                "source": source,
                "destination": destination,
                "source_version": 1,
                "source_checksum": checksum,
                "installed_checksum": checksum,
                "merge_policy": merge_policy,
            }
        )
    return {
        "schema_version": 1,
        "managed_by": "agentic-os self-improvement",
        "entries": entries,
    }


def previous_managed_checksums(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return {}
    entries = data.get("entries") if isinstance(data, dict) else []
    if not isinstance(entries, list):
        return {}
    checksums = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        destination = entry.get("destination")
        installed_checksum = entry.get("installed_checksum")
        if destination and installed_checksum:
            checksums[str(destination)] = str(installed_checksum)
    return checksums


def write_managed_file(source: Path, destination: Path, previous_checksum: str | None, result: ScaffoldResult) -> None:
    source_checksum = file_sha256(source)
    if not destination.exists():
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        result.created.append(destination)
        return
    destination_checksum = file_sha256(destination)
    if destination_checksum == source_checksum:
        result.skipped.append(destination)
        return
    if previous_checksum and destination_checksum == previous_checksum:
        shutil.copy2(source, destination)
        result.updated.append(destination)
        return
    conflict_path = destination.with_name(f"{destination.name}.new")
    if conflict_path.exists() and file_sha256(conflict_path) == source_checksum:
        result.skipped.append(conflict_path)
        return
    existed = conflict_path.exists()
    conflict_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, conflict_path)
    if existed:
        result.updated.append(conflict_path)
    else:
        result.created.append(conflict_path)


def ensure_notion_tracking_config(root: Path, result: ScaffoldResult) -> None:
    """Install the notion-tracking.yml config file into 00-control-plane if absent.

    This is a write-once install — existing operator edits are never overwritten.
    The template lives at ``templates/runtime/notion-tracking.yml`` in the source tree.
    """
    destination = shared_factory_path(root, "00-control-plane", "notion-tracking.yml")
    if destination.exists():
        result.skipped.append(destination)
        return
    source = source_relative_path("templates/runtime/notion-tracking.yml")
    if not source.is_file():
        return  # source package missing template — skip silently
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    result.created.append(destination)


def ensure_runtime_control_config(root: Path, template_name: str, destination_name: str, result: ScaffoldResult) -> None:
    destination = shared_factory_path(root, "00-control-plane", destination_name)
    if destination.exists():
        result.skipped.append(destination)
        return
    source = source_relative_path(f"templates/runtime/{template_name}")
    if not source.is_file():
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    result.created.append(destination)


def ensure_self_improvement_surface(root: Path, result: ScaffoldResult) -> None:
    for directory in ("runs", "proposals", "approvals", "drafts"):
        ensure_dir(shared_factory_path(root, "06-runs-and-logs", "self-improvement", directory), result)

    manifest_path = shared_factory_path(root, "00-control-plane", "managed-templates.yml")
    previous_checksums = previous_managed_checksums(manifest_path)
    for source, destination, _merge_policy in MANAGED_RUNTIME_FILES:
        source_path = source_relative_path(source)
        destination_path = root / destination
        write_managed_file(source_path, destination_path, previous_checksums.get(destination), result)

    desired_manifest = yaml.safe_dump(managed_templates_payload(), sort_keys=False)
    if not manifest_path.exists():
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(desired_manifest, encoding="utf-8")
        result.created.append(manifest_path)
    elif manifest_path.read_text(encoding="utf-8") == desired_manifest:
        result.skipped.append(manifest_path)
    else:
        manifest_path.write_text(desired_manifest, encoding="utf-8")
        result.updated.append(manifest_path)

    ensure_notion_tracking_config(root, result)
    ensure_runtime_control_config(root, "documentation-upkeep.yml", "documentation-upkeep.yml", result)
    ensure_runtime_control_config(root, "doc-config.yml", "doc-config.yml", result)
    ensure_runtime_control_config(root, "notion-organization.yml", "notion-organization.yml", result)
    ensure_runtime_control_config(root, "automation-control.yml", "automation-control.yml", result)
    ensure_runtime_control_config(
        root,
        "adaptive-routing-observation-report.yml",
        "adaptive-routing-observation-report.yml",
        result,
    )
    ensure_runtime_control_config(
        root,
        "adaptive-routing-pricing.yml",
        "adaptive-routing-pricing.yml",
        result,
    )


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


def ensure_managed_resource_surfaces(root: Path, result: ScaffoldResult) -> None:
    """Install source-owned programs, workflows, and toolkits additively.

    Runtime state is intentionally absent from these allowlists.  Each source
    path is a reusable definition required for cross-harness discovery; local
    receipts, schedules, articles, and project data remain operator-owned.
    """
    for source, destination in MANAGED_RESOURCE_TREES:
        source_path = source_relative_path(source)
        if source_path.is_dir():
            result.extend(copy_tree(source_path, root / destination))


def ensure_visible_capability_directories(root: Path, result: ScaffoldResult) -> None:
    for directory in VISIBLE_CAPABILITY_DIRECTORIES:
        ensure_dir(root / directory, result)


def ensure_capability_registries(root: Path, result: ScaffoldResult) -> None:
    for relative_path, payload in registry_file_payloads().items():
        merge_registry_file(root / relative_path, payload, result)
    write_file_once(harness_path(root, "INVENTORY.md"), inventory_markdown(), result)


def merge_registry_file(path: Path, payload: dict[str, list[dict[str, str]]], result: ScaffoldResult) -> None:
    if not path.exists():
        write_file_once(path, yaml.safe_dump(payload, sort_keys=False), result)
        return
    existing = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(existing, dict):
        result.skipped.append(path)
        return
    changed = False
    for key, entries in payload.items():
        current = existing.get(key)
        if not isinstance(current, list):
            existing[key] = []
            current = existing[key]
            changed = True
        current_by_id = {entry.get("id"): entry for entry in current if isinstance(entry, dict)}
        existing_ids = set(current_by_id)
        for entry in entries:
            if entry.get("id") not in existing_ids:
                current.append(entry)
                existing_ids.add(entry.get("id"))
                changed = True
                continue
            existing_entry = current_by_id.get(entry.get("id"))
            if not isinstance(existing_entry, dict):
                continue
            source = entry.get("source")
            if source and existing_entry.get("source") != source:
                existing_entry["source"] = source
                changed = True
    if changed:
        path.write_text(yaml.safe_dump(existing, sort_keys=False), encoding="utf-8")
        result.updated.append(path)
    else:
        result.skipped.append(path)


def ensure_visible_capability_surface(root: Path, result: ScaffoldResult) -> None:
    ensure_visible_capability_directories(root, result)
    ensure_capability_registries(root, result)
    hooks_root = harness_source_dir() / "hooks"
    if hooks_root.is_dir():
        result.extend(copy_tree_missing(hooks_root, harness_path(root, "hooks")))


def mirror_visible_capability_assets(root: Path) -> ScaffoldResult:
    result = ScaffoldResult()
    harness_root = harness_source_dir()
    for directory in (
        "bin",
        "commands",
        "skills",
        "mcp",
        "plugins",
        "libraries",
        "hooks",
        "reports",
        "rules",
        "shared_factory",
    ):
        source = harness_root / directory
        if source.is_dir():
            result.extend(copy_tree_missing(source, harness_path(root, directory)))
    return result


def titleize_name(name: str) -> str:
    known_names = {
        "personal": "Personal",
        "work": "Work",
        "shared_factory": "Shared Factory",
        "archive": "Archive",
    }
    return known_names.get(name, name.replace("_", " ").title())


def domain_purpose(domain: str) -> str:
    purposes = {
        "personal": "Personal administration, household operations, learning, planning, and life logistics.",
        "work": "Professional work: product delivery, client engagements, operations, and reusable service workflows.",
        "shared_factory": "Shared patterns, templates, routers, reusable automations, schemas, and cross-domain tools.",
        "archive": "Inactive work, retired projects, historical runs, and preserved decisions.",
    }
    return purposes.get(domain, "Describe the operating boundary this domain owns.")


def root_readme(domains_list: tuple[str, ...] | list[str] = DEFAULT_DOMAINS) -> str:
    domains = "\n".join(f"- `{domain}/` - {domain_purpose(domain)}" for domain in domains_list)
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


def root_router(domains_list: tuple[str, ...] | list[str] = DEFAULT_DOMAINS) -> str:
    routing_rows = "\n".join(
        f"| `{domain}` | {domain_purpose(domain)} | `{domain}/01-inbox/` |"
        for domain in domains_list
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
- Examples: requests mentioning a professional project, product, or client engagement route to that work domain; requests about household, learning, or life logistics route to `personal/`.
- If a request says `add an idea`, `capture an idea`, `idea for`, or similar, route to the matching domain's `01-inbox/` unless the user explicitly asks to create a project, workflow, automation, tracker ticket, or implementation branch.

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

## Adaptive Observe Receipt

When the installed adaptive observation config is enabled and `CODEX_THREAD_ID`
is available, run `agentic-os adaptive-routing observe --root <root> "<original
user request>"` once per substantive user task before its first action. The command analyzes
locally, never executes the route, never persists task text, and treats a
duplicate turn correlation as an idempotent no-op.

## Context Precedence

- User instructions override local defaults.
- Narrower `RULES.md` files override broader rules unless the broader rule is stricter for safety, privacy, production, billing, legal, or customer-visible work.
- `TOOLS.md` is the visible tool contract. Harness-specific install folders only implement that contract.
"""


def claude_adapter() -> str:
    return "@AGENTS.md\n"


def root_instruction_adapter(filename: str) -> str:
    """Return a root-level discovery adapter for the canonical harness contract.

    The installed root is a conversation launch point for both Claude and
    Codex.  Keep the complete contract under ``harness/``, but leave a small,
    portable entry surface at the root so neither harness starts without a
    route-read context contract after the harness-layout migration.
    """

    if filename == "AGENTS.md":
        return """# Agentic OS Root Entry Point

This directory is the automatic entry point for the installed Agentic OS.
Before replying, selecting a tool, or changing state for Agentic OS work, read
the canonical root contract in this order:

1. `harness/AGENTS.md`
2. `harness/ROUTER.md`, `harness/CONTEXT.md`, `harness/RULES.md`, and `harness/TOOLS.md`
3. The routed domain's local `AGENTS.md`, `ROUTER.md`, `CONTEXT.md`, `RULES.md`, and `TOOLS.md`

Route to the narrowest domain, project, workflow, automation, or run before
acting, then repeat the local route-read loop. `harness/` owns the canonical
root contract; these root adapters exist solely so Claude and Codex discover it
when a conversation starts in this directory.
"""
    if filename == "CLAUDE.md":
        return claude_adapter()
    title = filename.removesuffix(".md").replace("_", " ").title()
    return f"""# Agentic OS Root {title} Adapter

The canonical root `{filename}` is `harness/{filename}`. Read that file before
acting on Agentic OS work started from this directory.
"""


def ensure_root_instruction_adapters(root: Path, result: ScaffoldResult) -> None:
    for filename in ("AGENTS.md", "CLAUDE.md", "ROUTER.md", "CONTEXT.md", "RULES.md", "TOOLS.md"):
        write_file_once(root / filename, root_instruction_adapter(filename), result)


def legacy_agent_adapter() -> str:
    return """# Legacy Agent Adapter

Load `AGENTS.md` first, then follow the local route-read-cd loop.
"""


def root_context(domains_list: tuple[str, ...] | list[str] = DEFAULT_DOMAINS) -> str:
    domains = "\n".join(f"- `{domain}/` - {domain_purpose(domain)}" for domain in domains_list)
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
- When creating or changing Agentic OS commands, skills, workflows,
  automations, tools, registries, feature intake, bug intake, or project
  worktrees, follow `harness/rules/os-authoring-rules.md`.
- External source checkouts used for project work must be visible through the
  project `worktrees/` registry/link surface.

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
| `doc-config-router` | Decide where docs belong before filesystem or Notion projection work. | `shared_factory/05-knowledge/skills/doc-config-router/` |
| `spec-intake-router` | Capture new specs and future work through doc-config and work-item intake. | `shared_factory/05-knowledge/skills/spec-intake-router/` |
| `spec-groomer` | Groom rough ideas into implementation-ready specs with intent preservation, discovery, QA, and projection receipts. | `shared_factory/05-knowledge/skills/spec-groomer/` |
| `feature-intake-router` | Deprecated alias for spec intake. | `shared_factory/05-knowledge/skills/feature-intake-router/` |
| `bug-intake-router` | Capture bugs and missed enforcement through doc-config and work-item intake. | `shared_factory/05-knowledge/skills/bug-intake-router/` |
| `auto-spec-intake` | Create/update spec packets for long OS-shaping requests. | `shared_factory/05-knowledge/skills/auto-spec-intake/` |
| `auto-feature-intake` | Deprecated alias for auto spec intake. | `shared_factory/05-knowledge/skills/auto-feature-intake/` |
| `os-authoring-guard` | Apply compact OS authoring rules to reusable surface changes. | `shared_factory/05-knowledge/skills/os-authoring-guard/` |
| `automation-qualifier` | Decide whether a process is safe to automate. | `shared_factory/05-knowledge/skills/automation-qualifier/` |
| `quiet-async-runner` | Run long waits through artifact-backed async state instead of chat polling. | `shared_factory/05-knowledge/skills/quiet-async-runner/` |
| `cockpit` | Build or open the local engineering cockpit over canonical OS state. | `shared_factory/05-knowledge/skills/cockpit/` |
| `os-doctor` | Audit installed OS structure and contracts. | `shared_factory/05-knowledge/skills/os-doctor/` |

## Commands

| Command | Use When | Notes |
| --- | --- | --- |
| `/make-skill` | Create or improve a reusable skill. | Declared in `registries/commands.yml`. |
| `/make-domain` | Create a routed OS domain or room. | Declared in `registries/commands.yml`. |
| `/make-automation` | Create a guarded automation spec. | Declared in `registries/commands.yml`. |
| `/make-workflow` | Create a reusable workflow contract. | Declared in `registries/commands.yml`. |
| `/add-spec` | Capture future work through the configured spec intake workflow. | Declared in `registries/commands.yml`. |
| `/groom-spec` | Groom rough ideas into complete implementation specs with discovery and projection receipts. | Declared in `registries/commands.yml`. |
| `/new-feature` | Deprecated alias for `/add-spec`. | Declared in `registries/commands.yml`. |
| `/add-bug` | Capture a bug or missed OS enforcement into a routed work item. | Declared in `registries/commands.yml`. |
| `/auto-add-spec` | Create/update a spec packet for long OS-shaping requests. | Declared in `registries/commands.yml`. |
| `/auto-add-feature` | Deprecated alias for `/auto-add-spec`. | Declared in `registries/commands.yml`. |
| `/orchestrate` | Decompose, delegate, verify, and merge feature work. | Declared in `registries/commands.yml`. |
| `agentic-os validate` | Validate the installed root. | Run before handoff after structural changes. |
| `agentic-os route` | Route a request to a domain or workflow. | Use before creating new work. |
| `agentic-os context build` | Build a deterministic context packet. | Use for handoffs and repeatable runs. |
| `agentic-os project onboard` | Create or repair a project-local agent/config surface. | Additive by default. |
| `harness/bin/agentic-os-quiet-run` | Run long local commands with file-backed state. | Use for tests, setup, watchers, and slow waits. |
| `agentic-os cockpit snapshot/build/open` | Build or open the read-only local engineering cockpit. | Generates disposable JSON/HTML under the canonical report root. |
| `agentic-os project worktree cleanup-closed` | Move terminal-status or merged-PR worktree registrations to `worktrees/closed.yml`. | `--remove-files` deletes merged-PR checkouts unless `REOPEN.md` is present. |
| `agentic-os project work-item infer-complete` | Infer completed active work items from terminal evidence, closeout artifacts, and quiet conversation activity. | Use before `finalize-lingering` in cleanup workflows. |
| `agentic-os project work-item finalize-lingering` | Move terminal-status packets out of active lanes and refresh the global active symlink container. | Use after closeout/stale-finalization cleanup. |
| `agentic-os project work-item sync-active` | Rebuild the root `00-control-plane/active/` symlink view. | Uses filesystem work-items, project worktrees, and active automations. |
| `agentic-os thread stale-finalize --dry-run` | List work items untouched for more than 3 days before applying conservative closeout. | Dry-run by default. |
| `agentic-os config doctor` | Check Codex config contracts. | Does not store secrets. |
| `agentic-os doc-config plan` | Resolve filesystem and Notion projection destinations for documents. | Dry-run planner; external writes still require verification. |
| `agentic-os config install-tree` | Install Codex config across routed OS layers. | Dry-run by default. |

## Programs

| Program | Use When | Source |
| --- | --- | --- |
| `spec_grooming` | Turn rough ideas into implementation-ready specs while preserving original intent, discovering existing capability, and projecting to filesystem, tracker, and Notion surfaces. | `harness/shared_factory/00-programs/spec_grooming/` |

## MCP Servers

{mcp_tools_markdown()}

## Composio Tool Routes

{composio_tools_markdown()}

## Plugins And Libraries

| Name | Use When | Notes |
| --- | --- | --- |
|  |  |  |

## Local Wrappers

| Wrapper | Use When | Path |
| --- | --- | --- |
| host tool registry | Shell, terminal, runtime, package-manager, and cleanup work. | `shared_factory/05-knowledge/host-tool-registry.<host>.yml` |
| agentic-os quiet run | Detached local commands with `state.json`, `events.jsonl`, `summary.md`, and `output.log`. | `harness/bin/agentic-os-quiet-run` |

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
  programs: 00-programs
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
    composio_markdown = composio_tools_markdown(public_customer=public_customer)
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

## Composio Tool Routes

{composio_markdown}

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
    domains: tuple[str, ...] | list[str] | None = None,
) -> None:
    domains_list = tuple(domains) if domains else DEFAULT_DOMAINS
    ensure_dir(root, result)
    write_root_marker(root, result, projects_source)
    ensure_dir(harness_path(root), result)
    ensure_visible_capability_surface(root, result)
    ensure_schemas_dir(root, result)
    ensure_report_engine_contract(root, result)
    ensure_context_migration_contract(root, result)
    ensure_update_metadata(root, result)
    ensure_customer_update_contract(root, result)
    harness_root = harness_path(root)
    write_file_once(harness_root / "README.md", root_readme(domains_list), result)
    router = root_router(domains_list)
    write_file_once(harness_root / "ROUTER.md", router, result)
    write_file_once(harness_root / "AGENTS.md", agent_entrypoint("the installed Agentic OS root harness"), result)
    write_file_once(harness_root / "CLAUDE.md", claude_adapter(), result)
    write_file_once(harness_root / "CONTEXT.md", root_context(domains_list), result)
    write_file_once(harness_root / "RULES.md", root_rules(), result)
    write_file_once(harness_root / "TOOLS.md", root_tools(), result)
    ensure_root_instruction_adapters(root, result)
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

    write_file_once(domain_root / "00-programs" / "README.md", programs_readme(domain), result)

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


def ensure_default_domains(
    os_root: Path,
    result: ScaffoldResult,
    *,
    include_legacy_agent: bool = False,
    domains: tuple[str, ...] | list[str] | None = None,
) -> None:
    for domain in tuple(domains) if domains else DEFAULT_DOMAINS:
        create_domain_structure(os_root, domain, result, include_legacy_agent=include_legacy_agent)
    create_domain_structure(os_root, SHARED_FACTORY_DOMAIN, result, include_legacy_agent=include_legacy_agent)
    result.extend(copy_tree_missing(template_source_dir(), shared_factory_path(os_root, "05-knowledge", "templates")))
    result.extend(install_docs(os_root))


def init_os(
    target: str | Path,
    *,
    projects_source: str | Path = DEFAULT_PROJECTS_SOURCE,
    include_legacy_agent: bool = False,
    domains: tuple[str, ...] | list[str] | None = None,
) -> ScaffoldResult:
    """Create (or additively repair) an installed OS tree.

    ``domains`` overrides the built-in neutral ``DEFAULT_DOMAINS`` with an
    explicit domain list; each name is validated as a domain slug.
    """
    root = expand_path(target)
    domains_list = tuple(normalize_domain(domain) for domain in domains) if domains else None
    result = ScaffoldResult()
    ensure_root_files(root, result, projects_source, include_legacy_agent=include_legacy_agent, domains=domains_list)
    ensure_default_domains(root, result, include_legacy_agent=include_legacy_agent, domains=domains_list)
    return result


def install_docs(root: str | Path) -> ScaffoldResult:
    os_root = expand_path(root)
    result = ScaffoldResult()
    result.extend(mirror_visible_capability_assets(os_root))
    ensure_capability_registries(os_root, result)
    # Existing roots predate harness/schemas/; docs update is their delivery path.
    ensure_schemas_dir(os_root, result)
    ensure_report_engine_contract(os_root, result)
    ensure_context_migration_contract(os_root, result)
    copy_file(
        template_source_dir() / "runtime" / "doc-config.yml",
        shared_factory_path(os_root, "00-control-plane", "doc-config.yml"),
        result,
    )
    copy_file(
        template_source_dir() / "runtime" / "notion-organization.yml",
        shared_factory_path(os_root, "00-control-plane", "notion-organization.yml"),
        result,
    )
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
    result.extend(
        copy_tree(
            harness_source_dir() / "rules",
            shared_factory_path(os_root, "05-knowledge", "rules"),
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
            template_source_dir() / "reference",
            shared_factory_path(os_root, "05-knowledge", "references"),
        )
    )
    ensure_managed_resource_surfaces(os_root, result)
    ensure_self_improvement_surface(os_root, result)
    return result


def create_domain(root: str | Path, domain: str, *, include_legacy_agent: bool = False) -> ScaffoldResult:
    domain = normalize_domain(domain)
    os_root = expand_path(root)
    # Additive on existing trees: reuse the domains already installed on disk
    # instead of planting the built-in defaults next to an operator's custom
    # domain set. A fresh target falls back to DEFAULT_DOMAINS.
    existing = installed_domain_names(os_root)
    result = init_os(os_root, include_legacy_agent=include_legacy_agent, domains=existing or None)
    if domain not in (existing or DEFAULT_DOMAINS):
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
    remotes: list[dict[str, str]] | None = None,
) -> str:
    remotes_block = ""
    if remotes:
        remotes_block = "\n  remotes:\n"
        for r in remotes:
            name = r.get("name") or project
            host = r.get("host", "")
            path = r.get("path", "")
            kind = r.get("kind", "git")
            authority = r.get("authority", "remote")
            remotes_block += (
                f"    - name: {name}\n"
                f"      host: {host}\n"
                f"      path: {path}\n"
                f"      kind: {kind}\n"
                f"      authority: {authority}\n"
            )
    return f"""id: {project}
name: {project}
domain: {domain}
status: {status}
lane: {lane or ""}

sources:
  repo: {repo or ""}
  notion: {notion or ""}
  jira: {jira or ""}{remotes_block}

routing:
  project_root: 02-projects/{project}
  status_file: status.md
  source_map: source-map.md
  decisions: decisions.md

work_lifecycle:
  enabled: true
  source_of_truth: agentic_os
  work_items_root: work-items
  default_state: captured
  lanes:
    intake: 01-intake
    active: 02-active
    complete: 03-complete
  lane_state_map:
    01-intake: [captured, triaged]
    02-active: [specified, ready, building, validating, blocked]
    03-complete: [finished, documented, archived]
  naming:
    intake_pattern: "{{index:03d}}_{{slug}}.md"
    expanded_intake_pattern: "{{index:03d}}_{{slug}}/"
    packet_pattern: "{{index:03d}}_{{slug}}/"
    subtask_pattern: "{{parent_index:03d}}_{{subindex:02d}}_{{slug}}.md"
    default_intake_format: single_markdown
  transcript_logging:
    enabled: true
    include_raw_transcript: true
    include_tool_call_jsonl: true
    include_tool_call_markdown: true
    redaction_policy: strict
  spec_destination:
    type: local
    path: work-items/02-active
  external_tracker:
    type: none
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


def project_agents(domain: str, project: str, remotes: list[dict[str, str]] | None = None) -> str:
    remote_section = ""
    if remotes:
        lines = ["\n## Remote Sources\n"]
        for r in remotes:
            name = r.get("name") or project
            host = r.get("host", "")
            path = r.get("path", "")
            authority = r.get("authority", "remote")
            auth_note = (
                "Code is authoritative on the remote host."
                if authority == "remote"
                else "Local copy is authoritative; remote is a deploy/reference copy."
            )
            mount = r.get("mount") or {}
            mount_note = ""
            if isinstance(mount, dict) and mount.get("namespace"):
                ns = mount["namespace"]
                local_path = mount.get("local_path", f"~/{ns}/{name}")
                mount_note = (
                    f"\n  SSHFS namespace: `{local_path}` -> `{host}:{path}`."
                    " Files may be read/edited locally; repo commands run remotely."
                )
            lines.append(
                f"- **{name}** (`{host}:{path}`): {auth_note}\n"
                f"  Reach via commands in `remote/{name}/REMOTE.md`.\n"
                f"  Artifacts, work-items, and decisions stay local in this room."
                f"{mount_note}"
            )
        ssh_rule = _ssh_namespace_rule_section(remotes)
        if ssh_rule:
            lines.append(ssh_rule)
        remote_section = "\n".join(lines)
    return f"""# Agent Entry Point: {project}

This file is the harness-neutral entrypoint for this Agentic OS layer.

This is the project-local entrypoint for `{domain}/02-projects/{project}`.

## Required Loop

1. Read `ROUTER.md`, `CONTEXT.md`, `RULES.md`, `TOOLS.md`, `project.yml`, and `config/*.yml`.
2. Decide whether the request belongs in project state, `work-items/`, `src/`, a registered worktree, or `artifacts/`.
3. If source work is required, use `src/` for the canonical checkout or `worktrees/<name>` for an active branch-specific checkout.
4. Follow local `RULES.md` and tool boundaries before touching source files.
5. For lifecycle work, read the matching `work-items/<lane>/<id>` object and the state-specific files before editing.
6. Record project-known ideas in `work-items/01-intake/`, active work in `work-items/02-active/`, complete work in `work-items/03-complete/`, outputs in `artifacts/`, and execution evidence in the domain run log.

## Source Priority

- `project.yml` and `source-map.md` identify the project and canonical sources.
- `config/work-lifecycle.yml` declares lifecycle lanes and naming rules.
- `config/output-artifacts.yml` declares feature artifact roots such as `work-items/02-active/{{ticket_or_slug}}/artifacts`.
- Source repository `features/` and `.features/` folders are mirrors/artifact locations unless project config explicitly assigns lifecycle ownership there.
- `worktrees/index.yml` lists visible worktrees and their real filesystem targets.
{remote_section}
"""


def project_router(domain: str, project: str) -> str:
    return f"""# Agent Router: {project}

Route project work to the narrowest local surface before acting.

| Request Type | Route |
| --- | --- |
| New project-known idea, product thought, rough note | `work-items/01-intake/<index>_<slug>.md` |
| Domain-level idea without a known project | `<domain>/01-inbox/raw-ideas.md` |
| Lifecycle work item | `work-items/01-intake/`, `work-items/02-active/`, or `work-items/03-complete/` based on state |
| Expanded idea packet from duel/spec work | `work-items/01-intake/<index>_<slug>/` until promoted |
| Project status or next action | `status.md` |
| Source map, repo, Notion, Jira, or MCP setup | `source-map.md` and `config/*.yml` |
| Feature implementation | OS `work-items/02-active/<index>_<slug>/` for lifecycle state, then `src/` or a registered `worktrees/<name>` link for source edits |
| Feature artifact or generated output | `artifacts/` or configured source artifact root |
| Durable decision | `decisions.md` |

## Worktree Rule

Use `worktrees/index.yml` before assuming where active branch checkouts live.
Register visible worktrees with `agentic-os project worktree add {domain} {project} <name> --path <path>`.
"""


def project_context(domain: str, project: str, remotes: list[dict[str, str]] | None = None) -> str:
    remote_section = ""
    if remotes:
        lines = ["\n## Remote Sources\n"]
        for r in remotes:
            name = r.get("name") or project
            host = r.get("host", "")
            path = r.get("path", "")
            authority = r.get("authority", "remote")
            auth_note = (
                "Code is authoritative on the remote host."
                if authority == "remote"
                else "Local copy is authoritative; remote is a deploy/reference copy."
            )
            lines.append(
                f"- **{name}** (`{host}:{path}`): {auth_note}\n"
                f"  Reach via commands in `remote/{name}/REMOTE.md`.\n"
                f"  Artifacts, work-items, and decisions stay local in this room."
            )
        remote_section = "\n".join(lines)
    return f"""# Context: {project}

Describe the local room, source systems, routing hints for `{domain}/02-projects/{project}`.

This project layer is the operating surface for `{domain}/02-projects/{project}`.
It connects project state, source links, worktrees, ideas, output artifacts, and local rules.

## Load Order

1. `project.yml`
2. `source-map.md`
3. `config/project-profile.yml`
4. `config/workflows.yml`, `config/output-artifacts.yml`, and `config/validation.yml`
5. `config/work-lifecycle.yml` and the matching lane object under `work-items/` when lifecycle work is active
6. `worktrees/index.yml` when source work may use a branch checkout

## Markdown vs YAML

- Markdown files explain intent, decisions, source maps, and human-readable context.
- YAML files under `config/` are for parsed defaults, paths, validation commands, MCP boundaries, and tool declarations.
- Use Markdown with YAML front matter for hybrid specs, ideas, and ticket drafts when both narrative and machine-readable metadata are needed.
{remote_section}
"""


def _ssh_namespace_rule_section(remotes: list[dict[str, str]] | None) -> str:
    """Return the SSH_<host> managed rule section when any remote has a mount block."""
    if not remotes:
        return ""
    has_mount = any(r.get("mount") for r in remotes)
    if not has_mount:
        return ""
    return (
        "\n## SSH Remote Namespace Rule\n\n"
        "Any path component named `SSH_<host>` is an SSHFS remote namespace. "
        "Files under it may be read or edited locally, but repo commands run on "
        "`<host>` with the remote cwd from the project manifest. "
        "Do not run builds, tests, package installs, git, or watchers locally "
        "from an SSHFS path unless the operator explicitly asks for local-mount execution.\n"
    )


def project_rules(domain: str, project: str, remotes: list[dict[str, str]] | None = None) -> str:
    ssh_section = _ssh_namespace_rule_section(remotes)
    return f"""# Rules: {project}

These rules apply to `{domain}/02-projects/{project}` unless a narrower source
checkout or feature artifact defines a stricter rule.

## Operating Rules

- Do not move source repositories into the OS; keep `src` and `worktrees/*` as links unless the operator explicitly requests otherwise.
- Preserve `project.yml`, `source-map.md`, `config/*.yml`, and `worktrees/index.yml` as the project control surface.
- Use `work-items/01-intake/` for future work and proposed Specs. `ideas/` is a compatibility index, not the lifecycle source of truth.
- Use `WORKLOGS/` or `worklogs/` for human-readable work history; lowercase `logs/` is reserved for raw system output and transcripts.
- Keep exactly one canonical work object per spec. Move or promote that object through `01-intake`, `02-active`, and `03-complete` instead of copying it into competing lifecycle folders.
- Use increasing indexes for work items: `001_idea_slug.md` for default intake, `001_idea_slug/` for expanded intake or active packets, and `001_01_subtask_slug.md` for generated subtasks.
- Treat OS `work-items/` as the lifecycle source of truth. Source repo `features/` or `.features/` folders are mirrors/artifact locations unless `config/work-lifecycle.yml` explicitly says otherwise.
- Keep secrets out of markdown, YAML, generated config, logs, and artifacts.
- Follow the strictest applicable parent, project, source-repo, and workflow rule.
{ssh_section}
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
| `agentic-os project worktree cleanup-closed` | Move terminal-status or merged-PR worktree registrations to `worktrees/closed.yml`. | `--remove-files` deletes merged-PR checkouts unless `REOPEN.md` is present. |
| `agentic-os project work-item create` | Capture a project-known idea or create a lifecycle packet. | Defaults to `work-items/01-intake/<index>_<slug>.md`; use `--format packet` when intake needs multiple files. |
| `agentic-os project work-item repair` | Backfill missing lifecycle packet files and log folders on legacy or partial work items. | Use before full validation when a `work-item.md`-only packet blocks the OS. |
| `agentic-os project work-item infer-complete` | Infer completed active work items from terminal evidence, closeout artifacts, and quiet conversation activity. | Use before `finalize-lingering`; stale-only work stays active. |
| `agentic-os project work-item finalize-lingering` | Move terminal-status packets out of active lanes and update the global active symlink container. | Use after thread closeout or stale-finalization leaves finished/documented packets under `02-active/`. |
| `agentic-os project work-item sync-active` | Rebuild the root `00-control-plane/active/` symlink view from active work items, worktrees, and automations. | Use after changing active work, worktree registry entries, or automation active-work rows. |
| `agentic-os context build --project {project}` | Build a deterministic project context packet from this routed project or a unique project match. | Use `--domain {domain}` when outside the project route or when project names could collide. |
| `agentic-os validate` | Validate OS and project layer structure. | Run before handoff after scaffold changes. |
| `/add-spec` | Capture future work through doc-config and project work-item intake. | Primary command for proposed features/specs. |
| `/auto-add-spec` | Create or update a spec packet for long OS-shaping requests. | Use before implementation continues. |
| `/new-feature` | Deprecated alias for `/add-spec`. | Compatibility only. |
| `/auto-add-feature` | Deprecated alias for `/auto-add-spec`. | Compatibility only. |

## Local Paths

| Path | Use When |
| --- | --- |
| `src/` | Canonical source checkout for this project. |
| `worktrees/` | Visible links to active worktrees. |
| `config/` | Parsed project defaults and tool/workflow configuration. |
| `worklogs/` or `WORKLOGS/` | Human-readable work history and receipt summaries, matching local folder casing. |
| `ideas/` | Legacy compatibility index for project ideas; do not use as the lifecycle source of truth. |
| `work-items/01-intake/` | Canonical future-work and Spec intake, defaulting to `001_spec_slug.md`; expanded packets keep the same index as `001_spec_slug/`. |
| `work-items/02-active/` | Specified, ready, building, validating, or blocked work packets. |
| `work-items/03-complete/` | Finished, documented, or archived work packets. |
| `artifacts/` | Project outputs that do not belong in a run log. |

## Composio Tool Routes

{composio_tools_markdown()}
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


def project_config_file_content(
    domain: str,
    project: str,
    status: str,
    lane: str | None,
    filename: str,
    *,
    repo: str | None = None,
) -> str:
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
                    "specs": "work-items",
                    "worklogs": "worklogs",
                    "ideas": "work-items/01-intake",
                    "artifacts": "artifacts",
                }
            },
            sort_keys=False,
        )
    if filename == "development.yml":
        return yaml.safe_dump(
            {
                "version": 1,
                "enabled": True,
                "tracker": {"primary": "filesystem"},
                "repository": {"root": repo or "", "base_branch": "main"},
                "worktrees": {
                    "directory": "worktrees",
                    "branch_template": "feature/{ticket}-{slug}",
                },
                "work_items": {"active_status": "building"},
                "validation": {
                    "commands": [],
                    "test_policy": "risk_based_triangle",
                    "ci_fallback_on_environment_failure": True,
                },
                "review": {
                    "opposing_harness": {
                        "required": True,
                        "preferred": "claude",
                        "fallback": "codex",
                        "unavailable_policy": "continue_with_receipt",
                    }
                },
                "merge": {"policy": "never_auto"},
                "release": {"fix_version_drives_targets": True},
                "deployment": {"required": False, "monitor_after_merge": True},
                "recovery": {"max_attempts": 3, "lease_minutes": 30, "stale_after_minutes": 45},
                "retention": {"raw_logs_days": 4, "merged_worktree_grace_days": 3},
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
    if filename == "work-lifecycle.yml":
        return yaml.safe_dump(
            {
                "work_lifecycle": {
                    "enabled": True,
                    "source_of_truth": "agentic_os",
                    "work_items_root": "work-items",
                    "worklogs_root": "worklogs",
                    "default_state": "captured",
                    "lanes": {
                        "intake": "01-intake",
                        "active": "02-active",
                        "complete": "03-complete",
                    },
                    "lane_state_map": {
                        "01-intake": ["captured", "triaged"],
                        "02-active": ["specified", "ready", "building", "validating", "blocked"],
                        "03-complete": ["finished", "documented", "archived"],
                    },
                    "naming": {
                        "intake_pattern": "{index:03d}_{slug}.md",
                        "expanded_intake_pattern": "{index:03d}_{slug}/",
                        "packet_pattern": "{index:03d}_{slug}/",
                        "subtask_pattern": "{parent_index:03d}_{subindex:02d}_{slug}.md",
                        "default_intake_format": "single_markdown",
                        "default_packet_capture_file": "SPEC.md",
                        "legacy_capture_file": "IDEA.md",
                    },
                    "states": [
                        "captured",
                        "triaged",
                        "specified",
                        "ready",
                        "building",
                        "validating",
                        "finished",
                        "documented",
                        "blocked",
                        "archived",
                    ],
                    "transcript_logging": {
                        "enabled": True,
                        "include_raw_transcript": True,
                        "include_tool_call_jsonl": True,
                        "include_tool_call_markdown": True,
                        "redaction_policy": "strict",
                    },
                    "spec_destination": {
                        "type": "local",
                        "path": "work-items/02-active",
                    },
                    "external_tracker": {
                        "type": "none",
                    },
                }
            },
            sort_keys=False,
        )
    if filename == "spec-engine.yml":
        return yaml.safe_dump(
            {
                "schema_version": 1,
                "spec_engine": {
                    "enabled": True,
                    "authority": {"content": "filesystem", "lifecycle": "filesystem"},
                    "defaults": {"type": "feature", "status": "idea", "disposition": "active"},
                    "adapters": {
                        "primary": "filesystem",
                        "mirrors": [],
                        "filesystem": {"enabled": True, "work_items_root": "work-items"},
                        "linear": {"enabled": False, "mode": "backlog", "target": {}, "status_map": {}},
                        "jira": {
                            "enabled": False,
                            "mode": "sprint",
                            "target": {},
                            "placement": {"default": "backlog", "allow_active_sprint_override": True},
                            "issue_type_map": {"bug": "Bug", "feature": "Story", "config": "Task"},
                            "status_map": {},
                        },
                    },
                    "sync": {"conflict_policy": "authority_wins", "local_identity_required": True},
                },
            },
            sort_keys=False,
        )
    if filename == "output-artifacts.yml":
        return yaml.safe_dump(
            {
                "output_artifacts": {
                    "feature_root": "work-items/02-active/{ticket_or_slug}/artifacts",
                    "spec_root": "work-items/01-intake/{ticket_or_slug}",
                    "worklog_root": "worklogs/{ticket_or_slug}",
                    "project_artifacts": "artifacts",
                    "run_logs": "../../06-runs-and-logs/runs",
                    "front_matter": True,
                    "source_repo_feature_root": "src/features/{ticket_or_slug}",
                    "legacy_source_feature_root": "src/.features/{ticket_or_slug}",
                    "source_of_truth": "agentic_os",
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

Project-known ideas now start in `work-items/01-intake/`.

This folder is a compatibility index for older tools and should point to the
canonical work item instead of becoming a separate idea backlog.
"""


def ideas_raw(project: str) -> str:
    return f"""# Raw Ideas: {project}

Project-known ideas should be captured as `work-items/01-intake/NNN_slug.md`.
Use this table only as a compatibility index.

| Date | Source | Idea | Next Step |
| --- | --- | --- | --- |
"""


def worklogs_dir_name(project_root: Path) -> str:
    uppercase_markers = {"PLANS", "BUILD_LOGS", "WORKLOGS"}
    existing_names = {path.name for path in project_root.iterdir()} if project_root.exists() else set()
    if uppercase_markers.intersection(existing_names):
        return "WORKLOGS"
    return "worklogs"


def worklogs_readme(project: str) -> str:
    return f"""# Worklogs: {project}

Use this folder for human-readable work history, status receipts, and links to
evidence.

Raw command output, transcripts, async state, and large machine artifacts belong
under lowercase `logs/` or `artifacts/`, not here.
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


def append_project_remote_refs(
    source_map: Path,
    remotes: list[dict[str, str]],
    result: ScaffoldResult,
) -> None:
    """Append one source-map row per declared remote."""
    for r in remotes:
        name = r.get("name", "")
        host = r.get("host", "")
        path = r.get("path", "")
        authority = r.get("authority", "remote")
        purpose = (
            "Authoritative working tree"
            if authority == "remote"
            else "Reference working tree (local is authoritative)"
        )
        row = f"| Remote ({host}) | {host}:{path} | {purpose} | pending sync |\n"
        append_once(source_map, row, result)


def _remote_ssh_connect_cmd(host: str, root: str | Path, ssh_options: list[str] | None = None) -> str:
    """Return the interactive connect command for *host*, pulling ssh_options from hosts.yml if available."""
    if ssh_options is None:
        try:
            hosts = load_hosts(root)
            entry = hosts.get(host, {})
            ssh_options = entry.get("ssh_options") or []
        except Exception:
            ssh_options = []
    if ssh_options:
        opts_str = " ".join(ssh_options)
        return f"ssh {opts_str} {host}"
    return f"ssh {host}"


def remote_readme_content(
    project: str,
    remote: dict[str, str],
    root: str | Path,
    local_repo: str | None = None,
) -> str:
    """Return the managed REMOTE.md content for one remote entry."""
    name = remote.get("name") or project
    host = remote.get("host", "")
    path = remote.get("path", "")
    authority = remote.get("authority", "remote")

    connect_cmd = _remote_ssh_connect_cmd(host, root)
    batch_cmd = f"ssh -o BatchMode=yes {host} '<cmd>'"

    authority_stmt = (
        f"Code is **authoritative on {host}**. The local room is a read-only reference."
        if authority == "remote"
        else f"Local copy is **authoritative**. `{host}:{path}` is a deploy or reference copy."
    )
    mirror_warning = ""
    if local_repo and authority == "remote":
        mirror_warning = (
            f"\n> **Reference-only warning**: `src/` points to `{local_repo}` (local mirror). "
            f"The authoritative working tree is `{host}:{path}`. "
            f"Edits must be made on the remote; the local mirror is a reference snapshot."
        )

    return f"""# Remote: {name}

## Authority

{authority_stmt}{mirror_warning}

## Connect

Interactive session:

```sh
{connect_cmd}
cd {path}
```

Non-interactive (agent-safe):

```sh
{batch_cmd}
```

## Notes

- Sync state is tracked in `manifest.yml` alongside this file.
- Run `agentic-os project sync-remote` to refresh the manifest.
- Never commit credentials, keys, or hostnames-with-passwords here.
  All connectivity lives in `~/.ssh/config` under the alias `{host}`.
"""


def remote_manifest_stub(project: str, remote: dict[str, str]) -> str:
    """Return the initial manifest.yml stub content for one remote."""
    name = remote.get("name") or project
    host = remote.get("host", "")
    path = remote.get("path", "")
    kind = remote.get("kind", "git")
    authority = remote.get("authority", "remote")
    payload = {
        "name": name,
        "host": host,
        "path": path,
        "kind": kind,
        "authority": authority,
        "reachable": "unknown",
        "synced_at": None,
    }
    return yaml.safe_dump(payload, sort_keys=False, allow_unicode=True)


def ensure_project_remote_dirs(
    project_root: Path,
    project: str,
    remotes: list[dict[str, str]],
    root: str | Path,
    result: ScaffoldResult,
    local_repo: str | None = None,
) -> None:
    """Materialize remote/<name>/ for every declared remote."""
    for r in remotes:
        name = r.get("name") or project
        remote_dir = project_root / "remote" / name
        ensure_dir(remote_dir, result)
        # REMOTE.md is a managed file — refreshed on re-runs if the marker phrase appears
        write_project_file(
            remote_dir / "REMOTE.md",
            remote_readme_content(project, r, root, local_repo=local_repo),
            result,
            replace_markers=("Never commit credentials, keys, or hostnames-with-passwords here.",),
        )
        # manifest.yml is a stub written once; sync-remote owns it after creation
        write_file_once(
            remote_dir / "manifest.yml",
            remote_manifest_stub(project, r),
            result,
        )


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
    *,
    remotes: list[dict[str, str]] | None = None,
    root: str | Path | None = None,
    repo: str | None = None,
) -> None:
    worklogs_dir = worklogs_dir_name(project_root)
    ensure_dir(project_root / "artifacts", result)
    ensure_dir(project_root / "config", result)
    ensure_dir(project_root / worklogs_dir, result)
    ensure_dir(project_root / "ideas", result)
    ensure_dir(project_root / "work-items", result)
    for lane_name in ("01-intake", "02-active", "03-complete"):
        ensure_dir(project_root / "work-items" / lane_name, result)
    ensure_dir(project_root / "worktrees", result)
    ensure_spotlight_never_index(project_root / "worktrees", result)
    write_project_file(
        project_root / "AGENTS.md",
        project_agents(domain, project, remotes=remotes),
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
        project_context(domain, project, remotes=remotes),
        result,
        replace_markers=("Describe the local room, source systems, routing hints",),
    )
    write_project_file(
        project_root / "RULES.md",
        project_rules(domain, project, remotes=remotes),
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
    write_file_once(project_root / worklogs_dir / "README.md", worklogs_readme(project), result)
    write_file_once(project_root / "ideas" / "README.md", ideas_readme(project), result)
    write_file_once(project_root / "ideas" / "raw-ideas.md", ideas_raw(project), result)
    for filename in PROJECT_CONFIG_FILES:
        write_file_once(
            project_root / "config" / filename,
            project_config_file_content(domain, project, status, lane, filename, repo=repo),
            result,
        )
    ensure_codex_config(project_root, "project", result)
    if remotes:
        ensure_project_remote_dirs(
            project_root,
            project,
            remotes,
            root if root is not None else project_root,
            result,
            local_repo=repo,
        )


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


def _remotes_from_config(data: dict) -> list[dict[str, str]]:
    """Extract sources.remotes list from a parsed project.yml data dict."""
    sources = data.get("sources")
    if not isinstance(sources, dict):
        return []
    remotes = sources.get("remotes")
    if not isinstance(remotes, list):
        return []
    result = []
    for r in remotes:
        if isinstance(r, dict):
            result.append({str(k): str(v) for k, v in r.items() if v is not None})
    return result


def _upsert_remote_in_config(
    project_root: Path,
    project: str,
    remote: dict[str, str],
    *,
    force: bool = False,
) -> dict[str, str]:
    """Add or replace a remote entry in project.yml sources.remotes.

    Returns the final remote dict that was written.
    Raises ValueError on name conflict when force=False.
    """
    config = project_root / "project.yml"
    data = yaml.safe_load(config.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"project config must be a YAML mapping: {config}")
    sources = data.get("sources")
    if not isinstance(sources, dict):
        sources = {}
        data["sources"] = sources
    existing_remotes: list[dict] = []
    if isinstance(sources.get("remotes"), list):
        existing_remotes = sources["remotes"]

    name = remote.get("name") or project
    conflict_index = next(
        (i for i, r in enumerate(existing_remotes) if (r.get("name") or project) == name),
        None,
    )
    if conflict_index is not None and not force:
        raise ValueError(
            f"Remote {name!r} already exists in {config}. Use --force to replace."
        )
    if conflict_index is not None:
        existing_remotes[conflict_index] = remote
    else:
        existing_remotes.append(remote)
    sources["remotes"] = existing_remotes
    config.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return remote


def link_project_remote(
    root: str | Path,
    domain: str,
    project: str,
    *,
    host: str,
    path: str,
    name: str | None = None,
    kind: str = "git",
    authority: str = "remote",
    force: bool = False,
) -> ScaffoldResult:
    """Attach a remote to an existing project: update project.yml, materialize remote dir, append source-map row."""
    domain = normalize_domain(domain)
    project = validate_name(project, "project")
    os_root = expand_path(root)
    project_root = domain_path(os_root, domain) / "02-projects" / project
    if not (project_root / "project.yml").is_file():
        raise ValueError(f"project not found: {domain}/{project}")

    remote: dict[str, str] = {
        "name": name or project,
        "host": host,
        "path": path,
        "kind": kind,
        "authority": authority,
    }
    result = ScaffoldResult()
    _upsert_remote_in_config(project_root, project, remote, force=force)
    data = yaml.safe_load((project_root / "project.yml").read_text(encoding="utf-8")) or {}
    repo = str(data.get("sources", {}).get("repo") or "") or None

    ensure_project_remote_dirs(project_root, project, [remote], os_root, result, local_repo=repo)
    append_project_remote_refs(project_root / "source-map.md", [remote], result)
    # Re-run AGENTS.md and CONTEXT.md with the updated full remotes list so the section is refreshed
    all_remotes = _remotes_from_config(data)
    write_project_file(
        project_root / "AGENTS.md",
        project_agents(domain, project, remotes=all_remotes),
        result,
        replace_markers=("This file is the harness-neutral entrypoint for this Agentic OS layer",),
    )
    write_project_file(
        project_root / "CONTEXT.md",
        project_context(domain, project, remotes=all_remotes),
        result,
        replace_markers=("Describe the local room, source systems, routing hints",),
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
    remotes = _remotes_from_config(data) or None
    repo = str(data.get("sources", {}).get("repo") or "") or None
    result = ScaffoldResult()
    ensure_project_operating_surface(
        project_root,
        domain,
        project,
        str(data.get("status") or "active"),
        str(data.get("lane") or "") or None,
        result,
        remotes=remotes,
        root=os_root,
        repo=repo,
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
    entries = [entry for entry in index_data.get("worktrees") or [] if isinstance(entry, dict)]
    link_policy = (
        "symlink_to_external_worktree"
        if any(entry.get("link_policy") == "symlink_to_external_worktree" for entry in entries)
        else "in_place_worktree"
    )
    before = config_path.read_text(encoding="utf-8") if config_path.exists() else ""
    after = yaml.safe_dump(
        {
            "worktrees": {
                "directory": "worktrees",
                "index": "worktrees/index.yml",
                "link_policy": link_policy,
                "registered": entries,
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
    name = validate_worktree_name(name)
    os_root = expand_path(root)
    project_root = domain_path(os_root, domain) / "02-projects" / project
    if not (project_root / "project.yml").is_file():
        raise ValueError(f"project not found: {domain}/{project}")
    target = expand_path(path)
    if not target.is_dir():
        raise ValueError(f"worktree path must be an existing directory: {target}")

    result = onboard_project(os_root, domain, project)
    link_path = project_root / "worktrees" / name
    worktrees_root = (project_root / "worktrees").resolve()
    in_place = target.is_relative_to(worktrees_root)
    if in_place:
        if target != worktrees_root / name:
            raise ValueError(f"in-place worktree path must be the worktrees/{name} directory itself: {target}")
        result.skipped.append(link_path)
    elif link_path.is_symlink():
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
        "link_policy": "in_place_worktree" if in_place else "symlink_to_external_worktree",
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


def create_project_worktree(
    root: str | Path,
    domain: str,
    project: str,
    name: str | None = None,
    *,
    repo: str | Path,
    branch: str,
    runner: object | None = None,
) -> ScaffoldResult:
    domain = normalize_domain(domain)
    project = validate_name(project, "project")
    name = worktree_name_from_branch(branch) if name is None else validate_worktree_name(name)
    os_root = expand_path(root)
    project_root = domain_path(os_root, domain) / "02-projects" / project
    if not (project_root / "project.yml").is_file():
        raise ValueError(f"project not found: {domain}/{project}")
    repo_path = expand_path(repo)
    if not repo_path.is_dir():
        raise ValueError(f"worktree repo must be an existing local directory: {repo_path}")
    destination = project_root / "worktrees" / name
    if destination.is_symlink() or destination.exists():
        raise ValueError(f"worktree destination already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)

    run = runner or (lambda args: subprocess.run(args, capture_output=True, text=True, timeout=120))  # noqa: S603
    probe = run(["git", "-C", str(repo_path), "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}"])
    if probe.returncode == 0:
        command = ["git", "-C", str(repo_path), "worktree", "add", str(destination), branch]
    else:
        command = ["git", "-C", str(repo_path), "worktree", "add", "-b", branch, str(destination)]
    created = run(command)
    if created.returncode != 0:
        detail = (created.stderr or created.stdout or "").strip()
        raise ValueError(f"git worktree add failed for {destination}: {detail}")
    if not destination.is_dir():
        raise ValueError(f"git worktree add did not produce a directory: {destination}")
    return register_project_worktree(os_root, domain, project, name, path=destination)


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
    remotes: list[dict[str, str]] | None = None,
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
    write_file_once(project_root / "project.yml", project_config(domain, project, status, lane, repo, notion, jira, remotes=remotes), result)
    write_file_once(project_root / "status.md", project_status(project, status), result)
    write_file_once(project_root / "decisions.md", project_decisions(project), result)
    write_file_once(project_root / "source-map.md", project_source_map(project, repo, notion, jira), result)
    ensure_project_source_link(project_root, repo, result)
    ensure_project_operating_surface(project_root, domain, project, status, lane, result, remotes=remotes, root=root, repo=repo)

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
    if remotes:
        append_project_remote_refs(project_root / "source-map.md", remotes, result)
    return result


def programs_readme(scope: str) -> str:
    display_name = titleize_name(scope)
    return f"""# Programs: {display_name}

This folder contains OSProgram and InstanceOSProgram contracts for discrete
capabilities that span multiple skills, commands, workflows, automations,
scripts, templates, schedules, documentation, or external state surfaces.

Create one folder per program and keep `components.yml`, `documentation.md`,
`runbook.md`, `tests.md`, and `worklog.md` current with the owned surfaces.
"""


def program_agent_entrypoint(program_type: str, name: str) -> str:
    return f"""# Agent Entry Point: {name}

This layer owns the `{name}` {program_type}.

## Startup Loop

1. Read `ROUTER.md`, `CONTEXT.md`, `RULES.md`, `TOOLS.md`, and `program.md`.
2. Classify the request as create, read, update, delete, investigate, operate,
   validate, document, or promote.
3. Load `components.yml` and only the linked surfaces needed for that operation.
4. Make the requested change across every affected component.
5. Update `documentation.md`, `worklog.md`, and validation receipts before handoff.

## Precedence

Active user instructions win. The strictest safety, approval, privacy, Notion,
secret-handling, and destructive-action rule wins across all loaded files.
"""


def program_router(program_type: str, name: str) -> str:
    return f"""# Router: {name}

Use this router when a prompt names `{name}` or any alias listed in `program.md`.

## CRUD Routes

| Intent | Load First | Also Inspect | Required Output |
| --- | --- | --- | --- |
| Create capability surface | `program.md`, `components.yml`, `documentation.md` | command docs, skill adapters, workflow/automation specs | scaffolded files plus updated docs |
| Read or explain behavior | `context-pack.md`, `components.yml` | source scripts, run logs, Notion/database links | concise source-backed explanation |
| Update or tweak behavior | `crud.md`, `components.yml`, owning component specs | scripts, commands, schedules, templates, tests | changed component plus docs/worklog/tests |
| Delete or retire | `RULES.md`, `components.yml`, `runbook.md` | schedules, Notion pages, archives | explicit approval before destructive action |
| Investigate failure | `runbook.md`, `tests.md`, latest logs/state | external source receipts | root cause, fix, validation receipt |
| Promote to shared OS | `documentation.md`, `components.yml` | source package docs/templates/tests | source-package patch and migration notes |

## Routing Rules

- Treat the program as the ownership boundary for named capability changes.
- Route to the narrowest linked workflow, automation, skill, command, or script
  only after this program context is loaded.
- Update surrounding docs, tests, routing, schedules, and registries when a
  behavior change affects them.
"""


def program_context(program_type: str, name: str) -> str:
    return f"""# Context: {name}

`{name}` is a {program_type}: a discrete OS capability that may span multiple
execution and documentation surfaces.

## Load Order

1. `program.md` for purpose, aliases, owner, status, and linked surfaces.
2. `components.yml` for canonical component paths.
3. `crud.md` for how create/read/update/delete work should propagate.
4. `runbook.md` and `tests.md` for operation and validation.
5. Linked component files only as needed.

## Documentation Contract

Every material OS-level feature change must update filesystem docs, affected
linked surfaces, Notion projection notes when present, and `worklog.md`.
"""


def program_rules(program_type: str, name: str) -> str:
    return f"""# Rules: {name}

The strictest applicable rule wins across parent domain, shared factory,
component, and program files.

## Program Boundaries

- This folder owns context and documentation for the `{name}` {program_type}.
- Do not update a linked skill, command, workflow, automation, schedule, Notion
  database, script, or template without updating this program's documentation.
- Do not create undocumented OS-level behavior.

## Safety

- Secrets stay out of prompts, docs, logs, code, generated config, and Notion.
- External writes, destructive actions, production changes, billing/legal
  changes, and customer-visible output require approval gates.
"""


def program_tools(program_type: str, name: str) -> str:
    return f"""# Tools: {name}

List the tools, commands, skills, scripts, and external systems this {program_type}
is allowed to use.

## Skills

| Skill | Use When | Source |
| --- | --- | --- |
| `program-builder` | Creating or updating OSProgram / InstanceOSProgram contracts. | `harness/skills/program-builder/SKILL.md` |
| `os-authoring-guard` | Editing OS commands, skills, workflows, automations, tools, registries, or templates. | `harness/skills/os-authoring-guard/SKILL.md` |

## Commands

| Command | Use When | Notes |
| --- | --- | --- |
| `agentic-os program create` | Create a shared OSProgram. | Writes under `harness/shared_factory/00-programs/`. |
| `agentic-os instance-program create` | Create an instance/domain program. | Writes under `<domain>/00-programs/`. |
"""


def program_components(name: str, program_type: str) -> str:
    return yaml.safe_dump(
        {
            "schema_version": 1,
            "name": name,
            "type": program_type,
            "aliases": [],
            "components": {
                "skills": [],
                "commands": [],
                "workflows": [],
                "automations": [],
                "scripts": [],
                "templates": [],
                "documentation": [],
                "notion": [],
                "schedules": [],
                "state": [],
            },
            "context_routes": {
                "create": ["program.md", "components.yml", "documentation.md"],
                "read": ["context-pack.md", "components.yml"],
                "update": ["crud.md", "components.yml", "tests.md"],
                "delete": ["RULES.md", "components.yml", "runbook.md"],
                "investigate": ["runbook.md", "tests.md", "worklog.md"],
            },
            "documentation_required": True,
        },
        sort_keys=False,
    )


def program_scaffold_content(
    name: str,
    filename: str,
    *,
    program_type: str,
    domain: str | None = None,
) -> str:
    scope = domain or "shared_factory"
    created = datetime.now(timezone.utc).date().isoformat()
    if filename == "program.md":
        return f"""# {program_type}: {name}

## Status

- Status: scaffolded
- Owner: OS Owner
- Created: {created}
- Scope: `{scope}`
- Documentation required: yes

## Purpose

Explain what discrete OS capability this program owns and why it exists.

## Aliases

- `{name}`

## Owned Surfaces

List every skill, command, workflow, automation, script, template, Notion page or
database, schedule, state file, and documentation surface this program owns.
Keep `components.yml` as the machine-readable source of truth.
"""
    if filename == "components.yml":
        return program_components(name, program_type)
    if filename == "context-pack.md":
        return f"""# Context Pack: {name}

## Load First

1. `program.md`
2. `components.yml`
3. `crud.md`
4. `runbook.md`
5. `tests.md`
"""
    if filename == "crud.md":
        return f"""# CRUD Contract: {name}

## Create

- Add the new component surface.
- Register it in `components.yml`.
- Add routing/docs/tests before use.

## Read

- Explain behavior from `program.md`, `components.yml`, source scripts, and latest receipts.

## Update

- Patch the owning component.
- Update linked docs, commands, skills, workflows, automations, templates,
  schedules, state docs, and tests affected by the change.
- Record validation in `worklog.md`.

## Delete / Retire

- Require explicit approval before destructive changes.
- Disable schedules before removing files or external surfaces.
"""
    if filename == "documentation.md":
        return f"""# Documentation Map: {name}

## Filesystem Documentation

| Surface | Path | Update Trigger |
| --- | --- | --- |
| Program contract | `program.md` | Any ownership or behavior change |
| Components registry | `components.yml` | Any linked surface change |
| CRUD contract | `crud.md` | Any routing/update policy change |
| Runbook/tests | `runbook.md`, `tests.md` | Any operation or validation change |
"""
    if filename == "runbook.md":
        return f"""# Runbook: {name}

## Investigate

1. Load the program startup loop.
2. Read `components.yml`.
3. Inspect latest logs/state for linked automations or workflows.
4. Identify whether the issue is routing, source data, permissions, schedule,
   code, documentation drift, or external system access.

## Update

1. Patch the narrowest owning component.
2. Update surrounding docs and registries.
3. Run focused validation.
4. Record the receipt in `worklog.md`.
"""
    if filename == "tests.md":
        return f"""# Tests: {name}

## Static Checks

- `components.yml` lists every owned surface.
- `program.md`, `crud.md`, `documentation.md`, and `runbook.md` are current.
- Linked command/skill/workflow/automation docs match implementation.
"""
    return f"""# Worklog: {name}

| Date | Actor | Change | Validation | Follow-up |
| --- | --- | --- | --- | --- |
"""


def create_program(root: str | Path, name: str) -> ScaffoldResult:
    name = validate_name(name, "program")
    os_root = expand_path(root)
    result = ScaffoldResult()
    programs_root = shared_factory_path(os_root, "00-programs")
    ensure_dir(programs_root, result)
    write_file_once(programs_root / "README.md", programs_readme("shared_factory"), result)
    program_root = programs_root / name
    ensure_dir(program_root, result)
    ensure_dir(program_root / "artifacts", result)
    write_file_once(program_root / "AGENTS.md", program_agent_entrypoint("OSProgram", name), result)
    write_file_once(program_root / "ROUTER.md", program_router("OSProgram", name), result)
    write_file_once(program_root / "CONTEXT.md", program_context("OSProgram", name), result)
    write_file_once(program_root / "RULES.md", program_rules("OSProgram", name), result)
    write_file_once(program_root / "TOOLS.md", program_tools("OSProgram", name), result)
    for filename in PROGRAM_FILES:
        write_file_once(program_root / filename, program_scaffold_content(name, filename, program_type="OSProgram"), result)
    ensure_codex_config(program_root, "workflow_or_task", result)
    return result


def create_instance_program(root: str | Path, domain: str, name: str) -> ScaffoldResult:
    domain = normalize_domain(domain)
    name = validate_name(name, "instance program")
    result = create_domain(root, domain)
    domain_root = domain_path(root, domain)
    programs_root = domain_root / "00-programs"
    ensure_dir(programs_root, result)
    write_file_once(programs_root / "README.md", programs_readme(domain), result)
    program_root = programs_root / name
    ensure_dir(program_root, result)
    ensure_dir(program_root / "artifacts", result)
    write_file_once(program_root / "AGENTS.md", program_agent_entrypoint("InstanceOSProgram", name), result)
    write_file_once(program_root / "ROUTER.md", program_router("InstanceOSProgram", name), result)
    write_file_once(program_root / "CONTEXT.md", program_context("InstanceOSProgram", name), result)
    write_file_once(program_root / "RULES.md", program_rules("InstanceOSProgram", name), result)
    write_file_once(program_root / "TOOLS.md", program_tools("InstanceOSProgram", name), result)
    for filename in PROGRAM_FILES:
        write_file_once(
            program_root / filename,
            program_scaffold_content(name, filename, program_type="InstanceOSProgram", domain=domain),
            result,
        )
    ensure_codex_config(program_root, "workflow_or_task", result)
    append_control_signal(
        domain_root,
        "Program Status",
        f"`{name}`",
        "scaffolded",
        f"`00-programs/{name}/`",
        "InstanceOSProgram scaffold owns context routing for a discrete capability.",
        result,
    )
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
    if filename == "context-contract.yml":
        return (template_source_dir() / "context-contract" / "workflow.yml").read_text(encoding="utf-8")
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
    ensure_codex_config(workflow_root, "workflow_or_task", result, compact_context=True)
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
    if filename == "context-contract.yml":
        return (template_source_dir() / "context-contract" / "automation.yml").read_text(encoding="utf-8")
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
    ensure_codex_config(automation_root, "automation", result, compact_context=True)
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
