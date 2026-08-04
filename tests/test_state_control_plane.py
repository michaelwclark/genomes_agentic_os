from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from genomes_agentic_os.state import control_plane, db, work_items


@pytest.fixture()
def conn() -> sqlite3.Connection:
    connection = db.connect(":memory:")
    try:
        yield connection
    finally:
        connection.close()


def test_approval_wait_state_is_durable_and_requires_the_named_approver(conn):
    request = control_plane.request_approval(
        conn,
        request_id="approval_demo",
        subject_type="host_cleanup",
        subject_id="cleanup-153",
        requested_by="agent",
        approver="michael",
        requested_at="2026-08-02T10:00:00Z",
        expires_at="2026-08-02T11:00:00Z",
    )

    assert request["status"] == "waiting"
    with pytest.raises(control_plane.ControlPlaneError, match="named approver"):
        control_plane.decide_approval(conn, request["id"], approver="someone-else", decision="approved")

    decision = control_plane.decide_approval(
        conn,
        request["id"],
        approver="michael",
        decision="approved",
        decided_at="2026-08-02T10:30:00Z",
    )
    assert decision["status"] == "approved"
    assert decision["decided_at"] == "2026-08-02T10:30:00Z"


def test_approval_expiry_is_explicit_and_projection_is_read_only(conn):
    request = control_plane.request_approval(
        conn,
        subject_type="release",
        subject_id="v1",
        requested_by="agent",
        approver="michael",
        requested_at="2026-08-02T10:00:00Z",
        expires_at="2026-08-02T11:00:00Z",
    )

    projection = control_plane.control_plane_projection(conn, now="2026-08-02T12:00:00Z")
    assert projection["approvals"][0]["status"] == "expired"
    assert control_plane.get_approval(conn, request["id"])["status"] == "waiting"
    assert control_plane.expire_approvals(conn, now="2026-08-02T12:00:00Z") == 1
    assert control_plane.get_approval(conn, request["id"])["status"] == "expired"


def test_artifact_reference_stores_uri_hash_classification_and_retention_only(conn):
    reference = control_plane.record_artifact_reference(
        conn,
        reference_id="artifact_demo",
        uri="s3://receipts/cleanup-153.json",
        content_sha256="a" * 64,
        classification="internal",
        retention_days=30,
        source_ref="cleanup-153",
    )

    assert reference == {
        "id": "artifact_demo",
        "uri": "s3://receipts/cleanup-153.json",
        "content_sha256": "a" * 64,
        "classification": "internal",
        "retention_days": 30,
        "source_ref": "cleanup-153",
        "created_at": reference["created_at"],
    }
    assert control_plane.control_plane_projection(conn)["artifact_reference_counts"] == {"internal": 1}
    with pytest.raises(control_plane.ControlPlaneError, match="SHA-256"):
        control_plane.record_artifact_reference(conn, uri="s3://receipts/bad", content_sha256="body", classification="internal", retention_days=1)


def test_change_linkage_requires_one_linear_work_item_and_worktree(conn):
    item = work_items.upsert(
        conn,
        item_id="age-92",
        title="Enforce link",
        state="building",
        attention="active",
        context_summary="Implement guard.",
        source_system="linear",
        source_key="AGE-92",
        worktree_path="/worktrees/age-92",
        branch="feature/age-92",
    )

    assert control_plane.validate_change_linkage(item) == {
        "work_item_id": "age-92",
        "worktree_path": "/worktrees/age-92",
        "branch": "feature/age-92",
        "linear_issue": "AGE-92",
    }
    item["source_system"] = "jira"
    with pytest.raises(control_plane.ControlPlaneError, match="Linear-backed"):
        control_plane.validate_change_linkage(item)


def test_read_only_change_linkage_guard_validates_the_canonical_row(tmp_path: Path):
    db_path = tmp_path / "state.db"
    conn = db.connect(db_path)
    try:
        work_items.upsert(
            conn,
            item_id="age-92",
            title="Enforce link",
            state="building",
            attention="active",
            context_summary="Implement guard.",
            source_system="linear",
            source_key="AGE-92",
            worktree_path="/worktrees/age-92",
            branch="feature/age-92",
        )
    finally:
        conn.close()

    script = Path(__file__).resolve().parents[1] / "scripts" / "check-change-linkage.py"
    result = subprocess.run(
        [sys.executable, str(script), "--db", str(db_path), "--work-item", "age-92", "--json"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert json.loads(result.stdout) == {
        "linkage": {
            "branch": "feature/age-92",
            "linear_issue": "AGE-92",
            "work_item_id": "age-92",
            "worktree_path": "/worktrees/age-92",
        },
        "ok": True,
    }
