"""Transactional named queues, worker pools, leases, and admission control."""

from __future__ import annotations

from datetime import timedelta
import json
import sqlite3
from typing import Any
import uuid

from . import queue as state_queue
from .db import parse_iso, row_to_dict, transaction, utc_now_iso


class ExecutionFabricError(RuntimeError):
    """Raised when an execution-fabric invariant would be violated."""


DEFAULT_RECOVERY_BACKOFF_SECONDS = 60
MAX_RECOVERY_BACKOFF_SECONDS = 1800


def _future_iso(now: str, seconds: int) -> str:
    if seconds < 1:
        raise ExecutionFabricError("lease_seconds must be at least 1")
    return (parse_iso(now) + timedelta(seconds=seconds)).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _recovery_backoff_seconds(item: dict[str, Any]) -> int:
    """Use the task's persisted retry policy for abandoned lease recovery."""
    payload = item.get("payload")
    if not isinstance(payload, dict):
        try:
            payload = json.loads(str(item.get("payload_json") or "{}"))
        except (TypeError, ValueError, json.JSONDecodeError):
            payload = {}
    retry_policy = payload.get("retry_policy") if isinstance(payload.get("retry_policy"), dict) else {}
    try:
        base = max(1, int(retry_policy.get("backoff_seconds", DEFAULT_RECOVERY_BACKOFF_SECONDS)))
    except (TypeError, ValueError):
        base = DEFAULT_RECOVERY_BACKOFF_SECONDS
    attempt = max(1, int(item.get("attempts") or 1))
    return min(MAX_RECOVERY_BACKOFF_SECONDS, base * (2 ** (attempt - 1)))


def _decode_json_row(row: sqlite3.Row | None) -> dict[str, Any] | None:
    value = row_to_dict(row)
    if value is None:
        return None
    value["metadata"] = json.loads(value.pop("metadata_json") or "{}")
    if "enabled" in value:
        value["enabled"] = bool(value["enabled"])
    return value


