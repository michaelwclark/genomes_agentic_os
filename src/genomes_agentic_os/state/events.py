"""Append-only event ledger table (SQLite).

Mirrors the envelope already produced by ``event_graph.append_event`` (one
YAML file per event) so the importer can map real ``evt_*.yml`` files onto
this table losslessly. Deliberately append-only: there is no update or
delete API here, matching the file-per-event ledger's own append-only
contract. ``prune_events`` is the one explicit, separately-named retention
call — never a generic delete.

Natural idempotency key is the event ``id`` (the same value used for the
``evt_<hash>.yml`` filename): re-appending an event with an ``id`` already
present is a no-op (``INSERT OR IGNORE``). The event envelope also carries
its own ``idempotency_key`` field (``event_type:sha256(source_ref)[:16]``,
per ``event_graph.append_event``), but that value is deliberately NOT
unique-constrained here — two distinct events of the same type from the
same source_ref (different ``observed_at``) legitimately share it.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any, Iterable, Sequence
import uuid

from .db import days_ago_iso, row_to_dict, transaction, utc_now_iso

_INSERT_SQL = """
INSERT OR IGNORE INTO events (
    id, type, schema_version, occurred_at, observed_at, source_ref, correlation_id,
    idempotency_key, summary, payload_json, contains_secret, contains_customer_data,
    run_log_link, source_url, domain, created_at
) VALUES (
    :id, :type, :schema_version, :occurred_at, :observed_at, :source_ref, :correlation_id,
    :idempotency_key, :summary, :payload_json, :contains_secret, :contains_customer_data,
    :run_log_link, :source_url, :domain, :created_at
)
"""


def _build_row(
    *,
    event_type: str,
    id: str | None = None,  # noqa: A002 - matches the domain's "id" vocabulary
    schema_version_value: int = 1,
    occurred_at: str | None = None,
    observed_at: str | None = None,
    source_ref: str | None = None,
    correlation_id: str | None = None,
    idempotency_key: str | None = None,
    summary: str | None = None,
    payload: dict[str, Any] | list[Any] | None = None,
    contains_secret: bool = False,
    contains_customer_data: bool = False,
    run_log_link: str | None = None,
    source_url: str | None = None,
    domain: str | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    now_value = utc_now_iso()
    observed = observed_at or now_value
    return {
        "id": id or f"evt_{uuid.uuid4().hex[:12]}",
        "type": event_type,
        "schema_version": schema_version_value,
        "occurred_at": occurred_at or observed,
        "observed_at": observed,
        "source_ref": source_ref,
        "correlation_id": correlation_id,
        "idempotency_key": idempotency_key,
        "summary": summary,
        "payload_json": json.dumps(payload if payload is not None else {}, sort_keys=True),
        "contains_secret": int(bool(contains_secret)),
        "contains_customer_data": int(bool(contains_customer_data)),
        "run_log_link": run_log_link,
        "source_url": source_url,
        "domain": domain,
        "created_at": created_at or now_value,
    }


def _decode(row: sqlite3.Row | None) -> dict[str, Any] | None:
    data = row_to_dict(row)
    if data is None:
        return None
    data["payload"] = json.loads(data.pop("payload_json") or "{}")
    data["contains_secret"] = bool(data["contains_secret"])
    data["contains_customer_data"] = bool(data["contains_customer_data"])
    return data


def append(conn: sqlite3.Connection, *, event_type: str, **kwargs: Any) -> dict[str, Any]:
    """Append a single event. Returns the stored row (existing row if the
    ``id`` was already present — append is idempotent, not an upsert)."""
    row = _build_row(event_type=event_type, **kwargs)
    conn.execute(_INSERT_SQL, row)
    return _decode(conn.execute("SELECT * FROM events WHERE id = ?", (row["id"],)).fetchone())  # type: ignore[return-value]


def batch_append(conn: sqlite3.Connection, events: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Append many events in one transaction. Each item is a kwargs dict for
    ``_build_row`` (must include ``event_type``). Idempotent: re-appending
    the same ``id`` twice does not duplicate or error."""
    rows = [_build_row(**event) for event in events]
    with transaction(conn):
        before = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        conn.executemany(_INSERT_SQL, rows)
        after = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    inserted = after - before
    return {"submitted": len(rows), "inserted": inserted, "skipped": len(rows) - inserted}


def get(conn: sqlite3.Connection, event_id: str) -> dict[str, Any] | None:
    return _decode(conn.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone())


def _filters(
    *,
    event_type: str | None,
    since: str | None,
    until: str | None,
    correlation_id: str | None,
    domain: str | None,
) -> tuple[str, list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if event_type is not None:
        clauses.append("type = ?")
        params.append(event_type)
    if since is not None:
        clauses.append("occurred_at >= ?")
        params.append(since)
    if until is not None:
        clauses.append("occurred_at <= ?")
        params.append(until)
    if correlation_id is not None:
        clauses.append("correlation_id = ?")
        params.append(correlation_id)
    if domain is not None:
        clauses.append("domain = ?")
        params.append(domain)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    return where, params


def query(
    conn: sqlite3.Connection,
    *,
    event_type: str | None = None,
    since: str | None = None,
    until: str | None = None,
    correlation_id: str | None = None,
    domain: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict[str, Any]]:
    where, params = _filters(
        event_type=event_type, since=since, until=until, correlation_id=correlation_id, domain=domain
    )
    rows = conn.execute(
        f"SELECT * FROM events {where} ORDER BY occurred_at ASC, id ASC LIMIT ? OFFSET ?",
        (*params, limit, offset),
    ).fetchall()
    return [_decode(row) for row in rows]  # type: ignore[misc]


def count(
    conn: sqlite3.Connection,
    *,
    event_type: str | None = None,
    since: str | None = None,
    until: str | None = None,
    correlation_id: str | None = None,
    domain: str | None = None,
) -> int:
    where, params = _filters(
        event_type=event_type, since=since, until=until, correlation_id=correlation_id, domain=domain
    )
    row = conn.execute(f"SELECT COUNT(*) FROM events {where}", params).fetchone()
    return int(row[0])


def prune_events(
    conn: sqlite3.Connection,
    *,
    older_than_days: int,
    dry_run: bool = True,
    now: str | None = None,
) -> dict[str, Any]:
    """The one explicit retention call for the append-only ledger. Never a
    generic delete: callers must name a retention window."""
    cutoff = days_ago_iso(older_than_days, now=now)
    rows = conn.execute("SELECT id FROM events WHERE occurred_at < ?", (cutoff,)).fetchall()
    ids: Sequence[str] = [row["id"] for row in rows]
    if not dry_run and ids:
        with transaction(conn):
            conn.executemany("DELETE FROM events WHERE id = ?", [(item_id,) for item_id in ids])
    return {"dry_run": dry_run, "cutoff": cutoff, "matched": len(ids), "deleted": 0 if dry_run else len(ids)}
