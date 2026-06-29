"""Offline Notion organization checks for Agentic OS."""

from __future__ import annotations

from pathlib import Path
from typing import Any
import json

import yaml

from .scaffold import expand_path, template_source_dir


CONFIG_RELATIVE_PATH = Path("harness/shared_factory/00-control-plane/notion-organization.yml")


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def default_notion_org_config() -> dict[str, Any]:
    return _load_yaml(template_source_dir() / "runtime" / "notion-organization.yml")


def installed_notion_org_config_path(root: str | Path) -> Path:
    return expand_path(root) / CONFIG_RELATIVE_PATH


def load_notion_org_config(root: str | Path, config: str | Path | None = None) -> dict[str, Any]:
    data = default_notion_org_config()
    installed = _load_yaml(installed_notion_org_config_path(root))
    data.update(installed)
    if config:
        data.update(_load_yaml(Path(config).expanduser()))
    return data


def _backup_files(backup_dir: Path) -> list[Path]:
    if not backup_dir.is_dir():
        return []
    manifest = backup_dir / "manifest.json"
    if manifest.is_file():
        rows = json.loads(manifest.read_text(encoding="utf-8"))
        return [Path(row["file"]) for row in rows if row.get("file")]
    return sorted(backup_dir.glob("*.json"))


def _plain_title(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "".join(part.get("plain_text", "") for part in value if isinstance(part, dict))
    return ""


def _root_child_page_titles(snapshot: dict[str, Any]) -> list[str]:
    root_id = snapshot.get("root_id")
    pages = snapshot.get("pages") or {}
    root = pages.get(root_id) or {}
    titles = []
    for block in root.get("blocks") or []:
        if block.get("type") == "child_page":
            titles.append(((block.get("child_page") or {}).get("title") or "").strip())
    return [title for title in titles if title]


def analyze_notion_backup(backup_dir: Path, config: dict[str, Any]) -> dict[str, Any]:
    required_buckets = [str(item) for item in config.get("project_buckets", [])]
    max_root_children = int(config.get("max_root_child_pages") or 25)
    findings: list[dict[str, Any]] = []
    roots = []
    for path in _backup_files(backup_dir):
        if path.name == "manifest.json":
            continue
        snapshot = json.loads(path.read_text(encoding="utf-8"))
        titles = _root_child_page_titles(snapshot)
        missing = [bucket for bucket in required_buckets if bucket not in titles]
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
                    "message": f"root page has {len(titles)} direct child pages; prefer canonical buckets and linked database views",
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


def analyze_os_structure(root: Path, config: dict[str, Any]) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    projects = []
    for project_yml in sorted(root.glob("*/02-projects/*/project.yml")):
        project_root = project_yml.parent
        missing = []
        for folder in ("SPECS",):
            if not (project_root / folder).is_dir():
                missing.append(folder)
        if not ((project_root / "worklogs").is_dir() or (project_root / "WORKLOGS").is_dir()):
            missing.append("worklogs or WORKLOGS")
        if missing:
            findings.append(
                {
                    "severity": "warning",
                    "path": str(project_root),
                    "message": f"project is missing filesystem mirrors: {', '.join(missing)}",
                }
            )
        projects.append(str(project_root))
    return {"project_count": len(projects), "projects": projects, "findings": findings}


def notion_org_doctor(root: str | Path, *, backup_dir: str | Path | None = None, config: str | Path | None = None) -> dict[str, Any]:
    os_root = expand_path(root)
    loaded = load_notion_org_config(os_root, config=config)
    findings: list[dict[str, Any]] = []
    os_result = analyze_os_structure(os_root, loaded)
    findings.extend(os_result["findings"])
    backup_result = None
    if backup_dir:
        backup_path = Path(backup_dir).expanduser().resolve()
        backup_result = analyze_notion_backup(backup_path, loaded)
        findings.extend(backup_result["findings"])
    else:
        findings.append(
            {
                "severity": "warning",
                "path": str(os_root),
                "message": "no Notion backup dir supplied; only filesystem mirrors were checked",
            }
        )
    return {
        "ok": not any(item["severity"] == "blocker" for item in findings),
        "config_path": str(installed_notion_org_config_path(os_root)),
        "expected_workspace": loaded.get("workspace"),
        "canonical_buckets": loaded.get("project_buckets", []),
        "os": os_result,
        "notion_backup": backup_result,
        "findings": findings,
    }
