"""Notion organization checks for Agentic OS operator surfaces."""

from __future__ import annotations

import json
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


def _backup_files(backup_dir: Path) -> list[Path]:
    if not backup_dir.is_dir():
        return []
    manifest = backup_dir / "manifest.json"
    if manifest.is_file():
        rows = json.loads(manifest.read_text(encoding="utf-8"))
        files = []
        for row in rows:
            if not isinstance(row, dict) or not row.get("file"):
                continue
            path = Path(str(row["file"])).expanduser()
            files.append(path if path.is_absolute() else backup_dir / path)
        return files
    return sorted(path for path in backup_dir.glob("*.json") if path.name != "manifest.json")


def _root_child_page_titles(snapshot: dict[str, Any]) -> list[str]:
    root_id = snapshot.get("root_id")
    pages = snapshot.get("pages") or {}
    root = pages.get(root_id) if isinstance(pages, dict) else {}
    if not isinstance(root, dict):
        return []
    titles = []
    for block in root.get("blocks") or []:
        if isinstance(block, dict) and block.get("type") == "child_page":
            titles.append(str(((block.get("child_page") or {}).get("title") or "")).strip())
    return [title for title in titles if title]


def analyze_notion_backup(backup_dir: Path, buckets: set[str], max_root_children: int) -> dict[str, Any]:
    findings: list[dict[str, str]] = []
    roots = []
    for path in _backup_files(backup_dir):
        if not path.is_file():
            continue
        snapshot = json.loads(path.read_text(encoding="utf-8"))
        titles = _root_child_page_titles(snapshot)
        missing = sorted(buckets - set(titles))
        if missing:
            findings.append(
                {
                    "severity": "warning",
                    "path": str(path),
                    "message": f"root page is missing canonical buckets: {', '.join(missing)}",
                }
            )
        if len(titles) > max_root_children:
            findings.append(
                {
                    "severity": "warning",
                    "path": str(path),
                    "message": f"root page has {len(titles)} direct child pages; prefer canonical buckets",
                }
            )
        roots.append(
            {
                "file": str(path),
                "root_id": snapshot.get("root_id"),
                "page_count": snapshot.get("page_count"),
                "database_count": snapshot.get("database_count"),
                "direct_child_pages": len(titles),
                "direct_child_titles": titles[:50],
            }
        )
    return {"backup_dir": str(backup_dir), "roots": roots, "findings": findings}


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
    backup_result = None
    if backup_path and backup_path.exists():
        backup_files = sum(1 for path in backup_path.rglob("*") if path.is_file())
        backup_result = analyze_notion_backup(
            backup_path,
            buckets,
            int(config.get("max_root_child_pages") or 25),
        )
        findings.extend(backup_result["findings"])
    return {
        "ok": not any(item["severity"] == "blocker" for item in findings),
        "root": str(os_root),
        "config_path": str(config_path),
        "workspace": workspace,
        "expected_workspace": workspace,
        "project_buckets": sorted(buckets),
        "canonical_buckets": sorted(buckets),
        "backup_dir": str(backup_path) if backup_path else None,
        "backup_files": backup_files,
        "notion_backup": backup_result,
        "findings": findings,
        "live_moves_allowed": False,
    }


def format_notion_org_result(result: dict[str, Any]) -> str:
    return yaml.safe_dump(result, sort_keys=False).strip()
