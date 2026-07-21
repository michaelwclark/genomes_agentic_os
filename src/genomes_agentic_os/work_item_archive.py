"""Retention-based work-item archival with state-plane path migration."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import shutil
from typing import Any

import yaml

from .lifecycle import ARCHIVE_DIRECTORY, lifecycle_status, load_yaml_mapping, root_project_dirs
from .scaffold import expand_path
from .state import work_items
from .state.db import connect, default_db_path


DEFAULT_TERMINAL_STATES = {"finished", "documented", "archived"}
RETENTION_UNIT_DAYS = {"day": 1, "days": 1, "week": 7, "weeks": 7, "month": 30, "months": 30}


def _parse_timestamp(packet: Path, payload: dict[str, Any]) -> datetime:
    fallback = datetime.fromtimestamp(packet.stat().st_mtime, tz=timezone.utc)
    for key in ("archivable_at", "completed_at", "finished_at", "updated_at", "created_at"):
        value = payload.get(key)
        if not value:
            continue
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            continue
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    return fallback


def _project_policy(project: Path) -> tuple[Path, dict[str, Any]]:
    config = load_yaml_mapping(project / "config" / "work-lifecycle.yml")
    if isinstance(config.get("work_lifecycle"), dict):
        config = dict(config["work_lifecycle"])
    if not config:
        project_data = load_yaml_mapping(project / "project.yml")
        nested = project_data.get("work_lifecycle")
        config = dict(nested) if isinstance(nested, dict) else {}
    items = project / str(config.get("work_items_root") or "work-items")
    archive = config.get("archive") if isinstance(config.get("archive"), dict) else {}
    retention = archive.get("retention") if isinstance(archive.get("retention"), dict) else {}
    value = int(retention.get("value") or archive.get("retention_days") or 7)
    unit = str(retention.get("unit") or "days").lower()
    if value < 0:
        raise ValueError(f"archive retention value must not be negative: {project}")
    if unit not in RETENTION_UNIT_DAYS:
        raise ValueError(f"archive retention unit must be days, weeks, or months: {project}")
    return items, {
        "enabled": bool(archive.get("enabled", True)),
        "directory": str(archive.get("directory") or ARCHIVE_DIRECTORY),
        "retention_value": value,
        "retention_unit": unit,
        "retention_days": value * RETENTION_UNIT_DAYS[unit],
        "terminal_states": {
            str(value).lower()
            for value in (archive.get("terminal_states") or DEFAULT_TERMINAL_STATES)
        },
    }


def archive_retained_work_items(
    root: str | Path,
    *,
    apply: bool = False,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Plan or move terminal packets after their configured retention window."""
    os_root = expand_path(root).resolve()
    current = now or datetime.now(timezone.utc)
    candidates: list[dict[str, Any]] = []
    for project in root_project_dirs(os_root):
        items, policy = _project_policy(project)
        if not policy["enabled"] or not items.is_dir():
            continue
        target_root = items / str(policy["directory"])
        cutoff = current - timedelta(days=int(policy["retention_days"]))
        for packet in sorted(items.iterdir()):
            metadata = packet / "work.yml"
            if (
                not packet.is_dir()
                or packet == target_root
                or packet.name in {"01-intake", "02-active", "03-complete"}
                or not metadata.is_file()
                or (packet / "REOPEN.md").exists()
            ):
                continue
            payload = load_yaml_mapping(metadata)
            if lifecycle_status(payload).lower() not in policy["terminal_states"]:
                continue
            if _parse_timestamp(packet, payload) > cutoff:
                continue
            candidates.append(
                {
                    "id": str(payload.get("id") or packet.name),
                    "project": project,
                    "source": packet,
                    "destination": target_root / packet.name,
                    "retention_value": policy["retention_value"],
                    "retention_unit": policy["retention_unit"],
                    "retention_days": policy["retention_days"],
                }
            )

    result: dict[str, Any] = {
        "schema": "agentic-os-work-item-archive/v1",
        "mode": "apply" if apply else "dry-run",
        "candidate_count": len(candidates),
        "candidates": [
            {
                "id": row["id"],
                "project": str(row["project"].relative_to(os_root)),
                "from": str(row["source"].relative_to(os_root)),
                "to": str(row["destination"].relative_to(os_root)),
                    "retention_days": row["retention_days"],
                    "retention": f"{row['retention_value']} {row['retention_unit']}",
            }
            for row in candidates
        ],
        "archived": [],
        "skipped": [],
    }
    receipt_root = os_root / "harness" / "shared_factory" / "06-runs-and-logs" / "work-item-archive"

    if not apply:
        receipt_root.mkdir(parents=True, exist_ok=True)
        receipt = receipt_root / f"{current.strftime('%Y%m%dT%H%M%SZ')}-work-item-archive-dry-run.json"
        result["receipt"] = str(receipt)
        receipt.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return result

    db_path = default_db_path(os_root)
    for row in candidates:
        source = row["source"]
        destination = row["destination"]
        state_migrated = False
        try:
            if destination.exists():
                raise RuntimeError("archive destination exists")
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(destination))
            if db_path.exists():
                conn = connect(db_path)
                try:
                    work_items.migrate_path_prefix(
                        conn,
                        from_prefix=source.relative_to(os_root).as_posix(),
                        to_prefix=destination.relative_to(os_root).as_posix(),
                        dry_run=False,
                        actor="work_item_archive_health",
                    )
                    state_migrated = True
                    work_items.write_active_projection(conn, os_root)
                finally:
                    conn.close()
            if not destination.is_dir() or source.exists():
                raise RuntimeError("archive move readback failed")
            result["archived"].append(row["id"])
        except (OSError, RuntimeError, ValueError) as exc:
            if destination.exists() and not source.exists():
                shutil.move(str(destination), str(source))
            if state_migrated and db_path.exists():
                conn = connect(db_path)
                try:
                    work_items.migrate_path_prefix(
                        conn,
                        from_prefix=destination.relative_to(os_root).as_posix(),
                        to_prefix=source.relative_to(os_root).as_posix(),
                        dry_run=False,
                        actor="work_item_archive_health_rollback",
                    )
                    work_items.write_active_projection(conn, os_root)
                finally:
                    conn.close()
            result["skipped"].append({"id": row["id"], "reason": str(exc)})

    receipt_root.mkdir(parents=True, exist_ok=True)
    receipt = receipt_root / f"{current.strftime('%Y%m%dT%H%M%SZ')}-work-item-archive.json"
    result["receipt"] = str(receipt)
    receipt.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result
