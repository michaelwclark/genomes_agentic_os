"""``run_queue`` table: the dispatch queue (distinct from the ``events``
audit ledger and from any future ``runs`` audit-log table).

Column set is grounded in the real, live ``run-queue.yml`` item shape
(verified by structural inspection, not just the audit's sketch — see
``docs/design-notes/state-plane.md``), plus four columns that do not exist
in the YAML today: ``priority``, ``attempts``, ``lease_owner``,
``lease_until``. Those four exist to support ``claim_next``'s lease-based
outbox-style claiming, which the YAML format has no equivalent for.

Fields specific to only some queue-item kinds (``command``, ``log``,
``dispatch_log``, ``evidence``, ``external_effect``, and the
event-chain-only fields like ``work_type``/``workflow``/``chain_depth``)
live in ``payload_json`` rather than as dedicated columns, matching the
event ledger's own ``payload_ref`` catch-all pattern.
"""

from __future__ import annotations

from datetime import timedelta
import json
import sqlite3
from typing import Any, Sequence
import uuid

from .db import days_ago_iso, parse_iso, row_to_dict, transaction, utc_now_iso

# Matches the "states"/"approval_states" vocabulary declared in the real
# run-queue.yml (and in event_graph.default_run_queue()).
VALID_STATUSES = (
    "dry-run",
    "queued",
    "approval-needed",
    "running",
    "blocked",
    "done",
    "failed",
    "skipped",
    "cancelled",
    "dead-letter",
)
VALID_APPROVAL_STATES = ("not_required", "required", "approved", "denied", "expired", "blocked")

TERMINAL_STATUSES = ("done", "failed", "skipped", "cancelled", "dead-letter")
DISPATCH_STARVATION_AGE_SECONDS = 3600

_INSERT_SQL = """
INSERT INTO run_queue (
    id, kind, ref, status, approval_state, priority, idempotency_key, execution_target,
    dry_run, created_at, updated_at, due_at, started_at, finished_at, attempts,
    lease_owner, lease_until, blocked_reason, error, payload_json, queue_name,
    worker_pool, max_attempts, dead_letter_queue, lease_token
) VALUES (
    :id, :kind, :ref, :status, :approval_state, :priority, :idempotency_key, :execution_target,
    :dry_run, :created_at, :updated_at, :due_at, :started_at, :finished_at, :attempts,
    :lease_owner, :lease_until, :blocked_reason, :error, :payload_json, :queue_name,
    :worker_pool, :max_attempts, :dead_letter_queue, :lease_token
)
"""


class StateQueueError(RuntimeError):
    """Raised for run_queue item errors (not found, invalid status, ...)."""


def starvation_cutoff(now: str) -> str:
    """Return the availability timestamp before which queued work is starvation-aged."""
    return (parse_iso(now) - timedelta(seconds=DISPATCH_STARVATION_AGE_SECONDS)).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def _decode(row: sqlite3.Row | None) -> dict[str, Any] | None:
    data = row_to_dict(row)
    if data is None:
        return None
    data["payload"] = json.loads(data.pop("payload_json") or "{}")
    data["dry_run"] = bool(data["dry_run"])
    return data


