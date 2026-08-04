"""SQLite implementation of the first ControlPlaneStore contract slice."""

from __future__ import annotations

from contextlib import closing
from pathlib import Path
from typing import Any

from .. import cursors, db, events


class SQLiteControlPlaneStore:
    """Event-ledger and cursor adapter for the local SQLite control plane.

    Each operation owns a short-lived connection so callers never receive a
    provider connection.  Existing state modules continue to own their schema
    and transaction behavior; migrating their callers is deliberately outside
    this boundary-establishment slice.
    """

    backend = "sqlite"

    def __init__(self, path: Path | str, *, busy_timeout_ms: int = 5000) -> None:
        self.path = Path(path) if str(path) != db.MEMORY_DB_PATH else db.MEMORY_DB_PATH
        self.busy_timeout_ms = busy_timeout_ms

    def _connect(self):
        return db.connect(self.path, busy_timeout_ms=self.busy_timeout_ms)

    def append_event(self, event_type: str, **fields: Any) -> dict[str, Any]:
        with closing(self._connect()) as conn:
            return events.append(conn, event_type=event_type, **fields)

    def get_event(self, event_id: str) -> dict[str, Any] | None:
        with closing(self._connect()) as conn:
            return events.get(conn, event_id)

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
    ) -> list[dict[str, Any]]:
        with closing(self._connect()) as conn:
            return events.query(
                conn,
                event_type=event_type,
                since=since,
                until=until,
                correlation_id=correlation_id,
                domain=domain,
                limit=limit,
                offset=offset,
            )

    def set_cursor(
        self,
        name: str,
        *,
        cursor_type: str | None = None,
        last_value: str | None = None,
        last_idempotency_key: str | None = None,
        payload: dict[str, Any] | list[Any] | None = None,
        updated_at: str | None = None,
    ) -> dict[str, Any]:
        with closing(self._connect()) as conn:
            return cursors.set_cursor(
                conn,
                name,
                cursor_type=cursor_type,
                last_value=last_value,
                last_idempotency_key=last_idempotency_key,
                payload=payload,
                updated_at=updated_at,
            )

    def get_cursor(self, name: str) -> dict[str, Any] | None:
        with closing(self._connect()) as conn:
            return cursors.get_cursor(conn, name)
