"""Read-only process-style snapshot for Agentic OS runtime state."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Any

import yaml

from .lifecycle import (
    ACTIVE_WORK_ITEM_STATES,
    active_automation_entries,
    local_project_work_items,
    root_project_dirs,
)
from .runtime_ops import RUN_QUEUE, RUNTIME_REGISTRY, _is_due, _normalized_queue
from .scaffold import expand_path
from .thread_closeout import DEFAULT_STALE_DAYS, stale_candidates


CONTROL_PLANE = Path("harness/shared_factory/00-control-plane")
CONTROL_CONFIG = "harness/shared_factory/00-control-plane/automation-control.yml"
WATCH_SOURCES_FILE = CONTROL_PLANE / "watch-sources.yml"
HARNESS_RUNS_LOG = Path("harness/shared_factory/06-runs-and-logs/harness-runs/runs.jsonl")
ACTIVE_QUEUE_STATUSES = {"queued", "running", "approval-needed"}
NOW_QUEUE_STATUSES = {"running"}
PS_MODES = ("now", "active", "all")
KIND_ORDER = {
    "process": -1,
    "queue": 0,
    "automation": 1,
    "schedule": 2,
    "heartbeat": 3,
    "watch": 4,
    "thread": 5,
    "workflow": 6,
    "harness": 7,
}
STATUS_ORDER = {
    "running": 0,
    "approval-needed": 1,
    "blocked": 2,
    "failed": 3,
    "queued": 4,
    "due": 5,
    "stale": 6,
    "building": 7,
    "validating": 8,
    "ready": 9,
    "scheduled": 10,
    "active": 11,
    "disabled": 90,
    "done": 91,
    "skipped": 92,
}
GROUP_ORDER = {
    "running_now": 0,
    "run_queue": 1,
    "automations": 2,
    "schedules": 3,
    "heartbeats": 4,
    "watchers": 5,
    "thread_closeouts": 6,
    "harness_runs": 7,
    "workflows": 8,
}
GROUP_TITLES = {
    "running_now": "RUNNING NOW",
    "run_queue": "RUN QUEUE",
    "automations": "AUTOMATIONS",
    "schedules": "SCHEDULES",
    "heartbeats": "HEARTBEATS",
    "watchers": "WATCHERS",
    "thread_closeouts": "THREAD CLOSEOUTS",
    "harness_runs": "HARNESS RUNS",
    "workflows": "WORKFLOWS",
}
STATUS_COLORS = {
    "running": "1;32",
    "queued": "1;33",
    "approval-needed": "1;35",
    "blocked": "1;31",
    "failed": "1;31",
    "due": "1;36",
    "stale": "1;33",
    "scheduled": "36",
    "active": "34",
    "building": "32",
    "validating": "36",
    "ready": "35",
    "disabled": "2",
    "done": "2",
    "skipped": "2",
}
KIND_COLORS = {
    "process": "1;32",
    "queue": "36",
    "automation": "34",
    "schedule": "35",
    "heartbeat": "35",
    "watch": "34",
    "thread": "33",
    "workflow": "32",
    "harness": "36",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def _items(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _rel(root: Path, value: str | Path | None) -> str | None:
    if not value:
        return None
    path = Path(value)
    if not path.is_absolute():
        path = root / path
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except (OSError, ValueError):
        return str(path)


def _project_ref(root: Path, project_root: Path) -> str:
    try:
        parts = project_root.resolve().relative_to(root.resolve()).parts
    except (OSError, ValueError):
        return project_root.name
    if len(parts) >= 4 and parts[:3] == ("harness", "shared_factory", "02-projects"):
        return f"shared_factory/{parts[3]}"
    if len(parts) >= 3 and parts[1] == "02-projects":
        return f"{parts[0]}/{parts[2]}"
    return project_root.name


def _row(
    kind: str,
    status: str,
    row_id: str,
    *,
    ref: str | None = None,
    detail: str | None = None,
    path: str | Path | None = None,
    root: Path | None = None,
    attrs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "kind": kind,
        "status": status,
        "id": row_id,
        "ref": ref or "",
        "detail": detail or "",
    }
    if path is not None:
        payload["path"] = _rel(root, path) if root is not None else str(path)
    if attrs:
        payload.update({key: value for key, value in attrs.items() if value not in (None, "", [])})
    return payload


def _queue_rows(root: Path, mode: str) -> list[dict[str, Any]]:
    queue = _normalized_queue(_read_yaml(root / RUN_QUEUE))
    raw_rows: list[dict[str, Any]] = []
    for item in _items(queue.get("items")):
        status = str(item.get("status") or "unknown")
        if mode == "now" and status not in NOW_QUEUE_STATUSES:
            continue
        if mode == "active" and status not in ACTIVE_QUEUE_STATUSES:
            continue
        row_id = str(item.get("id") or item.get("idempotency_key") or item.get("ref") or "queue-item")
        detail = str(item.get("command") or item.get("blocked_reason") or item.get("summary") or "")
        raw_rows.append(
            _row(
                "queue",
                status,
                row_id,
                ref=str(item.get("ref") or item.get("kind") or ""),
                detail=detail,
                path=item.get("log"),
                root=root,
                attrs={
                    "group": "running_now" if status == "running" else "run_queue",
                    "approval_state": item.get("approval_state"),
                    "created_at": item.get("created_at"),
                    "execution_target": item.get("execution_target"),
                },
            )
        )
    if mode == "all":
        return raw_rows

    grouped: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in raw_rows:
        key = (str(row["status"]), str(row.get("ref") or ""), str(row.get("detail") or ""))
        existing = grouped.get(key)
        if existing is None:
            grouped[key] = {**row, "queue_count": 1}
            continue
        existing["queue_count"] = int(existing.get("queue_count") or 1) + 1
        existing["id"] = f"{row.get('ref') or row.get('id')} x{existing['queue_count']}"
        existing.pop("created_at", None)
    return list(grouped.values())


def _schedule_rows(root: Path, mode: str, now: datetime) -> list[dict[str, Any]]:
    if mode == "now":
        return []
    registry = _read_yaml(root / RUNTIME_REGISTRY)
    rows: list[dict[str, Any]] = []
    for schedule in _items(registry.get("schedules")):
        enabled = bool(schedule.get("enabled", False))
        if mode == "active" and not enabled:
            continue
        status = "disabled"
        detail = str(schedule.get("command") or schedule.get("display_name") or "")
        try:
            if enabled:
                status = "due" if _is_due(schedule, now) else "scheduled"
        except ValueError as exc:
            status = "blocked"
            detail = str(exc)
        rows.append(
            _row(
                "schedule",
                status,
                str(schedule.get("id") or "schedule"),
                ref=str(schedule.get("cadence") or ""),
                detail=detail,
                attrs={
                    "group": "schedules",
                    "next_due_at": schedule.get("next_due_at"),
                    "last_queued_at": schedule.get("last_queued_at"),
                    "timezone": schedule.get("timezone"),
                },
            )
        )
    return rows


def _heartbeat_rows(root: Path, mode: str) -> list[dict[str, Any]]:
    if mode == "now":
        return []
    registry = _read_yaml(root / RUNTIME_REGISTRY)
    rows: list[dict[str, Any]] = []
    for heartbeat in _items(registry.get("heartbeats")):
        enabled = bool(heartbeat.get("enabled", False))
        if mode == "active" and not enabled:
            continue
        rows.append(
            _row(
                "heartbeat",
                "active" if enabled else "disabled",
                str(heartbeat.get("id") or "heartbeat"),
                ref=str(heartbeat.get("cadence") or ""),
                detail=str(heartbeat.get("display_name") or heartbeat.get("integration") or ""),
                attrs={
                    "group": "heartbeats",
                    "execution_target": heartbeat.get("execution_target"),
                    "integration": heartbeat.get("integration"),
                },
            )
        )
    return rows


def _watch_rows(root: Path, mode: str) -> list[dict[str, Any]]:
    if mode == "now":
        return []
    data = _read_yaml(root / WATCH_SOURCES_FILE)
    rows: list[dict[str, Any]] = []
    for source in _items(data.get("watch_sources")):
        enabled = bool(source.get("enabled", False))
        if mode == "active" and not enabled:
            continue
        rows.append(
            _row(
                "watch",
                "active" if enabled else "disabled",
                str(source.get("id") or "watch-source"),
                ref=str(source.get("cadence") or source.get("source_type") or ""),
                detail=str(source.get("display_name") or source.get("connected_system") or ""),
                attrs={
                    "group": "watchers",
                    "source_type": source.get("source_type"),
                    "connected_system": source.get("connected_system"),
                },
            )
        )
    return rows


def _automation_rows(root: Path, mode: str) -> list[dict[str, Any]]:
    if mode == "now":
        return []
    data = _read_yaml(root / CONTROL_CONFIG)
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for automation in _items(data.get("managed_automations")):
        enabled = bool(automation.get("enabled", False))
        if mode == "active" and not enabled:
            continue
        target = automation.get("target") if isinstance(automation.get("target"), dict) else {}
        row = _row(
            "automation",
            "active" if enabled else "disabled",
            str(automation.get("id") or "automation"),
            ref="automation-control",
            detail=str(target.get("command") or automation.get("display_name") or ""),
            attrs={
                "group": "automations",
                "source_probe": (automation.get("source_probe") or {}).get("type"),
            },
        )
        rows.append(row)
        seen.add((row["id"], row.get("path", "")))

    for automation in active_automation_entries(root):
        row_id = str(automation.get("id") or "automation")
        path = automation.get("path")
        key = (row_id, str(path or ""))
        if key in seen:
            continue
        rows.append(
            _row(
                "automation",
                str(automation.get("status") or "active"),
                row_id,
                ref="active-work",
                detail="domain active-work automation",
                path=path,
                root=root,
                attrs={
                    "group": "automations",
                    "last_activity": automation.get("last_activity"),
                    "updated_at": automation.get("updated_at"),
                },
            )
        )
    return rows


def _workflow_rows(root: Path, mode: str) -> list[dict[str, Any]]:
    if mode == "now":
        return []
    rows: list[dict[str, Any]] = []
    for project_root in root_project_dirs(root):
        ref = _project_ref(root, project_root)
        for record in local_project_work_items(project_root):
            if mode == "active" and record.status not in ACTIVE_WORK_ITEM_STATES:
                continue
            rows.append(
                _row(
                    "workflow",
                    record.status,
                    record.slug,
                    ref=ref,
                    detail=record.title,
                    path=record.path,
                    root=root,
                    attrs={"group": "workflows", "metadata": _rel(root, record.metadata_path)},
                )
            )
    return rows


def _thread_rows(root: Path, mode: str, stale_days: int) -> list[dict[str, Any]]:
    if mode == "now":
        return []
    rows: list[dict[str, Any]] = []
    for candidate in stale_candidates(root, older_than_days=stale_days):
        rows.append(
            _row(
                "thread",
                "stale",
                str(candidate.get("work_item") or "thread"),
                ref=str(candidate.get("project") or ""),
                detail=str(candidate.get("title") or candidate.get("reason") or ""),
                path=candidate.get("path"),
                root=root,
                attrs={
                    "group": "thread_closeouts",
                    "age_days": candidate.get("age_days"),
                    "last_activity": candidate.get("last_activity"),
                    "reason": candidate.get("reason"),
                },
            )
        )
    return rows


def _harness_run_rows(root: Path, mode: str) -> list[dict[str, Any]]:
    if mode == "now":
        return []
    path = root / HARNESS_RUNS_LOG
    if not path.exists():
        return []
    parsed: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(row, dict):
            continue
        host = str(row.get("host") or "")
        if host in ("", "local", "bigmac"):
            continue
        parsed.append(row)

    rows: list[dict[str, Any]] = []
    for row in parsed[-10:]:
        exit_code = row.get("exit_code")
        status = "done" if exit_code == 0 else "failed"
        detail = str(row.get("local_view_path") or row.get("remote_cwd") or row.get("output_file") or "")
        row_id = str(row.get("ts") or "harness-run")
        rows.append(
            _row(
                "harness",
                status,
                row_id,
                ref=str(row.get("host") or ""),
                detail=detail,
                path=row.get("output_file"),
                root=root,
                attrs={
                    "group": "harness_runs",
                    "harness": row.get("harness"),
                    "task_type": row.get("task_type"),
                    "remote_cwd": row.get("remote_cwd"),
                    "local_view_path": row.get("local_view_path"),
                    "exit_code": exit_code,
                },
            )
        )
    return rows


def _process_alive(pid: Any) -> bool:
    try:
        parsed = int(pid)
    except (TypeError, ValueError):
        return False
    if parsed <= 0:
        return False
    try:
        os.kill(parsed, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _state_json_candidates(root: Path) -> list[Path]:
    patterns = (
        "*/02-projects/*/work-items/02-active/*/artifacts/async-runs/*/state.json",
        "*/02-projects/*/work-items/02-active/*/runs/*/state.json",
        "harness/shared_factory/02-projects/*/work-items/02-active/*/artifacts/async-runs/*/state.json",
        "harness/shared_factory/02-projects/*/work-items/02-active/*/runs/*/state.json",
        "*/02-projects/*/team_prs/logs/async-runs/*/state.json",
        "harness/shared_factory/06-runs-and-logs/runs/*/state.json",
    )
    seen: set[str] = set()
    paths: list[Path] = []
    for pattern in patterns:
        for path in root.glob(pattern):
            key = str(path)
            if key in seen:
                continue
            seen.add(key)
            paths.append(path)
    return paths


def _running_process_rows(root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in _state_json_candidates(root):
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if str(state.get("status") or "") != "running" or not _process_alive(state.get("pid")):
            continue
        run_dir = path.parent
        label = str(state.get("label") or state.get("id") or run_dir.name)
        command = state.get("command")
        if isinstance(command, list):
            detail = " ".join(str(part) for part in command)
        else:
            detail = str(command or state.get("work_dir") or "")
        rows.append(
            _row(
                "process",
                "running",
                label,
                ref=str(state.get("pid") or ""),
                detail=detail,
                path=path,
                root=root,
                attrs={
                    "group": "running_now",
                    "pid": state.get("pid"),
                    "started_at": state.get("started_at"),
                    "updated_at": state.get("updated_at"),
                },
            )
        )
    return rows


def _sort_key(row: dict[str, Any]) -> tuple[int, int, int, str, str]:
    return (
        GROUP_ORDER.get(str(row.get("group") or ""), 99),
        KIND_ORDER.get(str(row.get("kind")), 99),
        STATUS_ORDER.get(str(row.get("status")), 50),
        str(row.get("ref") or ""),
        str(row.get("id") or ""),
    )


def _counts(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "total": len(rows),
        "by_group": dict(sorted(Counter(str(row.get("group") or row["kind"]) for row in rows).items())),
        "by_kind": dict(sorted(Counter(str(row["kind"]) for row in rows).items())),
        "by_status": dict(sorted(Counter(str(row["status"]) for row in rows).items())),
    }


def ps_snapshot(
    root: str | Path,
    *,
    mode: str = "now",
    include_all: bool | None = None,
    limit: int = 120,
    stale_days: int = DEFAULT_STALE_DAYS,
) -> dict[str, Any]:
    """Build a read-only process-style snapshot of active Agentic OS state."""
    if include_all is not None:
        mode = "all" if include_all else mode
    if mode not in PS_MODES:
        raise ValueError(f"unsupported ps mode: {mode}")
    os_root = expand_path(root)
    now = datetime.now(timezone.utc)
    rows: list[dict[str, Any]] = []
    rows.extend(_running_process_rows(os_root))
    rows.extend(_queue_rows(os_root, mode))
    rows.extend(_thread_rows(os_root, mode, stale_days))
    rows.extend(_harness_run_rows(os_root, mode))
    rows.extend(_workflow_rows(os_root, mode))
    rows.extend(_schedule_rows(os_root, mode, now))
    rows.extend(_heartbeat_rows(os_root, mode))
    rows.extend(_automation_rows(os_root, mode))
    rows.extend(_watch_rows(os_root, mode))
    rows.sort(key=_sort_key)

    bounded_rows = rows if limit <= 0 else rows[:limit]
    return {
        "root": str(os_root),
        "generated_at": _now_iso(),
        "mode": mode,
        "include_all": mode == "all",
        "limit": limit,
        "stale_days": stale_days,
        "counts": _counts(rows),
        "truncated": len(bounded_rows) < len(rows),
        "rows": bounded_rows,
    }


def _trim(value: Any, width: int) -> str:
    text = str(value or "")
    if len(text) <= width:
        return text
    if width <= 1:
        return text[:width]
    return text[: width - 1] + "..."


def _ansi(value: str, code: str | None, enabled: bool) -> str:
    if not enabled or not code:
        return value
    return f"\033[{code}m{value}\033[0m"


def _cell(value: Any, width: int, *, color_code: str | None = None, color: bool = False) -> str:
    text = _trim(value, width).ljust(width)
    return _ansi(text, color_code, color)


def _grouped_rows(rows: list[dict[str, Any]]) -> list[tuple[str, list[dict[str, Any]]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        group = str(row.get("group") or row.get("kind") or "other")
        grouped.setdefault(group, []).append(row)
    return sorted(grouped.items(), key=lambda item: GROUP_ORDER.get(item[0], 99))


def format_ps_result(result: dict[str, Any], *, as_json: bool = False, color: bool = False) -> str:
    if as_json:
        return json.dumps(result, indent=2, sort_keys=True)

    rows = result.get("rows") or []
    counts = result.get("counts") or {}
    by_kind = counts.get("by_kind") or {}
    summary = " ".join(f"{kind}={count}" for kind, count in by_kind.items()) or "none"
    mode = str(result.get("mode") or "now")
    lines = [
        f"{result.get('prog') or 'agentic-os'} ps {result.get('root')}",
        f"mode={mode} rows={counts.get('total', 0)} {summary}",
    ]
    if result.get("truncated"):
        lines.append(f"showing first {result.get('limit')} rows; rerun with --limit 0")
    if not rows:
        if mode == "now":
            lines.append("Nothing is running right now. Use --active for queued/configured work or --all for audit history.")
        else:
            lines.append("No Agentic OS runtime, workflow, or thread rows found for this mode.")
        return "\n".join(lines)

    headers = ("KIND", "STATUS", "ID", "REF", "DETAIL")
    widths = (12, 16, 34, 24, 72)
    for group, group_rows in _grouped_rows(rows):
        lines.append("")
        title = GROUP_TITLES.get(group, group.replace("_", " ").upper())
        lines.append(_ansi(title, "1;36", color))
        lines.append(
            " ".join(
                header.ljust(width) for header, width in zip(headers, widths, strict=True)
            ).rstrip()
        )
        for row in group_rows:
            kind = str(row.get("kind", ""))
            status = str(row.get("status", ""))
            values = (
                _cell(kind, widths[0], color_code=KIND_COLORS.get(kind), color=color),
                _cell(status, widths[1], color_code=STATUS_COLORS.get(status), color=color),
                _cell(row.get("id", ""), widths[2]),
                _cell(row.get("ref", ""), widths[3]),
                _cell(row.get("detail", ""), widths[4]),
            )
            lines.append(" ".join(values).rstrip())
    return "\n".join(lines)
