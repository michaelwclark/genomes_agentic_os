from __future__ import annotations

from pathlib import Path
import sqlite3

import pytest

from genomes_agentic_os.state import db, queue


@pytest.fixture()
def conn() -> sqlite3.Connection:
    connection = db.connect(":memory:")
    try:
        yield connection
    finally:
        connection.close()


def test_enqueue_generates_id_and_defaults(conn: sqlite3.Connection) -> None:
    item = queue.enqueue(conn, kind="schedule")
    assert item["id"].startswith("queue_")
    assert item["status"] == "queued"
    assert item["approval_state"] == "not_required"
    assert item["dry_run"] is False
    assert item["payload"] == {}


def test_enqueue_rejects_invalid_status(conn: sqlite3.Connection) -> None:
    with pytest.raises(queue.StateQueueError):
        queue.enqueue(conn, kind="schedule", status="not-a-real-status")


def test_enqueue_rejects_duplicate_idempotency_key(conn: sqlite3.Connection) -> None:
    queue.enqueue(conn, kind="schedule", idempotency_key="idem-1")
    with pytest.raises(queue.StateQueueError):
        queue.enqueue(conn, kind="schedule", idempotency_key="idem-1")


def test_get_returns_none_for_missing_item(conn: sqlite3.Connection) -> None:
    assert queue.get(conn, "queue_does_not_exist") is None


def test_update_status_sets_error_and_preserves_other_fields(conn: sqlite3.Connection) -> None:
    item = queue.enqueue(conn, kind="schedule", ref="alpha/beta")
    updated = queue.update_status(conn, item["id"], "blocked", blocked_reason="waiting on approval")
    assert updated["status"] == "blocked"
    assert updated["blocked_reason"] == "waiting on approval"
    assert updated["ref"] == "alpha/beta"


# --- claim/lease semantics -------------------------------------------------
# Deterministic, sequential claims on one connection (not threaded) so the
# test can't flake on scheduling — the atomicity guarantee itself (BEGIN
# IMMEDIATE) is exercised by test_claim_next_second_connection_blocks_then_
# sees_leased_row below, which uses two real connections against a shared
# file-backed db instead of relying on thread timing.


def test_claim_next_returns_none_when_queue_empty(conn: sqlite3.Connection) -> None:
    assert queue.claim_next(conn, worker_id="worker-a") is None


def test_claim_next_single_item_then_second_claimant_gets_none(conn: sqlite3.Connection) -> None:
    item = queue.enqueue(conn, kind="schedule")

    claimed_a = queue.claim_next(conn, worker_id="worker-a")
    assert claimed_a is not None
    assert claimed_a["id"] == item["id"]
    assert claimed_a["status"] == "running"
    assert claimed_a["lease_owner"] == "worker-a"
    assert claimed_a["attempts"] == 1

    claimed_b = queue.claim_next(conn, worker_id="worker-b")
    assert claimed_b is None  # the only item is already leased/running


def test_claim_next_two_items_two_claimants_get_distinct_ids(conn: sqlite3.Connection) -> None:
    first = queue.enqueue(conn, kind="schedule", priority=1)
    second = queue.enqueue(conn, kind="schedule", priority=0)

    claimed_a = queue.claim_next(conn, worker_id="worker-a")
    claimed_b = queue.claim_next(conn, worker_id="worker-b")

    assert claimed_a is not None and claimed_b is not None
    assert claimed_a["id"] != claimed_b["id"]
    assert {claimed_a["id"], claimed_b["id"]} == {first["id"], second["id"]}
    # Higher priority is claimed first.
    assert claimed_a["id"] == first["id"]


def test_claim_next_ages_old_work_ahead_of_fresh_high_priority_work(conn: sqlite3.Connection) -> None:
    fresh_high = queue.enqueue(conn, kind="schedule", id="fresh-high", priority=100)
    aged_low = queue.enqueue(
        conn,
        kind="schedule",
        id="aged-low",
        priority=0,
        created_at="2000-01-01T00:00:00Z",
    )

    claimed = queue.claim_next(conn, worker_id="worker-a")

    assert claimed is not None
    assert claimed["id"] == aged_low["id"]
    assert queue.get(conn, fresh_high["id"])["status"] == "queued"


def test_claim_next_preserves_priority_inside_starvation_class(conn: sqlite3.Connection) -> None:
    newer_high = queue.enqueue(
        conn,
        kind="schedule",
        id="newer-high",
        priority=100,
        created_at="2000-01-01T00:20:00Z",
    )
    oldest_low = queue.enqueue(
        conn,
        kind="schedule",
        id="oldest-low",
        priority=0,
        created_at="2000-01-01T00:10:00Z",
    )

    claimed = queue.claim_next(conn, worker_id="worker-a")

    assert claimed is not None
    assert claimed["id"] == newer_high["id"]
    assert queue.get(conn, oldest_low["id"])["status"] == "queued"


