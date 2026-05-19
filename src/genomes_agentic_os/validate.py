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
)


ROOT_FILES = (
    "README.md",
    "AGENTS.md",
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


@dataclass
class ValidationResult:
    root: Path
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def require_file(path: Path, result: ValidationResult) -> None:
    if not path.is_file():
        result.errors.append(f"missing required file: {path}")


def require_dir(path: Path, result: ValidationResult) -> None:
    if not path.is_dir():
        result.errors.append(f"missing required folder: {path}")


def validate_domain(domain_root: Path, result: ValidationResult) -> None:
    require_dir(domain_root, result)
    require_file(domain_root / "README.md", result)
    require_file(domain_root / "AGENTS.md", result)
    require_file(domain_root / "AGENT.md", result)
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

    for domain in DEFAULT_DOMAINS:
        validate_domain(os_root / domain, result)

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
