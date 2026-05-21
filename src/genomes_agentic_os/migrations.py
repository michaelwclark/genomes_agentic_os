"""Reviewable local migrations for installed Agentic OS roots."""

from __future__ import annotations

from dataclasses import dataclass
import difflib
import hashlib
from pathlib import Path
from typing import Any

import yaml

from .scaffold import expand_path


MIGRATION_ID = "notion-sync-readme-v1"
TARGET = ".notion-sync/README.md"
CONTENT = """# Notion Sync Mapping

This folder stores local Notion sync planning state.

## Contract

- Filesystem state remains the source of truth.
- Apply only after the target workspace is verified.
- Mapping IDs are local until a verified live Notion write replaces them.
"""


@dataclass
class MigrationPreview:
    migration_id: str
    target: Path
    expected_sha256: str | None
    proposed_content: str

    def as_dict(self) -> dict[str, Any]:
        existing = self.target.read_text(encoding="utf-8") if self.target.is_file() else ""
        diff = "".join(
            difflib.unified_diff(
                existing.splitlines(keepends=True),
                self.proposed_content.splitlines(keepends=True),
                fromfile=str(self.target),
                tofile=f"{self.target} (proposed)",
            )
        )
        return {
            "migration_id": self.migration_id,
            "purpose": "Add the local Notion sync mapping contract README.",
            "target": str(self.target),
            "expected_sha256": self.expected_sha256,
            "approval_required": True,
            "rollback": "Remove the README or restore the previous file content from version control.",
            "diff": diff,
        }


def sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def plan_file(root: Path, migration_id: str) -> Path:
    return root / ".migrations" / f"{migration_id}.yml"


def migrate_plan(root: str | Path) -> dict[str, Any]:
    os_root = expand_path(root)
    target = os_root / TARGET
    preview = MigrationPreview(MIGRATION_ID, target, sha256(target), CONTENT)
    plan = preview.as_dict()
    plan_path = plan_file(os_root, MIGRATION_ID)
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    plan_path.write_text(yaml.safe_dump(plan, sort_keys=False), encoding="utf-8")
    return {"root": str(os_root), "migrations": [plan], "plan_path": str(plan_path)}


def migrate_apply(root: str | Path, migration_id: str) -> dict[str, Any]:
    if migration_id != MIGRATION_ID:
        raise ValueError(f"unknown migration id: {migration_id}")
    os_root = expand_path(root)
    saved_plan = load_plan(os_root, migration_id)
    target = Path(saved_plan["target"])
    expected_sha = saved_plan.get("expected_sha256")
    current_sha = sha256(target)
    if current_sha != expected_sha:
        raise ValueError(f"target changed after preview: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(CONTENT, encoding="utf-8")
    return {"root": str(os_root), "migration_id": migration_id, "applied": True, "target": str(target)}


def load_plan(root: Path, migration_id: str) -> dict[str, Any]:
    path = plan_file(root, migration_id)
    if not path.is_file():
        raise ValueError(f"migration plan is missing; run migrate plan first: {migration_id}")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"invalid migration plan: {path}")
    return data


def format_migration_result(result: dict[str, Any]) -> str:
    return yaml.safe_dump(result, sort_keys=False).strip()
