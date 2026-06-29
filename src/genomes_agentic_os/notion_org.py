"""Notion organization checks for Agentic OS operator surfaces."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .scaffold import expand_path


CONFIG_RELATIVE_PATH = Path("harness/shared_factory/00-control-plane/notion-organization.yml")
REQUIRED_BUCKETS = {
    "Dashboard",
    "Specs",
    "Worklogs",
    "Active Work",
    "Automations",
    "Workflows",
    "Runs",
    "PRs",
    "Docs",
    "Archive",
}


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def notion_org_config_path(root: str | Path) -> Path:
    return expand_path(root) / CONFIG_RELATIVE_PATH


def doctor_notion_org(root: str | Path, *, backup_dir: str | None = None) -> dict[str, Any]:
    os_root = expand_path(root)
    config_path = notion_org_config_path(os_root)
    config = _load_yaml(config_path)
    findings: list[dict[str, str]] = []
    if not config_path.is_file():
        findings.append({"severity": "blocker", "path": str(config_path), "message": "notion-organization.yml is missing"})
    workspace = str(config.get("workspace", ""))
    if workspace != "Genome's Notion":
        findings.append({"severity": "blocker", "path": str(config_path), "message": "workspace must be Genome's Notion"})
    buckets = set(config.get("project_buckets") or [])
    for bucket in sorted(REQUIRED_BUCKETS - buckets):
        findings.append({"severity": "blocker", "path": str(config_path), "message": f"missing project bucket: {bucket}"})
    backup_config = config.get("backup") if isinstance(config.get("backup"), dict) else {}
    backup_required = bool(backup_config.get("required_before_moves", True))
    backup_path = Path(backup_dir).expanduser() if backup_dir else None
    if backup_dir and not backup_path.exists():
        findings.append({"severity": "blocker", "path": str(backup_path), "message": "backup dir does not exist"})
    elif backup_required and not backup_dir:
        findings.append(
            {
                "severity": "warning",
                "path": str(config_path),
                "message": "backup dir not supplied; live page moves remain blocked",
            }
        )
    backup_files = 0
    if backup_path and backup_path.exists():
        backup_files = sum(1 for path in backup_path.rglob("*") if path.is_file())
    return {
        "ok": not any(item["severity"] == "blocker" for item in findings),
        "root": str(os_root),
        "config_path": str(config_path),
        "workspace": workspace,
        "project_buckets": sorted(buckets),
        "backup_dir": str(backup_path) if backup_path else None,
        "backup_files": backup_files,
        "findings": findings,
        "live_moves_allowed": False,
    }


def format_notion_org_result(result: dict[str, Any]) -> str:
    return yaml.safe_dump(result, sort_keys=False).strip()
