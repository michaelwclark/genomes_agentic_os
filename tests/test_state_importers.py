from __future__ import annotations

from pathlib import Path
import sqlite3

import pytest
import yaml

from genomes_agentic_os.state import db, importers, queue


def _write_yaml(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


@pytest.fixture()
def fixture_root(tmp_path: Path) -> Path:
    """A synthetic installed-OS tree matching the real file formats
    (verified against the live instance by structural inspection — see
    docs/design-notes/state-plane.md), with only neutral/synthetic names."""
    root = tmp_path / "fixture_os"
    (root / ".agentic_root").parent.mkdir(parents=True, exist_ok=True)
    (root / ".agentic_root").write_text("marker\n", encoding="utf-8")

    control_plane = root / "harness" / "shared_factory" / "00-control-plane"
    events_dir = root / "harness" / "shared_factory" / "06-runs-and-logs" / "events"

    _write_yaml(
        control_plane / "run-queue.yml",
        {
            "version": "0.1.0",
            "managed_by": "agentic-os runtime",
            "states": ["dry-run", "queued", "approval-needed", "running", "blocked", "done", "failed", "skipped"],
            "approval_states": ["not_required", "required", "approved", "denied", "expired", "blocked"],
            "items": [
                {
                    "id": "queue_synthetic0001",
                    "kind": "schedule",
                    "ref": "automation/example-alpha/heartbeat",
                    "status": "done",
                    "approval_state": "not_required",
                    "created_at": "2026-01-01T00:00:00Z",
                    "dry_run": False,
                    "due_at": "2026-01-01T00:00:00Z",
                    "idempotency_key": "idem-synthetic-0001",
                    "execution_target": "script",
                    "command": "example-command --flag",
                    "log": "harness/logs/example-0001.log",
                    "evidence": [{"type": "log", "path": "harness/logs/example-0001.log"}],
                    "blocked_reason": None,
                    "updated_at": "2026-01-01T00:01:00Z",
                    "started_at": "2026-01-01T00:00:05Z",
                    "finished_at": "2026-01-01T00:01:00Z",
                    "dispatch_log": "harness/logs/dispatch-0001.log",
                    "error": "",
                },
                {
                    "id": "queue_synthetic0002",
                    "kind": "schedule",
                    "ref": "automation/example-beta/poll",
                    "status": "queued",
                    "approval_state": "not_required",
                    "created_at": "2026-01-02T00:00:00Z",
                    "dry_run": False,
                    "idempotency_key": "idem-synthetic-0002",
                    "execution_target": "script",
                },
            ],
            "run_queue": [],
        },
    )

    _write_yaml(
        events_dir / "evt_synthetic00a1.yml",
        {
            "id": "evt_synthetic00a1",
            "type": "os.doctor.regression",
            "schema_version": 1,
            "occurred_at": "2026-01-01T00:00:00Z",
            "observed_at": "2026-01-01T00:00:00Z",
            "source": {"ref": "harness/shared_factory/00-control-plane/doctor-snapshot.yml"},
            "correlation": {"correlation_id": "corr-0001"},
            "idempotency_key": "os.doctor.regression:corr-0001",
            "summary": "doctor detected regression in: core.",
            "payload_ref": {"type": "inline", "regressions": [{"subsystem": "core", "was_ok": False}]},
            "privacy": {"contains_secret": False, "contains_customer_data": False},
            "links": {"run_log": None, "source_url": "harness/shared_factory/00-control-plane/doctor-snapshot.yml"},
        },
    )
    _write_yaml(
        events_dir / "evt_synthetic00b2.yml",
        {
            "id": "evt_synthetic00b2",
            "type": "os.watch.poll",
            "schema_version": 1,
            "occurred_at": "2026-01-02T00:00:00Z",
            "observed_at": "2026-01-02T00:00:00Z",
            "source": {"ref": "watch/example-source"},
            "correlation": {"correlation_id": "corr-0002"},
            "idempotency_key": "os.watch.poll:corr-0002",
            "summary": "Observed poll from example-source.",
            "payload_ref": {"type": "ref", "href": "watch/example-source"},
            "privacy": {"contains_secret": False, "contains_customer_data": False},
            "links": {"run_log": None, "source_url": "watch/example-source"},
        },
    )

    _write_yaml(control_plane / "event-cursors.yml", {"processed_idempotency_keys": ["k1", "k2"]})
    _write_yaml(
        control_plane / "watch-cursors.yml",
        {
            "watch_cursors": [
                {
                    "id": "example_source_alpha",
                    "watch_source_id": "example_source_alpha",
                    "cursor_type": "event_id",
                    "last_value": "src_evt_0001",
                    "last_idempotency_key": "{a}#{b}",
                    "updated_at": "2026-01-01T00:00:00Z",
                },
                {
                    "id": "example_source_beta",
                    "watch_source_id": "example_source_beta",
                    "cursor_type": "event_id",
                    "last_value": "src_evt_0002",
                    "last_idempotency_key": "{a}#{b}",
                    "updated_at": "2026-01-02T00:00:00Z",
                },
            ]
        },
    )
    return root


@pytest.fixture()
def conn() -> sqlite3.Connection:
    connection = db.connect(":memory:")
    try:
        yield connection
    finally:
        connection.close()


def _all_files(root: Path) -> set[str]:
    return {str(path.relative_to(root)) for path in root.rglob("*") if path.is_file()}


def test_scan_all_never_touches_the_filesystem(fixture_root: Path) -> None:
    before = _all_files(fixture_root)
    result = importers.scan_all(fixture_root)
    after = _all_files(fixture_root)
    assert before == after  # scan is pure: no new files, no db, nothing written
    assert result["run_queue"]["item_count"] == 2
    assert result["events"]["event_count"] == 2
    assert result["cursors"]["cursor_row_count"] == 3  # 1 event-cursor row + 2 watch-cursor rows


def test_scan_all_reports_missing_sources_as_zero(tmp_path: Path) -> None:
    empty_root = tmp_path / "empty_os"
    empty_root.mkdir()
    result = importers.scan_all(empty_root)
    assert result["run_queue"]["item_count"] == 0
    assert result["run_queue"]["exists"] is False
    assert result["events"]["event_count"] == 0
    assert result["cursors"]["cursor_row_count"] == 0


def test_import_run_queue_maps_core_fields_and_catch_all_payload(fixture_root: Path, conn: sqlite3.Connection) -> None:
    paths = importers.default_source_paths(fixture_root)
    result = importers.import_run_queue(conn, paths.run_queue)
    assert result["inserted"] == 2
    assert result["source_item_count"] == 2

    item = queue.get(conn, "queue_synthetic0001")
    assert item["status"] == "done"
    assert item["ref"] == "automation/example-alpha/heartbeat"
    assert "ref" not in item["payload"]  # core column, not duplicated into payload
    assert item["payload"]["command"] == "example-command --flag"
    assert item["payload"]["dispatch_log"] == "harness/logs/dispatch-0001.log"


def test_import_run_queue_skips_distinct_ids_with_duplicate_idempotency_key(
    fixture_root: Path, conn: sqlite3.Connection
) -> None:
    paths = importers.default_source_paths(fixture_root)
    source = yaml.safe_load(paths.run_queue.read_text(encoding="utf-8"))
    source["items"].append(
        {
            "id": "queue_synthetic0003",
            "kind": "schedule",
            "status": "queued",
            "created_at": "2026-01-03T00:00:00Z",
            "idempotency_key": source["items"][0]["idempotency_key"],
        }
    )
    _write_yaml(paths.run_queue, source)

    result = importers.import_run_queue(conn, paths.run_queue)

    assert result["source_item_count"] == 3
    assert result["processed"] == 2
    assert result["skipped_duplicate_idempotency_key"] == 1
    assert result["inserted"] == 2
    assert queue.get(conn, "queue_synthetic0001") is not None
    assert queue.get(conn, "queue_synthetic0003") is None


def test_import_events_maps_envelope_fields(fixture_root: Path, conn: sqlite3.Connection) -> None:
    paths = importers.default_source_paths(fixture_root)
    result = importers.import_events(conn, paths.events_dir)
    assert result["inserted"] == 2

    from genomes_agentic_os.state import events as events_module

    row = events_module.get(conn, "evt_synthetic00a1")
    assert row["type"] == "os.doctor.regression"
    assert row["correlation_id"] == "corr-0001"
    assert row["source_ref"] == "harness/shared_factory/00-control-plane/doctor-snapshot.yml"
    assert row["payload"]["type"] == "inline"


def test_import_cursors_folds_event_cursors_into_one_row(fixture_root: Path, conn: sqlite3.Connection) -> None:
    paths = importers.default_source_paths(fixture_root)
    result = importers.import_cursors(conn, event_cursors_path=paths.event_cursors, watch_cursors_path=paths.watch_cursors)
    assert result["written"] == 3

    from genomes_agentic_os.state import cursors as cursors_module

    dedupe = cursors_module.get_cursor(conn, importers.EVENT_CHAIN_DEDUPE_CURSOR_NAME)
    assert dedupe["payload"]["processed_idempotency_keys"] == ["k1", "k2"]

    watch_row = cursors_module.get_cursor(conn, "example_source_alpha")
    assert watch_row["last_value"] == "src_evt_0001"


def test_import_all_is_idempotent_across_two_runs(fixture_root: Path, conn: sqlite3.Connection) -> None:
    first = importers.import_all(conn, fixture_root)
    assert first["run_queue"]["inserted"] == 2
    assert first["events"]["inserted"] == 2
    assert first["cursors"]["written"] == 3

    counts_after_first = db.table_counts(conn)

    second = importers.import_all(conn, fixture_root)
    assert second["run_queue"]["inserted"] == 0  # nothing NEW, all upserted
    assert second["events"]["inserted"] == 0  # append-only: re-seen ids are skipped
    assert second["cursors"]["written"] == 3  # same 3 rows upserted again, not duplicated

    counts_after_second = db.table_counts(conn)
    assert counts_after_first == counts_after_second == {
        "events": 2,
        "run_queue": 2,
        "cursors": 3,
        "work_items": 0,
        "work_item_history": 0,
        "approval_requests": 0,
        "artifact_references": 0,
    }


def test_import_all_respects_source_filter(fixture_root: Path, conn: sqlite3.Connection) -> None:
    result = importers.import_all(conn, fixture_root, source="events")
    assert "events" in result
    assert "run_queue" not in result
    assert "cursors" not in result
    assert db.table_counts(conn) == {
        "events": 2,
        "run_queue": 0,
        "cursors": 0,
        "work_items": 0,
        "work_item_history": 0,
        "approval_requests": 0,
        "artifact_references": 0,
    }


def test_verify_import_reports_ok_when_synced(fixture_root: Path, conn: sqlite3.Connection) -> None:
    importers.import_all(conn, fixture_root)
    result = importers.verify_import(conn, fixture_root)
    assert result["ok"] is True
    assert result["drift"] == {"run_queue": 0, "events": 0, "cursors": 0}


def test_verify_import_detects_drift(fixture_root: Path, conn: sqlite3.Connection) -> None:
    importers.import_all(conn, fixture_root)
    conn.execute("DELETE FROM run_queue WHERE id = 'queue_synthetic0001'")
    result = importers.verify_import(conn, fixture_root)
    assert result["ok"] is False
    assert result["drift"]["run_queue"] == -1
    assert result["drift"]["events"] == 0


def test_importers_never_mutate_source_files(fixture_root: Path, conn: sqlite3.Connection) -> None:
    before = {
        path: path.read_bytes() for path in fixture_root.rglob("*") if path.is_file()
    }
    importers.import_all(conn, fixture_root)
    importers.verify_import(conn, fixture_root)
    after = {path: path.read_bytes() for path in fixture_root.rglob("*") if path.is_file()}
    assert before == after
