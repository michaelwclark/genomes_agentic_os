from __future__ import annotations

import sqlite3

import pytest

from genomes_agentic_os.state import db, events


@pytest.fixture()
def conn() -> sqlite3.Connection:
    connection = db.connect(":memory:")
    try:
        yield connection
    finally:
        connection.close()


def test_append_generates_id_when_omitted(conn: sqlite3.Connection) -> None:
    event = events.append(conn, event_type="os.example.observed", source_ref="ref/a")
    assert event["id"].startswith("evt_")
    assert event["type"] == "os.example.observed"
    assert event["contains_secret"] is False
    assert event["payload"] == {}


def test_append_is_idempotent_on_explicit_id(conn: sqlite3.Connection) -> None:
    first = events.append(conn, event_type="os.example.observed", id="evt_fixed0001", summary="first")
    second = events.append(conn, event_type="os.example.observed", id="evt_fixed0001", summary="second")
    assert first["summary"] == "first"
    assert second["summary"] == "first"  # append never updates an existing row
    assert events.count(conn) == 1


def test_batch_append_dedupes_within_batch_and_against_existing(conn: sqlite3.Connection) -> None:
    events.append(conn, event_type="os.example.observed", id="evt_pre00000001")
    result = events.batch_append(
        conn,
        [
            {"event_type": "os.example.observed", "id": "evt_pre00000001"},  # already exists
            {"event_type": "os.example.observed", "id": "evt_new00000001"},
            {"event_type": "os.example.observed", "id": "evt_new00000001"},  # dup within batch
            {"event_type": "os.example.observed", "id": "evt_new00000002"},
        ],
    )
    assert result == {"submitted": 4, "inserted": 2, "skipped": 2}
    assert events.count(conn) == 3


def test_query_filters_by_type_and_time_range(conn: sqlite3.Connection) -> None:
    events.append(conn, event_type="os.alpha", id="evt_a", occurred_at="2026-01-01T00:00:00Z")
    events.append(conn, event_type="os.beta", id="evt_b", occurred_at="2026-01-02T00:00:00Z")
    events.append(conn, event_type="os.alpha", id="evt_c", occurred_at="2026-01-03T00:00:00Z")

    by_type = events.query(conn, event_type="os.alpha")
    assert sorted(item["id"] for item in by_type) == ["evt_a", "evt_c"]

    by_range = events.query(conn, since="2026-01-02T00:00:00Z", until="2026-01-02T23:59:59Z")
    assert [item["id"] for item in by_range] == ["evt_b"]


def test_query_filters_by_correlation_id(conn: sqlite3.Connection) -> None:
    events.append(conn, event_type="os.alpha", id="evt_a", correlation_id="corr-1")
    events.append(conn, event_type="os.alpha", id="evt_b", correlation_id="corr-2")
    result = events.query(conn, correlation_id="corr-1")
    assert [item["id"] for item in result] == ["evt_a"]


def test_count_matches_query_filters(conn: sqlite3.Connection) -> None:
    events.append(conn, event_type="os.alpha", id="evt_a")
    events.append(conn, event_type="os.beta", id="evt_b")
    assert events.count(conn) == 2
    assert events.count(conn, event_type="os.alpha") == 1


def test_events_module_exposes_no_update_or_delete_api() -> None:
    public_names = {name for name in dir(events) if not name.startswith("_")}
    assert not any(name in public_names for name in ("update", "delete", "remove"))


def test_prune_events_dry_run_does_not_delete(conn: sqlite3.Connection) -> None:
    events.append(conn, event_type="os.old", id="evt_old0001", occurred_at="2020-01-01T00:00:00Z")
    events.append(conn, event_type="os.new", id="evt_new0001", occurred_at="2026-01-01T00:00:00Z")

    result = events.prune_events(conn, older_than_days=1, dry_run=True, now="2026-01-02T00:00:00Z")
    assert result["dry_run"] is True
    assert result["matched"] == 1
    assert result["deleted"] == 0
    assert events.count(conn) == 2  # nothing actually removed


def test_prune_events_apply_deletes_only_matched(conn: sqlite3.Connection) -> None:
    events.append(conn, event_type="os.old", id="evt_old0001", occurred_at="2020-01-01T00:00:00Z")
    events.append(conn, event_type="os.new", id="evt_new0001", occurred_at="2026-01-01T00:00:00Z")

    result = events.prune_events(conn, older_than_days=1, dry_run=False, now="2026-01-02T00:00:00Z")
    assert result["deleted"] == 1
    assert events.count(conn) == 1
    assert events.get(conn, "evt_new0001") is not None
    assert events.get(conn, "evt_old0001") is None
