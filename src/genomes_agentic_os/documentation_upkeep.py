"""Observe-mode documentation upkeep registry and drift planner."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import hashlib

import yaml

from .scaffold import expand_path


CONFIG_RELATIVE_PATH = Path("harness/shared_factory/00-control-plane/documentation-upkeep.yml")
TEMPLATE_RELATIVE_PATH = Path("templates/runtime/documentation-upkeep.yml")
INSTALLED_TEMPLATE_RELATIVE_PATH = Path("harness/shared_factory/05-knowledge/templates/runtime/documentation-upkeep.yml")
DEFAULT_RECEIPT_ROOT = Path("harness/shared_factory/06-runs-and-logs/documentation-upkeep/runs")


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def documentation_upkeep_path(root: str | Path) -> Path:
    return expand_path(root) / CONFIG_RELATIVE_PATH


def documentation_upkeep_template_path() -> Path:
    return _repo_root() / TEMPLATE_RELATIVE_PATH


def installed_documentation_upkeep_template_path(root: str | Path) -> Path:
    return expand_path(root) / INSTALLED_TEMPLATE_RELATIVE_PATH


def load_documentation_upkeep_config(root: str | Path) -> tuple[Path, dict[str, Any]]:
    path = documentation_upkeep_path(root)
    config = _load_yaml(path)
    if config:
        return path, config
    installed_template = installed_documentation_upkeep_template_path(root)
    config = _load_yaml(installed_template)
    if config:
        return installed_template, config
    return path, _load_yaml(documentation_upkeep_template_path())


def _source_hash(root: Path, sources: list[str]) -> tuple[str, list[str], list[str]]:
    digest = hashlib.sha256()
    found: list[str] = []
    missing: list[str] = []
    for source in sorted(sources):
        source_path = root / source
        digest.update(source.encode("utf-8"))
        digest.update(b"\0")
        if not source_path.is_file():
            missing.append(source)
            digest.update(b"missing")
            continue
        found.append(source)
        digest.update(hashlib.sha256(source_path.read_bytes()).hexdigest().encode("ascii"))
    return f"sha256:{digest.hexdigest()}", found, missing


def _registry_entries(config: dict[str, Any]) -> list[dict[str, Any]]:
    registry = config.get("registry")
    return [entry for entry in registry if isinstance(entry, dict)] if isinstance(registry, list) else []


def build_documentation_upkeep_plan(
    root: str | Path,
    *,
    write_receipt: bool = False,
    output_dir: str | Path | None = None,
) -> dict[str, Any]:
    os_root = expand_path(root)
    config_path, config = load_documentation_upkeep_config(os_root)
    entries: list[dict[str, Any]] = []
    counts = {"unchanged": 0, "stale": 0, "missing_sources": 0}
    for raw in _registry_entries(config):
        sources = [str(source) for source in raw.get("sources", []) or []]
        current_hash, found, missing = _source_hash(os_root, sources)
        previous_hash = str(raw.get("last_source_hash") or "")
        if missing:
            status = "missing_sources"
        elif previous_hash and previous_hash == current_hash:
            status = "unchanged"
        else:
            status = "stale"
        counts[status] += 1
        entries.append(
            {
                "id": str(raw.get("id") or ""),
                "scope": str(raw.get("scope") or ""),
                "domain": str(raw.get("domain") or ""),
                "project": str(raw.get("project") or ""),
                "title": str(raw.get("title") or ""),
                "status": status,
                "source_hash": current_hash,
                "last_source_hash": previous_hash,
                "sources_found": found,
                "sources_missing": missing,
                "target": raw.get("target", {}),
                "next_action": _next_action(status),
            }
        )
    generated_at = datetime.now(timezone.utc).isoformat()
    result: dict[str, Any] = {
        "ok": bool(config) and bool(entries),
        "mode": "observe",
        "root": str(os_root),
        "generated_at": generated_at,
        "config_path": str(config_path),
        "notion_writes": False,
        "counts": counts,
        "entry_count": len(entries),
        "entries": entries,
    }
    if not config:
        result["findings"] = [{"severity": "blocker", "message": "documentation-upkeep.yml is missing or invalid"}]
    if write_receipt:
        receipt_dir = Path(output_dir).expanduser() if output_dir else os_root / DEFAULT_RECEIPT_ROOT / _run_id(generated_at)
        receipt_dir.mkdir(parents=True, exist_ok=True)
        yaml_path = receipt_dir / "documentation-upkeep-report.yml"
        md_path = receipt_dir / "documentation-upkeep-report.md"
        yaml_path.write_text(yaml.safe_dump(result, sort_keys=False), encoding="utf-8")
        md_path.write_text(_markdown_report(result), encoding="utf-8")
        result["receipt_dir"] = str(receipt_dir)
        result["receipt_files"] = [str(yaml_path), str(md_path)]
    return result


def _next_action(status: str) -> str:
    if status == "unchanged":
        return "Skip; sources match the last recorded hash."
    if status == "missing_sources":
        return "Fix the registry sources before drafting documentation updates."
    return "Draft or review documentation update; do not write Notion in observe mode."


def _run_id(timestamp: str) -> str:
    return timestamp.replace(":", "").replace("-", "").split(".")[0].replace("T", "T")


def _markdown_report(result: dict[str, Any]) -> str:
    lines = [
        "# Documentation Upkeep Report",
        "",
        f"- Generated: `{result['generated_at']}`",
        f"- Mode: `{result['mode']}`",
        f"- Notion writes: `{result['notion_writes']}`",
        "",
        "## Counts",
        "",
    ]
    for key, value in (result.get("counts") or {}).items():
        lines.append(f"- `{key}`: {value}")
    lines.extend(["", "## Entries", ""])
    for entry in result.get("entries") or []:
        lines.extend(
            [
                f"### {entry['id']}",
                "",
                f"- Title: {entry['title']}",
                f"- Status: `{entry['status']}`",
                f"- Source hash: `{entry['source_hash']}`",
                f"- Next action: {entry['next_action']}",
                "",
            ]
        )
    return "\n".join(lines)


def format_documentation_upkeep_result(result: dict[str, Any]) -> str:
    return yaml.safe_dump(result, sort_keys=False)
