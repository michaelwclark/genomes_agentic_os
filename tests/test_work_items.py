from __future__ import annotations

import json
from pathlib import Path

import pytest

from genomes_agentic_os.cli import main
from genomes_agentic_os.lifecycle import sync_active_container
from genomes_agentic_os.state import db, work_items
from genomes_agentic_os.validate import ValidationResult, validate_work_state


def test_active_attention_requires_resume_context() -> None:
    conn = db.connect(":memory:")
    try:
        with pytest.raises(work_items.WorkItemError):
            work_items.upsert(
                conn,
                item_id="los:one",
                title="One",
                state="building",
                attention="active",
            )
    finally:
        conn.close()


def test_upsert_transition_history_and_active_projection(tmp_path: Path) -> None:
    root = tmp_path / "os"
    root.mkdir()
    db_path = db.default_db_path(root)
    conn = db.connect(db_path)
    try:
        created = work_items.upsert(
            conn,
            item_id="los:django:flywl-1",
            title="Fix the thing",
            state="building",
            attention="active",
            domain="los",
            project="django",
            context_summary="Implementation is in progress on the guarded fix.",
            source_system="jira",
            source_key="FLYWL-1",
            verified=True,
        )
        assert created["attention"] == "active"
        projection = work_items.write_active_projection(conn, root)
        assert projection["active_count"] == 1
        assert projection["stale_count"] == 0

        finished = work_items.update(
            conn,
            created["id"],
            state="finished",
            actor="test",
            receipt_ref="receipt://merged",
        )
        assert finished["attention"] == "closed"
        assert work_items.active_now(conn)["active_count"] == 0
        assert conn.execute("SELECT COUNT(*) FROM work_item_history").fetchone()[0] == 2

        reopened = work_items.update(conn, created["id"], state="building", actor="test")
        assert reopened["attention"] == "parked"
    finally:
        conn.close()


def test_legacy_import_is_conservative_and_idempotent(tmp_path: Path) -> None:
    root = tmp_path / "os"
    packet = root / "los/02-projects/django/work-items/02-active/001_example"
    packet.mkdir(parents=True)
    (packet / "NEXT.md").write_text("# Next\n\nVerify the migration.\n", encoding="utf-8")
    (packet.parent / ".artifacts").mkdir()
    (packet.parent / "001_example.artifacts").mkdir()
    plan = work_items.legacy_import_plan(root)
    assert plan["candidate_count"] == 1
    assert plan["items"][0]["attention"] == "queued"

    conn = db.connect(db.default_db_path(root))
    try:
        first = work_items.import_legacy(conn, root, dry_run=False)
        second = work_items.import_legacy(conn, root, dry_run=False)
        assert first["imported"] == 1
        assert second["existing"] == 1
        assert work_items.active_now(conn)["active_count"] == 0
    finally:
        conn.close()


def test_legacy_active_index_observation_imports_as_parked(tmp_path: Path) -> None:
    root = tmp_path / "os"
    packet = root / "los/02-projects/django/work-items/02-active/001_example"
    packet.mkdir(parents=True)
    index = root / "00-control-plane/active/index.yml"
    index.parent.mkdir(parents=True)
    index.write_text(
        "work_items:\n"
        f"  - target: {packet}\n"
        "    status: building\n",
        encoding="utf-8",
    )
    plan = work_items.legacy_import_plan(root)
    assert plan["items"][0]["state"] == "building"
    assert plan["items"][0]["attention"] == "parked"


def test_legacy_blocked_item_gets_a_verification_reason(tmp_path: Path) -> None:
    root = tmp_path / "os"
    packet = root / "los/02-projects/django/work-items/02-active/001_example"
    packet.mkdir(parents=True)
    index = root / "00-control-plane/active/index.yml"
    index.parent.mkdir(parents=True)
    index.write_text(
        "work_items:\n"
        f"  - target: {packet}\n"
        "    status: blocked\n",
        encoding="utf-8",
    )

    plan = work_items.legacy_import_plan(root)

    assert plan["items"][0]["state"] == "blocked"
    assert "requires verification" in plan["items"][0]["blocked_reason"]


def test_work_cli_round_trip(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = tmp_path / "os"
    root.mkdir()
    assert main(
        [
            "work",
            "upsert",
            "--root",
            str(root),
            "los:one",
            "--title",
            "One",
            "--state",
            "building",
            "--attention",
            "active",
            "--summary",
            "The active implementation context.",
            "--verified",
        ]
    ) == 0
    capsys.readouterr()
    assert main(["work", "active-now", "--root", str(root)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["active_count"] == 1
    assert (root / work_items.ACTIVE_NOW_RELATIVE).is_file()


def test_global_active_container_uses_state_after_projection_opt_in(tmp_path: Path) -> None:
    root = tmp_path / "os"
    project = root / "los/02-projects/django"
    packet = project / "work-items/02-active/001_example"
    packet.mkdir(parents=True)
    active_worktree = tmp_path / "active-worktree"
    active_worktree.mkdir()
    unrelated_worktree = project / "worktrees/unrelated"
    unrelated_worktree.mkdir(parents=True)
    (project / "worktrees/index.yml").write_text(
        "worktrees:\n"
        "  - id: unrelated\n"
        f"    path: {unrelated_worktree}\n"
        "    status: active\n",
        encoding="utf-8",
    )
    (root / "los/domain.yml").write_text("name: los\n", encoding="utf-8")
    conn = db.connect(db.default_db_path(root))
    try:
        work_items.upsert(
            conn,
            item_id="los:django:001_example",
            title="Example",
            state="building",
            attention="active",
            domain="los",
            project="django",
            packet_path=packet.relative_to(root).as_posix(),
            worktree_path=str(active_worktree),
            context_summary="Only this verified row is active.",
            verified=True,
        )
        work_items.write_active_projection(conn, root)
    finally:
        conn.close()

    result = sync_active_container(root)
    assert result["work_items"] == 1
    assert result["worktrees"] == 1
    index = (root / "00-control-plane/active/index.yml").read_text(encoding="utf-8")
    assert "state.db active work_items" in index
    assert "Only this verified row is active." in index
    assert str(active_worktree) in index
    assert str(unrelated_worktree) not in index


def test_validate_work_state_detects_stale_projection(tmp_path: Path) -> None:
    root = tmp_path / "os"
    root.mkdir()
    conn = db.connect(db.default_db_path(root))
    try:
        work_items.write_active_projection(conn, root)
        healthy = ValidationResult(root=root)
        validate_work_state(root, healthy)
        assert healthy.errors == []

        work_items.upsert(
            conn,
            item_id="one",
            title="One",
            state="building",
            attention="active",
            context_summary="Now active but not projected.",
        )
    finally:
        conn.close()
    stale = ValidationResult(root=root)
    validate_work_state(root, stale)
    assert any("projection is stale" in error for error in stale.errors)
