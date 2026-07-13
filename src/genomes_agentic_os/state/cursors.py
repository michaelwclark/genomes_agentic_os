"""Named cursor KV store: one row per watcher/dedupe cursor.

Covers both real cursor file formats in one generic table:

- ``watch-cursors.yml`` (``watch_cursors: [{id, watch_source_id, cursor_type,
  last_value, last_idempotency_key, updated_at}, ...]``) maps directly: one
  row per watch source, ``name`` = ``watch_source_id``.
- ``event-cursors.yml`` (``processed_idempotency_keys: [...]``) has no
  natural per-row name — it is a single growing dedupe set, not a list of
  named cursors. The importer stores it as one fixed-name row
  (``name="event_chain_dedupe"``) with the whole key list in
  ``payload_json``. This is a deliberate, documented mapping choice (see
  ``docs/design-notes/state-plane.md``), not an obvious 1:1 translation.

Unlike ``events.py``, this is a genuine KV store: ``set_cursor`` is an
upsert (a cursor's entire purpose is being overwritten as it advances).
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from .db import row_to_dict, utc_now_iso

_UPSERT_SQL = """
INSERT INTO cursors (name, cursor_type, last_value, last_idempotency_key, payload_json, updated_at)
VALUES (:name, :cursor_type, :last_value, :last_idempotency_key, :payload_json, :updated_at)
ON CONFLICT(name) DO UPDATE SET
    cursor_type = excluded.cursor_type,
    last_value = excluded.last_value,
    last_idempotency_key = excluded.last_idempotency_key,
    payload_json = excluded.payload_json,
    updated_at = excluded.updated_at
"""


def _decode(row: sqlite3.Row | None) -> dict[str, Any] | None:
    data = row_to_dict(row)
    if data is None:
        return None
    data["payload"] = json.loads(data.pop("payload_json") or "{}")
    return data


def set_cursor(
    conn: sqlite3.Connection,
    name: str,
    *,
    cursor_type: str | None = None,
    last_value: str | None = None,
    last_idempotency_key: str | None = None,
    payload: dict[str, Any] | list[Any] | None = None,
    updated_at: str | None = None,
) -> dict[str, Any]:
    row = {
        "name": name,
        "cursor_type": cursor_type,
        "last_value": last_value,
        "last_idempotency_key": last_idempotency_key,
        "payload_json": json.dumps(payload if payload is not None else {}, sort_keys=True),
        "updated_at": updated_at or utc_now_iso(),
    }
    conn.execute(_UPSERT_SQL, row)
    return _decode(conn.execute("SELECT * FROM cursors WHERE name = ?", (name,)).fetchone())  # type: ignore[return-value]


def get_cursor(conn: sqlite3.Connection, name: str) -> dict[str, Any] | None:
    return _decode(conn.execute("SELECT * FROM cursors WHERE name = ?", (name,)).fetchone())


def list_cursors(conn: sqlite3.Connection, *, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM cursors ORDER BY name ASC LIMIT ? OFFSET ?", (limit, offset)
    ).fetchall()
    return [_decode(row) for row in rows]  # type: ignore[misc]


def delete_cursor(conn: sqlite3.Connection, name: str) -> bool:
    cursor = conn.execute("DELETE FROM cursors WHERE name = ?", (name,))
    return cursor.rowcount > 0


def count(conn: sqlite3.Connection) -> int:
    return int(conn.execute("SELECT COUNT(*) FROM cursors").fetchone()[0])
