"""Backend-neutral point-in-time runtime snapshots for operators and GUIs."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import sqlite3
import tempfile
from typing import Any, Iterable
from urllib.parse import quote

import yaml

from .runtime_backend import (
    EXECUTION_FABRIC_CONFIG,
    EXECUTION_FABRIC_MODE,
    FILESYSTEM_MODE,
    RUN_QUEUE,
    effective_queue_mode,
)
from .scaffold import expand_path
from .state import db as state_db


SCHEMA_VERSION = "agentic-os-runtime-snapshot/v1"
TASK_FIELDS = (
    "id",
    "kind",
    "status",
    "queue_name",
    "worker_pool",
    "priority",
    "execution_target",
    "approval_state",
    "attempts",
    "created_at",
    "updated_at",
    "due_at",
    "started_at",
    "finished_at",
    "lease_owner",
    "lease_until",
)
TASK_QUERY_FIELDS = (*TASK_FIELDS, "ref")
WORKER_FIELDS = (
    "id",
    "pool_name",
    "queue_name",
    "provider",
    "status",
    "capacity",
    "active_tasks",
    "heartbeat_at",
    "lease_until",
    "created_at",
    "updated_at",
)
REQUIRED_FABRIC_TABLES = frozenset(
    {"run_queue", "execution_queues", "worker_pools", "execution_workers"}
)


def _iso(value: datetime | None = None) -> str:
    return (value or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parsed(value: object) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _snapshot_read_hook(stage: str) -> None:
    """No-op test seam used to prove concurrent-write snapshot isolation."""


def _project_task(item: dict[str, Any], *, queue_mode: str) -> dict[str, Any]:
    projected = {field: item[field] for field in TASK_FIELDS if item.get(field) not in (None, "")}
    ref = str(item.get("ref") or "")
    if (
        len(ref) <= 128
        and re.fullmatch(r"[a-z][a-z0-9]*(?:_[a-z0-9]+)+", ref)
        and not re.match(r"^(?:api_key|password|secret|sk|token)_", ref)
    ):
        projected["display_name"] = ref
    if queue_mode != EXECUTION_FABRIC_MODE:
        projected["queue_name"] = "filesystem"
        projected["worker_pool"] = "filesystem"
    else:
        projected.setdefault("queue_name", "unrouted")
        projected.setdefault("worker_pool", "unrouted")
    return projected


def _admission_metrics(root: Path) -> dict[str, int]:
    config_root = root / EXECUTION_FABRIC_CONFIG
    if not config_root.is_dir():
        config_root = Path(__file__).resolve().parents[2] / EXECUTION_FABRIC_CONFIG
    try:
        loaded = yaml.safe_load((config_root / "queues.yml").read_text(encoding="utf-8")) or {}
        admission = loaded.get("admission") if isinstance(loaded, dict) else {}
        admission = admission if isinstance(admission, dict) else {}
    except (OSError, yaml.YAMLError):
        admission = {}
    global_max = int(admission.get("global_max_running") or 1)
    reserved = int(admission.get("reserved_interactive_slots") or 0)
    max_interactive = int(admission.get("max_interactive_running") or max(1, reserved))
    return {
        "global_max_running": global_max,
        "reserved_interactive_slots": reserved,
        "max_interactive_running": max_interactive,
        "background_max_running": max(1, global_max - reserved),
    }


def _filesystem_backend_snapshot(root: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any], str]:
    path = root / RUN_QUEUE
    loaded = yaml.safe_load(path.read_text(encoding="utf-8")) if path.is_file() else {}
    loaded = loaded if isinstance(loaded, dict) else {}
    rows = loaded.get("items") or loaded.get("run_queue") or []
    tasks = [dict(row) for row in rows if isinstance(row, dict)]
    _snapshot_read_hook("filesystem_tasks")
    statuses = Counter(str(row.get("status") or "unknown") for row in tasks)
    metrics = {
        "queue_count": 1,
        "worker_pool_count": 0,
        "worker_count": 0,
        "live_worker_count": 0,
        "unhealthy_worker_count": 0,
        "running_tasks": [task for task in tasks if task.get("status") == "running"],
        "queues": [{"queue_name": "filesystem", "statuses": dict(statuses), "total": len(tasks)}],
        "worker_pools": [],
        **_admission_metrics(root),
    }
    return tasks, [], metrics, "single_yaml_document"


def _fabric_backend_snapshot(
    root: Path,
    *,
    captured: datetime,
    queue_name: str | None,
    statuses: set[str],
    task_limit: int | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any], dict[str, Any], str]:
    admission = _admission_metrics(root)
    db_path = state_db.default_db_path(root)
    if not db_path.is_file():
        raise RuntimeError(f"Execution Fabric state database is missing: {db_path}")
    try:
        conn = sqlite3.connect(
            f"file:{quote(str(db_path))}?mode=ro",
            uri=True,
            isolation_level=None,
            timeout=5,
        )
    except sqlite3.DatabaseError as exc:
        raise RuntimeError(f"Execution Fabric state database is unreadable: {exc}") from exc
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA query_only = ON")
        conn.execute("BEGIN")
        tables = {
            str(row[0])
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
        }
        missing_tables = sorted(REQUIRED_FABRIC_TABLES - tables)
        if missing_tables:
            raise RuntimeError(
                "Execution Fabric state database is not initialized; missing required tables: "
                + ", ".join(missing_tables)
            )
        where: list[str] = []
        parameters: list[Any] = []
        if queue_name is not None:
            where.append("queue_name = ?")
            parameters.append(queue_name)
        if statuses:
            ordered_statuses = sorted(statuses)
            where.append(f"status IN ({','.join('?' for _ in ordered_statuses)})")
            parameters.extend(ordered_statuses)
        predicate = f" WHERE {' AND '.join(where)}" if where else ""
        limit_clause = "" if task_limit is None else " LIMIT ?"
        task_parameters = [*parameters, *([] if task_limit is None else [task_limit])]
        task_rows = conn.execute(
            f"""
            SELECT {', '.join(TASK_QUERY_FIELDS)} FROM run_queue{predicate}
            ORDER BY
                CASE status
                    WHEN 'running' THEN 0
                    WHEN 'approval-needed' THEN 1
                    WHEN 'queued' THEN 2
                    WHEN 'blocked' THEN 3
                    ELSE 4
                END,
                COALESCE(updated_at, created_at) DESC,
                id DESC{limit_clause}
            """,
            task_parameters,
        ).fetchall()
        tasks = [dict(row) for row in task_rows]
        _snapshot_read_hook("fabric_tasks")

        running_rows = conn.execute(
            f"""
            SELECT {', '.join(TASK_QUERY_FIELDS)} FROM run_queue
            WHERE status = 'running'
            ORDER BY COALESCE(started_at, updated_at, created_at) DESC, id DESC
            LIMIT 100
            """
        ).fetchall()

        queue_map: dict[str, dict[str, Any]] = {}
        status_counts: Counter[str] = Counter()
        for row in conn.execute(
            "SELECT queue_name, status, COUNT(*) AS count FROM run_queue GROUP BY queue_name, status ORDER BY queue_name, status"
        ).fetchall():
            task_queue = str(row["queue_name"] or "unrouted")
            status = str(row["status"] or "unknown")
            count = int(row["count"])
            entry = queue_map.setdefault(task_queue, {"queue_name": task_queue, "statuses": {}, "total": 0})
            entry["statuses"][status] = count
            entry["total"] += count
            status_counts[status] += count
        captured_iso = _iso(captured)
        for row in conn.execute(
            """
            SELECT queue_name,
                   COUNT(*) AS retrying,
                   SUM(CASE WHEN due_at IS NOT NULL AND due_at > ? THEN 1 ELSE 0 END) AS delayed_retries
            FROM run_queue
            WHERE status = 'queued' AND attempts > 0
            GROUP BY queue_name
            """,
            (captured_iso,),
        ).fetchall():
            task_queue = str(row["queue_name"] or "unrouted")
            entry = queue_map.setdefault(task_queue, {"queue_name": task_queue, "statuses": {}, "total": 0})
            entry["retrying"] = int(row["retrying"] or 0)
            entry["delayed_retries"] = int(row["delayed_retries"] or 0)
        for row in conn.execute(
            "SELECT name, max_concurrency, enabled, metadata_json FROM execution_queues ORDER BY name"
        ).fetchall():
            name = str(row["name"])
            entry = queue_map.setdefault(name, {"queue_name": name, "statuses": {}, "total": 0})
            metadata = json.loads(row["metadata_json"] or "{}")
            entry.update(
                max_concurrency=int(row["max_concurrency"]),
                enabled=bool(row["enabled"]),
                max_queued=int(metadata.get("max_queued") or 0),
            )

        pools: list[dict[str, Any]] = []
        if {"worker_pools", "execution_workers"}.issubset(tables):
            pool_rows = conn.execute(
                """
                SELECT p.name, p.queue_name, p.provider, p.max_workers, p.max_concurrency,
                       COUNT(DISTINCT w.id) AS worker_count,
                       COALESCE(SUM(w.active_tasks), 0) AS active_tasks,
                       SUM(CASE WHEN w.status = 'online' AND w.lease_until >= ? THEN 1 ELSE 0 END) AS live_workers,
                       SUM(CASE WHEN w.active_tasks > 0 AND (w.status != 'online' OR w.lease_until < ?) THEN 1 ELSE 0 END) AS unhealthy_workers
                FROM worker_pools p LEFT JOIN execution_workers w ON w.pool_name = p.name
                GROUP BY p.name, p.queue_name, p.provider, p.max_workers, p.max_concurrency
                ORDER BY p.name
                """,
                (captured_iso, captured_iso),
            ).fetchall()
            pools = [dict(row) for row in pool_rows]

        workers: list[dict[str, Any]] = []
        if {"execution_workers", "worker_pools"}.issubset(tables):
            worker_rows = conn.execute(
                """
                SELECT w.id, w.pool_name, p.queue_name, p.provider, w.status, w.capacity,
                       w.active_tasks, w.heartbeat_at, w.lease_until, w.created_at, w.updated_at
                FROM execution_workers w
                JOIN worker_pools p ON p.name = w.pool_name
                WHERE (w.status = 'online' AND w.lease_until >= ?) OR w.active_tasks > 0
                ORDER BY w.active_tasks DESC, w.updated_at DESC, w.id
                LIMIT 50
                """,
                (captured_iso,),
            ).fetchall()
            workers = [
                {field: row[field] for field in WORKER_FIELDS if row[field] not in (None, "")}
                for row in worker_rows
            ]
        metrics = {
            "queue_count": len(queue_map),
            "worker_pool_count": len(pools),
            "worker_count": sum(int(row.get("worker_count") or 0) for row in pools),
            "live_worker_count": sum(int(row.get("live_workers") or 0) for row in pools),
            "unhealthy_worker_count": sum(int(row.get("unhealthy_workers") or 0) for row in pools),
            "running_tasks": [dict(row) for row in running_rows],
            "queues": [queue_map[name] for name in sorted(queue_map)],
            "worker_pools": pools,
            **admission,
        }
        matching_tasks = int(conn.execute(f"SELECT COUNT(*) FROM run_queue{predicate}", parameters).fetchone()[0])
        health_row = conn.execute(
            """
            SELECT
                MIN(CASE WHEN status IN ('queued', 'approval-needed') THEN julianday(COALESCE(due_at, created_at)) END) AS oldest_wait,
                SUM(CASE WHEN status IN ('queued', 'approval-needed') AND julianday(COALESCE(due_at, created_at)) < julianday(?) - 1 THEN 1 ELSE 0 END) AS stale_queued,
                SUM(CASE WHEN status = 'running' AND julianday(lease_until) < julianday(?) THEN 1 ELSE 0 END) AS expired_running_leases,
                SUM(CASE WHEN status = 'failed' AND julianday(COALESCE(finished_at, updated_at)) >= julianday(?) - (1.0 / 24.0) AND julianday(COALESCE(finished_at, updated_at)) <= julianday(?) THEN 1 ELSE 0 END) AS failed_last_hour,
                SUM(CASE WHEN status = 'queued' AND attempts > 0 THEN 1 ELSE 0 END) AS retrying,
                SUM(CASE WHEN status = 'queued' AND attempts > 0 AND due_at IS NOT NULL AND julianday(due_at) > julianday(?) THEN 1 ELSE 0 END) AS delayed_retries
            FROM run_queue
            """,
            (captured_iso, captured_iso, captured_iso, captured_iso, captured_iso),
        ).fetchone()
        oldest_wait_seconds = 0.0
        if health_row is not None and health_row["oldest_wait"] is not None:
            captured_julian = conn.execute("SELECT julianday(?)", (captured_iso,)).fetchone()[0]
            oldest_wait_seconds = max(0.0, (float(captured_julian) - float(health_row["oldest_wait"])) * 86400)
        stats = {
            "total_records": sum(status_counts.values()),
            "matching_tasks": matching_tasks,
            "status_counts": dict(status_counts),
            "oldest_wait_seconds": round(oldest_wait_seconds, 3),
            "stale_queued": int(health_row["stale_queued"] or 0) if health_row is not None else 0,
            "expired_running_leases": int(health_row["expired_running_leases"] or 0) if health_row is not None else 0,
            "failed_last_hour": int(health_row["failed_last_hour"] or 0) if health_row is not None else 0,
            "retrying": int(health_row["retrying"] or 0) if health_row is not None else 0,
            "delayed_retries": int(health_row["delayed_retries"] or 0) if health_row is not None else 0,
        }
        return tasks, workers, metrics, stats, "sqlite_read_transaction"
    except sqlite3.DatabaseError as exc:
        raise RuntimeError(f"Execution Fabric state database is unreadable: {exc}") from exc
    finally:
        try:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
        except sqlite3.DatabaseError:
            pass
        conn.close()


def _matching_tasks(
    tasks: Iterable[dict[str, Any]],
    *,
    queue_name: str | None,
    statuses: set[str],
) -> list[dict[str, Any]]:
    matching = [
        task
        for task in tasks
        if (queue_name is None or task.get("queue_name") == queue_name)
        and (not statuses or str(task.get("status") or "unknown") in statuses)
    ]
    return sorted(
        matching,
        key=lambda task: (str(task.get("updated_at") or task.get("created_at") or ""), str(task.get("id") or "")),
        reverse=True,
    )


def build_runtime_snapshot(
    root: str | Path,
    *,
    queue_name: str | None = None,
    statuses: Iterable[str] = (),
    task_limit: int | None = 50,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Capture one read-only queue, worker, and task snapshot from the selected backend."""
    if task_limit is not None and task_limit < 1:
        raise ValueError("task_limit must be at least 1 or None")
    os_root = expand_path(root)
    captured = now or datetime.now(timezone.utc)
    captured = captured.replace(tzinfo=timezone.utc) if captured.tzinfo is None else captured.astimezone(timezone.utc)
    requested_statuses = {str(status) for status in statuses if str(status)}
    queue_mode = effective_queue_mode(os_root)
    if queue_mode == FILESYSTEM_MODE:
        raw_tasks, workers, metrics, consistency = _filesystem_backend_snapshot(os_root)
        all_tasks = [_project_task(item, queue_mode=queue_mode) for item in raw_tasks]
        status_counts = Counter(str(task.get("status") or "unknown") for task in all_tasks)
        matching = _matching_tasks(all_tasks, queue_name=queue_name, statuses=requested_statuses)
        displayed = matching if task_limit is None else matching[:task_limit]
        total_records = len(all_tasks)
        matching_tasks = len(matching)
        queued_tasks = [task for task in all_tasks if task.get("status") in {"queued", "approval-needed"}]
        queued_ages = [
            max(0.0, (captured - timestamp.astimezone(timezone.utc)).total_seconds())
            for task in queued_tasks
            if (timestamp := _parsed(task.get("due_at") or task.get("created_at"))) is not None
        ]
        oldest_wait_seconds = round(max(queued_ages), 3) if queued_ages else 0.0
        stale_queued = sum(age > 86400 for age in queued_ages)
        expired_leases = sum(
            1
            for task in all_tasks
            if task.get("status") == "running"
            and (lease := _parsed(task.get("lease_until"))) is not None
            and lease < captured
        )
        recent_failed = sum(
            1
            for task in all_tasks
            if task.get("status") == "failed"
            and (finished := _parsed(task.get("finished_at") or task.get("updated_at"))) is not None
            and timedelta(0) <= captured - finished.astimezone(timezone.utc) <= timedelta(hours=1)
        )
        retrying = sum(
            1
            for task in all_tasks
            if task.get("status") == "queued" and int(task.get("attempts") or 0) > 0
        )
        delayed_retries = sum(
            1
            for task in all_tasks
            if task.get("status") == "queued"
            and int(task.get("attempts") or 0) > 0
            and (due := _parsed(task.get("due_at"))) is not None
            and due.astimezone(timezone.utc) > captured
        )
    else:
        raw_tasks, workers, metrics, stats, consistency = _fabric_backend_snapshot(
            os_root,
            captured=captured,
            queue_name=queue_name,
            statuses=requested_statuses,
            task_limit=task_limit,
        )
        displayed = [_project_task(item, queue_mode=queue_mode) for item in raw_tasks]
        status_counts = Counter({str(name): int(count) for name, count in stats["status_counts"].items()})
        total_records = int(stats["total_records"])
        matching_tasks = int(stats["matching_tasks"])
        oldest_wait_seconds = float(stats["oldest_wait_seconds"])
        stale_queued = int(stats["stale_queued"])
        expired_leases = int(stats["expired_running_leases"])
        recent_failed = int(stats["failed_last_hour"])
        retrying = int(stats["retrying"])
        delayed_retries = int(stats["delayed_retries"])

    dead_letter = int(status_counts.get("dead-letter", 0))
    unhealthy_workers = int(metrics.get("unhealthy_worker_count") or 0)
    registered_workers = int(metrics.get("worker_count") or 0)
    running_tasks = [
        _project_task(item, queue_mode=queue_mode)
        for item in metrics.get("running_tasks") or []
    ]

    queues: list[dict[str, Any]] = []
    for queue in metrics.get("queues") or []:
        item = dict(queue)
        counts = dict(item.get("statuses") or {})
        item["depth"] = int(counts.get("queued", 0)) + int(counts.get("approval-needed", 0))
        item["running"] = int(counts.get("running", 0))
        item["failed"] = int(counts.get("failed", 0))
        item["dead_letter"] = int(counts.get("dead-letter", 0))
        if queue_mode == FILESYSTEM_MODE:
            queue_tasks = [task for task in all_tasks if task.get("status") == "queued"]
            item["retrying"] = sum(int(task.get("attempts") or 0) > 0 for task in queue_tasks)
            item["delayed_retries"] = sum(
                int(task.get("attempts") or 0) > 0
                and (due := _parsed(task.get("due_at"))) is not None
                and due.astimezone(timezone.utc) > captured
                for task in queue_tasks
            )
        else:
            item["retrying"] = int(item.get("retrying") or 0)
            item["delayed_retries"] = int(item.get("delayed_retries") or 0)
        queues.append(item)
    saturated = any(
        int(queue.get("max_queued") or 0)
        and int(queue.get("depth") or 0) >= int(queue["max_queued"]) * 0.8
        for queue in queues
    )
    health = (
        "critical"
        if dead_letter or expired_leases or stale_queued
        else "degraded"
        if unhealthy_workers or recent_failed or saturated
        else "healthy"
    )

    return {
        "schema_version": SCHEMA_VERSION,
        "captured_at": _iso(captured),
        "root": str(os_root),
        "queue_mode": queue_mode,
        "consistency": consistency,
        "health": health,
        "summary": {
            "total_records": total_records,
            "queued": int(status_counts.get("queued", 0)),
            "approval_needed": int(status_counts.get("approval-needed", 0)),
            "running": int(status_counts.get("running", 0)),
            "failed": int(status_counts.get("failed", 0)),
            "dead_letter": dead_letter,
            "done": int(status_counts.get("done", 0)),
            "cancelled": int(status_counts.get("cancelled", 0)),
            "oldest_wait_seconds": oldest_wait_seconds,
            "stale_queued": stale_queued,
            "expired_running_leases": expired_leases,
            "active_workers": int(metrics.get("live_worker_count") or 0),
            "unhealthy_workers": unhealthy_workers,
            "registered_workers": registered_workers,
            "historical_worker_records": max(
                0,
                registered_workers - int(metrics.get("live_worker_count") or 0) - unhealthy_workers,
            ),
            "failed_last_hour": recent_failed,
            "retrying": retrying,
            "delayed_retries": delayed_retries,
            "global_max_running": int(metrics.get("global_max_running") or 0),
            "background_max_running": int(metrics.get("background_max_running") or 0),
            "reserved_interactive_slots": int(metrics.get("reserved_interactive_slots") or 0),
            "max_interactive_running": int(metrics.get("max_interactive_running") or 1),
        },
        "filters": {
            "queue_name": queue_name,
            "statuses": sorted(requested_statuses),
            "task_limit": task_limit,
            "matching_tasks": matching_tasks,
            "displayed_tasks": len(displayed),
        },
        "queues": queues,
        "worker_pools": [dict(pool) for pool in metrics.get("worker_pools") or []],
        "workers": workers,
        "running_tasks": running_tasks,
        "tasks": displayed,
    }