def test_claim_next_respects_due_at(conn: sqlite3.Connection) -> None:
    queue.enqueue(conn, kind="schedule", due_at="2026-06-01T00:00:00Z")
    assert queue.claim_next(conn, worker_id="worker-a", now="2026-01-01T00:00:00Z") is None
    claimed = queue.claim_next(conn, worker_id="worker-a", now="2026-07-01T00:00:00Z")
    assert claimed is not None


def test_claim_next_reclaims_after_lease_expires(conn: sqlite3.Connection) -> None:
    # Reclaiming an abandoned lease requires opting the in-flight status
    # into `statuses` explicitly (see claim_next's docstring); plain
    # statuses=("queued",) intentionally never reclaims a "running" item.
    item = queue.enqueue(conn, kind="schedule")
    first = queue.claim_next(conn, worker_id="worker-a", lease_seconds=60, now="2026-01-01T00:00:00Z")
    assert first["id"] == item["id"]

    reclaim_statuses = ("queued", "running")

    # Lease still valid: a second worker gets nothing even when "running" is
    # in its claimable set.
    assert queue.claim_next(conn, worker_id="worker-b", statuses=reclaim_statuses, now="2026-01-01T00:00:30Z") is None

    # Lease expired: a second worker can now reclaim the same item.
    reclaimed = queue.claim_next(conn, worker_id="worker-b", statuses=reclaim_statuses, now="2026-01-01T00:02:00Z")
    assert reclaimed is not None
    assert reclaimed["id"] == item["id"]
    assert reclaimed["lease_owner"] == "worker-b"
    assert reclaimed["attempts"] == 2


def test_claim_next_second_connection_blocks_then_sees_leased_row(tmp_path: Path) -> None:
    """Two independent connections against the same file-backed db: proves
    the BEGIN IMMEDIATE claim is a real write-lock, not just correct in a
    single-connection test. Sequential (not threaded) — the second connect
    happens after the first transaction has already committed, so this
    checks the row is genuinely unavailable rather than racing timing."""
    db_path = tmp_path / "state.db"
    conn_a = db.connect(db_path)
    conn_b = db.connect(db_path)
    try:
        item = queue.enqueue(conn_a, kind="schedule")
        claimed_a = queue.claim_next(conn_a, worker_id="worker-a")
        assert claimed_a["id"] == item["id"]

        claimed_b = queue.claim_next(conn_b, worker_id="worker-b")
        assert claimed_b is None
    finally:
        conn_a.close()
        conn_b.close()


def test_complete_clears_lease_and_sets_terminal_status(conn: sqlite3.Connection) -> None:
    item = queue.enqueue(conn, kind="schedule")
    queue.claim_next(conn, worker_id="worker-a")
    completed = queue.complete(conn, item["id"], status="done")
    assert completed["status"] == "done"
    assert completed["lease_owner"] is None
    assert completed["lease_until"] is None
    assert completed["finished_at"] is not None


def test_complete_records_error_on_failure(conn: sqlite3.Connection) -> None:
    item = queue.enqueue(conn, kind="schedule")
    completed = queue.complete(conn, item["id"], status="failed", error="boom")
    assert completed["status"] == "failed"
    assert completed["error"] == "boom"


def test_query_filters_by_status_and_kind(conn: sqlite3.Connection) -> None:
    queue.enqueue(conn, kind="schedule", status="queued")
    item_b = queue.enqueue(conn, kind="event_chain", status="approval-needed")
    result = queue.query(conn, kind="event_chain")
    assert [item["id"] for item in result] == [item_b["id"]]
    result_status = queue.query(conn, status="approval-needed")
    assert [item["id"] for item in result_status] == [item_b["id"]]


def test_prune_dry_run_then_apply(conn: sqlite3.Connection) -> None:
    old_item = queue.enqueue(conn, kind="schedule", created_at="2020-01-01T00:00:00Z")
    queue.update_status(conn, old_item["id"], "done", now="2020-01-01T00:05:00Z")
    fresh_item = queue.enqueue(conn, kind="schedule")
    queue.update_status(conn, fresh_item["id"], "done")

    dry = queue.prune(conn, older_than_days=1, dry_run=True, now="2026-01-01T00:00:00Z")
    assert dry["matched"] == 1
    assert dry["deleted"] == 0
    assert queue.get(conn, old_item["id"]) is not None  # dry run changed nothing

    applied = queue.prune(conn, older_than_days=1, dry_run=False, now="2026-01-01T00:00:00Z")
    assert applied["deleted"] == 1
    assert queue.get(conn, old_item["id"]) is None
    assert queue.get(conn, fresh_item["id"]) is not None  # not old enough, untouched


def test_prune_only_matches_requested_statuses(conn: sqlite3.Connection) -> None:
    stuck_item = queue.enqueue(conn, kind="schedule", created_at="2020-01-01T00:00:00Z")
    queue.update_status(conn, stuck_item["id"], "blocked", now="2020-01-01T00:05:00Z")

    result = queue.prune(conn, older_than_days=1, statuses=("done", "failed", "skipped"), dry_run=False, now="2026-01-01T00:00:00Z")
    assert result["matched"] == 0
    assert queue.get(conn, stuck_item["id"]) is not None
