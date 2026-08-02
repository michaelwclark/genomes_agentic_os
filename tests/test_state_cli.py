from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest
import yaml

from genomes_agentic_os.state import register_state_cli
from genomes_agentic_os.state import db as db_module


def _build_parser() -> argparse.ArgumentParser:
    """Mirrors the integration contract documented in state/cli.py:
    register_state_cli(subparsers) against a plain
    parser.add_subparsers(dest="command", required=True) — deliberately not
    routed through genomes_agentic_os.cli.main, which does not know about
    the "state" group yet (it is wired in separately, see AGE-39 return)."""
    parser = argparse.ArgumentParser(prog="test-agentic-os")
    subparsers = parser.add_subparsers(dest="command", required=True)
    register_state_cli(subparsers)
    return parser


def _run(argv: list[str]) -> tuple[int, argparse.Namespace]:
    parser = _build_parser()
    args = parser.parse_args(argv)
    return args.handler(args), args


def test_register_state_cli_adds_state_group_with_all_subcommands() -> None:
    parser = _build_parser()
    args = parser.parse_args(["state", "status", "--db", ":memory:"])
    assert args.command == "state"
    assert args.state_command == "status"


@pytest.mark.parametrize(
    "state_command",
    ["init", "status", "backup", "import", "query", "prune", "verify-import"],
)
def test_all_documented_subcommands_are_registered(state_command: str) -> None:
    parser = _build_parser()
    # --help exits with SystemExit(0) on success; a genuinely missing
    # subcommand raises SystemExit(2) with an argparse "invalid choice" error.
    with pytest.raises(SystemExit) as exc_info:
        parser.parse_args(["state", state_command, "--help"])
    assert exc_info.value.code == 0


def test_init_creates_schema_at_explicit_db_path(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    db_path = tmp_path / "state.db"
    rc, _ = _run(["state", "init", "--db", str(db_path), "--json"])
    assert rc == 0
    assert db_path.is_file()
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema_version"] == 4
    assert payload["table_counts"] == {
        "events": 0,
        "run_queue": 0,
        "cursors": 0,
        "work_items": 0,
        "work_item_history": 0,
        "approval_requests": 0,
        "artifact_references": 0,
    }


def test_status_reports_counts_after_writes(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    db_path = tmp_path / "state.db"
    conn = db_module.connect(db_path)
    from genomes_agentic_os.state import events as events_module

    events_module.append(conn, event_type="os.example", id="evt_cli_test01")
    conn.close()

    rc, _ = _run(["state", "status", "--db", str(db_path), "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["table_counts"]["events"] == 1


def test_backup_is_dry_run_by_default_and_apply_writes_valid_snapshot(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = tmp_path / "fixture_os"
    db_path = db_module.default_db_path(root)
    conn = db_module.connect(db_path)
    conn.close()

    rc, _ = _run(["state", "backup", "--root", str(root), "--json"])
    assert rc == 0
    dry_run = json.loads(capsys.readouterr().out)
    assert dry_run["status"] == "would_backup"
    assert list((root / "harness/shared_factory/06-runs-and-logs/state-backups").glob("*.db")) == []

    rc, _ = _run(["state", "backup", "--root", str(root), "--apply", "--json"])
    assert rc == 0
    applied = json.loads(capsys.readouterr().out)
    assert applied["status"] == "completed"
    assert applied["integrity_check"] == "ok"
    assert Path(applied["snapshot"]).is_file()


def test_import_dry_run_never_creates_a_database(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = tmp_path / "fixture_os"
    control_plane = root / "harness" / "shared_factory" / "00-control-plane"
    control_plane.mkdir(parents=True)
    (control_plane / "run-queue.yml").write_text(
        yaml.safe_dump({"items": [{"id": "queue_a", "kind": "schedule", "status": "queued"}]}), encoding="utf-8"
    )

    rc, _ = _run(["state", "import", "--root", str(root), "--source", "run-queue", "--dry-run", "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["dry_run"] is True
    assert payload["run_queue"]["item_count"] == 1

    # No state.db anywhere under the fixture root, and no stray files at all.
    assert list(root.rglob("*.db")) == []
    assert list(root.rglob("*.db-*")) == []  # WAL/SHM sidecars


def test_import_then_query_round_trips_through_cli(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = tmp_path / "fixture_os"
    control_plane = root / "harness" / "shared_factory" / "00-control-plane"
    control_plane.mkdir(parents=True)
    (control_plane / "run-queue.yml").write_text(
        yaml.safe_dump({"items": [{"id": "queue_a", "kind": "schedule", "status": "queued", "idempotency_key": "k-a"}]}),
        encoding="utf-8",
    )
    db_path = tmp_path / "state.db"

    rc, _ = _run(["state", "import", "--root", str(root), "--db", str(db_path), "--source", "run-queue", "--json"])
    assert rc == 0
    capsys.readouterr()

    rc, _ = _run(["state", "query", "--db", str(db_path), "--table", "run_queue", "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["count"] == 1
    assert payload["rows"][0]["id"] == "queue_a"


def test_prune_defaults_to_dry_run_without_apply(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    db_path = tmp_path / "state.db"
    conn = db_module.connect(db_path)
    from genomes_agentic_os.state import queue as queue_module

    item = queue_module.enqueue(conn, kind="schedule", created_at="2020-01-01T00:00:00Z")
    queue_module.update_status(conn, item["id"], "done", now="2020-01-01T00:05:00Z")
    conn.close()

    rc, _ = _run(["state", "prune", "--db", str(db_path), "--older-than-days", "1", "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["dry_run"] is True
    assert payload["deleted"] == 0
    assert payload["matched"] == 1

    rc, _ = _run(["state", "prune", "--db", str(db_path), "--older-than-days", "1", "--apply", "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["dry_run"] is False
    assert payload["deleted"] == 1


def test_verify_import_returns_nonzero_exit_on_drift(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = tmp_path / "fixture_os"
    control_plane = root / "harness" / "shared_factory" / "00-control-plane"
    control_plane.mkdir(parents=True)
    (control_plane / "run-queue.yml").write_text(
        yaml.safe_dump({"items": [{"id": "queue_a", "kind": "schedule", "status": "queued"}]}), encoding="utf-8"
    )
    db_path = tmp_path / "state.db"

    rc, _ = _run(["state", "import", "--root", str(root), "--db", str(db_path), "--json"])
    assert rc == 0
    capsys.readouterr()

    rc, _ = _run(["state", "verify-import", "--root", str(root), "--db", str(db_path), "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True

    conn = db_module.connect(db_path)
    conn.execute("DELETE FROM run_queue")
    conn.close()

    rc, _ = _run(["state", "verify-import", "--root", str(root), "--db", str(db_path), "--json"])
    assert rc == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
