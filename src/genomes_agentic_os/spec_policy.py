"""Layered configuration for the Spec Engine."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping

import yaml

from .scaffold import domain_path, expand_path, normalize_domain, repo_root, validate_name


DEFAULT_SPEC_POLICY: dict[str, Any] = {
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
}


def _deep_merge(base: Mapping[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    result = deepcopy(dict(base))
    for key, value in override.items():
        if isinstance(value, Mapping) and isinstance(result.get(key), Mapping):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"spec policy must be a mapping: {path}")
    return data


def shipped_policy_path() -> Path:
    return repo_root() / "templates" / "runtime" / "spec-engine.yml"


def policy_paths(root: str | Path, *, domain: str | None = None, project: str | None = None) -> list[Path]:
    os_root = expand_path(root)
    paths = [shipped_policy_path(), os_root / "harness" / "shared_factory" / "00-control-plane" / "spec-engine.yml"]
    if domain:
        domain_slug = normalize_domain(domain)
        domain_root = domain_path(os_root, domain_slug)
        paths.append(domain_root / "00-control-plane" / "spec-engine.yml")
        if project:
            paths.append(domain_root / "02-projects" / validate_name(project, "project") / "config" / "spec-engine.yml")
    elif project:
        raise ValueError("domain is required when project is provided")
    return paths


def load_spec_policy(
    root: str | Path,
    *,
    domain: str | None = None,
    project: str | None = None,
    invocation: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    merged: dict[str, Any] = deepcopy(DEFAULT_SPEC_POLICY)
    loaded: list[str] = ["built-in-defaults"]
    for path in policy_paths(root, domain=domain, project=project):
        data = _read_yaml(path)
        if data:
            merged = _deep_merge(merged, data)
            loaded.append(str(path))
    if invocation:
        payload = dict(invocation)
        if "spec_engine" not in payload:
            payload = {"spec_engine": payload}
        merged = _deep_merge(merged, payload)
        loaded.append("invocation")
    policy = merged.get("spec_engine")
    if not isinstance(policy, dict):
        raise ValueError("spec_engine policy must be a mapping")
    policy = deepcopy(policy)
    policy["loaded_from"] = loaded
    return policy
