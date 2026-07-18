"""Runtime queue backend selection with guarded, receipted mode changes."""

from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
from enum import Enum
import fcntl
import os
from pathlib import Path
import sqlite3
from typing import Any, Iterator
from urllib.parse import quote
from uuid import uuid4

import yaml

from .scaffold import expand_path
from .state import db as state_db
from .state import execution_fabric

class QueueMode(str, Enum):
    FILESYSTEM = "filesystem"
    EXECUTION_FABRIC = "execution_fabric"


FILESYSTEM_MODE = QueueMode.FILESYSTEM.value
EXECUTION_FABRIC_MODE = QueueMode.EXECUTION_FABRIC.value
QUEUE_MODES = (FILESYSTEM_MODE, EXECUTION_FABRIC_MODE)
RUNTIME_REGISTRY = Path("harness/shared_factory/00-control-plane/runtime-registry.yml")
RUN_QUEUE = Path("harness/shared_factory/00-control-plane/run-queue.yml")


class RuntimeBackendError(ValueError):
    """Raised when a queue-mode transition is invalid or unsafe."""


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _registry_path(root: str | Path) -> Path:
    return expand_path(root) / RUNTIME_REGISTRY


def _read_registry(root: str | Path) -> tuple[Path, dict[str, Any]]:
    path = _registry_path(root)
    if not path.is_file():
        raise RuntimeBackendError(f"runtime registry is missing: {path}; run `agentic-os runtime init --root {expand_path(root)}`")
    loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(loaded, dict):
        raise RuntimeBackendError(f"runtime registry must contain a mapping: {path}")
    return path, loaded


def _runtime_config(registry: dict[str, Any]) -> dict[str, Any]:
    runtime = registry.get("runtime")
    if runtime is None:
        return {}
    if not isinstance(runtime, dict):
        raise RuntimeBackendError("runtime-registry.yml runtime must be a mapping")
    return runtime


def _mode_from_registry(registry: dict[str, Any]) -> tuple[str, str]:
    runtime = _runtime_config(registry)
    raw = runtime.get("queue_mode")
    if raw is None:
        return FILESYSTEM_MODE, "default"
    mode = str(raw).strip()
    if mode not in QUEUE_MODES:
        raise RuntimeBackendError(f"invalid runtime.queue_mode {mode!r}; expected one of {QUEUE_MODES}")
    return mode, "explicit"


def effective_queue_mode(root: str | Path) -> str:
    """Compatibility selector for producers in roots without runtime init."""
    path = _registry_path(root)
    if not path.is_file():
        return FILESYSTEM_MODE
    _, registry = _read_registry(root)
    mode, _ = _mode_from_registry(registry)
    return mode


def _active_leases_readonly(root: str | Path, *, now: str | None = None) -> list[dict[str, Any]]:
    db_path = state_db.default_db_path(root)
    if not db_path.is_file():
        return []
    now_value = now or _now()
    uri = f"file:{quote(str(db_path))}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    try:
        table = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'run_queue'"
        ).fetchone()
        if table is None:
            return []
        rows = conn.execute(
            """
            SELECT id, lease_owner, lease_until FROM run_queue
            WHERE status = 'running' AND lease_owner IS NOT NULL AND lease_until >= ?
            ORDER BY lease_until, id
            """,
            (now_value,),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def _filesystem_projection_blockers(root: str | Path) -> list[dict[str, Any]]:
    """Return fabric state that cannot be recovered faithfully from YAML."""
    db_path = state_db.default_db_path(root)
    if not db_path.is_file():
        return []
    queue_path = expand_path(root) / RUN_QUEUE
    filesystem_statuses: dict[str, str] = {}
    if queue_path.is_file():
        loaded = yaml.safe_load(queue_path.read_text(encoding="utf-8")) or {}
        if isinstance(loaded, dict):
            rows = loaded.get("items") or loaded.get("run_queue") or []
            filesystem_statuses = {
                str(row["id"]): str(row.get("status") or "unknown")
                for row in rows
                if isinstance(row, dict) and row.get("id")
            }
    uri = f"file:{db_path}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    try:
        table = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'run_queue'"
        ).fetchone()
        if table is None:
            return []
        rows = conn.execute(
            """
            SELECT id, status, queue_name, worker_pool FROM run_queue
            ORDER BY created_at, id
            """
        ).fetchall()
        blockers: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item_id = str(item["id"])
            filesystem_status = filesystem_statuses.get(item_id)
            if filesystem_status is None:
                if item["status"] in {"queued", "approval-needed", "running"}:
                    item["projection_issue"] = "missing_nonterminal_task"
                    blockers.append(item)
                continue
            if filesystem_status != item["status"]:
                item["projection_issue"] = "status_drift"
                item["filesystem_status"] = filesystem_status
                blockers.append(item)
        return blockers
    finally:
        conn.close()


