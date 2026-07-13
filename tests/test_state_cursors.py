from __future__ import annotations

import sqlite3

import pytest

from genomes_agentic_os.state import cursors, db


@pytest.fixture()
def conn() -> sqlite3.Connection:
    connection = db.connect(":memory:")
    try:
        yield connection
    finally:
        connection.close()


def test_set_cursor_creates_row(conn: sqlite3.Connection) -> None:
    row = cursors.set_cursor(conn, "source_alpha", cursor_type="event_id", last_value="evt_0001")
    assert row["name"] == "source_alpha"
    assert row["last_value"] == "evt_0001"
    assert row["payload"] == {}


def test_set_cursor_upserts_not_duplicates(conn: sqlite3.Connection) -> None:
    cursors.set_cursor(conn, "source_alpha", last_value="evt_0001")
    updated = cursors.set_cursor(conn, "source_alpha", last_value="evt_0002")
    assert updated["last_value"] == "evt_0002"
    assert cursors.count(conn) == 1


def test_set_cursor_stores_arbitrary_payload(conn: sqlite3.Connection) -> None:
    row = cursors.set_cursor(conn, "event_chain_dedupe", payload={"processed_idempotency_keys": ["a", "b"]})
    assert row["payload"] == {"processed_idempotency_keys": ["a", "b"]}


def test_get_cursor_returns_none_for_missing(conn: sqlite3.Connection) -> None:
    assert cursors.get_cursor(conn, "does-not-exist") is None


def test_list_cursors_orders_by_name(conn: sqlite3.Connection) -> None:
    cursors.set_cursor(conn, "source_beta", last_value="1")
    cursors.set_cursor(conn, "source_alpha", last_value="2")
    rows = cursors.list_cursors(conn)
    assert [row["name"] for row in rows] == ["source_alpha", "source_beta"]


def test_delete_cursor_removes_row_and_reports_result(conn: sqlite3.Connection) -> None:
    cursors.set_cursor(conn, "source_alpha", last_value="1")
    assert cursors.delete_cursor(conn, "source_alpha") is True
    assert cursors.get_cursor(conn, "source_alpha") is None
    assert cursors.delete_cursor(conn, "source_alpha") is False