def enqueue(
    conn: sqlite3.Connection,
    *,
    kind: str,
    id: str | None = None,  # noqa: A002 - matches the domain's "id" vocabulary
    ref: str | None = None,
    status: str = "queued",
    approval_state: str = "not_required",
    priority: int = 0,
    idempotency_key: str | None = None,
    execution_target: str | None = None,
    dry_run: bool = False,
    due_at: str | None = None,
    payload: dict[str, Any] | list[Any] | None = None,
    created_at: str | None = None,
    queue_name: str = "default",
    worker_pool: str = "default",
    max_attempts: int = 3,
    dead_letter_queue: str | None = None,
) -> dict[str, Any]:
    if status not in VALID_STATUSES:
        raise StateQueueError(f"invalid status: {status!r} (expected one of {VALID_STATUSES})")
    if approval_state not in VALID_APPROVAL_STATES:
        raise StateQueueError(f"invalid approval_state: {approval_state!r} (expected one of {VALID_APPROVAL_STATES})")
    if not queue_name or not worker_pool:
        raise StateQueueError("queue_name and worker_pool must be non-empty")
    if max_attempts < 1:
        raise StateQueueError("max_attempts must be at least 1")
    now_value = utc_now_iso()
    row = {
        "id": id or f"queue_{uuid.uuid4().hex[:12]}",
        "kind": kind,
        "ref": ref,
        "status": status,
        "approval_state": approval_state,
        "priority": priority,
        "idempotency_key": idempotency_key,
        "execution_target": execution_target,
        "dry_run": int(bool(dry_run)),
        "created_at": created_at or now_value,
        "updated_at": now_value,
        "due_at": due_at,
        "started_at": None,
        "finished_at": None,
        "attempts": 0,
        "lease_owner": None,
        "lease_until": None,
        "blocked_reason": None,
        "error": None,
        "payload_json": json.dumps(payload if payload is not None else {}, sort_keys=True),
        "queue_name": queue_name,
        "worker_pool": worker_pool,
        "max_attempts": max_attempts,
        "dead_letter_queue": dead_letter_queue,
        "lease_token": None,
    }
    try:
        conn.execute(_INSERT_SQL, row)
    except sqlite3.IntegrityError as exc:
        raise StateQueueError(f"could not enqueue item {row['id']!r}: {exc}") from exc
    return _decode(conn.execute("SELECT * FROM run_queue WHERE id = ?", (row["id"],)).fetchone())  # type: ignore[return-value]


def get(conn: sqlite3.Connection, item_id: str) -> dict[str, Any] | None:
    return _decode(conn.execute("SELECT * FROM run_queue WHERE id = ?", (item_id,)).fetchone())


def update_status(
    conn: sqlite3.Connection,
    item_id: str,
    status: str,
    *,
    error: str | None = None,
    blocked_reason: str | None = None,
    finished_at: str | None = None,
    now: str | None = None,
) -> dict[str, Any]:
    if status not in VALID_STATUSES:
        raise StateQueueError(f"invalid status: {status!r} (expected one of {VALID_STATUSES})")
    now_value = now or utc_now_iso()
    conn.execute(
        """
        UPDATE run_queue
        SET status = ?, error = COALESCE(?, error), blocked_reason = COALESCE(?, blocked_reason),
            finished_at = COALESCE(?, finished_at), updated_at = ?
        WHERE id = ?
        """,
        (status, error, blocked_reason, finished_at, now_value, item_id),
    )
    result = get(conn, item_id)
    if result is None:
        raise StateQueueError(f"run_queue item not found: {item_id}")
    return result


def claim_next(
    conn: sqlite3.Connection,
    *,
    worker_id: str,
    lease_seconds: int = 300,
    statuses: Sequence[str] = ("queued",),
    now: str | None = None,
) -> dict[str, Any] | None:
    """Lease-claim the next eligible item, per the FORGE outbox pattern
    (``claimNextPending`` / lease-based delivery). Uses BEGIN IMMEDIATE so
    two concurrent claimants cannot both win the same row: the second
    claimant's transaction blocks (up to busy_timeout) until the first
    commits, then re-evaluates the WHERE clause and sees the row already
    leased/running.

    ``statuses`` is the full set of statuses eligible for claiming (default
    ``("queued",)`` — plain fresh dispatch). An item is only ever actually
    claimable when its lease is absent or expired, so to additionally
    reclaim abandoned leases (e.g. a worker that crashed mid-item), pass
    ``statuses=("queued", "running")`` explicitly — active (non-expired)
    leases on "running" items stay protected either way.
    """
    now_value = now or utc_now_iso()
    placeholders = ",".join("?" for _ in statuses)
    lease_until = (parse_iso(now_value) + timedelta(seconds=lease_seconds)).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )
    lease_token = uuid.uuid4().hex
    starvation_cutoff_value = starvation_cutoff(now_value)
    with transaction(conn):
        row = conn.execute(
            f"""
            SELECT id FROM run_queue
            WHERE status IN ({placeholders})
              AND (due_at IS NULL OR due_at <= ?)
              AND (lease_until IS NULL OR lease_until < ?)
            ORDER BY
              CASE WHEN COALESCE(due_at, created_at) <= ? THEN 0 ELSE 1 END,
              CASE WHEN COALESCE(due_at, created_at) <= ? THEN COALESCE(due_at, created_at) END ASC,
              priority DESC, (due_at IS NULL) ASC, due_at ASC, created_at ASC
            LIMIT 1
            """,
            (*statuses, now_value, now_value, starvation_cutoff_value, starvation_cutoff_value),
        ).fetchone()
        if row is None:
            return None
        item_id = row["id"]
        conn.execute(
            """
            UPDATE run_queue
            SET status = 'running', lease_owner = ?, lease_until = ?, lease_token = ?, attempts = attempts + 1,
                started_at = COALESCE(started_at, ?), updated_at = ?
            WHERE id = ?
            """,
            (worker_id, lease_until, lease_token, now_value, now_value, item_id),
        )
        return _decode(conn.execute("SELECT * FROM run_queue WHERE id = ?", (item_id,)).fetchone())