def _queue_metrics_readonly(root: str | Path, mode: str) -> dict[str, Any]:
    if mode == FILESYSTEM_MODE:
        path = expand_path(root) / RUN_QUEUE
        loaded = yaml.safe_load(path.read_text(encoding="utf-8")) if path.is_file() else {}
        rows = (loaded or {}).get("items") or (loaded or {}).get("run_queue") or []
        statuses: dict[str, int] = {}
        for row in rows:
            if isinstance(row, dict):
                status = str(row.get("status") or "unknown")
                statuses[status] = statuses.get(status, 0) + 1
        return {
            "queue_count": 1,
            "worker_pool_count": 0,
            "worker_count": 0,
            "queues": [{"queue_name": "filesystem", "statuses": statuses, "total": sum(statuses.values())}],
            "worker_pools": [],
        }
    db_path = state_db.default_db_path(root)
    if not db_path.is_file():
        return {"queue_count": 0, "worker_pool_count": 0, "worker_count": 0, "queues": [], "worker_pools": []}
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        required = {"run_queue", "execution_queues", "worker_pools", "execution_workers"}
        present = {
            str(row["name"])
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
        }
        if not required.issubset(present):
            return {"queue_count": 0, "worker_pool_count": 0, "worker_count": 0, "queues": [], "worker_pools": []}
        queue_rows = conn.execute(
            "SELECT queue_name, status, COUNT(*) AS count FROM run_queue GROUP BY queue_name, status ORDER BY queue_name, status"
        ).fetchall()
        queue_map: dict[str, dict[str, Any]] = {}
        for row in queue_rows:
            entry = queue_map.setdefault(str(row["queue_name"]), {"queue_name": str(row["queue_name"]), "statuses": {}, "total": 0})
            entry["statuses"][str(row["status"])] = int(row["count"])
            entry["total"] += int(row["count"])
        configured = conn.execute("SELECT name FROM execution_queues ORDER BY name").fetchall()
        for row in configured:
            queue_map.setdefault(str(row["name"]), {"queue_name": str(row["name"]), "statuses": {}, "total": 0})
        pool_rows = conn.execute(
            """
            SELECT p.name, p.queue_name, p.provider, p.max_workers, p.max_concurrency,
                   COUNT(DISTINCT w.id) AS worker_count,
                   COALESCE(SUM(w.active_tasks), 0) AS active_tasks
            FROM worker_pools p LEFT JOIN execution_workers w ON w.pool_name = p.name
            GROUP BY p.name, p.queue_name, p.provider, p.max_workers, p.max_concurrency
            ORDER BY p.name
            """
        ).fetchall()
        pools = [dict(row) for row in pool_rows]
        return {
            "queue_count": len(queue_map),
            "worker_pool_count": len(pools),
            "worker_count": sum(int(row["worker_count"]) for row in pools),
            "queues": list(queue_map.values()),
            "worker_pools": pools,
        }
    finally:
        conn.close()


def _filesystem_running_tasks(root: str | Path) -> list[dict[str, Any]]:
    path = expand_path(root) / RUN_QUEUE
    if not path.is_file():
        return []
    loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(loaded, dict):
        return []
    rows = loaded.get("items") or loaded.get("run_queue") or []
    return [
        {"id": row.get("id"), "ref": row.get("ref"), "status": "running"}
        for row in rows
        if isinstance(row, dict) and row.get("status") == "running"
    ]


def queue_mode_status(root: str | Path) -> dict[str, Any]:
    path, registry = _read_registry(root)
    mode, source = _mode_from_registry(registry)
    leases = _active_leases_readonly(root)
    runtime = _runtime_config(registry)
    return {
        "root": str(expand_path(root)),
        "runtime_registry": str(path),
        "queue_mode": mode,
        "mode_source": source,
        "previous_mode": runtime.get("queue_mode_previous"),
        "changed_at": runtime.get("queue_mode_changed_at"),
        "change_id": runtime.get("queue_mode_change_id"),
        "state_db": str(state_db.default_db_path(root)),
        "active_lease_count": len(leases),
        "active_leases": leases,
        "metrics": _queue_metrics_readonly(root, mode),
    }


def plan_queue_mode(root: str | Path, target_mode: str) -> dict[str, Any]:
    if target_mode not in QUEUE_MODES:
        raise RuntimeBackendError(f"invalid target queue mode {target_mode!r}; expected one of {QUEUE_MODES}")
    status = queue_mode_status(root)
    switching = status["queue_mode"] != target_mode
    blockers: list[str] = []
    if switching and status["active_lease_count"]:
        blockers.append(f"{status['active_lease_count']} active execution lease(s) must finish or expire")
    filesystem_running = (
        _filesystem_running_tasks(root)
        if switching and status["queue_mode"] == FILESYSTEM_MODE
        else []
    )
    if filesystem_running:
        blockers.append(f"{len(filesystem_running)} filesystem dispatch(es) are still running")
    projection_blockers = _filesystem_projection_blockers(root) if switching and target_mode == FILESYSTEM_MODE else []
    if projection_blockers:
        blockers.append(
            f"{len(projection_blockers)} execution-fabric task state(s) are not safely projected to the filesystem queue"
        )
    return {
        **status,
        "target_mode": target_mode,
        "switching": switching,
        "ready": not blockers,
        "blockers": blockers,
        "filesystem_projection_blocker_count": len(projection_blockers),
        "filesystem_projection_blocker_sample": projection_blockers[:10],
        "filesystem_running_count": len(filesystem_running),
        "filesystem_running_sample": filesystem_running[:10],
        "will_initialize_state_db": target_mode == EXECUTION_FABRIC_MODE and not Path(status["state_db"]).is_file(),
        "will_import_filesystem_queue": switching and target_mode == EXECUTION_FABRIC_MODE,
    }