def configure_queue(
    conn: sqlite3.Connection,
    name: str,
    *,
    max_concurrency: int,
    enabled: bool = True,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not name or max_concurrency < 1:
        raise ExecutionFabricError("queue name must be non-empty and max_concurrency must be positive")
    now = utc_now_iso()
    with transaction(conn):
        conn.execute(
            """
            INSERT INTO execution_queues (name, max_concurrency, enabled, metadata_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(name) DO UPDATE SET
                max_concurrency = excluded.max_concurrency,
                enabled = excluded.enabled,
                metadata_json = excluded.metadata_json,
                updated_at = excluded.updated_at
            """,
            (name, max_concurrency, int(enabled), json.dumps(metadata or {}, sort_keys=True), now, now),
        )
    return _decode_json_row(conn.execute("SELECT * FROM execution_queues WHERE name = ?", (name,)).fetchone())  # type: ignore[return-value]


def configure_worker_pool(
    conn: sqlite3.Connection,
    name: str,
    *,
    queue_name: str,
    max_workers: int,
    max_concurrency: int,
    provider: str | None = None,
    enabled: bool = True,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not name or max_workers < 1 or max_concurrency < 1:
        raise ExecutionFabricError("pool name and positive worker/concurrency limits are required")
    now = utc_now_iso()
    with transaction(conn):
        if conn.execute("SELECT 1 FROM execution_queues WHERE name = ?", (queue_name,)).fetchone() is None:
            raise ExecutionFabricError(f"unknown execution queue: {queue_name}")
        conn.execute(
            """
            INSERT INTO worker_pools (
                name, queue_name, max_workers, max_concurrency, provider, enabled,
                metadata_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(name) DO UPDATE SET
                queue_name = excluded.queue_name,
                max_workers = excluded.max_workers,
                max_concurrency = excluded.max_concurrency,
                provider = excluded.provider,
                enabled = excluded.enabled,
                metadata_json = excluded.metadata_json,
                updated_at = excluded.updated_at
            """,
            (
                name,
                queue_name,
                max_workers,
                max_concurrency,
                provider,
                int(enabled),
                json.dumps(metadata or {}, sort_keys=True),
                now,
                now,
            ),
        )
    return _decode_json_row(conn.execute("SELECT * FROM worker_pools WHERE name = ?", (name,)).fetchone())  # type: ignore[return-value]


def configure_limit(
    conn: sqlite3.Connection,
    *,
    scope: str,
    key: str,
    max_concurrency: int,
) -> dict[str, Any]:
    if scope not in {"global", "provider"}:
        raise ExecutionFabricError("limit scope must be global or provider")
    if not key or max_concurrency < 1:
        raise ExecutionFabricError("limit key and positive max_concurrency are required")
    now = utc_now_iso()
    with transaction(conn):
        conn.execute(
            """
            INSERT INTO execution_limits (scope, key, max_concurrency, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(scope, key) DO UPDATE SET
                max_concurrency = excluded.max_concurrency,
                updated_at = excluded.updated_at
            """,
            (scope, key, max_concurrency, now, now),
        )
    row = conn.execute(
        "SELECT scope, key, max_concurrency, created_at, updated_at FROM execution_limits WHERE scope = ? AND key = ?",
        (scope, key),
    ).fetchone()
    return dict(row)  # type: ignore[arg-type]


def register_worker(
    conn: sqlite3.Connection,
    worker_id: str,
    *,
    pool_name: str,
    capacity: int = 1,
    lease_seconds: int = 300,
    metadata: dict[str, Any] | None = None,
    now: str | None = None,
) -> dict[str, Any]:
    if not worker_id or capacity < 1:
        raise ExecutionFabricError("worker_id and positive capacity are required")
    now_value = now or utc_now_iso()
    lease_until = _future_iso(now_value, lease_seconds)
    lease_token = uuid.uuid4().hex
    with transaction(conn):
        if conn.execute("SELECT 1 FROM worker_pools WHERE name = ?", (pool_name,)).fetchone() is None:
            raise ExecutionFabricError(f"unknown worker pool: {pool_name}")
        active_claims = conn.execute(
            "SELECT COUNT(*) FROM run_queue WHERE status = 'running' AND lease_owner = ?",
            (worker_id,),
        ).fetchone()[0]
        if active_claims:
            raise ExecutionFabricError(
                f"worker id still owns running tasks and cannot be re-registered: {worker_id}"
            )
        conn.execute(
            """
            INSERT INTO execution_workers (
                id, pool_name, status, capacity, active_tasks, heartbeat_at,
                lease_until, lease_token, metadata_json, created_at, updated_at
            ) VALUES (?, ?, 'online', ?, 0, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                pool_name = excluded.pool_name,
                status = 'online',
                capacity = excluded.capacity,
                heartbeat_at = excluded.heartbeat_at,
                lease_until = excluded.lease_until,
                lease_token = excluded.lease_token,
                metadata_json = excluded.metadata_json,
                updated_at = excluded.updated_at
            """,
            (
                worker_id,
                pool_name,
                capacity,
                now_value,
                lease_until,
                lease_token,
                json.dumps(metadata or {}, sort_keys=True),
                now_value,
                now_value,
            ),
        )
    return _decode_json_row(conn.execute("SELECT * FROM execution_workers WHERE id = ?", (worker_id,)).fetchone())  # type: ignore[return-value]


def heartbeat_worker(
    conn: sqlite3.Connection,
    worker_id: str,
    *,
    worker_token: str,
    lease_seconds: int = 300,
    task_lease_seconds: int | None = None,
    now: str | None = None,
) -> dict[str, Any]:
    now_value = now or utc_now_iso()
    worker_lease = _future_iso(now_value, lease_seconds)
    task_lease = _future_iso(now_value, task_lease_seconds or lease_seconds)
    with transaction(conn):
        current = conn.execute("SELECT * FROM execution_workers WHERE id = ?", (worker_id,)).fetchone()
        if current is None:
            raise ExecutionFabricError(f"unknown execution worker: {worker_id}")
        if (
            current["lease_token"] != worker_token
            or current["status"] != "online"
            or current["lease_until"] < now_value
        ):
            raise ExecutionFabricError(f"worker lease is inactive or fenced: {worker_id}")
        active = conn.execute(
            """
            SELECT COUNT(*) FROM run_queue
            WHERE status = 'running' AND lease_owner = ? AND lease_until >= ?
            """,
            (worker_id, now_value),
        ).fetchone()[0]
        conn.execute(
            """
            UPDATE execution_workers
            SET status = 'online', active_tasks = ?, heartbeat_at = ?, lease_until = ?, updated_at = ?
            WHERE id = ? AND lease_token = ? AND status = 'online' AND lease_until >= ?
            """,
            (active, now_value, worker_lease, now_value, worker_id, worker_token, now_value),
        )
        conn.execute(
            """
            UPDATE run_queue SET lease_until = ?, updated_at = ?
            WHERE status = 'running' AND lease_owner = ? AND lease_until >= ?
            """,
            (task_lease, now_value, worker_id, now_value),
        )
    return _decode_json_row(conn.execute("SELECT * FROM execution_workers WHERE id = ?", (worker_id,)).fetchone())  # type: ignore[return-value]


def enqueue_task(
    conn: sqlite3.Connection,
    *,
    queue_name: str,
    worker_pool: str,
    kind: str,
    **kwargs: Any,
) -> dict[str, Any]:
    with transaction(conn):
        route = conn.execute(
            """
            SELECT q.enabled AS queue_enabled, p.enabled AS pool_enabled, q.metadata_json
            FROM execution_queues q
            JOIN worker_pools p ON p.queue_name = q.name
            WHERE q.name = ? AND p.name = ?
            """,
            (queue_name, worker_pool),
        ).fetchone()
        if route is None:
            raise ExecutionFabricError(f"worker pool {worker_pool!r} does not serve queue {queue_name!r}")
        if not route["queue_enabled"] or not route["pool_enabled"]:
            raise ExecutionFabricError("execution queue or worker pool is disabled")
        metadata = json.loads(route["metadata_json"] or "{}")
        max_queued = int(metadata.get("max_queued") or 0)
        if max_queued:
            queued = conn.execute(
                "SELECT COUNT(*) FROM run_queue WHERE queue_name = ? AND status IN ('queued', 'approval-needed')",
                (queue_name,),
            ).fetchone()[0]
            if queued >= max_queued:
                raise ExecutionFabricError(f"execution queue {queue_name!r} reached max_queued={max_queued}")
        return state_queue.enqueue(
            conn,
            queue_name=queue_name,
            worker_pool=worker_pool,
            kind=kind,
            **kwargs,
        )


def claim_next(
    conn: sqlite3.Connection,
    *,
    worker_id: str,
    worker_token: str,
    lease_seconds: int = 300,
    now: str | None = None,
    item_id: str | None = None,
) -> dict[str, Any] | None:
    """Atomically admit and lease one task without exceeding queue/pool/worker caps."""
    now_value = now or utc_now_iso()
    task_lease = _future_iso(now_value, lease_seconds)
    with transaction(conn):
        worker = conn.execute(
            """
            SELECT w.*, p.queue_name, p.provider, p.max_workers, p.max_concurrency AS pool_max_concurrency,
                   p.enabled AS pool_enabled, q.max_concurrency AS queue_max_concurrency,
                   q.enabled AS queue_enabled
            FROM execution_workers w
            JOIN worker_pools p ON p.name = w.pool_name
            JOIN execution_queues q ON q.name = p.queue_name
            WHERE w.id = ?
            """,
            (worker_id,),
        ).fetchone()
        if worker is None:
            raise ExecutionFabricError(f"unknown execution worker: {worker_id}")
        if (
            worker["lease_token"] != worker_token
            or worker["status"] != "online"
            or worker["lease_until"] < now_value
        ):
            raise ExecutionFabricError(f"worker lease is inactive or fenced: {worker_id}")
        if not worker["pool_enabled"] or not worker["queue_enabled"]:
            return None

        worker_running = conn.execute(
            """
            SELECT COUNT(*) FROM run_queue
            WHERE status = 'running' AND lease_owner = ? AND lease_until >= ?
            """,
            (worker_id, now_value),
        ).fetchone()[0]
        if worker_running >= worker["capacity"]:
            return None

        active_workers = conn.execute(
            """
            SELECT COUNT(DISTINCT lease_owner) FROM run_queue
            WHERE status = 'running' AND worker_pool = ? AND lease_until >= ?
            """,
            (worker["pool_name"], now_value),
        ).fetchone()[0]
        if worker_running == 0 and active_workers >= worker["max_workers"]:
            return None

        global_limit = conn.execute(
            "SELECT max_concurrency FROM execution_limits WHERE scope = 'global' AND key = '*'"
        ).fetchone()
        if global_limit is not None:
            global_running = conn.execute(
                "SELECT COUNT(*) FROM run_queue WHERE status = 'running' AND lease_until >= ?",
                (now_value,),
            ).fetchone()[0]
            if global_running >= global_limit["max_concurrency"]:
                return None

        if worker["provider"]:
            provider_limit = conn.execute(
                "SELECT max_concurrency FROM execution_limits WHERE scope = 'provider' AND key = ?",
                (worker["provider"],),
            ).fetchone()
            if provider_limit is not None:
                provider_running = conn.execute(
                    """
                    SELECT COUNT(*) FROM run_queue q
                    JOIN worker_pools p ON p.name = q.worker_pool
                    WHERE q.status = 'running' AND q.lease_until >= ? AND p.provider = ?
                    """,
                    (now_value, worker["provider"]),
                ).fetchone()[0]
                if provider_running >= provider_limit["max_concurrency"]:
                    return None

        pool_running = conn.execute(
            """
            SELECT COUNT(*) FROM run_queue
            WHERE status = 'running' AND worker_pool = ? AND lease_until >= ?
            """,
            (worker["pool_name"], now_value),
        ).fetchone()[0]
        queue_running = conn.execute(
            """
            SELECT COUNT(*) FROM run_queue
            WHERE status = 'running' AND queue_name = ? AND lease_until >= ?
            """,
            (worker["queue_name"], now_value),
        ).fetchone()[0]
        if pool_running >= worker["pool_max_concurrency"] or queue_running >= worker["queue_max_concurrency"]:
            return None

        item_filter = "AND id = ?" if item_id else ""
        params: tuple[Any, ...] = (
            worker["queue_name"],
            worker["pool_name"],
            now_value,
            now_value,
            *((item_id,) if item_id else ()),
            state_queue.starvation_cutoff(now_value),
            state_queue.starvation_cutoff(now_value),
        )
        row = conn.execute(
            f"""
            SELECT id FROM run_queue
            WHERE status = 'queued' AND queue_name = ? AND worker_pool = ?
              AND (due_at IS NULL OR due_at <= ?)
              AND (lease_until IS NULL OR lease_until < ?)
              {item_filter}
            ORDER BY
              COALESCE(priority, 0) + CASE WHEN COALESCE(due_at, created_at) <= ? THEN 10 ELSE 0 END DESC,
              COALESCE(CASE WHEN COALESCE(due_at, created_at) <= ? THEN substr(COALESCE(due_at, created_at), 1, 13) END, '~') ASC,
              priority DESC,
              (due_at IS NULL) ASC, due_at ASC, created_at ASC
            LIMIT 1
            """,
            params,
        ).fetchone()
        if row is None:
            return None
        item_id = row["id"]
        lease_token = uuid.uuid4().hex
        conn.execute(
            """
            UPDATE run_queue
            SET status = 'running', lease_owner = ?, lease_until = ?, lease_token = ?, attempts = attempts + 1,
                started_at = COALESCE(started_at, ?), updated_at = ?
            WHERE id = ? AND status = 'queued'
            """,
            (worker_id, task_lease, lease_token, now_value, now_value, item_id),
        )
        conn.execute(
            "UPDATE execution_workers SET active_tasks = ?, updated_at = ? WHERE id = ?",
            (worker_running + 1, now_value, worker_id),
        )
        return state_queue.get(conn, item_id)


def _release_worker(conn: sqlite3.Connection, worker_id: str | None, now: str) -> None:
    if not worker_id:
        return
    active = conn.execute(
        "SELECT COUNT(*) FROM run_queue WHERE status = 'running' AND lease_owner = ?",
        (worker_id,),
    ).fetchone()[0]
    conn.execute(
        "UPDATE execution_workers SET active_tasks = ?, updated_at = ? WHERE id = ?",
        (active, now, worker_id),
    )


def retire_worker(
    conn: sqlite3.Connection,
    worker_id: str,
    *,
    worker_token: str,
    now: str | None = None,
) -> bool:
    """Mark an ephemeral dispatcher offline once it owns no running tasks."""
    now_value = now or utc_now_iso()
    with transaction(conn):
        running = conn.execute(
            "SELECT COUNT(*) FROM run_queue WHERE status = 'running' AND lease_owner = ?",
            (worker_id,),
        ).fetchone()[0]
        if running:
            return False
        cursor = conn.execute(
            """
            UPDATE execution_workers
            SET status = 'offline', active_tasks = 0, lease_until = ?, updated_at = ?
            WHERE id = ? AND lease_token = ?
            """,
            (now_value, now_value, worker_id, worker_token),
        )
    return cursor.rowcount == 1


def complete_task(
    conn: sqlite3.Connection,
    item_id: str,
    *,
    worker_id: str,
    worker_token: str,
    lease_token: str,
    status: str = "done",
    error: str | None = None,
    now: str | None = None,
) -> dict[str, Any]:
    if status not in ("done", "failed", "skipped"):
        raise ExecutionFabricError("completion status must be done, failed, or skipped")
    now_value = now or utc_now_iso()
    with transaction(conn):
        worker = conn.execute(
            "SELECT status, lease_until, lease_token FROM execution_workers WHERE id = ?",
            (worker_id,),
        ).fetchone()
        item = state_queue.get(conn, item_id)
        if item is None:
            raise ExecutionFabricError(f"unknown execution task: {item_id}")
        if (
            worker is None
            or worker["status"] != "online"
            or worker["lease_until"] < now_value
            or worker["lease_token"] != worker_token
            or item.get("status") != "running"
            or item.get("lease_owner") != worker_id
            or item.get("lease_token") != lease_token
            or not item.get("lease_until")
            or str(item["lease_until"]) < now_value
        ):
            raise ExecutionFabricError(
                f"worker {worker_id!r} does not own the active fenced lease for task {item_id!r}"
            )
        conn.execute(
            """
            UPDATE run_queue SET status = ?, error = COALESCE(?, error), finished_at = ?,
                lease_owner = NULL, lease_until = NULL, lease_token = NULL, updated_at = ?
            WHERE id = ? AND status = 'running' AND lease_owner = ? AND lease_token = ? AND lease_until >= ?
            """,
            (status, error, now_value, now_value, item_id, worker_id, lease_token, now_value),
        )
        _release_worker(conn, worker_id, now_value)
    return state_queue.get(conn, item_id)  # type: ignore[return-value]


def retry_task(
    conn: sqlite3.Connection,
    item_id: str,
    *,
    error: str | None = None,
    backoff_seconds: int = 0,
    worker_id: str | None = None,
    worker_token: str | None = None,
    lease_token: str | None = None,
    now: str | None = None,
) -> dict[str, Any]:
    """Requeue a recoverable failure or dead-letter an exhausted task.

    A running task is mutable only by the worker holding both the current
    worker fence and task lease tokens. Queued tasks may still be retried by
    recovery/operator paths without fabricating a worker lease.
    """
    if backoff_seconds < 0:
        raise ExecutionFabricError("backoff_seconds cannot be negative")
    now_value = now or utc_now_iso()
    with transaction(conn):
        item = state_queue.get(conn, item_id)
        if item is None:
            raise ExecutionFabricError(f"unknown execution task: {item_id}")
        lease_owner = item.get("lease_owner")
        if item.get("status") == "running":
            worker = conn.execute(
                "SELECT status, lease_until, lease_token FROM execution_workers WHERE id = ?",
                (worker_id,),
            ).fetchone()
            if (
                not worker_id
                or not worker_token
                or not lease_token
                or worker is None
                or worker["status"] != "online"
                or worker["lease_until"] < now_value
                or worker["lease_token"] != worker_token
                or lease_owner != worker_id
                or item.get("lease_token") != lease_token
                or not item.get("lease_until")
                or str(item["lease_until"]) < now_value
            ):
                raise ExecutionFabricError(
                    f"worker {worker_id!r} does not own the active fenced lease for task {item_id!r}"
                )
        exhausted = int(item["attempts"]) >= int(item["max_attempts"])
        status = "dead-letter" if exhausted else "queued"
        queue_name = item.get("dead_letter_queue") if exhausted and item.get("dead_letter_queue") else item["queue_name"]
        due_at = None if exhausted else (_future_iso(now_value, backoff_seconds) if backoff_seconds else now_value)
        finished_at = now_value if exhausted else None
        conn.execute(
            """
            UPDATE run_queue SET status = ?, queue_name = ?, error = COALESCE(?, error),
                due_at = ?, lease_owner = NULL, lease_until = NULL, lease_token = NULL,
                finished_at = ?, updated_at = ?
            WHERE id = ?
            """,
            (status, queue_name, error, due_at, finished_at, now_value, item_id),
        )
        _release_worker(conn, lease_owner, now_value)
    return state_queue.get(conn, item_id)  # type: ignore[return-value]


def cancel_task(conn: sqlite3.Connection, item_id: str, *, reason: str | None = None, now: str | None = None) -> dict[str, Any]:
    now_value = now or utc_now_iso()
    with transaction(conn):
        item = state_queue.get(conn, item_id)
        if item is None:
            raise ExecutionFabricError(f"unknown execution task: {item_id}")
        worker_id = item.get("lease_owner")
        conn.execute(
            """
            UPDATE run_queue SET status = 'cancelled', error = COALESCE(?, error),
                finished_at = ?, lease_owner = NULL, lease_until = NULL, lease_token = NULL, updated_at = ?
            WHERE id = ?
            """,
            (reason, now_value, now_value, item_id),
        )
        _release_worker(conn, worker_id, now_value)
    return state_queue.get(conn, item_id)  # type: ignore[return-value]


def recover_expired_leases(conn: sqlite3.Connection, *, now: str | None = None) -> dict[str, Any]:
    """Requeue abandoned work, dead-lettering tasks whose attempt budget is exhausted."""
    now_value = now or utc_now_iso()
    recovered: list[str] = []
    dead_lettered: list[str] = []
    workers: set[str] = set()
    expired_workers: list[str] = []
    with transaction(conn):
        rows = conn.execute(
            """
            SELECT * FROM run_queue
            WHERE status = 'running' AND lease_until IS NOT NULL AND lease_until < ?
            ORDER BY lease_until, id
            """,
            (now_value,),
        ).fetchall()
        for row in rows:
            item = dict(row)
            if item.get("lease_owner"):
                workers.add(str(item["lease_owner"]))
            exhausted = int(item["attempts"]) >= int(item["max_attempts"])
            status = "dead-letter" if exhausted else "queued"
            queue_name = (
                item.get("dead_letter_queue")
                if exhausted and item.get("dead_letter_queue")
                else item["queue_name"]
            )
            due_at = None if exhausted else _future_iso(now_value, _recovery_backoff_seconds(item))
            finished_at = now_value if exhausted else None
            conn.execute(
                """
                UPDATE run_queue SET status = ?, queue_name = ?, lease_owner = NULL,
                    lease_until = NULL, lease_token = NULL, due_at = ?, finished_at = ?,
                    updated_at = ? WHERE id = ?
                """,
                (status, queue_name, due_at, finished_at, now_value, item["id"]),
            )
            (dead_lettered if exhausted else recovered).append(str(item["id"]))
        for worker_id in workers:
            _release_worker(conn, worker_id, now_value)
        expired_rows = conn.execute(
            "SELECT id FROM execution_workers WHERE lease_until < ? AND status != 'offline' ORDER BY id",
            (now_value,),
        ).fetchall()
        expired_workers = [str(row["id"]) for row in expired_rows]
        if expired_workers:
            conn.executemany(
                "UPDATE execution_workers SET status = 'offline', active_tasks = 0, updated_at = ? WHERE id = ?",
                [(now_value, worker_id) for worker_id in expired_workers],
            )
    return {
        "recovered": recovered,
        "dead_lettered": dead_lettered,
        "matched": len(recovered) + len(dead_lettered),
        "expired_workers": expired_workers,
    }


def active_leases(conn: sqlite3.Connection, *, now: str | None = None) -> list[dict[str, Any]]:
    now_value = now or utc_now_iso()
    rows = conn.execute(
        """
        SELECT id, queue_name, worker_pool, lease_owner, lease_until
        FROM run_queue
        WHERE status = 'running' AND lease_owner IS NOT NULL AND lease_until >= ?
        ORDER BY lease_until, id
        """,
        (now_value,),
    ).fetchall()
    return [dict(row) for row in rows]
