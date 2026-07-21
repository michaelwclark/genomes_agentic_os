from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import threading
import time
from types import SimpleNamespace

import pytest
import yaml

from genomes_agentic_os.cli import main
from genomes_agentic_os.cli import runtime as runtime_cli
from genomes_agentic_os.runtime_backend import (
    RuntimeBackendError,
    apply_queue_mode,
    plan_queue_mode,
    plan_execution_state_reconciliation,
    queue_mode_status,
    reconcile_execution_state,
    rollback_queue_mode,
    runtime_queue_items,
)
from genomes_agentic_os import runtime_ops, runtime_snapshot
from genomes_agentic_os.runtime_snapshot import build_runtime_snapshot, format_runtime_snapshot, write_runtime_snapshot
from genomes_agentic_os.state import db
from genomes_agentic_os.state import execution_fabric as fabric
from genomes_agentic_os.state import queue as state_queue


def _root(tmp_path: Path) -> Path:
    root = tmp_path / "agentic_os"
    control = root / "harness/shared_factory/00-control-plane"
    control.mkdir(parents=True)
    (control / "runtime-registry.yml").write_text(
        yaml.safe_dump({"version": "0.1.0", "execution_targets": []}, sort_keys=False),
        encoding="utf-8",
    )
    (control / "run-queue.yml").write_text(
        yaml.safe_dump(
            {
                "version": "0.1.0",
                "items": [
                    {
                        "id": "legacy-1",
                        "kind": "schedule",
                        "status": "queued",
                        "approval_state": "not_required",
                        "created_at": "2026-01-01T00:00:00Z",
                    }
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return root


def test_missing_selector_defaults_to_filesystem_and_dry_run_is_read_only(tmp_path: Path) -> None:
    root = _root(tmp_path)
    registry = root / "harness/shared_factory/00-control-plane/runtime-registry.yml"
    before = registry.read_text(encoding="utf-8")

    status = queue_mode_status(root)
    plan = apply_queue_mode(root, "execution_fabric")

    assert status["queue_mode"] == "filesystem"
    assert status["mode_source"] == "default"
    assert status["metrics"]["queues"][0]["statuses"]["queued"] == 1
    assert plan["dry_run"] is True
    assert plan["applied"] is False
    assert registry.read_text(encoding="utf-8") == before
    assert not Path(plan["state_db"]).exists()


def test_runtime_snapshot_is_backend_neutral_and_projects_safe_task_fields(tmp_path: Path) -> None:
    root = _root(tmp_path)
    filesystem = build_runtime_snapshot(root, task_limit=10)

    assert filesystem["queue_mode"] == "filesystem"
    assert filesystem["summary"]["queued"] == 1
    assert filesystem["queues"][0]["queue_name"] == "filesystem"
    assert filesystem["queues"][0]["depth"] == 1
    assert filesystem["tasks"][0]["queue_name"] == "filesystem"
    assert not (root / "harness/shared_factory/00-control-plane/.runtime-queue-mode.lock").exists()

    apply_queue_mode(root, "execution_fabric", dry_run=False)
    runtime_ops.append_run_queue_item(
        root,
        {
            "id": "snapshot-codex",
            "kind": "manual",
            "ref": "self_improvement_action_watch",
            "status": "queued",
            "execution_target": "codex_harness",
            "command": "secret command must not be projected",
        },
    )
    conn = db.connect(db.default_db_path(root))
    try:
        conn.execute(
            "UPDATE run_queue SET error = ? WHERE id = ?",
            ("provider rejected sk-abcdefghijklmnopqrstuvwxyz", "snapshot-codex"),
        )
        fabric.register_worker(conn, "snapshot-worker", pool_name="codex_workers")
    finally:
        conn.close()

    snapshot = build_runtime_snapshot(root, queue_name="codex", statuses=["queued"], task_limit=10)

    assert snapshot["queue_mode"] == "execution_fabric"
    assert {queue["queue_name"] for queue in snapshot["queues"]} == {
        "codex",
        "claude",
        "pr_reviews",
        "los_environment",
        "non_llm",
    }
    assert snapshot["filters"]["matching_tasks"] == 1
    assert snapshot["tasks"][0]["id"] == "snapshot-codex"
    assert snapshot["tasks"][0]["display_name"] == "self_improvement_action_watch"
    assert "command" not in snapshot["tasks"][0]
    assert "ref" not in snapshot["tasks"][0]
    assert "error" not in snapshot["tasks"][0]
    assert "blocked_reason" not in snapshot["tasks"][0]
    assert snapshot["workers"][0]["id"] == "snapshot-worker"
    assert "lease_token" not in snapshot["workers"][0]
    assert "display_name" not in runtime_snapshot._project_task(
        {"id": "secret-ref", "kind": "manual", "status": "queued", "ref": "sk_super_secret_value"},
        queue_mode="execution_fabric",
    )
    assert "QUEUES" in format_runtime_snapshot(snapshot)
    assert "snapshot-codex" in format_runtime_snapshot(snapshot)


def test_runtime_snapshot_hides_inactive_worker_history_and_projects_running_work(tmp_path: Path) -> None:
    root = _root(tmp_path)
    apply_queue_mode(root, "execution_fabric", dry_run=False)
    runtime_ops.append_run_queue_item(
        root,
        {
            "id": "queue-running",
            "kind": "schedule",
            "ref": "slack_ingest_watcher",
            "status": "queued",
            "execution_target": "script",
        },
    )
    conn = db.connect(db.default_db_path(root))
    try:
        active = fabric.register_worker(
            conn,
            "runtime-bigmac.example-4242-active",
            pool_name="non_llm_workers",
            lease_seconds=600,
            now="2026-07-19T11:55:00Z",
        )
        conn.execute(
            """
            UPDATE execution_workers SET active_tasks = 1 WHERE id = ?
            """,
            (active["id"],),
        )
        conn.execute(
            """
            UPDATE run_queue
            SET status = 'running', started_at = ?, updated_at = ?, lease_owner = ?, lease_until = ?
            WHERE id = 'queue-running'
            """,
            ("2026-07-19T11:56:00Z", "2026-07-19T11:56:00Z", active["id"], "2026-07-19T12:05:00Z"),
        )
        conn.executemany(
            """
            INSERT INTO execution_workers (
                id, pool_name, status, capacity, active_tasks, heartbeat_at,
                lease_until, lease_token, metadata_json, created_at, updated_at
            ) VALUES (?, 'non_llm_workers', 'offline', 1, 0, ?, ?, ?, '{}', ?, ?)
            """,
            [
                (
                    f"runtime-bigmac.example-4000-{index:04d}",
                    "2026-07-18T10:00:00Z",
                    "2026-07-18T10:00:00Z",
                    f"token-{index}",
                    "2026-07-18T10:00:00Z",
                    "2026-07-18T10:00:00Z",
                )
                for index in range(250)
            ],
        )
        conn.commit()
    finally:
        conn.close()

    snapshot = build_runtime_snapshot(
        root,
        task_limit=10,
        now=datetime(2026, 7, 19, 12, 0, tzinfo=timezone.utc),
    )

    assert snapshot["summary"]["registered_workers"] == 251
    assert snapshot["summary"]["active_workers"] == 1
    assert snapshot["summary"]["historical_worker_records"] == 250
    assert [worker["id"] for worker in snapshot["workers"]] == [active["id"]]
    assert snapshot["running_tasks"][0]["id"] == "queue-running"
    assert snapshot["running_tasks"][0]["display_name"] == "slack_ingest_watcher"


def test_fabric_snapshot_rejects_missing_state_database(tmp_path: Path) -> None:
    root = _root(tmp_path)
    apply_queue_mode(root, "execution_fabric", dry_run=False)
    db.default_db_path(root).unlink()

    with pytest.raises(RuntimeError, match="state database is missing"):
        build_runtime_snapshot(root)


def test_fabric_snapshot_rejects_corrupt_state_database(tmp_path: Path) -> None:
    root = _root(tmp_path)
    apply_queue_mode(root, "execution_fabric", dry_run=False)
    db.default_db_path(root).write_bytes(b"not a sqlite database")

    with pytest.raises(RuntimeError, match="state database is unreadable"):
        build_runtime_snapshot(root)


def test_fabric_snapshot_rejects_pre_migration_state_database(tmp_path: Path) -> None:
    root = _root(tmp_path)
    apply_queue_mode(root, "execution_fabric", dry_run=False)
    db.default_db_path(root).unlink()
    conn = sqlite3.connect(db.default_db_path(root))
    conn.execute("CREATE TABLE legacy_queue (id TEXT PRIMARY KEY)")
    conn.close()

    with pytest.raises(RuntimeError, match="missing required tables"):
        build_runtime_snapshot(root)


def test_fabric_snapshot_uses_one_sqlite_read_transaction_during_concurrent_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _root(tmp_path)
    apply_queue_mode(root, "execution_fabric", dry_run=False)
    runtime_ops.append_run_queue_item(
        root,
        {"id": "snapshot-race", "kind": "manual", "status": "queued", "execution_target": "codex_harness"},
    )
    wrote = False

    def write_after_task_read(stage: str) -> None:
        nonlocal wrote
        if stage != "fabric_tasks" or wrote:
            return
        wrote = True
        conn = db.connect(db.default_db_path(root))
        try:
            conn.execute(
                "UPDATE run_queue SET status = 'done', updated_at = '2026-07-18T12:00:00Z' WHERE id = 'snapshot-race'"
            )
        finally:
            conn.close()

    monkeypatch.setattr(runtime_snapshot, "_snapshot_read_hook", write_after_task_read)
    snapshot = build_runtime_snapshot(root, task_limit=None)

    task = next(item for item in snapshot["tasks"] if item["id"] == "snapshot-race")
    queue = next(item for item in snapshot["queues"] if item["queue_name"] == "codex")
    assert snapshot["consistency"] == "sqlite_read_transaction"
    assert task["status"] == "queued"
    assert queue["statuses"]["queued"] == sum(
        item["status"] == "queued" and item["queue_name"] == "codex" for item in snapshot["tasks"]
    )
    conn = db.connect(db.default_db_path(root))
    try:
        assert conn.execute("SELECT status FROM run_queue WHERE id = 'snapshot-race'").fetchone()[0] == "done"
    finally:
        conn.close()


def test_snapshot_receipt_writes_use_unique_atomic_siblings(tmp_path: Path) -> None:
    target = tmp_path / "same-receipt.json"
    errors: list[Exception] = []

    def writer(index: int) -> None:
        try:
            write_runtime_snapshot(target, {"writer": index})
        except Exception as exc:  # pragma: no cover - asserted below
            errors.append(exc)

    threads = [threading.Thread(target=writer, args=(index,)) for index in range(12)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    assert json.loads(target.read_text(encoding="utf-8"))["writer"] in range(12)
    assert list(tmp_path.glob(".same-receipt.json.*.tmp")) == []


def test_fabric_snapshot_projects_only_the_sql_limited_task_sample(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _root(tmp_path)
    apply_queue_mode(root, "execution_fabric", dry_run=False)
    conn = db.connect(db.default_db_path(root))
    try:
        for index in range(75):
            fabric.enqueue_task(
                conn,
                queue_name="codex",
                worker_pool="codex_workers",
                kind="sample",
                id=f"sample-{index:03d}",
            )
    finally:
        conn.close()
    projected = 0
    original = runtime_snapshot._project_task

    def count_projection(item: dict[str, object], *, queue_mode: str) -> dict[str, object]:
        nonlocal projected
        projected += 1
        return original(item, queue_mode=queue_mode)

    monkeypatch.setattr(runtime_snapshot, "_project_task", count_projection)
    snapshot = build_runtime_snapshot(root, queue_name="codex", statuses=["queued"], task_limit=5)

    assert snapshot["summary"]["total_records"] == 76
    assert snapshot["filters"]["matching_tasks"] == 75
    assert snapshot["filters"]["displayed_tasks"] == 5
    assert projected == 5


def test_cli_runtime_snapshot_supports_filters_json_and_receipt(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = _root(tmp_path)
    receipt = tmp_path / "runtime-snapshot.json"

    assert main(
        [
            "runtime",
            "snapshot",
            "--root",
            str(root),
            "--status",
            "queued",
            "--limit",
            "1",
            "--output",
            str(receipt),
            "--json",
        ]
    ) == 0
    result = json.loads(capsys.readouterr().out)

    assert result["schema_version"] == "agentic-os-runtime-snapshot/v1"
    assert result["filters"]["displayed_tasks"] == 1
    assert result["receipt_path"] == str(receipt)
    assert json.loads(receipt.read_text(encoding="utf-8"))["captured_at"] == result["captured_at"]


def test_apply_imports_legacy_queue_reads_back_and_rolls_back(tmp_path: Path) -> None:
    root = _root(tmp_path)

    applied = apply_queue_mode(root, "execution_fabric", dry_run=False)
    assert applied["queue_mode"] == "execution_fabric"
    assert applied["mode_source"] == "explicit"
    assert applied["import_receipt"]["processed"] == 1
    assert applied["metrics"]["queue_count"] == 5
    assert applied["metrics"]["worker_pool_count"] == 5
    assert applied["metrics"]["global_max_running"] == 6
    assert applied["metrics"]["reserved_interactive_slots"] == 1
    assert applied["metrics"]["max_interactive_running"] == 2
    assert applied["metrics"]["background_max_running"] == 5

    conn = db.connect(db.default_db_path(root))
    try:
        assert db.schema_version(conn) == 5
        assert conn.execute("SELECT COUNT(*) FROM run_queue WHERE id = 'legacy-1'").fetchone()[0] == 1
        assert {row[0] for row in conn.execute("SELECT name FROM execution_queues")} == {
            "codex",
            "claude",
            "pr_reviews",
            "los_environment",
            "non_llm",
        }
        assert {row[0] for row in conn.execute("SELECT name FROM worker_pools")} == {
            "codex_workers",
            "claude_workers",
            "pr_reviewers",
            "los_environment_workers",
            "non_llm_workers",
        }
        assert conn.execute("SELECT queue_name FROM run_queue WHERE id = 'legacy-1'").fetchone()[0] == "non_llm"
        assert conn.execute("SELECT max_concurrency FROM execution_limits WHERE scope = 'global' AND key = '*'").fetchone()[0] == 5
    finally:
        conn.close()

    dry_rollback = rollback_queue_mode(root)
    assert dry_rollback["target_mode"] == "filesystem"
    assert queue_mode_status(root)["queue_mode"] == "execution_fabric"

    rolled_back = rollback_queue_mode(root, dry_run=False)
    assert rolled_back["queue_mode"] == "filesystem"


def test_active_lease_blocks_mode_switch_and_rollback(tmp_path: Path) -> None:
    root = _root(tmp_path)
    apply_queue_mode(root, "execution_fabric", dry_run=False)
    conn = db.connect(db.default_db_path(root))
    try:
        worker = fabric.register_worker(conn, "worker-a", pool_name="non_llm_workers")
        fabric.enqueue_task(conn, queue_name="non_llm", worker_pool="non_llm_workers", kind="manual")
        assert fabric.claim_next(conn, worker_id="worker-a", worker_token=worker["lease_token"]) is not None
    finally:
        conn.close()

    plan = plan_queue_mode(root, "filesystem")
    assert plan["ready"] is False
    assert plan["active_lease_count"] == 1
    with pytest.raises(RuntimeBackendError, match="active execution lease"):
        rollback_queue_mode(root, dry_run=False)


def test_filesystem_running_dispatch_blocks_cutover(tmp_path: Path) -> None:
    root = _root(tmp_path)
    queue_path = root / "harness/shared_factory/00-control-plane/run-queue.yml"
    queue = yaml.safe_load(queue_path.read_text(encoding="utf-8"))
    queue["items"][0]["status"] = "running"
    queue_path.write_text(yaml.safe_dump(queue, sort_keys=False), encoding="utf-8")

    plan = plan_queue_mode(root, "execution_fabric")
    assert plan["ready"] is False
    assert plan["filesystem_running_count"] == 1


def test_rollback_blocks_unprojected_queued_fabric_work(tmp_path: Path) -> None:
    root = _root(tmp_path)
    apply_queue_mode(root, "execution_fabric", dry_run=False)
    conn = db.connect(db.default_db_path(root))
    try:
        fabric.enqueue_task(conn, queue_name="non_llm", worker_pool="non_llm_workers", kind="manual")
    finally:
        conn.close()

    plan = plan_queue_mode(root, "filesystem")
    assert plan["ready"] is False
    assert plan["filesystem_projection_blocker_count"] == 1
    with pytest.raises(RuntimeBackendError, match="not safely projected"):
        rollback_queue_mode(root, dry_run=False)


def test_rollback_blocks_status_drift_for_imported_tasks(tmp_path: Path) -> None:
    root = _root(tmp_path)
    apply_queue_mode(root, "execution_fabric", dry_run=False)
    conn = db.connect(db.default_db_path(root))
    try:
        state_queue.update_status(conn, "legacy-1", "done", finished_at="2026-01-01T00:01:00Z")
    finally:
        conn.close()

    plan = plan_queue_mode(root, "filesystem")
    assert plan["ready"] is False
    assert plan["filesystem_projection_blocker_sample"][0]["projection_issue"] == "status_drift"


def test_activation_blocks_and_reconciles_stale_nonterminal_database_state(tmp_path: Path) -> None:
    root = _root(tmp_path)
    apply_queue_mode(root, "execution_fabric", dry_run=False)
    rollback_queue_mode(root, dry_run=False)

    conn = db.connect(db.default_db_path(root))
    try:
        stale = fabric.enqueue_task(
            conn,
            queue_name="non_llm",
            worker_pool="non_llm_workers",
            kind="manual",
        )
    finally:
        conn.close()

    activation = plan_queue_mode(root, "execution_fabric")
    assert activation["ready"] is False
    assert activation["filesystem_projection_blocker_count"] == 1
    assert activation["filesystem_projection_blocker_sample"][0]["id"] == stale["id"]
    assert activation["filesystem_projection_blocker_sample"][0]["projection_issue"] == "missing_nonterminal_task"
    with pytest.raises(RuntimeBackendError, match="cannot be safely activated"):
        apply_queue_mode(root, "execution_fabric", dry_run=False)

    dry_reconcile = plan_execution_state_reconciliation(root)
    assert dry_reconcile["ready"] is True
    assert dry_reconcile["reconciliation_count"] == 1
    assert dry_reconcile["reconciliation_counts"] == {"missing_nonterminal_task": 1}

    applied = reconcile_execution_state(root, dry_run=False)
    assert applied["applied"] is True
    assert applied["cancelled_missing_nonterminal"] == 1
    receipt_path = Path(applied["receipt"])
    assert receipt_path.is_file()
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert Path(receipt["before"]).is_file()
    assert Path(receipt["before"]).stat().st_mode & 0o777 == 0o600

    conn = db.connect(db.default_db_path(root))
    try:
        row = conn.execute(
            "SELECT status, blocked_reason FROM run_queue WHERE id = ?",
            (stale["id"],),
        ).fetchone()
        assert tuple(row) == (
            "cancelled",
            "reconciled: absent from authoritative filesystem queue",
        )
    finally:
        conn.close()

    activation = plan_queue_mode(root, "execution_fabric")
    assert activation["ready"] is True
    switched = apply_queue_mode(root, "execution_fabric", dry_run=False)
    assert switched["queue_mode"] == "execution_fabric"
    assert sum(queue["statuses"].get("queued", 0) for queue in switched["metrics"]["queues"]) == 1


def test_queue_mode_reconcile_cli_is_dry_run_first(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = _root(tmp_path)
    apply_queue_mode(root, "execution_fabric", dry_run=False)
    rollback_queue_mode(root, dry_run=False)
    conn = db.connect(db.default_db_path(root))
    try:
        fabric.enqueue_task(conn, queue_name="non_llm", worker_pool="non_llm_workers", kind="manual")
    finally:
        conn.close()

    assert main(["runtime", "queue-mode", "reconcile", "--root", str(root), "--json"]) == 0
    dry_run = json.loads(capsys.readouterr().out)
    assert dry_run["dry_run"] is True
    assert dry_run["reconciliation_count"] == 1

    assert main(
        ["runtime", "queue-mode", "reconcile", "--root", str(root), "--apply", "--json"]
    ) == 0
    applied = json.loads(capsys.readouterr().out)
    assert applied["applied"] is True
    assert plan_queue_mode(root, "execution_fabric")["ready"] is True


def test_named_queue_pool_and_worker_capacity_are_transactional() -> None:
    conn = db.connect(":memory:")
    try:
        fabric.configure_queue(conn, "llm", max_concurrency=1)
        fabric.configure_worker_pool(
            conn,
            "codex",
            queue_name="llm",
            max_workers=1,
            max_concurrency=1,
            provider="openai",
        )
        worker_a = fabric.register_worker(conn, "worker-a", pool_name="codex")
        worker_b = fabric.register_worker(conn, "worker-b", pool_name="codex")
        first = fabric.enqueue_task(conn, queue_name="llm", worker_pool="codex", kind="manual", priority=10)
        second = fabric.enqueue_task(conn, queue_name="llm", worker_pool="codex", kind="manual")

        claimed = fabric.claim_next(conn, worker_id="worker-a", worker_token=worker_a["lease_token"])
        assert claimed is not None and claimed["id"] == first["id"]
        assert fabric.claim_next(conn, worker_id="worker-b", worker_token=worker_b["lease_token"]) is None

        with pytest.raises(fabric.ExecutionFabricError, match="does not own"):
            fabric.complete_task(
                conn,
                first["id"],
                worker_id="worker-b",
                worker_token=worker_b["lease_token"],
                lease_token=claimed["lease_token"],
            )
        fabric.complete_task(
            conn,
            first["id"],
            worker_id="worker-a",
            worker_token=worker_a["lease_token"],
            lease_token=claimed["lease_token"],
        )
        claimed_second = fabric.claim_next(conn, worker_id="worker-b", worker_token=worker_b["lease_token"])
        assert claimed_second is not None and claimed_second["id"] == second["id"]
    finally:
        conn.close()


def test_named_queue_ages_old_work_ahead_of_fresh_high_priority_work() -> None:
    conn = db.connect(":memory:")
    try:
        fabric.configure_queue(conn, "non_llm", max_concurrency=1)
        fabric.configure_worker_pool(
            conn,
            "non_llm_workers",
            queue_name="non_llm",
            max_workers=1,
            max_concurrency=1,
        )
        worker = fabric.register_worker(conn, "worker-a", pool_name="non_llm_workers")
        fresh_high = fabric.enqueue_task(
            conn,
            queue_name="non_llm",
            worker_pool="non_llm_workers",
            kind="schedule",
            id="fresh-high",
            priority=100,
        )
        aged_low = fabric.enqueue_task(
            conn,
            queue_name="non_llm",
            worker_pool="non_llm_workers",
            kind="schedule",
            id="aged-low",
            priority=0,
            created_at="2000-01-01T00:00:00Z",
        )

        claimed = fabric.claim_next(conn, worker_id="worker-a", worker_token=worker["lease_token"])

        assert claimed is not None
        assert claimed["id"] == aged_low["id"]
        assert state_queue.get(conn, fresh_high["id"])["status"] == "queued"
    finally:
        conn.close()


def test_global_and_provider_caps_keep_work_queued() -> None:
    conn = db.connect(":memory:")
    try:
        for queue_name in ("codex-a", "codex-b"):
            fabric.configure_queue(conn, queue_name, max_concurrency=4)
        fabric.configure_worker_pool(
            conn, "codex-a-workers", queue_name="codex-a", max_workers=2, max_concurrency=4, provider="codex"
        )
        fabric.configure_worker_pool(
            conn, "codex-b-workers", queue_name="codex-b", max_workers=2, max_concurrency=4, provider="codex"
        )
        fabric.configure_limit(conn, scope="global", key="*", max_concurrency=2)
        fabric.configure_limit(conn, scope="provider", key="codex", max_concurrency=1)
        worker_a = fabric.register_worker(conn, "worker-a", pool_name="codex-a-workers")
        worker_b = fabric.register_worker(conn, "worker-b", pool_name="codex-b-workers")
        fabric.enqueue_task(conn, queue_name="codex-a", worker_pool="codex-a-workers", kind="manual")
        waiting = fabric.enqueue_task(conn, queue_name="codex-b", worker_pool="codex-b-workers", kind="manual")

        assert fabric.claim_next(conn, worker_id="worker-a", worker_token=worker_a["lease_token"]) is not None
        assert fabric.claim_next(conn, worker_id="worker-b", worker_token=worker_b["lease_token"]) is None
        assert state_queue.get(conn, waiting["id"])["status"] == "queued"
    finally:
        conn.close()


def test_heartbeat_retry_dead_letter_and_cancel() -> None:
    conn = db.connect(":memory:")
    try:
        fabric.configure_queue(conn, "llm", max_concurrency=2)
        fabric.configure_queue(conn, "dead", max_concurrency=1)
        fabric.configure_worker_pool(conn, "codex", queue_name="llm", max_workers=1, max_concurrency=2)
        worker = fabric.register_worker(
            conn,
            "worker-a",
            pool_name="codex",
            capacity=2,
            lease_seconds=60,
            now="2026-01-01T00:00:00Z",
        )
        doomed = fabric.enqueue_task(
            conn,
            queue_name="llm",
            worker_pool="codex",
            kind="manual",
            max_attempts=1,
            dead_letter_queue="dead",
        )
        claimed = fabric.claim_next(
            conn,
            worker_id="worker-a",
            worker_token=worker["lease_token"],
            now="2026-01-01T00:00:10Z",
        )
        assert claimed is not None
        heartbeat = fabric.heartbeat_worker(
            conn,
            "worker-a",
            worker_token=worker["lease_token"],
            now="2026-01-01T00:00:20Z",
        )
        assert heartbeat["heartbeat_at"] == "2026-01-01T00:00:20Z"

        dead = fabric.retry_task(
            conn,
            doomed["id"],
            worker_id="worker-a",
            worker_token=worker["lease_token"],
            lease_token=claimed["lease_token"],
            error="provider unavailable",
            now="2026-01-01T00:00:30Z",
        )
        assert dead["status"] == "dead-letter"
        assert dead["queue_name"] == "dead"

        recoverable = fabric.enqueue_task(
            conn,
            queue_name="llm",
            worker_pool="codex",
            kind="manual",
            max_attempts=2,
        )
        assert fabric.claim_next(
            conn,
            worker_id="worker-a",
            worker_token=worker["lease_token"],
            lease_seconds=10,
            now="2026-01-01T00:00:40Z",
        ) is not None
        recovery = fabric.recover_expired_leases(conn, now="2026-01-01T00:06:00Z")
        assert recovery["recovered"] == [recoverable["id"]]
        assert recovery["expired_workers"] == ["worker-a"]
        recovered = state_queue.get(conn, recoverable["id"])
        assert recovered is not None
        assert recovered["due_at"] == "2026-01-01T00:07:00Z"

        waiting = fabric.enqueue_task(conn, queue_name="llm", worker_pool="codex", kind="manual")
        cancelled = fabric.cancel_task(conn, waiting["id"], reason="operator cancelled")
        assert cancelled["status"] == "cancelled"
        assert cancelled["error"] == "operator cancelled"
    finally:
        conn.close()


def test_expired_lease_recovery_honors_backoff_and_dead_letters_exhausted_task() -> None:
    conn = db.connect(":memory:")
    try:
        fabric.configure_queue(conn, "llm", max_concurrency=2)
        fabric.configure_queue(conn, "dead", max_concurrency=1)
        fabric.configure_worker_pool(conn, "codex", queue_name="llm", max_workers=2, max_concurrency=2)
        first_worker = fabric.register_worker(
            conn, "worker-a", pool_name="codex", lease_seconds=60, now="2026-01-01T00:00:00Z"
        )
        delayed = fabric.enqueue_task(
            conn,
            queue_name="llm",
            worker_pool="codex",
            kind="manual",
            max_attempts=3,
            payload={"retry_policy": {"backoff_seconds": 15}},
        )
        assert fabric.claim_next(
            conn,
            worker_id="worker-a",
            worker_token=first_worker["lease_token"],
            lease_seconds=10,
            now="2026-01-01T00:00:01Z",
        ) is not None

        second_worker = fabric.register_worker(
            conn, "worker-b", pool_name="codex", lease_seconds=60, now="2026-01-01T00:00:02Z"
        )
        doomed = fabric.enqueue_task(
            conn,
            queue_name="llm",
            worker_pool="codex",
            kind="manual",
            max_attempts=1,
            dead_letter_queue="dead",
        )
        assert fabric.claim_next(
            conn,
            worker_id="worker-b",
            worker_token=second_worker["lease_token"],
            lease_seconds=10,
            now="2026-01-01T00:00:02Z",
            item_id=doomed["id"],
        ) is not None

        recovery = fabric.recover_expired_leases(conn, now="2026-01-01T00:00:20Z")
        assert recovery["recovered"] == [delayed["id"]]
        assert recovery["dead_lettered"] == [doomed["id"]]
        recovered = state_queue.get(conn, delayed["id"])
        dead = state_queue.get(conn, doomed["id"])
        assert recovered is not None and recovered["due_at"] == "2026-01-01T00:00:35Z"
        assert dead is not None
        assert dead["status"] == "dead-letter"
        assert dead["queue_name"] == "dead"
        assert dead["finished_at"] == "2026-01-01T00:00:20Z"
    finally:
        conn.close()


def test_expired_and_stale_leases_are_fenced() -> None:
    conn = db.connect(":memory:")
    try:
        fabric.configure_queue(conn, "llm", max_concurrency=1)
        fabric.configure_worker_pool(conn, "codex", queue_name="llm", max_workers=1, max_concurrency=1)
        first_worker = fabric.register_worker(
            conn,
            "worker-a",
            pool_name="codex",
            lease_seconds=20,
            now="2026-01-01T00:00:00Z",
        )
        task = fabric.enqueue_task(conn, queue_name="llm", worker_pool="codex", kind="manual")
        first_claim = fabric.claim_next(
            conn,
            worker_id="worker-a",
            worker_token=first_worker["lease_token"],
            lease_seconds=10,
            now="2026-01-01T00:00:05Z",
        )
        assert first_claim is not None
        with pytest.raises(fabric.ExecutionFabricError, match="cannot be re-registered"):
            fabric.register_worker(
                conn,
                "worker-a",
                pool_name="codex",
                now="2026-01-01T00:00:06Z",
            )

        with pytest.raises(fabric.ExecutionFabricError, match="inactive or fenced"):
            fabric.heartbeat_worker(
                conn,
                "worker-a",
                worker_token=first_worker["lease_token"],
                now="2026-01-01T00:00:21Z",
            )
        with pytest.raises(fabric.ExecutionFabricError, match="active fenced lease"):
            fabric.complete_task(
                conn,
                task["id"],
                worker_id="worker-a",
                worker_token=first_worker["lease_token"],
                lease_token=first_claim["lease_token"],
                now="2026-01-01T00:00:21Z",
            )

        fabric.recover_expired_leases(conn, now="2026-01-01T00:00:21Z")
        second_worker = fabric.register_worker(
            conn,
            "worker-a",
            pool_name="codex",
            lease_seconds=180,
            now="2026-01-01T00:00:22Z",
        )
        second_claim = fabric.claim_next(
            conn,
            worker_id="worker-a",
            worker_token=second_worker["lease_token"],
            now="2026-01-01T00:01:21Z",
        )
        assert second_claim is not None
        assert second_claim["lease_token"] != first_claim["lease_token"]
        with pytest.raises(fabric.ExecutionFabricError, match="active fenced lease"):
            fabric.complete_task(
                conn,
                task["id"],
                worker_id="worker-a",
                worker_token=first_worker["lease_token"],
                lease_token=second_claim["lease_token"],
                now="2026-01-01T00:01:22Z",
            )
        with pytest.raises(fabric.ExecutionFabricError, match="active fenced lease"):
            fabric.complete_task(
                conn,
                task["id"],
                worker_id="worker-a",
                worker_token=second_worker["lease_token"],
                lease_token=first_claim["lease_token"],
                now="2026-01-01T00:01:22Z",
            )
        completed = fabric.complete_task(
            conn,
            task["id"],
            worker_id="worker-a",
            worker_token=second_worker["lease_token"],
            lease_token=second_claim["lease_token"],
            now="2026-01-01T00:01:22Z",
        )
        assert completed["status"] == "done"
    finally:
        conn.close()


def test_retry_is_fenced_delayed_and_not_claimable_before_due() -> None:
    conn = db.connect(":memory:")
    try:
        fabric.configure_queue(conn, "llm", max_concurrency=1)
        fabric.configure_worker_pool(conn, "codex", queue_name="llm", max_workers=1, max_concurrency=1)
        worker = fabric.register_worker(
            conn,
            "worker-a",
            pool_name="codex",
            lease_seconds=600,
            now="2026-01-01T00:00:00Z",
        )
        task = fabric.enqueue_task(
            conn,
            queue_name="llm",
            worker_pool="codex",
            kind="manual",
            max_attempts=2,
        )
        claimed = fabric.claim_next(
            conn,
            worker_id="worker-a",
            worker_token=worker["lease_token"],
            lease_seconds=600,
            now="2026-01-01T00:00:01Z",
        )
        assert claimed is not None
        with pytest.raises(fabric.ExecutionFabricError, match="active fenced lease"):
            fabric.retry_task(
                conn,
                task["id"],
                worker_id="worker-a",
                worker_token="stale-worker-token",
                lease_token=claimed["lease_token"],
                now="2026-01-01T00:00:02Z",
            )
        retried = fabric.retry_task(
            conn,
            task["id"],
            worker_id="worker-a",
            worker_token=worker["lease_token"],
            lease_token=claimed["lease_token"],
            backoff_seconds=60,
            now="2026-01-01T00:00:02Z",
        )
        assert retried["status"] == "queued"
        assert retried["due_at"] == "2026-01-01T00:01:02Z"
        assert fabric.claim_next(
            conn,
            worker_id="worker-a",
            worker_token=worker["lease_token"],
            now="2026-01-01T00:01:01Z",
        ) is None
        second_claim = fabric.claim_next(
            conn,
            worker_id="worker-a",
            worker_token=worker["lease_token"],
            now="2026-01-01T00:01:02Z",
        )
        assert second_claim is not None
        dead = fabric.retry_task(
            conn,
            task["id"],
            worker_id="worker-a",
            worker_token=worker["lease_token"],
            lease_token=second_claim["lease_token"],
            backoff_seconds=120,
            now="2026-01-01T00:01:03Z",
        )
        assert dead["status"] == "dead-letter"
        assert dead["due_at"] is None
        assert dead["finished_at"] == "2026-01-01T00:01:03Z"
    finally:
        conn.close()


def test_cli_apply_is_dry_run_by_default(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = _root(tmp_path)
    assert main(["runtime", "queue-mode", "apply", "execution_fabric", "--root", str(root)]) == 0
    output = yaml.safe_load(capsys.readouterr().out)
    assert output["dry_run"] is True
    assert queue_mode_status(root)["queue_mode"] == "filesystem"

    assert main(
        ["runtime", "queue-mode", "apply", "execution_fabric", "--root", str(root), "--apply"]
    ) == 0
    capsys.readouterr()
    assert queue_mode_status(root)["queue_mode"] == "execution_fabric"


def test_runtime_append_uses_only_selected_execution_fabric_writer(tmp_path: Path) -> None:
    root = _root(tmp_path)
    yaml_queue = root / "harness/shared_factory/00-control-plane/run-queue.yml"
    apply_queue_mode(root, "execution_fabric", dry_run=False)
    before = yaml_queue.read_bytes()

    result = runtime_ops.append_run_queue_item(
        root,
        {
            "id": "fabric-only",
            "kind": "manual",
            "status": "queued",
            "approval_state": "not_required",
            "execution_target": "script",
            "command": "true",
        },
    )

    assert result["created"] is True
    assert result["run_queue"].endswith("state.db")
    assert yaml_queue.read_bytes() == before
    conn = db.connect(db.default_db_path(root))
    try:
        assert conn.execute("SELECT COUNT(*) FROM run_queue WHERE id = 'fabric-only'").fetchone()[0] == 1
    finally:
        conn.close()


def test_runtime_dispatch_claims_and_completes_in_execution_fabric(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _root(tmp_path)
    registry_path = root / "harness/shared_factory/00-control-plane/runtime-registry.yml"
    registry = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    registry["execution_targets"] = [{"id": "script", "status": "active"}]
    registry_path.write_text(yaml.safe_dump(registry, sort_keys=False), encoding="utf-8")
    apply_queue_mode(root, "execution_fabric", dry_run=False)
    runtime_ops.append_run_queue_item(
        root,
        {
            "id": "dispatch-me",
            "kind": "manual",
            "status": "queued",
            "approval_state": "not_required",
            "execution_target": "script",
            "command": "true",
        },
    )
    monkeypatch.setattr(
        runtime_ops,
        "_run_local_script",
        lambda *_args, **_kwargs: {
            "supported": True,
            "ok": True,
            "command": "true",
            "errors": [],
            "warnings": [],
            "external_effect": "test command executed",
        },
    )

    result = runtime_ops.runtime_run_next(root, dry_run=False, item_id="dispatch-me")

    assert result["status"] == "done"
    assert result["queue_backend"] == "execution_fabric"
    assert result["queue_item"]["status"] == "done"
    assert result["queue_item"]["lease_owner"] is None
    assert result["queue_item"]["dispatch_log"].endswith("run-log.yml")
    assert queue_mode_status(root)["metrics"]["live_worker_count"] == 0


def test_runtime_dispatch_queue_filter_keeps_other_queues_queued(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _root(tmp_path)
    registry_path = root / "harness/shared_factory/00-control-plane/runtime-registry.yml"
    registry = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    registry["execution_targets"] = [{"id": "script", "status": "active"}]
    registry_path.write_text(yaml.safe_dump(registry, sort_keys=False), encoding="utf-8")
    apply_queue_mode(root, "execution_fabric", dry_run=False)
    conn = db.connect(db.default_db_path(root))
    try:
        fabric.configure_queue(conn, "codex", max_concurrency=1)
        fabric.configure_worker_pool(conn, "codex_workers", queue_name="codex", max_workers=1, max_concurrency=1)
        fabric.configure_queue(conn, "non_llm", max_concurrency=1)
        fabric.configure_worker_pool(conn, "non_llm_workers", queue_name="non_llm", max_workers=1, max_concurrency=1)
    finally:
        conn.close()
    for item_id, queue_name, worker_pool in (("codex-item", "codex", "codex_workers"), ("other-item", "non_llm", "non_llm_workers")):
        runtime_ops.append_run_queue_item(root, {"id": item_id, "kind": "manual", "status": "queued", "approval_state": "not_required", "execution_target": "script", "command": "true", "queue_name": queue_name, "worker_pool": worker_pool})
    monkeypatch.setattr(runtime_ops, "_run_local_script", lambda *_args, **_kwargs: {"supported": True, "ok": True, "command": "true", "errors": [], "warnings": [], "external_effect": "test command executed"})
    result = runtime_ops.runtime_run_next(root, dry_run=False, queue_name="codex", worker_pool="codex_workers")
    assert result["queue_item"]["id"] == "codex-item"
    conn = db.connect(db.default_db_path(root))
    try:
        assert state_queue.get(conn, "other-item")["status"] == "queued"
    finally:
        conn.close()


def test_runtime_dispatch_blocks_divergent_pool_item_instead_of_reporting_idle(
    tmp_path: Path,
) -> None:
    root = _root(tmp_path)
    apply_queue_mode(root, "execution_fabric", dry_run=False)
    conn = db.connect(db.default_db_path(root))
    try:
        state_queue.enqueue(
            conn,
            id="misrouted-item",
            kind="manual",
            approval_state="not_required",
            execution_target="script",
            queue_name="codex",
            worker_pool="non_llm_workers",
        )
    finally:
        conn.close()

    result = runtime_ops.runtime_run_next(
        root,
        dry_run=False,
        queue_name="codex",
        worker_pool="codex_workers",
    )

    assert result["status"] == "blocked"
    assert result["queue_item"]["id"] == "misrouted-item"
    assert result["blocked_reason"] == (
        "queue item worker pool does not match the requested queue: "
        "non_llm_workers != codex_workers"
    )
    conn = db.connect(db.default_db_path(root))
    try:
        item = state_queue.get(conn, "misrouted-item")
        assert item is not None
        assert item["status"] == "blocked"
        assert item["blocked_reason"] == result["blocked_reason"]
    finally:
        conn.close()


def _local_runtime_work_args(root: Path, queues: list[str]) -> argparse.Namespace:
    return argparse.Namespace(
        root=str(root),
        host_id=None,
        queue=queues,
        max_concurrency=None,
        heartbeat_seconds=None,
        worker_id="test-worker",
        bootstrap_id=None,
        capability=[],
        apply=True,
        once=True,
        max_tasks=None,
        json=True,
    )


def _stub_local_runtime_work_dependencies(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, object]]:
    emitted: list[dict[str, object]] = []
    fabric_value = {
        "execution_fabric": {
            "queues": [
                {"id": "codex", "enabled": True, "worker_pool": "codex_workers"},
                {"id": "non_llm", "enabled": True, "worker_pool": "non_llm_workers"},
            ]
        }
    }
    monkeypatch.setattr(
        runtime_cli,
        "resolve_remote_settings",
        lambda *_args, **_kwargs: SimpleNamespace(remote=False, public=lambda: {"mode": "local"}),
    )
    monkeypatch.setattr(runtime_cli, "resolve_execution_fabric_host_id", lambda *_args, **_kwargs: "test-host")
    monkeypatch.setattr(
        runtime_cli,
        "load_execution_fabric_config",
        lambda *_args, **_kwargs: SimpleNamespace(value=fabric_value),
    )
    monkeypatch.setattr(runtime_cli, "_configured_worker_defaults", lambda *_args, **_kwargs: (1, 15))
    monkeypatch.setattr(
        runtime_cli,
        "_print_structured",
        lambda payload, **_kwargs: emitted.append(payload),
    )
    return emitted


def test_runtime_work_once_skips_idle_queue_and_emits_queue_receipts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _root(tmp_path)
    emitted = _stub_local_runtime_work_dependencies(monkeypatch)
    calls: list[str] = []

    def _run_next(_root: str, *, queue_name: str, **_kwargs: object) -> dict[str, object]:
        calls.append(queue_name)
        if queue_name == "codex":
            return {"status": "idle"}
        return {"status": "done", "queue_item": {"queue_name": "non_llm"}}

    monkeypatch.setattr(runtime_cli, "runtime_run_next", _run_next)

    assert runtime_cli.handle_runtime_work(
        _local_runtime_work_args(root, ["codex", "non_llm"])
    ) == 0

    assert calls == ["codex", "non_llm"]
    assert emitted == [
        {
            "status": "stopped-local-degraded",
            "transport": {"mode": "local"},
            "worker_id": "test-worker",
            "results": [
                {"status": "idle", "requested_queue": "codex", "selected_queue": None},
                {
                    "status": "done",
                    "queue_item": {"queue_name": "non_llm"},
                    "requested_queue": "non_llm",
                    "selected_queue": "non_llm",
                },
            ],
        }
    ]


def test_runtime_work_rejects_unknown_queue_before_dispatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _root(tmp_path)
    _stub_local_runtime_work_dependencies(monkeypatch)
    calls: list[str] = []
    monkeypatch.setattr(
        runtime_cli,
        "runtime_run_next",
        lambda *_args, **_kwargs: calls.append("dispatched"),
    )

    with pytest.raises(ValueError, match="disabled or unknown queues: typo"):
        runtime_cli.handle_runtime_work(_local_runtime_work_args(root, ["codex", "typo"]))

    assert calls == []


def test_runtime_dispatch_retries_transient_failures_and_honors_nested_policy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _root(tmp_path)
    registry_path = root / "harness/shared_factory/00-control-plane/runtime-registry.yml"
    registry = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    registry["execution_targets"] = [{"id": "script", "status": "active"}]
    registry_path.write_text(yaml.safe_dump(registry, sort_keys=False), encoding="utf-8")
    apply_queue_mode(root, "execution_fabric", dry_run=False)
    runtime_ops.append_run_queue_item(
        root,
        {
            "id": "retry-transient",
            "kind": "manual",
            "status": "queued",
            "approval_state": "not_required",
            "execution_target": "script",
            "command": "provider-call",
            "retry_policy": {"max_attempts": 3, "backoff_seconds": 30},
        },
    )
    monkeypatch.setattr(
        runtime_ops,
        "_run_local_script",
        lambda *_args, **_kwargs: {
            "supported": True,
            "ok": False,
            "command": "provider-call",
            "returncode": 1,
            "stdout": "",
            "stderr": "provider returned 503 service unavailable",
            "errors": ["local script exited 1"],
            "warnings": [],
            "external_effect": "test provider failed",
        },
    )

    first = runtime_ops.runtime_run_next(root, dry_run=False, item_id="retry-transient")

    assert first["status"] == "queued"
    assert first["retry_scheduled"] is True
    assert first["failure_class"] == "provider_or_network"
    assert first["queue_item"]["attempts"] == 1
    assert first["queue_item"]["max_attempts"] == 3
    assert first["queue_item"]["due_at"]
    snapshot = build_runtime_snapshot(root, task_limit=None)
    assert snapshot["summary"]["retrying"] == 1
    assert snapshot["summary"]["delayed_retries"] == 1
    retry_queue = next(queue for queue in snapshot["queues"] if queue["queue_name"] == "non_llm")
    assert retry_queue["retrying"] == 1
    assert retry_queue["delayed_retries"] == 1
    assert "Retrying: 1 (1 delayed)" in format_runtime_snapshot(snapshot)

    conn = db.connect(db.default_db_path(root))
    try:
        conn.execute("UPDATE run_queue SET due_at = '2000-01-01T00:00:00Z' WHERE id = 'retry-transient'")
    finally:
        conn.close()
    second = runtime_ops.runtime_run_next(root, dry_run=False, item_id="retry-transient")
    assert second["status"] == "queued"
    assert second["queue_item"]["attempts"] == 2

    conn = db.connect(db.default_db_path(root))
    try:
        conn.execute("UPDATE run_queue SET due_at = '2000-01-01T00:00:00Z' WHERE id = 'retry-transient'")
    finally:
        conn.close()
    exhausted = runtime_ops.runtime_run_next(root, dry_run=False, item_id="retry-transient")
    assert exhausted["status"] == "dead-letter"
    assert exhausted["retry_scheduled"] is False
    assert exhausted["queue_item"]["attempts"] == 3
    assert exhausted["queue_item"]["finished_at"]


def test_runtime_dispatch_does_not_retry_deterministic_configuration_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _root(tmp_path)
    registry_path = root / "harness/shared_factory/00-control-plane/runtime-registry.yml"
    registry = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    registry["execution_targets"] = [{"id": "script", "status": "active"}]
    registry_path.write_text(yaml.safe_dump(registry, sort_keys=False), encoding="utf-8")
    apply_queue_mode(root, "execution_fabric", dry_run=False)
    runtime_ops.append_run_queue_item(
        root,
        {
            "id": "terminal-config",
            "kind": "manual",
            "status": "queued",
            "approval_state": "not_required",
            "execution_target": "script",
            "command": "missing-tool",
            "retry_policy": {"max_attempts": 5, "backoff_seconds": 1},
        },
    )
    monkeypatch.setattr(
        runtime_ops,
        "_run_local_script",
        lambda *_args, **_kwargs: {
            "supported": True,
            "ok": False,
            "command": "missing-tool",
            "errors": ["local script executable not found: missing-tool"],
            "warnings": [],
            "external_effect": "local script failed before execution",
        },
    )

    result = runtime_ops.runtime_run_next(root, dry_run=False, item_id="terminal-config")

    assert result["status"] == "failed"
    assert result["retry_scheduled"] is False
    assert result["failure_class"] == "configuration"
    assert result["queue_item"]["attempts"] == 1


@pytest.mark.parametrize(
    ("evidence", "failure_class"),
    [
        ("429 too many requests", "provider_or_network"),
        ("usage limit reached; try again later", "provider_or_network"),
        ("insufficient_quota", "provider_or_network"),
        ("provider overloaded with status 529", "provider_or_network"),
        ("connection reset by peer", "provider_or_network"),
    ],
)
def test_provider_usage_and_network_failures_are_retryable(evidence: str, failure_class: str) -> None:
    result = runtime_ops._execution_failure_class(
        {"ok": False, "errors": ["local script exited 1"], "stderr": evidence, "stdout": ""}
    )
    assert result == {"retryable": True, "failure_class": failure_class}


def test_transient_words_in_stdout_do_not_make_a_failure_retryable() -> None:
    result = runtime_ops._execution_failure_class(
        {
            "ok": False,
            "errors": ["local script exited 1"],
            "stderr": "",
            "stdout": "processed historical 503 errors; previous request timed out",
        }
    )
    assert result == {"retryable": False, "failure_class": "execution"}


def test_run_latest_does_not_skip_work_claimed_during_snapshot_race(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _root(tmp_path)
    apply_queue_mode(root, "execution_fabric", dry_run=False)
    for item_id, created_at in (
        ("older", "2026-01-01T00:00:00Z"),
        ("latest", "2026-01-01T00:01:00Z"),
    ):
        runtime_ops.append_run_queue_item(
            root,
            {
                "id": item_id,
                "kind": "schedule",
                "ref": "priority_job",
                "status": "queued",
                "approval_state": "not_required",
                "execution_target": "script",
                "command": "true",
                "created_at": created_at,
            },
        )

    @contextmanager
    def competing_claim(_root: Path, _mode: str):
        conn = db.connect(db.default_db_path(root))
        try:
            with db.transaction(conn):
                conn.execute(
                    """
                    UPDATE run_queue
                    SET status = 'running', lease_owner = 'other-dispatcher',
                        lease_until = '2099-01-01T00:00:00Z', lease_token = 'other-token'
                    WHERE id = 'older' AND status = 'queued'
                    """
                )
        finally:
            conn.close()
        yield

    monkeypatch.setattr(runtime_ops, "queue_backend_mutation_guard", competing_claim)
    monkeypatch.setattr(
        runtime_ops,
        "runtime_run_next",
        lambda *_args, **_kwargs: {"root": str(root), "status": "done", "queue_item": {"id": "latest"}},
    )

    result = runtime_ops.runtime_run_latest_by_ref(root, "priority_job", dry_run=False)

    conn = db.connect(db.default_db_path(root))
    try:
        older = state_queue.get(conn, "older")
    finally:
        conn.close()
    assert older is not None and older["status"] == "running"
    assert result["superseded_count"] == 0


def test_priority_fabric_work_is_deduplicated_without_serial_dispatch(tmp_path: Path) -> None:
    root = _root(tmp_path)
    apply_queue_mode(root, "execution_fabric", dry_run=False)
    for item_id, created_at in (
        ("priority-old", "2026-01-01T00:00:00Z"),
        ("priority-latest", "2026-01-01T00:01:00Z"),
    ):
        runtime_ops.append_run_queue_item(
            root,
            {
                "id": item_id,
                "kind": "schedule",
                "ref": "priority_job",
                "status": "queued",
                "approval_state": "not_required",
                "execution_target": "script",
                "command": "true",
                "created_at": created_at,
            },
        )

    result = runtime_ops.runtime_prepare_priority_ref(root, "priority_job", dry_run=False)
    items = {item["id"]: item for item in runtime_queue_items(root)}

    assert result["status"] == "prioritized"
    assert result["superseded_count"] == 1
    assert items["priority-old"]["status"] == "skipped"
    assert items["priority-latest"]["status"] == "queued"
    assert items["priority-latest"]["priority"] == 100


def test_priority_fabric_deduplication_preserves_self_heal_work(tmp_path: Path) -> None:
    root = _root(tmp_path)
    apply_queue_mode(root, "execution_fabric", dry_run=False)
    for item_id, created_at in (
        ("priority-old", "2026-01-01T00:00:00Z"),
        ("priority-latest", "2026-01-01T00:02:00Z"),
    ):
        runtime_ops.append_run_queue_item(
            root,
            {
                "id": item_id,
                "kind": "schedule",
                "ref": "queue_worker_health_report",
                "status": "queued",
                "approval_state": "not_required",
                "execution_target": "script",
                "command": "true",
                "created_at": created_at,
            },
        )
    runtime_ops.append_run_queue_item(
        root,
        {
            "id": "runtime-self-heal",
            "kind": "runtime_self_heal",
            "ref": "queue_worker_health_report",
            "status": "queued",
            "approval_state": "not_required",
            "execution_target": "codex_harness",
            "command": "true",
            "created_at": "2026-01-01T00:01:00Z",
        },
    )

    result = runtime_ops.runtime_prepare_priority_ref(
        root,
        "queue_worker_health_report",
        dry_run=False,
    )
    items = {item["id"]: item for item in runtime_queue_items(root)}

    assert result["status"] == "prioritized"
    assert result["superseded_count"] == 1
    assert items["priority-old"]["status"] == "skipped"
    assert items["priority-latest"]["status"] == "queued"
    assert items["runtime-self-heal"]["status"] == "queued"


def test_all_runtime_task_classes_route_to_managed_named_queues(tmp_path: Path) -> None:
    root = _root(tmp_path)
    apply_queue_mode(root, "execution_fabric", dry_run=False)
    for item_id, target, task_type in (
        ("codex-task", "codex_harness", None),
        ("claude-task", "claude_harness", None),
        ("script-task", "script", "script"),
    ):
        runtime_ops.append_run_queue_item(
            root,
            {
                "id": item_id,
                "kind": "manual",
                "status": "queued",
                "approval_state": "not_required",
                "execution_target": target,
                "task_type": task_type,
                "command": "true",
            },
        )

    routes = {item["id"]: (item["queue_name"], item["worker_pool"]) for item in runtime_queue_items(root)}
    assert routes["codex-task"] == ("codex", "codex_workers")
    assert routes["claude-task"] == ("claude", "claude_workers")
    assert routes["script-task"] == ("non_llm", "non_llm_workers")


def test_execution_mode_readers_ignore_stale_filesystem_projection(tmp_path: Path) -> None:
    root = _root(tmp_path)
    yaml_queue = root / "harness/shared_factory/00-control-plane/run-queue.yml"
    apply_queue_mode(root, "execution_fabric", dry_run=False)
    loaded = yaml.safe_load(yaml_queue.read_text(encoding="utf-8"))
    loaded["items"] = [{"id": "stale-only", "status": "queued"}]
    loaded["run_queue"] = loaded["items"]
    yaml_queue.write_text(yaml.safe_dump(loaded, sort_keys=False), encoding="utf-8")

    assert "stale-only" not in {item["id"] for item in runtime_queue_items(root)}


def test_named_queue_rejects_work_at_configured_depth_limit(tmp_path: Path) -> None:
    root = _root(tmp_path)
    apply_queue_mode(root, "execution_fabric", dry_run=False)
    conn = db.connect(db.default_db_path(root))
    try:
        fabric.configure_queue(conn, "non_llm", max_concurrency=4, metadata={"max_queued": 1})
        with pytest.raises(fabric.ExecutionFabricError, match="reached max_queued=1"):
            fabric.enqueue_task(conn, queue_name="non_llm", worker_pool="non_llm_workers", kind="manual")
    finally:
        conn.close()


def test_harness_queue_items_materialize_bounded_provider_workers(tmp_path: Path) -> None:
    root = _root(tmp_path)
    registry_path = root / "harness/shared_factory/00-control-plane/runtime-registry.yml"
    registry = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    registry["execution_targets"] = [
        {"id": "codex_harness", "status": "active"},
        {"id": "claude_harness", "status": "active"},
    ]
    registry_path.write_text(yaml.safe_dump(registry, sort_keys=False), encoding="utf-8")
    apply_queue_mode(root, "execution_fabric", dry_run=False)

    codex = runtime_ops.append_run_queue_item(
        root,
        {"id": "provider-codex", "kind": "workflow", "status": "queued", "approval_state": "not_required", "execution_target": "codex_harness"},
    )["queue_item"]
    claude = runtime_ops.append_run_queue_item(
        root,
        {"id": "provider-claude", "kind": "workflow", "status": "queued", "approval_state": "not_required", "execution_target": "claude_harness"},
    )["queue_item"]

    assert codex["queue_name"] == "codex"
    assert codex["worker_materialized"] is True
    assert codex["command"].startswith("codex exec --cd")
    assert "--ephemeral --json" in codex["command"]
    assert claude["queue_name"] == "claude"
    assert claude["command"].startswith("claude --print --output-format json --no-session-persistence")
    assert runtime_ops.runtime_run_next(root, dry_run=True, item_id="provider-codex")["status"] == "would-run"


def test_runtime_batch_runs_named_pools_concurrently_with_reserved_capacity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _root(tmp_path)
    registry_path = root / "harness/shared_factory/00-control-plane/runtime-registry.yml"
    registry = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    registry["execution_targets"] = [
        {"id": "script", "status": "active"},
        {"id": "codex_harness", "status": "active"},
        {"id": "claude_harness", "status": "active"},
    ]
    registry_path.write_text(yaml.safe_dump(registry, sort_keys=False), encoding="utf-8")
    apply_queue_mode(root, "execution_fabric", dry_run=False)

    for item_id, execution_target in (
        ("batch-codex-1", "codex_harness"),
        ("batch-codex-2", "codex_harness"),
        ("batch-claude-1", "claude_harness"),
        ("batch-claude-2", "claude_harness"),
        ("batch-script-1", "script"),
        ("batch-script-2", "script"),
    ):
        runtime_ops.append_run_queue_item(
            root,
            {
                "id": item_id,
                "kind": "manual",
                "status": "queued",
                "approval_state": "not_required",
                "execution_target": execution_target,
                "command": "true",
            },
        )

    lock = threading.Lock()
    active = 0
    maximum_active = 0

    def _bounded_probe(_root: Path, command: str, **_kwargs):
        nonlocal active, maximum_active
        with lock:
            active += 1
            maximum_active = max(maximum_active, active)
        time.sleep(0.1)
        with lock:
            active -= 1
        return {
            "supported": True,
            "ok": True,
            "command": command,
            "errors": [],
            "warnings": [],
            "external_effect": "concurrency probe",
        }

    monkeypatch.setattr(runtime_ops, "_run_local_script", _bounded_probe)
    result = runtime_ops.runtime_run_batch(root, dry_run=False)

    assert result["status"] == "batch-complete"
    assert result["dispatched_count"] == 5
    assert maximum_active == 5
    queued = [item for item in runtime_queue_items(root) if item["status"] == "queued"]
    assert [item["id"] for item in queued] == ["batch-script-2"]


def test_quiet_run_timeout_extends_execution_fabric_lease_budget(tmp_path: Path) -> None:
    root = _root(tmp_path)
    apply_queue_mode(root, "execution_fabric", dry_run=False)

    queued = runtime_ops.append_run_queue_item(
        root,
        {
            "id": "bounded-quiet-run",
            "kind": "schedule",
            "status": "queued",
            "approval_state": "not_required",
            "execution_target": "script",
            "command": "harness/bin/agentic-os-quiet-run start --timeout-minutes 20 -- /bin/true",
        },
    )["queue_item"]

    assert queued["timeout_seconds"] == 1260


def test_registered_watcher_timeout_extends_execution_fabric_lease_budget(tmp_path: Path) -> None:
    root = _root(tmp_path)
    watcher = root / "watchers/notion_work_intake"
    script = watcher / "scripts/watch.py"
    script.parent.mkdir(parents=True)
    script.write_text("print('ok')\n", encoding="utf-8")
    (watcher / "watcher.yml").write_text(
        "id: notion_work_intake\nharness_run_timeout_sec: 7200\nharness_run_outer_grace_sec: 30\n",
        encoding="utf-8",
    )
    apply_queue_mode(root, "execution_fabric", dry_run=False)

    queued = runtime_ops.append_run_queue_item(
        root,
        {
            "id": "bounded-watcher",
            "kind": "schedule",
            "status": "queued",
            "approval_state": "not_required",
            "execution_target": "script",
            "command": f"python3 {script} --once",
        },
    )["queue_item"]

    assert queued["timeout_seconds"] == 7290


def test_legacy_shell_wrapped_llm_work_routes_to_provider_pool(tmp_path: Path) -> None:
    root = _root(tmp_path)
    wrapper = root / "automations/run-codex-worker.sh"
    wrapper.parent.mkdir(parents=True)
    wrapper.write_text(
        "#!/usr/bin/env bash\nexec codex exec --skip-git-repo-check 'do the work'\n",
        encoding="utf-8",
    )
    apply_queue_mode(root, "execution_fabric", dry_run=False)

    queued = runtime_ops.append_run_queue_item(
        root,
        {
            "id": "legacy-codex-wrapper",
            "kind": "schedule",
            "status": "queued",
            "approval_state": "not_required",
            "execution_target": "script",
            "command": (
                "harness/bin/agentic-os-quiet-run start --timeout-minutes 20 -- "
                f"{wrapper}"
            ),
        },
    )["queue_item"]

    assert queued["execution_target"] == "codex_harness"
    assert queued["task_type"] == "llm.codex"
    assert queued["queue_name"] == "codex"
    assert queued["worker_pool"] == "codex_workers"
    assert queued["timeout_seconds"] == 1260
    assert queued["provider_inferred_from_command"] is True


def test_provider_inference_ignores_shell_comments(tmp_path: Path) -> None:
    root = _root(tmp_path)
    wrapper = root / "automations/deterministic.sh"
    wrapper.parent.mkdir(parents=True)
    wrapper.write_text(
        "#!/usr/bin/env bash\n# This worker must not invoke codex exec.\nexec /bin/true\n",
        encoding="utf-8",
    )
    apply_queue_mode(root, "execution_fabric", dry_run=False)

    queued = runtime_ops.append_run_queue_item(
        root,
        {
            "id": "deterministic-wrapper",
            "kind": "schedule",
            "status": "queued",
            "approval_state": "not_required",
            "execution_target": "script",
            "command": str(wrapper),
        },
    )["queue_item"]

    assert queued["queue_name"] == "non_llm"
    assert queued["worker_pool"] == "non_llm_workers"
    assert queued.get("provider_inferred_from_command") is None