def format_runtime_snapshot(snapshot: dict[str, Any]) -> str:
    """Render the compact terminal view while JSON remains the machine contract."""
    summary = snapshot["summary"]
    lines = [
        f"Execution Fabric Snapshot  {snapshot['captured_at']}",
        f"Mode: {snapshot['queue_mode']}  Health: {snapshot['health']}",
        (
            f"Queued: {summary['queued'] + summary['approval_needed']}  Running: {summary['running']}  "
            f"Workers: {summary['active_workers']}  Recent failed/dead: {summary['failed_last_hour']}/{summary['dead_letter']}  "
            f"Retrying: {summary['retrying']} ({summary['delayed_retries']} delayed)  "
            f"Oldest wait: {int(summary['oldest_wait_seconds'])}s"
        ),
        "",
        "QUEUES",
        "NAME             DEPTH  RUNNING  RETRY  DELAY  DEAD  HISTORY  LIMIT",
    ]
    for queue in snapshot["queues"]:
        lines.append(
            f"{str(queue.get('queue_name') or '-')[:16]:16} "
            f"{int(queue.get('depth') or 0):5}  {int(queue.get('running') or 0):7}  "
            f"{int(queue.get('retrying') or 0):5}  {int(queue.get('delayed_retries') or 0):5}  "
            f"{int(queue.get('dead_letter') or 0):4}  {int(queue.get('failed') or 0):7}  "
            f"{int(queue.get('max_queued') or 0):5}"
        )
    if not snapshot["queues"]:
        lines.append("(none)")
    lines.extend(["", "WORKER POOLS", "NAME                 LIVE  ACTIVE  CAPACITY  PROVIDER"])
    for pool in snapshot["worker_pools"]:
        lines.append(
            f"{str(pool.get('name') or '-')[:20]:20} "
            f"{int(pool.get('live_workers') or 0):4}  {int(pool.get('active_tasks') or 0):6}  "
            f"{int(pool.get('max_concurrency') or 0):8}  {str(pool.get('provider') or '-')[:12]}"
        )
    if not snapshot["worker_pools"]:
        lines.append("(filesystem-managed)")
    filters = snapshot["filters"]
    lines.extend(
        [
            "",
            f"TASKS ({filters['displayed_tasks']} of {filters['matching_tasks']} matching)",
            "STATUS           QUEUE            TARGET          TASK ID",
        ]
    )
    for task in snapshot["tasks"]:
        label = str(task.get("id") or "-")
        lines.append(
            f"{str(task.get('status') or '-')[:15]:15} "
            f"{str(task.get('queue_name') or '-')[:16]:16} "
            f"{str(task.get('execution_target') or '-')[:15]:15} {label[:64]}"
        )
    if not snapshot["tasks"]:
        lines.append("(none)")
    return "\n".join(lines)


def write_runtime_snapshot(path: str | Path, snapshot: dict[str, Any]) -> str:
    """Persist an atomic JSON receipt when the operator requests one."""
    target = Path(path).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(snapshot, indent=2, sort_keys=True) + "\n")
        temporary.replace(target)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return str(target)
