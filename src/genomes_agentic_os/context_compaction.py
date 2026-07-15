"""Read-only analysis and reversible planning for compact context contracts."""

from __future__ import annotations

import base64
from collections import defaultdict
from dataclasses import dataclass, field
import hashlib
from pathlib import Path
from typing import Any, Iterable

import yaml

from .context_contracts import load_context_manifest
from .scaffold import expand_path


CONTRACT_FILENAME = "context-contract.yml"
LEGACY_CONTEXT_FILES = ("ROUTER.md", "CONTEXT.md", "RULES.md", "TOOLS.md")


@dataclass
class ContextCheckResult:
    root: Path
    targets: int = 0
    manifests: int = 0
    legacy_fallbacks: int = 0
    duplicate_groups: int = 0
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def as_dict(self) -> dict[str, Any]:
        return {
            "root": str(self.root),
            "ok": self.ok,
            "targets": self.targets,
            "manifests": self.manifests,
            "legacy_fallbacks": self.legacy_fallbacks,
            "duplicate_groups": self.duplicate_groups,
            "errors": self.errors,
            "warnings": self.warnings,
        }


def managed_context_targets(root: str | Path) -> list[Path]:
    """Return active workflow/automation folders without traversing evidence trees."""

    os_root = expand_path(root)
    targets: set[Path] = set()
    patterns = (
        "*/03-workflows/*/*",
        "*/04-automations/*/*",
        "harness/shared_factory/03-workflows/*/*",
        "harness/shared_factory/04-automations/*/*",
    )
    for pattern in patterns:
        for path in os_root.glob(pattern):
            if path.is_dir() and not path.is_symlink():
                targets.add(path)
    return sorted(targets)


def file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def duplicate_legacy_groups(targets: Iterable[Path]) -> dict[str, list[Path]]:
    by_digest: dict[str, list[Path]] = defaultdict(list)
    for target in targets:
        for filename in LEGACY_CONTEXT_FILES:
            path = target / filename
            if path.is_file():
                by_digest[file_digest(path)].append(path)
    return {
        digest: sorted(paths)
        for digest, paths in sorted(by_digest.items())
        if len({path.parent for path in paths}) > 1
    }


def check_context_contracts(root: str | Path) -> ContextCheckResult:
    os_root = expand_path(root)
    result = ContextCheckResult(root=os_root)
    targets = managed_context_targets(os_root)
    result.targets = len(targets)
    duplicate_groups = duplicate_legacy_groups(targets)
    result.duplicate_groups = len(duplicate_groups)

    for target in targets:
        manifest_path = target / CONTRACT_FILENAME
        if not manifest_path.is_file():
            result.legacy_fallbacks += 1
            result.warnings.append(f"legacy context fallback: {target.relative_to(os_root)}")
            continue
        result.manifests += 1
        try:
            manifest = load_context_manifest(manifest_path)
        except (OSError, ValueError, yaml.YAMLError) as exc:
            result.errors.append(f"invalid context contract {manifest_path.relative_to(os_root)}: {exc}")
            continue
        if manifest is None:
            result.errors.append(f"empty context contract: {manifest_path.relative_to(os_root)}")

    for digest, paths in duplicate_groups.items():
        relative = ", ".join(str(path.relative_to(os_root)) for path in paths[:4])
        suffix = f" (+{len(paths) - 4} more)" if len(paths) > 4 else ""
        result.warnings.append(f"duplicate legacy context {digest[:12]}: {relative}{suffix}")
    return result


def build_compaction_plan(root: str | Path) -> dict[str, Any]:
    """Build a deterministic, non-mutating migration and rollback plan.

    Legacy files are candidates only when an object already has a valid manifest
    and the exact content occurs in more than one managed object. Operators can
    inspect this plan before a future apply command; this function never deletes.
    """

    os_root = expand_path(root)
    targets = managed_context_targets(os_root)
    duplicate_groups = duplicate_legacy_groups(targets)
    duplicate_paths = {path for paths in duplicate_groups.values() for path in paths}
    actions: list[dict[str, Any]] = []
    rollback_files: list[dict[str, Any]] = []

    for target in targets:
        manifest_path = target / CONTRACT_FILENAME
        try:
            manifest = load_context_manifest(manifest_path) if manifest_path.is_file() else None
        except (OSError, ValueError, yaml.YAMLError):
            manifest = None
        relative_target = target.relative_to(os_root).as_posix()
        if manifest is None:
            actions.append(
                {
                    "action": "create_manifest",
                    "target": relative_target,
                    "status": "review_required",
                    "reason": "legacy object has no valid context contract",
                }
            )
            continue
        for filename in LEGACY_CONTEXT_FILES:
            path = target / filename
            if not path.is_file() or path not in duplicate_paths:
                continue
            content = path.read_bytes()
            relative_path = path.relative_to(os_root).as_posix()
            actions.append(
                {
                    "action": "remove_duplicate_after_validation",
                    "target": relative_path,
                    "status": "proposed",
                    "sha256": hashlib.sha256(content).hexdigest(),
                }
            )
            rollback_files.append(
                {
                    "path": relative_path,
                    "sha256": hashlib.sha256(content).hexdigest(),
                    "content_base64": base64.b64encode(content).decode("ascii"),
                }
            )

    actions.sort(key=lambda action: (action["target"], action["action"]))
    rollback_files.sort(key=lambda item: item["path"])
    return {
        "schema_version": 1,
        "mode": "dry_run",
        "root": str(os_root),
        "summary": {
            "targets": len(targets),
            "actions": len(actions),
            "duplicate_groups": len(duplicate_groups),
            "files_preserved_in_rollback": len(rollback_files),
        },
        "actions": actions,
        "rollback_manifest": {
            "schema_version": 1,
            "operation": "context_compact",
            "files": rollback_files,
        },
    }
