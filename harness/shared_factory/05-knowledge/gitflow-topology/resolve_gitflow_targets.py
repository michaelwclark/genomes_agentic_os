#!/usr/bin/env python3
"""Deterministically resolve one tracker item into a PR target family."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

import yaml


def _load(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    value = json.loads(text) if path.suffix.lower() == ".json" else yaml.safe_load(text)
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain an object")
    return value


def _policy(project: dict[str, Any]) -> dict[str, Any]:
    return (
        project.get("dev_factory", {})
        .get("pull_request", {})
        .get("target_policy", {})
    )


def _tokens(ticket: dict[str, Any]) -> set[str]:
    values: list[str] = []
    for key in ("type", "issue_type", "topology_class", "route"):
        if ticket.get(key):
            values.append(str(ticket[key]))
    labels = ticket.get("labels", [])
    values.extend(str(item) for item in labels if item is not None)
    return {part.lower() for value in values for part in re.split(r"[^a-zA-Z0-9]+", value) if part}


def _fix_version(ticket: dict[str, Any]) -> str:
    return str(ticket.get("fix_version") or ticket.get("fixVersion") or "").strip()


def _same_release(left: str, right: str) -> bool:
    if not left or not right:
        return False
    a = left.removeprefix("v").split(".")
    b = right.removeprefix("v").split(".")
    width = min(len(a), len(b))
    return a[:width] == b[:width]


def _route(policy: dict[str, Any], ticket: dict[str, Any], registry: dict[str, Any]) -> str:
    explicit = ticket.get("topology_class") or ticket.get("route")
    if explicit:
        return str(explicit)
    tokens = _tokens(ticket)
    fix_version = _fix_version(ticket)
    branches = registry.get("branches", {})
    next_hotfix_fix_version = str(branches.get("next_hotfix_fix_version", ""))
    if "hotfix" in tokens or (
        fix_version and next_hotfix_fix_version and fix_version == next_hotfix_fix_version
    ):
        return "hotfix"
    if "regression" in tokens:
        return "regression"
    active_release = str(branches.get("active_release_fix_version", ""))
    prefixes = [str(item) for item in policy.get("release_fix_version_prefixes", [])]
    if fix_version and (_same_release(fix_version, active_release) or any(fix_version.startswith(p) for p in prefixes)):
        return "release"
    return "default"


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value and value not in seen:
            result.append(value)
            seen.add(value)
    return result


def _symbolic_targets(policy: dict[str, Any], route: str, registry: dict[str, Any]) -> list[str]:
    profile = str(policy.get("profile") or policy.get("strategy") or "registry_gitflow")
    if profile == "continuous_delivery":
        return list(policy.get("default_targets") or [policy.get("default", "main")])
    if profile == "promote":
        return list(policy.get("default_targets") or [policy.get("development_branch", "develop")])
    rules = registry.get("targeting_rules", {})
    if route in rules:
        return list(rules[route])
    if route == "hotfix":
        return list(policy.get("hotfix_with_active_release_targets", []))
    if route == "release":
        return list(policy.get("release_targets", []))
    return list(policy.get("default_targets") or [policy.get("default", "develop")])


def _active_release_branch(registry: dict[str, Any]) -> str | None:
    branches = registry.get("branches", {})
    direct = branches.get("next_major")
    if isinstance(direct, str) and direct:
        return direct
    active = str(branches.get("active_release_fix_version", ""))
    releases = registry.get("open_remote_branches", {}).get("release", [])
    matches = [branch for branch in releases if _same_release(branch.rsplit("/", 1)[-1], active)]
    return sorted(matches)[-1] if matches else None


def _resolve_alias(role: str, policy: dict[str, Any], registry: dict[str, Any]) -> str | None:
    branches = registry.get("branches", {})
    if role in branches and isinstance(branches[role], str):
        return branches[role]
    aliases = {
        "active_release_branch": _active_release_branch(registry),
        "release_branch": _active_release_branch(registry),
        "hotfix_branch": branches.get("next_hotfix"),
        "development_branch": policy.get("development_branch", "develop"),
        "production_branch": policy.get("production_branch", "main"),
    }
    if role in aliases:
        value = aliases[role]
        return str(value) if value else None
    if role.endswith("_branch"):
        return None
    return role


def resolve(
    project: dict[str, Any],
    ticket: dict[str, Any],
    registry: dict[str, Any] | None = None,
    existing_targets: list[str] | None = None,
) -> dict[str, Any]:
    registry = registry or {}
    policy = _policy(project)
    if not policy:
        raise ValueError("missing dev_factory.pull_request.target_policy")
    profile = str(policy.get("profile") or policy.get("strategy") or "registry_gitflow")
    route = _route(policy, ticket, registry)
    roles = _dedupe(_symbolic_targets(policy, route, registry))
    required: list[dict[str, str | None]] = []
    blockers: list[dict[str, str]] = []
    for role in roles:
        branch = _resolve_alias(role, policy, registry)
        required.append({"role": role, "branch": branch})
        if not branch:
            blockers.append({"code": "unresolved_branch_alias", "role": role})
    required_branches = _dedupe([str(item["branch"]) for item in required if item["branch"]])
    actual = None if existing_targets is None else _dedupe(existing_targets)
    missing = [] if actual is None else [branch for branch in required_branches if branch not in actual]
    unexpected = [] if actual is None else [branch for branch in actual if branch not in required_branches]
    for branch in missing:
        blockers.append({"code": "missing_required_target", "branch": branch})
    release_mode = str(policy.get("release_mode") or ("deferred" if profile == "promote" else "immediate"))
    return {
        "schema_version": 1,
        "project_id": project.get("id") or project.get("name"),
        "ticket_key": ticket.get("key") or ticket.get("id"),
        "profile": profile,
        "route": route,
        "required_targets": required,
        "existing_targets": actual,
        "missing_targets": missing,
        "unexpected_targets": unexpected,
        "family_complete": None if actual is None else not blockers,
        "propagation": policy.get("propagation", "none"),
        "release": {
            "mode": release_mode,
            "development_branch": policy.get("development_branch"),
            "production_branch": policy.get("production_branch"),
        },
        "blockers": blockers,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", required=True, type=Path)
    parser.add_argument("--ticket", required=True, type=Path)
    parser.add_argument("--registry", type=Path)
    parser.add_argument("--existing-target", action="append", default=None)
    args = parser.parse_args()
    project = _load(args.profile)
    policy = _policy(project)
    registry_path = args.registry or (Path(policy["branch_registry"]) if policy.get("branch_registry") else None)
    registry = _load(registry_path) if registry_path else {}
    print(json.dumps(resolve(project, _load(args.ticket), registry, args.existing_target), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
