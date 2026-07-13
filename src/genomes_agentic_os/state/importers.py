"""Idempotent importers from the real YAML file formats into the state-plane tables.

Two deliberately separate function families:

- ``scan_*`` — pure source reads. Parse YAML, count, return. Never import
  ``.db``/``.events``/``.queue``/``.cursors``, never accept or open a
  connection. This is what CLI ``--dry-run`` calls: a dry-run must be able
  to report counts against the live installed OS with zero risk of ever
  creating a database file as a side effect.
- ``import_*`` — take an already-open connection (opened by the caller,
  never by this module) and write. Re-running any of these must not
  duplicate rows:
    - events: reuses ``events.batch_append`` (INSERT OR IGNORE keyed by
      id) — matches the source ledger's own write-once contract.
    - run_queue: ``INSERT ... ON CONFLICT(id) DO UPDATE``, refreshing the
      YAML-mirrored columns but never touching ``priority``/``attempts``/
      ``lease_owner``/``lease_until`` — those only exist for the future
      SQLite-native claim path and re-importing from YAML must not clobber
      them.
    - cursors: reuses ``cursors.set_cursor`` (already an upsert).

Never mutates a source file. Never calls ``event_graph``'s writer
functions (``ensure_event_state``/``append_event``/``write_yaml``) — only
the pure ``load_yaml`` reader.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import sqlite3
from typing import Any

from ..event_graph import EVENT_CURSORS_FILE, EVENTS, RUN_QUEUE, load_yaml
from ..source_watch import WATCH_CURSORS_FILE
from . import cursors as cursors_module
from . import events as events_module
from .db import table_counts, transaction, utc_now_iso

__all__ = [
    "SourcePaths",
    "default_source_paths",
    "scan_run_queue",
    "scan_events",
    "scan_cursors",
    "scan_all",
    "import_run_queue",
    "import_events",
    "import_cursors",
    "import_all",
    "verify_import",
]

# RUN_QUEUE / EVENTS / EVENT_CURSORS_FILE are the same relative-path
# constants event_graph.py itself uses ("harness/shared_factory/00-control-
# plane/..."), reused here rather than re-derived, per AGE-39 scope.
EVENT_CHAIN_DEDUPE_CURSOR_NAME = "event_chain_dedupe"


@dataclass(frozen=True)
class SourcePaths:
    run_queue: Path
    events_dir: Path
    event_cursors: Path
    watch_cursors: Path


def default_source_paths(root: str | Path) -> SourcePaths:
    """Standard source file locations under an already-resolved OS root.

    ``root`` must already be resolved/expanded (callers use
    ``state.db.resolve_os_root`` upstream) — this function only joins
    relative paths, matching event_graph.py's own convention.
    """
    root_path = Path(root)
    return SourcePaths(
        run_queue=root_path / RUN_QUEUE,
        events_dir=root_path / EVENTS,
        event_cursors=root_path / EVENT_CURSORS_FILE,
        watch_cursors=root_path / WATCH_CURSORS_FILE,
    )


# --------------------------------------------------------------------------
# scan_* — pure source reads, no database involved at all.
# --------------------------------------------------------------------------


def scan_run_queue(path: Path) -> dict[str, Any]:
    data = load_yaml(path)
    items = [item for item in (data.get("items") or data.get("run_queue") or []) if isinstance(item, dict)]
    return {"path": str(path), "exists": path.is_file(), "item_count": len(items)}


def scan_events(events_dir: Path) -> dict[str, Any]:
    if not events_dir.is_dir():
        return {"path": str(events_dir), "exists": False, "event_count": 0}
    files = sorted(events_dir.glob("evt_*.yml"))
    return {"path": str(events_dir), "exists": True, "event_count": len(files)}


def scan_cursors(*, event_cursors_path: Path, watch_cursors_path: Path) -> dict[str, Any]:
    event_cursors_exists = event_cursors_path.is_file()
    event_cursor_data = load_yaml(event_cursors_path)
    processed_keys = event_cursor_data.get("processed_idempotency_keys") or []
    watch_cursor_data = load_yaml(watch_cursors_path)
    watch_rows = [
        row for row in (watch_cursor_data.get("watch_cursors") or []) if isinstance(row, dict) and row.get("watch_source_id")
    ]
    return {
        "event_cursors_path": str(event_cursors_path),
        "watch_cursors_path": str(watch_cursors_path),
        "event_cursors_exists": event_cursors_exists,
        "processed_idempotency_key_count": len(processed_keys),
        "watch_cursor_count": len(watch_rows),
        # event-cursors.yml folds into exactly one cursor row when present
        # (see module docstring / cursors.py docstring for why).
        "cursor_row_count": (1 if event_cursors_exists else 0) + len(watch_rows),
    }


def scan_all(root: str | Path, *, source: str = "all") -> dict[str, Any]:
    paths = default_source_paths(root)
    results: dict[str, Any] = {}
    if source in ("all", "run-queue"):
        results["run_queue"] = scan_run_queue(paths.run_queue)
    if source in ("all", "events"):
        results["events"] = scan_events(paths.events_dir)
    if source in ("all", "cursors"):
        results["cursors"] = scan_cursors(event_cursors_path=paths.event_cursors, watch_cursors_path=paths.watch_cursors)
    return results


# --------------------------------------------------------------------------
# import_* — write into an already-open connection provided by the caller.
# --------------------------------------------------------------------------

# Columns copied verbatim from the real YAML item into dedicated run_queue
# columns; everything else on the item lands in payload_json.
_RUN_QUEUE_CORE_FIELDS = frozenset(
    {
        "id",
        "kind",
        "ref",
        "status",
        "approval_state",
        "idempotency_key",
        "execution_target",
        "created_at",
        "updated_at",
        "due_at",
        "started_at",
        "finished_at",
        "blocked_reason",
        "error",
        "dry_run",
    }
)

_RUN_QUEUE_UPSERT_SQL = """
INSERT INTO run_queue (
    id, kind, ref, status, approval_state, priority, idempotency_key, execution_target,
    dry_run, created_at, updated_at, due_at, started_at, finished_at, attempts,
    lease_owner, lease_until, blocked_reason, error, payload_json
) VALUES (
    :id, :kind, :ref, :status, :approval_state, :priority, :idempotency_key, :execution_target,
    :dry_run, :created_at, :updated_at, :due_at, :started_at, :finished_at, :attempts,
    :lease_owner, :lease_until, :blocked_reason, :error, :payload_json
)
ON CONFLICT(id) DO UPDATE SET
    kind = excluded.kind,
    ref = excluded.ref,
    status = excluded.status,
    approval_state = excluded.approval_state,
    idempotency_key = excluded.idempotency_key,
    execution_target = excluded.execution_target,
    dry_run = excluded.dry_run,
    updated_at = excluded.updated_at,
    due_at = excluded.due_at,
    started_at = excluded.started_at,
    finished_at = excluded.finished_at,
    blocked_reason = excluded.blocked_reason,
    error = excluded.error,
    payload_json = excluded.payload_json