def complete(
    conn: sqlite3.Connection,
    item_id: str,
    *,
    status: str = "done",
    error: str | None = None,
    now: str | None = None,
) -> dict[str, Any]:
    if status not in VALID_STATUSES:
        raise StateQueueError(f"invalid status: {status!r} (expected one of {VALID_STATUSES})")
    now_value = now or utc_now_iso()
    conn.execute(
        """
        UPDATE run_queue
        SET status = ?, error = COALESCE(?, error), finished_at = ?, lease_owner = NULL,
            lease_until = NULL, lease_token = NULL, updated_at = ?
        WHERE id = ?
        """,
        (status, error, now_value, now_value, item_id),
    )
    result = get(conn, item_id)
    if result is None:
        raise StateQueueError(f"run_queue item not found: {item_id}")
    return result


def query(
    conn: sqlite3.Connection,
    *,
    status: str | None = None,
    kind: str | None = None,
    queue_name: str | None = None,
    worker_pool: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict[str, Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if status is not None:
        clauses.append("status = ?")
        params.append(status)
    if kind is not None:
        clauses.append("kind = ?")
        params.append(kind)
    if queue_name is not None:
        clauses.append("queue_name = ?")
        params.append(queue_name)
    if worker_pool is not None:
        clauses.append("worker_pool = ?")
        params.append(worker_pool)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = conn.execute(
        f"SELECT * FROM run_queue {where} ORDER BY priority DESC, created_at ASC LIMIT ? OFFSET ?",
        (*params, limit, offset),
    ).fetchall()
    return [_decode(row) for row in rows]  # type: ignore[misc]


def count(
    conn: sqlite3.Connection,
    *,
    status: str | None = None,
    kind: str | None = None,
    queue_name: str | None = None,
    worker_pool: str | None = None,
) -> int:
    clauses: list[str] = []
    params: list[Any] = []
    if status is not None:
        clauses.append("status = ?")
        params.append(status)
    if kind is not None:
        clauses.append("kind = ?")
        params.append(kind)
    if queue_name is not None:
        clauses.append("queue_name = ?")
        params.append(queue_name)
    if worker_pool is not None:
        clauses.append("worker_pool = ?")
        params.append(worker_pool)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    row = conn.execute(f"SELECT COUNT(*) FROM run_queue {where}", params).fetchone()
    return int(row[0])


def prune(
    conn: sqlite3.Connection,
    *,
    older_than_days: int,
    statuses: Sequence[str] = TERMINAL_STATUSES,
    dry_run: bool = True,
    now: str | None = None,
) -> dict[str, Any]:
    """Replaces the currently-manual ``run-queue-prune`` step. Dry-run by
    default at the CLI layer; this function defaults to dry-run too so
    calling it directly is equally safe."""
    cutoff = days_ago_iso(older_than_days, now=now)
    placeholders = ",".join("?" for _ in statuses)
    rows = conn.execute(
        f"SELECT id FROM run_queue WHERE status IN ({placeholders}) AND updated_at < ?",
        (*statuses, cutoff),
    ).fetchall()
    ids: Sequence[str] = [row["id"] for row in rows]
    if not dry_run and ids:
        with transaction(conn):
            conn.executemany("DELETE FROM run_queue WHERE id = ?", [(item_id,) for item_id in ids])
    return {
        "dry_run": dry_run,
        "cutoff": cutoff,
        "statuses": list(statuses),
        "matched": len(ids),
        "deleted": 0 if dry_run else len(ids),
    }
