from __future__ import annotations

import sqlite3

from genomes_agentic_os.state import db, events, queue, work_items


def _work_item(conn: sqlite3.Connection, item_id: str) -> None:
    work_items.upsert(
        conn,
        item_id=item_id,
        title=item_id,
        state="ready",
        attention="queued",
        source_system="linear",
        source_key=f"AGE-{item_id[-1:]}",
    )


def _agent_claim(conn: sqlite3.Connection, item_id: str, *, actor: str, state: str = "completed") -> None:
    conn.execute(
        """
        INSERT INTO work_item_history (
            work_item_id, changed_at, actor, from_state, to_state,
            from_attention, to_attention, summary, receipt_ref, metadata_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (item_id, "2026-08-01T00:00:00Z", actor, "building", state, "active", "closed", None, None, "{}"),
    )


def test_reconcile_completion_claims_reports_supported_and_phantom_run_and_agent_claims() -> None:
    conn = db.connect(":memory:")
    try:
        supported_run = queue.enqueue(conn, kind="run", id="queue_supported")
        queue.complete(conn, supported_run["id"], now="2026-08-01T00:00:00Z")
        events.append(
            conn,
            event_type="os.run.closed.done",
            id="evt_supported_run",
            correlation_id=supported_run["id"],
        )
        phantom_run = queue.enqueue(conn, kind="run", id="queue_phantom")
        queue.complete(conn, phantom_run["id"], now="2026-08-01T00:00:00Z")

        _work_item(conn, "work-supported")
        _agent_claim(conn, "work-supported", actor="agent-a")
        events.append(
            conn,
            event_type="agent.completed",
            id="evt_supported_agent",
            correlation_id="work-supported",
            payload={"actor": "agent-a"},
        )
        _work_item(conn, "work-phantom")
        _agent_claim(conn, "work-phantom", actor="agent-b")
        events.append(
            conn,
            event_type="agent.completed",
            id="evt_actor_mismatch",
            correlation_id="work-phantom",
            payload={"agent_id": "another-agent"},
        )

        result = work_items.reconcile_completion_claims(conn)
    finally:
        conn.close()

    assert result["status"] == "phantom_completions"
    assert result["claim_count"] == 4
    assert result["supported_count"] == 2
    assert result["phantom_count"] == 2
    claims = {claim["claim_id"]: claim for claim in result["claims"]}
    supported_agent = next(claim for claim in result["claims"] if claim["subject_id"] == "work-supported")
    phantom_agent = next(claim for claim in result["claims"] if claim["subject_id"] == "work-phantom")
    assert claims["run:queue_supported"]["supporting_event_ids"] == ["evt_supported_run"]
    assert claims["run:queue_phantom"]["status"] == "phantom"
    assert supported_agent["actor"] == "agent-a"
    assert supported_agent["supporting_event_ids"] == ["evt_supported_agent"]
    assert phantom_agent["claim_state"] == "completed"
    assert phantom_agent["status"] == "phantom"


def test_reconcile_ignores_unrelated_events_and_non_successful_agent_states() -> None:
    conn = db.connect(":memory:")
    try:
        run = queue.enqueue(conn, kind="run", id="queue_a")
        queue.complete(conn, run["id"], now="2026-08-01T00:00:00Z")
        events.append(conn, event_type="os.run.closed.done", id="evt_unrelated", correlation_id="queue_other")
        _work_item(conn, "work-cancelled")
        _agent_claim(conn, "work-cancelled", actor="agent-c", state="cancelled")

        result = work_items.reconcile_completion_claims(conn)
    finally:
        conn.close()

    assert result["claim_count"] == 1
    assert result["claims"][0]["claim_id"] == "run:queue_a"
    assert result["claims"][0]["status"] == "phantom"


def test_reconcile_completion_claims_performs_no_writes() -> None:
    conn = db.connect(":memory:")
    try:
        run = queue.enqueue(conn, kind="run", id="queue_clean")
        queue.complete(conn, run["id"], now="2026-08-01T00:00:00Z")
        events.append(conn, event_type="os.run.closed.done", id="evt_clean", correlation_id="queue_clean")
        statements: list[str] = []
        conn.set_trace_callback(statements.append)

        result = work_items.reconcile_completion_claims(conn)
    finally:
        conn.close()

    assert result["status"] == "clean"
    assert not any(statement.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE", "BEGIN")) for statement in statements)