"""
# Deliberately NOT updated on conflict: priority, attempts, lease_owner,
# lease_until. Those back the future SQLite-native claim path and have no
# YAML equivalent; re-mirroring the file must not clobber them.


def _run_queue_row_from_item(item: dict[str, Any]) -> dict[str, Any]:
    payload = {key: value for key, value in item.items() if key not in _RUN_QUEUE_CORE_FIELDS}
    now_value = utc_now_iso()
    created_at = item.get("created_at") or now_value
    return {
        "id": item["id"],
        "kind": item.get("kind") or "unknown",
        "ref": item.get("ref"),
        "status": item.get("status") or "queued",
        "approval_state": item.get("approval_state") or "not_required",
        "priority": 0,
        "idempotency_key": item.get("idempotency_key"),
        "execution_target": item.get("execution_target"),
        "dry_run": int(bool(item.get("dry_run", False))),
        "created_at": created_at,
        "updated_at": item.get("updated_at") or created_at,
        "due_at": item.get("due_at"),
        "started_at": item.get("started_at"),
        "finished_at": item.get("finished_at"),
        "attempts": 0,
        "lease_owner": None,
        "lease_until": None,
        "blocked_reason": item.get("blocked_reason"),
        "error": item.get("error"),
        "payload_json": json.dumps(payload, sort_keys=True, default=str),
    }


def import_run_queue(conn: sqlite3.Connection, path: Path) -> dict[str, Any]:
    data = load_yaml(path)
    items = [item for item in (data.get("items") or data.get("run_queue") or []) if isinstance(item, dict)]
    rows = [_run_queue_row_from_item(item) for item in items if item.get("id")]
    skipped_missing_id = len(items) - len(rows)
    with transaction(conn):
        before = conn.execute("SELECT COUNT(*) FROM run_queue").fetchone()[0]
        conn.executemany(_RUN_QUEUE_UPSERT_SQL, rows)
        after = conn.execute("SELECT COUNT(*) FROM run_queue").fetchone()[0]
    inserted = after - before
    return {
        "path": str(path),
        "source_item_count": len(items),
        "processed": len(rows),
        "skipped_missing_id": skipped_missing_id,
        "inserted": inserted,
        "updated": len(rows) - inserted,
    }


def _event_kwargs_from_yaml(event: dict[str, Any], *, domain: str | None) -> dict[str, Any]:
    source = event.get("source") or {}
    correlation = event.get("correlation") or {}
    privacy = event.get("privacy") or {}
    links = event.get("links") or {}
    payload_ref = event.get("payload_ref")
    observed_at = event.get("observed_at") or event.get("occurred_at")
    return {
        "event_type": event.get("type") or "unknown",
        "id": event["id"],
        "schema_version_value": int(event.get("schema_version") or 1),
        "occurred_at": event.get("occurred_at") or observed_at,
        "observed_at": observed_at,
        "source_ref": source.get("ref"),
        "correlation_id": correlation.get("correlation_id"),
        "idempotency_key": event.get("idempotency_key"),
        "summary": event.get("summary"),
        "payload": payload_ref if payload_ref is not None else {},
        "contains_secret": bool(privacy.get("contains_secret", False)),
        "contains_customer_data": bool(privacy.get("contains_customer_data", False)),
        "run_log_link": links.get("run_log"),
        "source_url": links.get("source_url"),
        "domain": domain,
    }


def import_events(conn: sqlite3.Connection, events_dir: Path, *, domain: str | None = "shared_factory") -> dict[str, Any]:
    if not events_dir.is_dir():
        return {"path": str(events_dir), "source_item_count": 0, "processed": 0, "inserted": 0, "skipped": 0}
    files = sorted(events_dir.glob("evt_*.yml"))
    mapped = []
    skipped_missing_id = 0
    for file_path in files:
        event = load_yaml(file_path)
        if not event.get("id"):
            skipped_missing_id += 1
            continue
        mapped.append(_event_kwargs_from_yaml(event, domain=domain))
    result = events_module.batch_append(conn, mapped)
    return {
        "path": str(events_dir),
        "source_item_count": len(files),
        "processed": result["submitted"],
        "skipped_missing_id": skipped_missing_id,
        "inserted": result["inserted"],
        "skipped": result["skipped"],
    }


def import_cursors(conn: sqlite3.Connection, *, event_cursors_path: Path, watch_cursors_path: Path) -> dict[str, Any]:
    written = 0
    with transaction(conn):
        if event_cursors_path.is_file():
            data = load_yaml(event_cursors_path)
            keys = data.get("processed_idempotency_keys") or []
            cursors_module.set_cursor(
                conn,
                EVENT_CHAIN_DEDUPE_CURSOR_NAME,
                cursor_type="idempotency_key_set",
                payload={"processed_idempotency_keys": keys},
            )
            written += 1
        watch_data = load_yaml(watch_cursors_path)
        for row in watch_data.get("watch_cursors") or []:
            if not isinstance(row, dict) or not row.get("watch_source_id"):
                continue
            extra = {"id": row["id"]} if row.get("id") and row.get("id") != row.get("watch_source_id") else {}
            cursors_module.set_cursor(
                conn,
                row["watch_source_id"],
                cursor_type=row.get("cursor_type"),
                last_value=row.get("last_value"),
                last_idempotency_key=row.get("last_idempotency_key"),
                payload=extra,
                updated_at=row.get("updated_at"),
            )
            written += 1
    return {
        "event_cursors_path": str(event_cursors_path),
        "watch_cursors_path": str(watch_cursors_path),
        "written": written,
    }


def import_all(conn: sqlite3.Connection, root: str | Path, *, source: str = "all") -> dict[str, Any]:
    paths = default_source_paths(root)
    results: dict[str, Any] = {}
    if source in ("all", "run-queue"):
        results["run_queue"] = import_run_queue(conn, paths.run_queue)
    if source in ("all", "events"):
        results["events"] = import_events(conn, paths.events_dir)
    if source in ("all", "cursors"):
        results["cursors"] = import_cursors(
            conn, event_cursors_path=paths.event_cursors, watch_cursors_path=paths.watch_cursors
        )
    return results


def verify_import(conn: sqlite3.Connection, root: str | Path) -> dict[str, Any]:
    """Compare file-side counts against table counts and report drift.
    ``drift`` is ``table_count - file_count`` per source; zero means parity."""
    file_side = scan_all(root)
    db_counts = table_counts(conn)
    expected_cursor_rows = file_side["cursors"]["cursor_row_count"]
    file_counts = {
        "run_queue": file_side["run_queue"]["item_count"],
        "events": file_side["events"]["event_count"],
        "cursors": expected_cursor_rows,
    }
    drift = {table: db_counts[table] - file_counts[table] for table in file_counts}
    return {
        "file_counts": file_counts,
        "table_counts": db_counts,
        "drift": drift,
        "ok": all(value == 0 for value in drift.values()),
    }
