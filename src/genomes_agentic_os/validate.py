"""Validation for installed Agentic OS roots."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path

import yaml

from .scaffold import BASE_FOLDERS, expand_path


@dataclass
class ValidationResult:
    root: Path
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def validate_root(root: str | Path) -> ValidationResult:
    os_root = expand_path(root)
    result = ValidationResult(root=os_root)
    if not os_root.exists():
        result.errors.append(f"missing root: {os_root}")
        return result
    if not os_root.is_dir():
        result.errors.append(f"root is not a directory: {os_root}")
        return result

    for folder in BASE_FOLDERS:
        path = os_root / folder
        if not path.is_dir():
            result.errors.append(f"missing required folder: {path}")

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
