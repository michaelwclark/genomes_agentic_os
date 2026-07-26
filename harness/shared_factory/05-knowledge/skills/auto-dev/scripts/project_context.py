#!/usr/bin/env python3
"""Load and validate the `project.yml` `dev_factory` block (AC10).

Required keys are validated per design §3.3 semantics: missing-but-required
config blocks the run with `config_missing` — there are NO defaults and NO
fallback values (never fall back to LOS). Files stay the source of truth;
this module only reads and fails closed.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover - Agentic OS declares pyyaml available.
    yaml = None


SPEC_SOURCES = {"jira", "linear"}
WORKFLOW_SOURCES = {"jira", "linear", "none"}


class ConfigMissingError(Exception):
    """Raised when required dev_factory config is missing or invalid (fail closed)."""


def missing(key: str, detail: str = "") -> ConfigMissingError:
    suffix = f" ({detail})" if detail else ""
    return ConfigMissingError(f"config_missing: {key}{suffix}")


def require_dict(value: Any, key: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise missing(key, "required mapping is absent")
    return value


def load_dev_factory(path: Path) -> dict[str, Any]:
    """Parse a project.yml and return its validated dev_factory block."""
    if yaml is None:
        raise ConfigMissingError("config_missing: pyyaml (required to parse project.yml)")
    if not path.exists():
        raise missing(str(path), "project config file not found")
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise missing("dev_factory", f"{path} must contain a YAML mapping")
    dev_factory = require_dict(payload.get("dev_factory"), "dev_factory")
    if dev_factory.get("enabled") is not True:
        raise missing("dev_factory.enabled", "must be true")
    tracker = require_dict(dev_factory.get("tracker"), "dev_factory.tracker")
    spec_source = tracker.get("spec_source")
    if spec_source not in SPEC_SOURCES:
        raise missing("dev_factory.tracker.spec_source", f"must be one of {sorted(SPEC_SOURCES)}")
    workflow_source = tracker.get("workflow_source")
    if workflow_source not in WORKFLOW_SOURCES:
        raise missing("dev_factory.tracker.workflow_source", f"must be one of {sorted(WORKFLOW_SOURCES)}")
    if spec_source == "linear":
        linear = tracker.get("linear") if isinstance(tracker.get("linear"), dict) else {}
        team_id = linear.get("team_id", tracker.get("team_id"))
        if team_id in (None, ""):
            raise missing("dev_factory.tracker.linear.team_id", "required when spec_source is linear")
    repo = require_dict(dev_factory.get("repo"), "dev_factory.repo")
    if not repo.get("path"):
        raise missing("dev_factory.repo.path")
    branch = require_dict(dev_factory.get("branch"), "dev_factory.branch")
    if not branch.get("base"):
        raise missing("dev_factory.branch.base")
    merge = require_dict(dev_factory.get("merge"), "dev_factory.merge")
    if not merge.get("policy"):
        raise missing("dev_factory.merge.policy")
    return dev_factory
