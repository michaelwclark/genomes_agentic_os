from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3

import pytest

from genomes_agentic_os.state import db


def test_memory_connect_creates_current_schema() -> None:
    conn = db.connect(":memory:")
    try:
        assert db.schema_version(conn) == 4
        assert db.table_counts(conn) == {
            "events": 0,
            "run_queue": 0,
            "cursors": 0,
            "work_items": 0,
            "work_item_history": 0,
            "approval_requests": 0,
            "artifact_references": 0,
        }
    finally:
        conn.close()


def test_foreign_keys_pragma_on() -> None:
    conn = db.connect(":memory:")
    try:
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    finally:
        conn.close()


def test_busy_timeout_pragma_set() -> None:
    conn = db.connect(":memory:", busy_timeout_ms=2500)
    try:
        assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 2500
    finally:
        conn.close()


def test_file_db_uses_wal_journal_mode(tmp_path: Path) -> None:
    db_path = tmp_path / "state.db"
    conn = db.connect(db_path)
    try:
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode.lower() == "wal"
    finally:
        conn.close()
    assert db_path.is_file()


def test_state_db_uses_full_synchronous_durability(tmp_path: Path) -> None:
    conn = db.connect(tmp_path / "state.db")
    try:
        assert conn.execute("PRAGMA synchronous").fetchone()[0] == 2
    finally:
        conn.close()


def test_state_backup_is_consistent_receipted_and_prunes_only_after_validation(tmp_path: Path) -> None:
    source = tmp_path / "state.db"
    backup_dir = tmp_path / "backups"
    conn = db.connect(source)
    try:
        conn.execute(
            "INSERT INTO cursors (name, payload_json, updated_at) VALUES ('durable', '{}', '2026-01-01T00:00:00Z')"
        )
    finally:
        conn.close()

    for day in range(1, 4):
        result = db.backup_database(
            source,
            backup_dir,
            retention=2,
            now=datetime(2026, 1, day, tzinfo=timezone.utc),
        )
        assert result["integrity_check"] == "ok"
        assert Path(result["snapshot"]).is_file()
        assert Path(result["receipt"]).is_file()

    snapshots = sorted(backup_dir.glob("state-*.db"))
    assert [path.name for path in snapshots] == [
        "state-20260102T000000Z.db",
        "state-20260103T000000Z.db",
    ]
    assert not (backup_dir / "state-20260101T000000Z.json").exists()
    latest = json.loads((backup_dir / "latest.json").read_text(encoding="utf-8"))
    assert latest["snapshot"].endswith("state-20260103T000000Z.db")
    restored = sqlite3.connect(snapshots[-1])
    try:
        assert restored.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert restored.execute("SELECT name FROM cursors").fetchone()[0] == "durable"
    finally:
        restored.close()


def test_connect_creates_parent_directories(tmp_path: Path) -> None:
    db_path = tmp_path / "nested" / "harness" / "state.db"
    conn = db.connect(db_path)
    conn.close()
    assert db_path.is_file()


def test_reopening_file_db_is_idempotent(tmp_path: Path) -> None:
    db_path = tmp_path / "state.db"
    conn1 = db.connect(db_path)
    conn1.close()

    conn2 = db.connect(db_path)
    try:
        assert db.schema_version(conn2) == 4
        assert db.table_counts(conn2) == {
            "events": 0,
            "run_queue": 0,
            "cursors": 0,
            "work_items": 0,
            "work_item_history": 0,
            "approval_requests": 0,
            "artifact_references": 0,
        }
    finally:
        conn2.close()


def test_ensure_schema_is_idempotent_on_same_connection() -> None:
    conn = db.connect(":memory:")
    try:
        version_before = db.ensure_schema(conn)
        version_after = db.ensure_schema(conn)
        assert version_before == version_after == 4
        # One schema_version row per migration ever applied, not one per call.
        row_count = conn.execute("SELECT COUNT(*) FROM schema_version").fetchone()[0]
        assert row_count == 4
    finally:
        conn.close()


def test_current_schema_check_does_not_acquire_a_write_transaction() -> None:
    conn = db.connect(":memory:")
    statements: list[str] = []
    try:
        conn.set_trace_callback(statements.append)
        assert db.ensure_schema(conn) == 4
        assert not any(statement.startswith("BEGIN IMMEDIATE") for statement in statements)
    finally:
        conn.close()


def test_resolve_os_root_with_explicit_root(tmp_path: Path) -> None:
    root = tmp_path / "some_os"
    assert db.resolve_os_root(str(root)) == root.resolve()


def test_resolve_os_root_uses_find_os_root_when_root_omitted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_root = tmp_path / "discovered_os"
    fake_root.mkdir()
    monkeypatch.setattr(db, "find_os_root", lambda cwd: fake_root)
    assert db.resolve_os_root(None) == fake_root


def test_resolve_os_root_raises_when_undiscoverable(monkeypatch: pytest.MonkeyPatch) -> None:
    # Reuses conversation_logging.find_os_root rather than reimplementing
    # discovery; this proves resolve_os_root actually calls through to it
    # (and surfaces a clear error) instead of silently returning garbage.
    monkeypatch.setattr(db, "find_os_root", lambda cwd: None)
    with pytest.raises(db.StateDbError):
        db.resolve_os_root(None)


def test_default_db_path_layout(tmp_path: Path) -> None:
    root = tmp_path / "some_os"
    path = db.default_db_path(root)
    assert path == root.resolve() / "harness" / "shared_factory" / "00-control-plane" / "state.db"


def test_default_db_path_honors_domain_override(tmp_path: Path) -> None:
    root = tmp_path / "some_os"
    path = db.default_db_path(root, domain="alpha_ops")
    assert path == root.resolve() / "harness" / "alpha_ops" / "00-control-plane" / "state.db"


def test_transaction_commits_on_success(tmp_path: Path) -> None:
    conn = db.connect(tmp_path / "state.db")
    try:
        with db.transaction(conn):
            conn.execute("INSERT INTO cursors (name, payload_json, updated_at) VALUES ('a', '{}', 'now')")
        assert conn.execute("SELECT COUNT(*) FROM cursors").fetchone()[0] == 1
    finally:
        conn.close()


def test_transaction_rolls_back_on_exception(tmp_path: Path) -> None:
    conn = db.connect(tmp_path / "state.db")
    try:
        with pytest.raises(ValueError):
            with db.transaction(conn):
                conn.execute("INSERT INTO cursors (name, payload_json, updated_at) VALUES ('a', '{}', 'now')")
                raise ValueError("boom")
        assert conn.execute("SELECT COUNT(*) FROM cursors").fetchone()[0] == 0
    finally:
        conn.close()


def test_table_counts_rejects_unknown_table() -> None:
    conn = db.connect(":memory:")
    try:
        with pytest.raises(db.StateDbError):
            db.table_counts(conn, tables=("not_a_real_table",))
    finally:
        conn.close()


def test_days_ago_iso_is_relative_to_explicit_now() -> None:
    assert db.days_ago_iso(1, now="2026-01-02T00:00:00Z") == "2026-01-01T00:00:00Z"
    assert db.days_ago_iso(10, now="2026-01-11T12:00:00Z") == "2026-01-01T12:00:00Z"
