"""Evaluate declarative, side-effect-free dispatch preconditions.

The registry deliberately evaluates only local facts.  It neither runs commands
nor changes maturity, approval, or queue state; callers decide whether a failed
evaluation should prevent their own dispatch request.
"""

from __future__ import annotations

from copy import deepcopy
import hashlib
from pathlib import Path
import re
from typing import Any, Mapping

import yaml

from .scaffold import expand_path


PRECONDITION_CONFIG = "harness/shared_factory/00-control-plane/preconditions.yml"
PRECONDITION_NAME = re.compile(r"^[a-z][a-z0-9_-]{0,79}$")


def _lookup(value: Mapping[str, Any], path: str) -> Any:
    current: Any = value
    for part in path.split("."):
        if not isinstance(current, Mapping) or part not in current:
            return None
        current = current[part]
    return current


def _read_registry(root: Path) -> tuple[dict[str, Any], Path | None]:
    path = root / PRECONDITION_CONFIG
    if not path.is_file():
        return {}, None
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ValueError(f"invalid precondition registry: {exc}") from exc
    if not isinstance(value, Mapping):
        raise ValueError("precondition registry must contain an object")
    checks = value.get("preconditions", value.get("checks", {}))
    if not isinstance(checks, Mapping):
        raise ValueError("precondition registry preconditions must contain an object")
    return {str(name): deepcopy(spec) for name, spec in checks.items()}, path


def _safe_path(root: Path, value: Any) -> Path:
    if not isinstance(value, str) or not value:
        raise ValueError("path_exists precondition requires path")
    candidate = (root / value).resolve() if not Path(value).is_absolute() else Path(value).resolve()
    if not candidate.is_relative_to(root.resolve()):
        raise ValueError("precondition path must remain within the installed OS root")
    return candidate


def evaluate_preconditions(
    root: str | Path,
    names: list[Any] | tuple[Any, ...] | None,
    *,
    context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Evaluate named checks without dispatching or making any other change."""

    os_root = expand_path(root)
    requested = list(names or [])
    if not all(isinstance(name, str) and PRECONDITION_NAME.fullmatch(name) for name in requested):
        raise ValueError("preconditions must be named using lowercase letters, numbers, underscores, or hyphens")
    registry, registry_path = _read_registry(os_root)
    supplied_context = deepcopy(dict(context or {}))

    def evaluate(name: str, stack: tuple[str, ...] = ()) -> dict[str, Any]:
        if name in stack:
            return {"name": name, "ok": False, "kind": "invalid", "reason": "cyclic precondition reference"}
        spec = registry.get(name)
        if not isinstance(spec, Mapping):
            return {"name": name, "ok": False, "kind": "missing", "reason": "precondition is not registered"}
        kind = str(spec.get("type") or "")
        if kind == "always":
            ok = bool(spec.get("value", True))
            return {"name": name, "ok": ok, "kind": kind, "reason": "configured constant"}
        if kind == "path_exists":
            try:
                path = _safe_path(os_root, spec.get("path"))
            except ValueError as exc:
                return {"name": name, "ok": False, "kind": kind, "reason": str(exc)}
            return {"name": name, "ok": path.exists(), "kind": kind, "reason": "path exists" if path.exists() else "path is missing", "path": str(path.relative_to(os_root))}
        if kind in {"context_equals", "context_truthy"}:
            key = spec.get("key")
            if not isinstance(key, str) or not key:
                return {"name": name, "ok": False, "kind": kind, "reason": f"{kind} precondition requires key"}
            actual = _lookup(supplied_context, key)
            ok = bool(actual) if kind == "context_truthy" else actual == spec.get("equals")
            return {"name": name, "ok": ok, "kind": kind, "reason": "context matched" if ok else "context did not match", "key": key}
        if kind in {"all", "any"}:
            children = spec.get("checks")
            if not isinstance(children, list) or not children:
                return {"name": name, "ok": False, "kind": kind, "reason": f"{kind} precondition requires checks"}
            if not all(isinstance(child, str) and PRECONDITION_NAME.fullmatch(child) for child in children):
                return {"name": name, "ok": False, "kind": kind, "reason": "composed precondition names are invalid"}
            results = [evaluate(child, (*stack, name)) for child in children]
            ok = all(item["ok"] for item in results) if kind == "all" else any(item["ok"] for item in results)
            return {"name": name, "ok": ok, "kind": kind, "reason": "all checks passed" if ok and kind == "all" else "one check passed" if ok else "composed checks did not pass", "checks": results}
        return {"name": name, "ok": False, "kind": kind or "invalid", "reason": "unsupported precondition type"}

    checks = [evaluate(name) for name in requested]
    registry_ref = None
    if registry_path is not None:
        registry_ref = {
            "path": PRECONDITION_CONFIG,
            "sha256": hashlib.sha256(registry_path.read_bytes()).hexdigest(),
        }
    return {
        "schema_version": "precondition-evaluation/v1",
        "mode": "evaluate_only",
        "ok": all(check["ok"] for check in checks),
        "registry": registry_ref,
        "checks": checks,
    }
