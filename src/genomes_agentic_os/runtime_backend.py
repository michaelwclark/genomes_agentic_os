"""Runtime queue backend selection with guarded, receipted mode changes."""

from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
from enum import Enum
import fcntl
import json
import os
from pathlib import Path
import sqlite3
from typing import Any, Iterator
from urllib.parse import quote
from uuid import uuid4

import yaml

from .execution_fabric_config import (
    catalog_diff,
    load_execution_fabric_config,
    reconcile_catalog,
    validate_execution_fabric_config,
)
from .scaffold import expand_path
from .long_running import atomic_json
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
QUEUE_RECONCILIATION_LOG = Path("harness/shared_factory/06-runs-and-logs/runtime-queue-reconciliation")


class RuntimeBackendError(ValueError):
    """Raised when a queue-mode transition is invalid or unsafe."""


def _execution_fabric_catalog(root: str | Path) -> tuple[dict[str, Any], dict[str, Any]]:
    fabric = load_execution_fabric_config(root).value["execution_fabric"]
    return {
        "admission": fabric["admission"],
        "queues": fabric["queues"],
    }, {
        "worker_pools": fabric["worker_pools"],
    }


def resolve_execution_route(root: str | Path, item: dict[str, Any]) -> dict[str, Any]:
    """Resolve one task onto a configured named queue without producer-specific logic."""
    explicit_queue = str(item.get("queue_name") or "").strip()
    explicit_pool = str(item.get("worker_pool") or "").strip()
    task_type = str(item.get("task_type") or "").strip()
    target = str(item.get("execution_target") or "").strip()
    queue_config, pools_config = _execution_fabric_catalog(root)
    queues = [row for row in queue_config.get("queues") or [] if isinstance(row, dict)]
    by_name = {str(row.get("id")): row for row in queues if row.get("id")}

    if explicit_queue:
        selected = by_name.get(explicit_queue)
        if selected is None:
            raise RuntimeBackendError(f"unknown execution queue: {explicit_queue}")
    else:
        selected = next(
            (row for row in queues if task_type and task_type in (row.get("accepted_task_types") or [])),
            None,
        )
        if selected is None:
            inferred = "codex" if target == "codex_harness" else "claude" if target == "claude_harness" else "non_llm"
            selected = by_name.get(inferred)
        if selected is None:
            raise RuntimeBackendError(f"no execution-fabric route for task type {task_type!r} and target {target!r}")

    queue_name = str(selected["id"])
    accepted = list(selected.get("accepted_task_types") or [])
    if task_type and accepted and task_type not in accepted:
        raise RuntimeBackendError(f"task type {task_type!r} is not accepted by execution queue {queue_name!r}")
    worker_pool = explicit_pool or str(selected.get("worker_pool") or "")
    if not worker_pool:
        raise RuntimeBackendError(f"execution queue {queue_name!r} has no worker pool")
    pool = next(
        (
            row
            for row in pools_config.get("worker_pools") or []
            if isinstance(row, dict) and str(row.get("id") or "") == worker_pool
        ),
        {},
    )
    retry_policy = pool.get("retry") if isinstance(pool.get("retry"), dict) else {}
    return {"queue_name": queue_name, "worker_pool": worker_pool, "retry_policy": dict(retry_policy)}


def _configure_execution_fabric(root: str | Path, conn: sqlite3.Connection) -> dict[str, Any]:
    effective = load_execution_fabric_config(root)
    result = reconcile_catalog(conn, effective)
    fabric = effective.value["execution_fabric"]
    return {
        "queues": [str(row["id"]) for row in fabric["queues"]],
        "worker_pools": [str(row["id"]) for row in fabric["worker_pools"]],
        "config_source": str(effective.source),
        "config_source_kind": effective.source_kind,
        "config_fingerprint": effective.fingerprint,
        **result,
    }


def ensure_execution_fabric_catalog(root: str | Path, conn: sqlite3.Connection) -> dict[str, Any]:
    return _configure_execution_fabric(root, conn)


