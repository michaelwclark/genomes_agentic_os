"""Validation for installed Agentic OS roots."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path

import yaml

from .scaffold import (
    CONTROL_PLANE_FILES,
    DEFAULT_DOMAINS,
    DOMAIN_DIRECTORIES,
    INBOX_FILES,
    KNOWLEDGE_FILES,
    METRIC_FILES,
    STANDARD_LANES,
    expand_path,
    repo_root,
)


ROOT_FILES = (
    "README.md",
    "ROUTER.md",
    "AGENTS.md",
    "CLAUDE.md",
    "AGENT.md",
)

LEGACY_ROOT_FOLDERS = (
    "domains",
    "workflows",
    "automations",
    "inbox",
    "runs",
    "context",
    "memory",
    "notion",
    "config",
    "templates",
    "lenders",
)


SHARED_KNOWLEDGE_FILES = (
    "templates/domain/context.md",
    "templates/workflow/workflow.md",
    "templates/room/context.md",
    "templates/room/router.md",
    "templates/room/routing-table.md",
    "templates/stage/stage-context.md",
    "templates/reference/naming-conventions.md",
    "templates/reference/tool-index.md",
    "templates/reference/style-and-output-rules.md",
    "templates/reference/source-priority.md",
    "templates/reference/decision-log.md",
    "references/naming-conventions.md",
    "references/tool-index.md",
    "references/style-and-output-rules.md",
    "references/source-priority.md",
    "references/decision-log.md",
    "templates/profile/customer-os-profile.yml",
    "templates/customer/client-automation-brief.md",
    "templates/customer/automation-fit-matrix.md",
    "templates/customer/customer-handoff-checklist.md",
    "templates/planning/feature-spec.md",
    "templates/planning/future-idea.md",
    "templates/runtime/heartbeat.yml",
    "templates/runtime/schedule.yml",
    "templates/runtime/execution-target.yml",
    "templates/runtime/integration.yml",
    "templates/runtime/run-queue-item.yml",
    "templates/notion/control-plane-database-spec.md",
    "templates/notion/runtime-tracking-database-spec.md",
    "templates/runtime/connected-system.yml",
    "templates/runtime/source-provider.yml",
    "templates/runtime/watch-source.yml",
    "templates/runtime/watch-cursor.yml",
    "templates/runtime/source-event.yml",
    "templates/runtime/trigger-rule.yml",
    "templates/runtime/event-envelope.yml",
    "templates/runtime/event-ledger-index.md",
    "templates/runtime/chain-rule.yml",
    "templates/runtime/event-processing-result.yml",
    "templates/runtime/dead-letter-event.yml",
    "operating-manual/README.md",
    "operating-manual/index.html",
    "operating-manual/manual-manifest.yml",
    "operating-manual/00-start-here/update-contract.md",
    "operating-manual/03-file-formats/README.md",
    "operating-manual/04-recipes/README.md",
    "operating-manual/07-diagrams/layer-map.svg",
    "operating-manual/07-diagrams/running-os-loop.svg",
    "commands/os-route.md",
    "commands/os-create-workflow.md",
    "commands/os-create-automation.md",
    "commands/os-doctor.md",
    "commands/os-update.md",
    "commands/os-client-automation-brief.md",
    "commands/os-control-plane-bootstrap.md",
    "commands/os-context-audit.md",
    "commands/os-watch-source.md",
    "commands/os-event.md",
    "commands/os-chain.md",
    "commands/os-capture-plan.md",
    "commands/os-discover-rooms.md",
    "commands/os-runtime-init.md",
    "commands/os-heartbeat.md",
    "commands/os-integration-setup.md",
    "plans/README.md",
    "plans/00-current-state-and-gap-map.md",
    "plans/09-future-ideas-intake.md",
    "plans/11-room-first-installer-and-routing.md",
    "plans/12-factory-template-import-backlog.md",
    "plans/13-reference-and-skill-index-layer.md",
    "plans/14-client-automation-and-control-plane-playbooks.md",
    "plans/15-always-on-runtime-heartbeats-schedules-and-integrations.md",
    "plans/16-connected-source-watch-registry.md",
    "plans/17-event-graph-and-chained-automations.md",
    "skills/os-navigator/SKILL.md",
    "skills/room-builder/SKILL.md",
    "skills/workflow-builder/SKILL.md",
    "skills/automation-qualifier/SKILL.md",
    "skills/os-doctor/SKILL.md",
    "skills/client-automation-brief/SKILL.md",
    "skills/control-plane-bootstrap/SKILL.md",
    "skills/context-audit/SKILL.md",
    "skills/runtime-operator/SKILL.md",
    "skills/integration-setup/SKILL.md",
    "skills/source-watcher/SKILL.md",
    "skills/event-graph-operator/SKILL.md",
)


@dataclass
class ValidationResult:
    root: Path
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


@dataclass(frozen=True)
class CodexConfigSource:
    path: str
    purpose: str


@dataclass
class SourcePackageValidation:
    root: Path
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


REQUIRED_CODEX_CONFIG_SOURCES = (
    CodexConfigSource(
        "docs/07-agent-surfaces/codex-config-toml-inventory.md",
        "operator-facing inventory of Codex config keys, precedence, and install boundaries",
    ),
    CodexConfigSource(
        "templates/agent-config/codex-config-layer-map.yml",
        "machine-readable map of Codex config layers copied or referenced by installers",
    ),
)

OPTIONAL_CODEX_LAYER_CONFIG_SOURCES = (
    CodexConfigSource(
        "docs/07-agent-surfaces/codex-config-profiles.md",
        "profile documentation for layer-specific Codex behavior",
    ),
    CodexConfigSource(
        "templates/agent-config/codex-profiles.toml",
        "copyable Codex profile templates for global, OS, lane, workflow, and automation layers",
    ),
    CodexConfigSource(
        "templates/agent-config/codex-profile-manifest.yml",
        "install manifest describing which profile templates are required for each layer",
    ),
)


def require_file(path: Path, result: ValidationResult) -> None:
    if not path.is_file():
        result.errors.append(f"missing required file: {path}")


def require_dir(path: Path, result: ValidationResult) -> None:
    if not path.is_dir():
        result.errors.append(f"missing required folder: {path}")


def validate_domain(domain_root: Path, result: ValidationResult) -> None:
    require_dir(domain_root, result)
    require_file(domain_root / "README.md", result)
    require_file(domain_root / "ROUTER.md", result)
    require_file(domain_root / "AGENTS.md", result)
    require_file(domain_root / "CLAUDE.md", result)
    require_file(domain_root / "AGENT.md", result)
    require_file(domain_root / "CONTEXT.md", result)
    require_file(domain_root / "REFERENCES.md", result)
    require_file(domain_root / "domain.yml", result)

    for directory in DOMAIN_DIRECTORIES:
        require_dir(domain_root / directory, result)

    for filename in CONTROL_PLANE_FILES:
        require_file(domain_root / "00-control-plane" / filename, result)

    for filename in INBOX_FILES:
        require_file(domain_root / "01-inbox" / filename, result)

    require_file(domain_root / "02-projects" / "README.md", result)
    require_file(domain_root / "03-workflows" / "README.md", result)
    require_file(domain_root / "04-automations" / "README.md", result)

    for lane in STANDARD_LANES:
        require_dir(domain_root / "03-workflows" / lane, result)
        require_dir(domain_root / "04-automations" / lane, result)
        require_file(domain_root / "03-workflows" / lane / "README.md", result)
        require_file(domain_root / "04-automations" / lane / "README.md", result)

    for filename in KNOWLEDGE_FILES:
        require_file(domain_root / "05-knowledge" / filename, result)

    require_file(domain_root / "06-runs-and-logs" / "activity-log.md", result)
    require_file(domain_root / "06-runs-and-logs" / "runs" / "README.md", result)
    require_file(domain_root / "06-runs-and-logs" / "failures" / "README.md", result)

    for filename in METRIC_FILES:
        require_file(domain_root / "07-metrics" / filename, result)

    require_file(domain_root / "08-archive" / "README.md", result)


def validate_root(root: str | Path) -> ValidationResult:
    os_root = expand_path(root)
    result = ValidationResult(root=os_root)
    if not os_root.exists():
        result.errors.append(f"missing root: {os_root}")
        return result
    if not os_root.is_dir():
        result.errors.append(f"root is not a directory: {os_root}")
        return result

    for filename in ROOT_FILES:
        require_file(os_root / filename, result)

    profile_domains = profile_domain_names(os_root)
    domains_to_validate = profile_domains or list(DEFAULT_DOMAINS)
    for domain in domains_to_validate:
        validate_domain(os_root / domain, result)

    shared_knowledge = os_root / "shared_factory" / "05-knowledge"
    for filename in SHARED_KNOWLEDGE_FILES:
        require_file(shared_knowledge / filename, result)

    for folder in LEGACY_ROOT_FOLDERS:
        path = os_root / folder
        if path.exists():
            result.warnings.append(f"legacy root folder present: {path}")

    for path in sorted(os_root.rglob("*.json")):
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            result.errors.append(f"invalid JSON: {path}: {exc}")

    for pattern in ("*.yml", "*.yaml"):
        for path in sorted(os_root.rglob(pattern)):
            try:
                yaml.safe_load(path.read_text(encoding="utf-8"))
            except yaml.YAMLError as exc:
                result.errors.append(f"invalid YAML: {path}: {exc}")

    return result


def validate_source_package(source: str | Path | None = None) -> SourcePackageValidation:
    source_root = expand_path(source) if source is not None else repo_root()
    result = SourcePackageValidation(root=source_root)
    if not source_root.exists():
        result.errors.append(f"missing source package root: {source_root}")
        return result
    if not source_root.is_dir():
        result.errors.append(f"source package root is not a directory: {source_root}")
        return result

    for item in REQUIRED_CODEX_CONFIG_SOURCES:
        path = source_root / item.path
        if not path.is_file():
            result.errors.append(
                f"missing required Codex config source: {path} ({item.purpose})"
            )

    for item in OPTIONAL_CODEX_LAYER_CONFIG_SOURCES:
        path = source_root / item.path
        if not path.is_file():
            result.warnings.append(
                f"missing optional Codex layer config: {path} ({item.purpose})"
            )

    for item in (*REQUIRED_CODEX_CONFIG_SOURCES, *OPTIONAL_CODEX_LAYER_CONFIG_SOURCES):
        path = source_root / item.path
        if path.suffix not in {".yml", ".yaml"} or not path.is_file():
            continue
        try:
            yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            result.errors.append(f"invalid YAML in Codex config source: {path}: {exc}")

    return result


def profile_domain_names(root: Path) -> list[str]:
    for filename in ("profile.yml", "customer.yml"):
        path = root / filename
        if not path.is_file():
            continue
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError:
            return []
        if filename == "profile.yml":
            rooms = data.get("rooms") or []
            return [str(room.get("slug")) for room in rooms if isinstance(room, dict) and room.get("slug")]
        customer = data.get("customer") or {}
        domains = customer.get("approved_domains") or []
        return [str(domain) for domain in domains]
    return []
