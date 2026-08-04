"""Durable control-plane facts and projections for integration adapters.

Adapters record approvals and artifact *references* here; they do not store
chat approvals or artifact bodies.  Operator views are pure derived read
models, so they never become a competing source of truth.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sqlite3
from typing import Any, Protocol
from urllib.parse import urlparse
from uuid import uuid4

from .db import parse_iso, row_to_dict, transaction, utc_now_iso


APPROVAL_STATUSES = frozenset({"waiting", "approved", "denied", "expired"})
DECISIONS = frozenset({"approved", "denied"})
CLASSIFICATIONS = frozenset({"public", "internal", "confidential", "restricted"})
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_LINEAR_ISSUE = re.compile(r"^[A-Za-z][A-Za-z0-9]+-\d+$")


class ControlPlaneError(ValueError):
    """Raised when an adapter attempts to record ambiguous or unsafe facts."""


def _text(value: Any, label: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ControlPlaneError(f"{label} is required")
    return normalized


def _time(value: str, label: str) -> datetime:
    try:
        parsed = parse_iso(value)
    except (AttributeError, ValueError) as exc:
        raise ControlPlaneError(f"{label} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ControlPlaneError(f"{label} must include a timezone")
    return parsed.astimezone(timezone.utc)


def _approval_row(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return row_to_dict(row)


def request_approval(
    conn: sqlite3.Connection,
    *,
    subject_type: str,
    subject_id: str,
    requested_by: str,
    approver: str,
    expires_at: str,
    request_id: str | None = None,
    metadata: Mapping[str, Any] | None = None,
    requested_at: str | None = None,
) -> dict[str, Any]:
    """Create a durable wait-state record; no implicit approval is possible."""
    requested = requested_at or utc_now_iso()
    if _time(expires_at, "expires_at") <= _time(requested, "requested_at"):
        raise ControlPlaneError("expires_at must be after requested_at")
    row = {
        "id": request_id or f"approval_{uuid4().hex}",
        "subject_type": _text(subject_type, "subject_type"),
        "subject_id": _text(subject_id, "subject_id"),
        "requested_by": _text(requested_by, "requested_by"),
        "approver": _text(approver, "approver"),
        "status": "waiting",
        "decision_note": None,
        "requested_at": requested,
        "expires_at": expires_at,
        "decided_at": None,
        "metadata_json": json.dumps(dict(metadata or {}), sort_keys=True),
    }
    try:
        conn.execute(
            """
            INSERT INTO approval_requests (
                id, subject_type, subject_id, requested_by, approver, status,
                decision_note, requested_at, expires_at, decided_at, metadata_json
            ) VALUES (
                :id, :subject_type, :subject_id, :requested_by, :approver, :status,
                :decision_note, :requested_at, :expires_at, :decided_at, :metadata_json
            )
            """,
            row,
        )
    except sqlite3.IntegrityError as exc:
        raise ControlPlaneError(f"approval request already exists: {row['id']}") from exc
    return get_approval(conn, row["id"]) or {}


def get_approval(conn: sqlite3.Connection, request_id: str) -> dict[str, Any] | None:
    return _approval_row(conn.execute("SELECT * FROM approval_requests WHERE id = ?", (request_id,)).fetchone())


def decide_approval(
    conn: sqlite3.Connection,
    request_id: str,
    *,
    approver: str,
    decision: str,
    note: str | None = None,
    decided_at: str | None = None,
) -> dict[str, Any]:
    """Record a decision only by the named approver and before expiry."""
    if decision not in DECISIONS:
        raise ControlPlaneError(f"unsupported approval decision: {decision}")
    record = get_approval(conn, request_id)
    if record is None:
        raise ControlPlaneError("approval request is not present")
    if record["status"] != "waiting":
        raise ControlPlaneError(f"approval request is already {record['status']}")
    if _text(approver, "approver") != record["approver"]:
        raise ControlPlaneError("only the named approver can decide this request")
    now = decided_at or utc_now_iso()
    if _time(now, "decided_at") >= _time(record["expires_at"], "expires_at"):
        expire_approvals(conn, now=now)
        raise ControlPlaneError("approval request has expired")
    conn.execute(
        "UPDATE approval_requests SET status = ?, decision_note = ?, decided_at = ? WHERE id = ?",
        (decision, str(note or "").strip() or None, now, request_id),
    )
    return get_approval(conn, request_id) or {}


def expire_approvals(conn: sqlite3.Connection, *, now: str | None = None) -> int:
    """Expire only still-waiting records; decisions are immutable facts."""
    timestamp = now or utc_now_iso()
    with transaction(conn):
        cursor = conn.execute(
            "UPDATE approval_requests SET status = 'expired' WHERE status = 'waiting' AND expires_at <= ?",
            (timestamp,),
        )
    return int(cursor.rowcount)


def record_artifact_reference(
    conn: sqlite3.Connection,
    *,
    uri: str,
    content_sha256: str,
    classification: str,
    retention_days: int,
    source_ref: str | None = None,
    reference_id: str | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    """Record metadata only. There is intentionally no artifact-body argument."""
    parsed = urlparse(_text(uri, "uri"))
    if not parsed.scheme:
        raise ControlPlaneError("uri must include a scheme")
    digest = _text(content_sha256, "content_sha256").lower()
    if not _SHA256.fullmatch(digest):
        raise ControlPlaneError("content_sha256 must be a lowercase SHA-256 hex digest")
    normalized_classification = _text(classification, "classification").lower()
    if normalized_classification not in CLASSIFICATIONS:
        raise ControlPlaneError(f"unsupported artifact classification: {classification}")
    if retention_days <= 0:
        raise ControlPlaneError("retention_days must be positive")
    row = {
        "id": reference_id or f"artifact_{uuid4().hex}",
        "uri": uri,
        "content_sha256": digest,
        "classification": normalized_classification,
        "retention_days": int(retention_days),
        "source_ref": str(source_ref or "").strip() or None,
        "created_at": created_at or utc_now_iso(),
    }
    try:
        conn.execute(
            """
            INSERT INTO artifact_references (
                id, uri, content_sha256, classification, retention_days, source_ref, created_at
            ) VALUES (
                :id, :uri, :content_sha256, :classification, :retention_days, :source_ref, :created_at
            )
            """,
            row,
        )
    except sqlite3.IntegrityError as exc:
        raise ControlPlaneError("artifact reference already exists for uri and content hash") from exc
    return get_artifact_reference(conn, row["id"]) or {}


def get_artifact_reference(conn: sqlite3.Connection, reference_id: str) -> dict[str, Any] | None:
    return row_to_dict(conn.execute("SELECT * FROM artifact_references WHERE id = ?", (reference_id,)).fetchone())


def validate_change_linkage(work_item: Mapping[str, Any]) -> dict[str, str]:
    """Shared pre-commit/CI adapter contract for every source-code change."""
    work_item_id = _text(work_item.get("id"), "work item id")
    worktree_path = _text(work_item.get("worktree_path"), "worktree_path")
    branch = _text(work_item.get("branch"), "branch")
    if work_item.get("source_system") != "linear":
        raise ControlPlaneError("code changes require a Linear-backed work item")
    linear_issue = _text(work_item.get("source_key"), "Linear issue")
    if not _LINEAR_ISSUE.fullmatch(linear_issue):
        raise ControlPlaneError("Linear issue must use the TEAM-123 identifier form")
    return {
        "work_item_id": work_item_id,
        "worktree_path": worktree_path,
        "branch": branch,
        "linear_issue": linear_issue,
    }


def control_plane_projection(conn: sqlite3.Connection, *, now: str | None = None) -> dict[str, Any]:
    """Return a UI-ready view derived from durable rows without writing them."""
    timestamp = now or utc_now_iso()
    rows = [dict(row) for row in conn.execute("SELECT * FROM approval_requests ORDER BY expires_at, requested_at, id")]
    approvals: list[dict[str, Any]] = []
    for row in rows:
        effective_status = "expired" if row["status"] == "waiting" and _time(row["expires_at"], "expires_at") <= _time(timestamp, "now") else row["status"]
        approvals.append(
            {
                "id": row["id"],
                "subject_type": row["subject_type"],
                "subject_id": row["subject_id"],
                "approver": row["approver"],
                "status": effective_status,
                "expires_at": row["expires_at"],
            }
        )
    artifact_rows = [dict(row) for row in conn.execute("SELECT classification, COUNT(*) AS count FROM artifact_references GROUP BY classification ORDER BY classification")]
    return {
        "api_version": "control-plane-projection/v1",
        "derived_at": timestamp,
        "source": "state.db",
        "approvals": approvals,
        "artifact_reference_counts": {row["classification"]: row["count"] for row in artifact_rows},
    }
class ControlPlaneConfigurationError(ValueError):
    """Raised when a control-plane backend configuration is invalid."""


class UnsupportedControlPlaneBackend(ControlPlaneConfigurationError):
    """Raised for a declared backend which has no verified adapter yet."""


class ControlPlaneStore(Protocol):
    """Application-facing event and cursor operations for this first slice.

    Later slices extend this port with queue, lease, fencing, idempotency, and
    outbox contracts only after both backends have a conformance suite.  The
    port intentionally exposes domain operations, never a database connection.
    """

    backend: str

    def append_event(self, event_type: str, **fields: Any) -> dict[str, Any]: ...

    def get_event(self, event_id: str) -> dict[str, Any] | None: ...

    def query_events(
        self,
        *,
        event_type: str | None = None,
        since: str | None = None,
        until: str | None = None,
        correlation_id: str | None = None,
        domain: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]: ...

    def set_cursor(
        self,
        name: str,
        *,
        cursor_type: str | None = None,
        last_value: str | None = None,
        last_idempotency_key: str | None = None,
        payload: dict[str, Any] | list[Any] | None = None,
        updated_at: str | None = None,
    ) -> dict[str, Any]: ...

    def get_cursor(self, name: str) -> dict[str, Any] | None: ...


@dataclass(frozen=True)
class ControlPlaneStoreConfig:
    """Explicit composition input for one control-plane store instance."""

    backend: str
    sqlite_path: Path | str | None = None
    sqlite_busy_timeout_ms: int = 5000

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "ControlPlaneStoreConfig":
        """Parse the portable ``control_plane`` config shape without I/O."""
        backend = value.get("backend", "sqlite")
        sqlite = value.get("sqlite", {})
        if not isinstance(backend, str):
            raise ControlPlaneConfigurationError("control_plane.backend must be a string")
        if not isinstance(sqlite, Mapping):
            raise ControlPlaneConfigurationError("control_plane.sqlite must be a mapping")
        timeout = sqlite.get("busy_timeout_ms", 5000)
        if not isinstance(timeout, int) or timeout < 1:
            raise ControlPlaneConfigurationError("control_plane.sqlite.busy_timeout_ms must be a positive integer")
        return cls(
            backend=backend,
            sqlite_path=sqlite.get("path"),
            sqlite_busy_timeout_ms=timeout,
        )


def build_control_plane_store(config: ControlPlaneStoreConfig) -> ControlPlaneStore:
    """Build the selected backend at the composition edge.

    PostgreSQL is intentionally rejected rather than represented by a fake.
    It needs a real driver, dialect-specific migrations, and the same
    concurrency conformance suite before it can be advertised as available.
    """
    backend = config.backend.strip().lower()
    if backend == "sqlite":
        if config.sqlite_path is None:
            raise ControlPlaneConfigurationError("control_plane.sqlite.path is required for the sqlite backend")
        from .adapters.sqlite import SQLiteControlPlaneStore

        return SQLiteControlPlaneStore(config.sqlite_path, busy_timeout_ms=config.sqlite_busy_timeout_ms)
    if backend == "postgres":
        raise UnsupportedControlPlaneBackend(
            "postgres backend is not implemented: it requires a driver, migrations, and passed lease/idempotency conformance tests"
        )
    raise UnsupportedControlPlaneBackend(f"unsupported control_plane.backend: {config.backend}")