def execution_fabric_config_status(root: str | Path) -> dict[str, Any]:
    """Report the validated effective config, source, dependencies, and drift."""
    os_root = expand_path(root)
    validation = validate_execution_fabric_config(os_root)
    effective = load_execution_fabric_config(os_root)
    db_path = state_db.default_db_path(os_root)
    if db_path.is_file():
        conn = sqlite3.connect(f"file:{quote(str(db_path))}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        try:
            tables = {
                str(row["name"])
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
            }
            required = {"execution_queues", "worker_pools", "execution_limits"}
            if required.issubset(tables):
                changes = catalog_diff(conn, effective)
            else:
                memory = state_db.connect()
                try:
                    changes = catalog_diff(memory, effective)
                finally:
                    memory.close()
        finally:
            conn.close()
    else:
        conn = state_db.connect()
        try:
            changes = catalog_diff(conn, effective)
        finally:
            conn.close()
    return {
        "root": str(os_root),
        "queue_mode": effective_queue_mode(os_root),
        **validation,
        "state_db": str(db_path),
        "state_db_initialized": db_path.is_file(),
        "drift_count": len(changes),
        "drift": changes,
    }


def reconcile_execution_fabric_configuration(
    root: str | Path,
    *,
    dry_run: bool = True,
) -> dict[str, Any]:
    """Plan or atomically apply the canonical config to the selected fabric."""
    os_root = expand_path(root)
    status = execution_fabric_config_status(os_root)
    ready = status["queue_mode"] == EXECUTION_FABRIC_MODE
    plan = {
        **status,
        "action": "runtime.execution-fabric.config.reconcile",
        "dry_run": dry_run,
        "ready": ready,
        "blockers": []
        if ready
        else ["execution_fabric is not the authoritative queue mode; no runtime config write is permitted"],
        "applied": False,
    }
    if dry_run:
        return plan
    if not ready:
        raise RuntimeBackendError("execution-fabric config reconcile blocked: " + "; ".join(plan["blockers"]))

    effective = load_execution_fabric_config(os_root)
    with queue_backend_mutation_guard(os_root, EXECUTION_FABRIC_MODE):
        conn = state_db.connect(state_db.default_db_path(os_root))
        try:
            result = reconcile_catalog(conn, effective)
            remaining = catalog_diff(conn, effective)
        finally:
            conn.close()
    if remaining:
        raise RuntimeBackendError(
            f"execution-fabric config readback still has {len(remaining)} difference(s)"
        )
    return {
        **plan,
        "dry_run": False,
        "applied": bool(result["reconciled"]),
        "status": "reconciled" if result["reconciled"] else "unchanged",
        "drift_count": 0,
        "drift": [],
        "changes": result["changes"],
        "catalog": {
            key: value
            for key, value in result.items()
            if key not in {"changes", "reconciled"}
        },
    }


def runtime_queue_items(root: str | Path) -> list[dict[str, Any]]:
    """Read queue items from the one backend selected by runtime.queue_mode."""
    os_root = expand_path(root)
    if effective_queue_mode(os_root) == FILESYSTEM_MODE:
        path = os_root / RUN_QUEUE
        loaded = yaml.safe_load(path.read_text(encoding="utf-8")) if path.is_file() else {}
        rows = (loaded or {}).get("items") or (loaded or {}).get("run_queue") or []
        return [dict(row) for row in rows if isinstance(row, dict)]
    db_path = state_db.default_db_path(os_root)
    if not db_path.is_file():
        return []
    conn = sqlite3.connect(f"file:{quote(str(db_path))}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='run_queue'").fetchone() is None:
            return []
        items: list[dict[str, Any]] = []
        for row in conn.execute("SELECT * FROM run_queue ORDER BY created_at, id").fetchall():
            value = dict(row)
            payload = json.loads(value.pop("payload_json") or "{}")
            flattened = dict(payload) if isinstance(payload, dict) else {"payload": payload}
            flattened.update(value)
            flattened["dry_run"] = bool(flattened.get("dry_run"))
            items.append(flattened)
        return items
    finally:
        conn.close()


def patch_runtime_queue_item(root: str | Path, item_id: str, changes: dict[str, Any]) -> dict[str, Any]:
    """Apply a bounded backend-neutral patch used by reconciliation jobs."""
    os_root = expand_path(root)
    mode = effective_queue_mode(os_root)
    with queue_backend_mutation_guard(os_root, mode):
        if mode == FILESYSTEM_MODE:
            path = os_root / RUN_QUEUE
            loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            rows = loaded.get("items") or loaded.get("run_queue") or []
            item = next((row for row in rows if isinstance(row, dict) and str(row.get("id")) == item_id), None)
            if item is None:
                raise RuntimeBackendError(f"run queue item not found: {item_id}")
            item.update(changes)
            loaded["items"] = rows
            loaded["run_queue"] = rows
            temporary = path.with_name(f".{path.name}.{os.getpid()}.{uuid4().hex}.tmp")
            temporary.write_text(yaml.safe_dump(loaded, sort_keys=False), encoding="utf-8")
            temporary.replace(path)
            return dict(item)
        conn = state_db.connect(state_db.default_db_path(os_root))
        try:
            current = conn.execute("SELECT payload_json FROM run_queue WHERE id = ?", (item_id,)).fetchone()
            if current is None:
                raise RuntimeBackendError(f"run queue item not found: {item_id}")
            core = {"status", "finished_at", "updated_at", "blocked_reason", "error"}
            payload = json.loads(current["payload_json"] or "{}")
            payload.update({key: value for key, value in changes.items() if key not in core})
            assignments = ["payload_json = ?"]
            values: list[Any] = [json.dumps(payload, sort_keys=True)]
            for key in core:
                if key in changes:
                    assignments.append(f"{key} = ?")
                    values.append(changes[key])
            values.append(item_id)
            with state_db.transaction(conn):
                conn.execute(f"UPDATE run_queue SET {', '.join(assignments)} WHERE id = ?", values)
            row = conn.execute("SELECT * FROM run_queue WHERE id = ?", (item_id,)).fetchone()
            value = dict(row)
            payload = json.loads(value.pop("payload_json") or "{}")
            return {**payload, **value}
        finally:
            conn.close()


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
    try:
        _, registry = _read_registry(root)
    except (RuntimeBackendError, yaml.YAMLError):
        return FILESYSTEM_MODE
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


def plan_execution_state_reconciliation(root: str | Path) -> dict[str, Any]:
    """Plan a filesystem-authoritative repair of stale nonterminal SQLite rows."""
    status = queue_mode_status(root)
    if status["queue_mode"] != FILESYSTEM_MODE:
        raise RuntimeBackendError("execution-state reconciliation requires filesystem queue mode")
    blockers = _filesystem_projection_blockers(root)
    counts: dict[str, int] = {}
    for row in blockers:
        issue = str(row.get("projection_issue") or "unknown")
        counts[issue] = counts.get(issue, 0) + 1
    return {
        **status,
        "action": "runtime.queue-mode.reconcile",
        "authoritative_mode": FILESYSTEM_MODE,
        "dry_run": True,
        "reconciliation_count": len(blockers),
        "reconciliation_counts": counts,
        "reconciliation_sample": blockers[:20],
        "ready": status["active_lease_count"] == 0,
        "blockers": []
        if status["active_lease_count"] == 0
        else [f"{status['active_lease_count']} active execution lease(s) must finish or expire"],
    }


def reconcile_execution_state(root: str | Path, *, dry_run: bool = True) -> dict[str, Any]:
    """Archive then reconcile stale fabric state to the authoritative YAML queue."""
    plan = plan_execution_state_reconciliation(root)
    if dry_run or not plan["reconciliation_count"]:
        return {**plan, "dry_run": dry_run, "applied": False, "status": "unchanged" if not plan["reconciliation_count"] else "planned"}
    if not plan["ready"]:
        raise RuntimeBackendError("execution-state reconciliation blocked: " + "; ".join(plan["blockers"]))

    os_root = expand_path(root)
    path = Path(plan["runtime_registry"])
    with _mode_lock(path):
        plan = plan_execution_state_reconciliation(root)
        if not plan["ready"]:
            raise RuntimeBackendError("execution-state reconciliation blocked: " + "; ".join(plan["blockers"]))
        issues = _filesystem_projection_blockers(root)
        issue_by_id = {str(row["id"]): row for row in issues}
        queue_path = os_root / RUN_QUEUE
        loaded = yaml.safe_load(queue_path.read_text(encoding="utf-8")) if queue_path.is_file() else {}
        filesystem_rows = (loaded or {}).get("items") or (loaded or {}).get("run_queue") or []
        filesystem_statuses = {
            str(row["id"]): str(row.get("status") or "unknown")
            for row in filesystem_rows
            if isinstance(row, dict) and row.get("id")
        }

        db_path = state_db.default_db_path(root)
        conn = state_db.connect(db_path)
        try:
            archived_rows = [
                dict(row)
                for row in conn.execute("SELECT * FROM run_queue ORDER BY created_at, id").fetchall()
                if str(row["id"]) in issue_by_id
            ]
            timestamp = datetime.now(timezone.utc).strftime("%m%d%y-%H%M%S")
            receipt_dir = os_root / QUEUE_RECONCILIATION_LOG / f"{timestamp}-{os.getpid()}"
            receipt_dir.mkdir(parents=True, exist_ok=False)
            receipt_dir.chmod(0o700)
            before_path = receipt_dir / "before.json"
            atomic_json(
                before_path,
                {
                    "schema": "agentic-os-runtime-queue-reconciliation-before/v1",
                    "created_at": _now(),
                    "authoritative_queue": str(queue_path),
                    "state_db": str(db_path),
                    "issues": issues,
                    "rows": archived_rows,
                },
            )
            before_path.chmod(0o600)
            changed_at = _now()
            cancelled = 0
            aligned = 0
            with state_db.transaction(conn):
                for item_id, issue in issue_by_id.items():
                    filesystem_status = filesystem_statuses.get(item_id)
                    if filesystem_status is None:
                        conn.execute(
                            """
                            UPDATE run_queue
                            SET status = 'cancelled', updated_at = ?, finished_at = COALESCE(finished_at, ?),
                                lease_owner = NULL, lease_until = NULL, lease_token = NULL,
                                blocked_reason = 'reconciled: absent from authoritative filesystem queue'
                            WHERE id = ?
                            """,
                            (changed_at, changed_at, item_id),
                        )
                        cancelled += 1
                    else:
                        terminal = filesystem_status in {"done", "failed", "skipped", "cancelled", "dead-letter"}
                        conn.execute(
                            """
                            UPDATE run_queue
                            SET status = ?, updated_at = ?, finished_at = CASE WHEN ? THEN COALESCE(finished_at, ?) ELSE finished_at END,
                                lease_owner = NULL, lease_until = NULL, lease_token = NULL,
                                blocked_reason = CASE WHEN ? THEN NULL ELSE blocked_reason END
                            WHERE id = ?
                            """,
                            (filesystem_status, changed_at, int(terminal), changed_at, int(filesystem_status != "blocked"), item_id),
                        )
                        aligned += 1
        finally:
            conn.close()

        remaining = _filesystem_projection_blockers(root)
        receipt_path = receipt_dir / "receipt.json"
        receipt = {
            "schema": "agentic-os-runtime-queue-reconciliation/v1",
            "status": "completed" if not remaining else "failed",
            "completed_at": _now(),
            "before": str(before_path),
            "reconciliation_count": len(issues),
            "cancelled_missing_nonterminal": cancelled,
            "aligned_status_drift": aligned,
            "remaining_count": len(remaining),
            "remaining_sample": remaining[:20],
        }
        atomic_json(receipt_path, receipt)
        if remaining:
            raise RuntimeBackendError(f"execution-state reconciliation left {len(remaining)} blocker(s); see {receipt_path}")
        return {
            **queue_mode_status(root),
            "action": "runtime.queue-mode.reconcile",
            "dry_run": False,
            "applied": True,
            "status": "completed",
            "receipt": str(receipt_path),
            **{key: receipt[key] for key in ("reconciliation_count", "cancelled_missing_nonterminal", "aligned_status_drift", "remaining_count")},
        }


def _queue_metrics_readonly(root: str | Path, mode: str) -> dict[str, Any]:
    try:
        queue_config, _ = _execution_fabric_catalog(root)
        admission = queue_config.get("admission") or {}
        global_max_running = int(admission.get("global_max_running") or 1)
        reserved_interactive_slots = int(admission.get("reserved_interactive_slots") or 0)
        max_interactive_running = int(admission.get("max_interactive_running") or max(1, reserved_interactive_slots))
    except RuntimeBackendError:
        global_max_running = 1
        reserved_interactive_slots = 0
        max_interactive_running = 1
    admission_metrics = {
        "global_max_running": global_max_running,
        "reserved_interactive_slots": reserved_interactive_slots,
        "max_interactive_running": max_interactive_running,
        "background_max_running": max(1, global_max_running - reserved_interactive_slots),
    }
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
            **admission_metrics,
        }
    db_path = state_db.default_db_path(root)
    if not db_path.is_file():
        return {"queue_count": 0, "worker_pool_count": 0, "worker_count": 0, "queues": [], "worker_pools": [], **admission_metrics}
    conn = sqlite3.connect(f"file:{quote(str(db_path))}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        required = {"run_queue", "execution_queues", "worker_pools", "execution_workers"}
        present = {
            str(row["name"])
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
        }
        if not required.issubset(present):
            return {"queue_count": 0, "worker_pool_count": 0, "worker_count": 0, "queues": [], "worker_pools": [], **admission_metrics}
        queue_rows = conn.execute(
            "SELECT queue_name, status, COUNT(*) AS count FROM run_queue GROUP BY queue_name, status ORDER BY queue_name, status"
        ).fetchall()
        queue_map: dict[str, dict[str, Any]] = {}
        for row in queue_rows:
            entry = queue_map.setdefault(str(row["queue_name"]), {"queue_name": str(row["queue_name"]), "statuses": {}, "total": 0})
            entry["statuses"][str(row["status"])] = int(row["count"])
            entry["total"] += int(row["count"])
        configured = conn.execute("SELECT name, max_concurrency, enabled, metadata_json FROM execution_queues ORDER BY name").fetchall()
        for row in configured:
            entry = queue_map.setdefault(str(row["name"]), {"queue_name": str(row["name"]), "statuses": {}, "total": 0})
            metadata = json.loads(row["metadata_json"] or "{}")
            entry.update({"max_concurrency": int(row["max_concurrency"]), "enabled": bool(row["enabled"]), "max_queued": int(metadata.get("max_queued") or 0)})
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
            (_now(), _now()),
        ).fetchall()
        pools = [dict(row) for row in pool_rows]
        return {
            "queue_count": len(queue_map),
            "worker_pool_count": len(pools),
            "worker_count": sum(int(row["worker_count"]) for row in pools),
            "live_worker_count": sum(int(row["live_workers"] or 0) for row in pools),
            "unhealthy_worker_count": sum(int(row["unhealthy_workers"] or 0) for row in pools),
            "dead_letter_count": sum(int(entry["statuses"].get("dead-letter", 0)) for entry in queue_map.values()),
            "queues": list(queue_map.values()),
            "worker_pools": pools,
            **admission_metrics,
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
    projection_blockers = _filesystem_projection_blockers(root) if switching else []
    if projection_blockers:
        if target_mode == EXECUTION_FABRIC_MODE:
            blockers.append(
                f"{len(projection_blockers)} execution-fabric task state(s) cannot be safely activated from the filesystem queue"
            )
        else:
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
            if target_mode == EXECUTION_FABRIC_MODE:
                conn = state_db.connect(state_db.default_db_path(root))
                try:
                    catalog = _configure_execution_fabric(root, conn)
                finally:
                    conn.close()
                return {**queue_mode_status(root), "target_mode": target_mode, "dry_run": False, "applied": True, "status": "reconciled", "catalog": catalog}
            return {**plan, "dry_run": False, "applied": False, "status": "unchanged"}

        import_receipt: dict[str, Any] | None = None
        if target_mode == EXECUTION_FABRIC_MODE:
            # Lazy import avoids loading event_graph -> runtime_ops while the
            # runtime composition root itself is still importing.
            from .state.importers import import_run_queue

            conn = state_db.connect(state_db.default_db_path(root))
            try:
                catalog = _configure_execution_fabric(root, conn)
                queue_path = expand_path(root) / RUN_QUEUE
                if queue_path.is_file():
                    import_receipt = import_run_queue(conn, queue_path)
                    for row in conn.execute("SELECT id, execution_target, payload_json FROM run_queue").fetchall():
                        payload = json.loads(row["payload_json"] or "{}")
                        route = resolve_execution_route(root, {**payload, "execution_target": row["execution_target"]})
                        conn.execute(
                            "UPDATE run_queue SET queue_name = ?, worker_pool = ? WHERE id = ?",
                            (route["queue_name"], route["worker_pool"], row["id"]),
                        )
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
            "catalog": catalog if target_mode == EXECUTION_FABRIC_MODE else None,
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