@contextmanager
def _mode_lock(registry_path: Path) -> Iterator[None]:
    lock_path = registry_path.with_name(".runtime-queue-mode.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


@contextmanager
def queue_backend_mutation_guard(root: str | Path, expected_mode: str) -> Iterator[None]:
    """Serialize a backend mutation with mode switches and verify authority."""
    if expected_mode not in QUEUE_MODES:
        raise RuntimeBackendError(f"invalid expected queue mode {expected_mode!r}")
    path = _registry_path(root)
    with _mode_lock(path):
        if path.is_file():
            _, registry = _read_registry(root)
            actual_mode, _ = _mode_from_registry(registry)
        else:
            actual_mode = FILESYSTEM_MODE
        if actual_mode != expected_mode:
            raise RuntimeBackendError(
                f"queue backend mutation denied: {expected_mode!r} is not authoritative; active mode is {actual_mode!r}"
            )
        yield


def _atomic_write_registry(path: Path, registry: dict[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{uuid4().hex}.tmp")
    try:
        temporary.write_text(yaml.safe_dump(registry, sort_keys=False), encoding="utf-8")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def apply_queue_mode(root: str | Path, target_mode: str, *, dry_run: bool = True) -> dict[str, Any]:
    plan = plan_queue_mode(root, target_mode)
    if dry_run:
        return {**plan, "dry_run": True, "applied": False}
    path = Path(plan["runtime_registry"])
    with _mode_lock(path):
        plan = plan_queue_mode(root, target_mode)
        if not plan["ready"]:
            raise RuntimeBackendError("queue-mode switch blocked: " + "; ".join(plan["blockers"]))
        if not plan["switching"]:
            return {**plan, "dry_run": False, "applied": False, "status": "unchanged"}

        import_receipt: dict[str, Any] | None = None
        if target_mode == EXECUTION_FABRIC_MODE:
            # Lazy import avoids loading event_graph -> runtime_ops while the
            # runtime composition root itself is still importing.
            from .state.importers import import_run_queue

            conn = state_db.connect(state_db.default_db_path(root))
            try:
                execution_fabric.configure_queue(conn, "default", max_concurrency=1)
                execution_fabric.configure_worker_pool(
                    conn,
                    "default",
                    queue_name="default",
                    max_workers=1,
                    max_concurrency=1,
                )
                execution_fabric.configure_limit(conn, scope="global", key="*", max_concurrency=1)
                queue_path = expand_path(root) / RUN_QUEUE
                if queue_path.is_file():
                    import_receipt = import_run_queue(conn, queue_path)
            finally:
                conn.close()

        _, registry = _read_registry(root)
        updated = deepcopy(registry)
        runtime = dict(_runtime_config(updated))
        changed_at = _now()
        change_id = f"queue-mode-{uuid4().hex[:12]}"
        runtime.update(
            {
                "queue_mode": target_mode,
                "queue_mode_previous": plan["queue_mode"],
                "queue_mode_changed_at": changed_at,
                "queue_mode_change_id": change_id,
            }
        )
        updated["runtime"] = runtime
        updated["updated_at"] = changed_at
        _atomic_write_registry(path, updated)
        readback = queue_mode_status(root)
        if readback["queue_mode"] != target_mode:
            raise RuntimeBackendError("queue-mode readback did not match the requested target")
        return {
            **readback,
            "target_mode": target_mode,
            "dry_run": False,
            "applied": True,
            "status": "switched",
            "import_receipt": import_receipt,
        }


def plan_queue_mode_rollback(root: str | Path) -> dict[str, Any]:
    status = queue_mode_status(root)
    previous = status.get("previous_mode")
    if previous not in QUEUE_MODES:
        raise RuntimeBackendError("no valid previous queue mode is available for rollback")
    return {**plan_queue_mode(root, str(previous)), "rollback": True}


def rollback_queue_mode(root: str | Path, *, dry_run: bool = True) -> dict[str, Any]:
    plan = plan_queue_mode_rollback(root)
    if dry_run:
        return {**plan, "dry_run": True, "applied": False}
    result = apply_queue_mode(root, str(plan["target_mode"]), dry_run=False)
    return {**result, "rollback": True}
