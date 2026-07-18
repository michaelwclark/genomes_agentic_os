from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import threading
import time

import pytest
import yaml

from genomes_agentic_os.cli import main
from genomes_agentic_os.runtime_backend import (
    RuntimeBackendError,
    apply_queue_mode,
    plan_queue_mode,
    queue_mode_status,
    rollback_queue_mode,
    runtime_queue_items,
)
from genomes_agentic_os import runtime_ops
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


def test_apply_imports_legacy_queue_reads_back_and_rolls_back(tmp_path: Path) -> None:
    root = _root(tmp_path)

    applied = apply_queue_mode(root, "execution_fabric", dry_run=False)
    assert applied["queue_mode"] == "execution_fabric"
    assert applied["mode_source"] == "explicit"
    assert applied["import_receipt"]["processed"] == 1
    assert applied["metrics"]["queue_count"] == 3
    assert applied["metrics"]["worker_pool_count"] == 3
    assert applied["metrics"]["global_max_running"] == 6
    assert applied["metrics"]["reserved_interactive_slots"] == 1
    assert applied["metrics"]["background_max_running"] == 5

    conn = db.connect(db.default_db_path(root))
    try:
        assert db.schema_version(conn) == 2
        assert conn.execute("SELECT COUNT(*) FROM run_queue WHERE id = 'legacy-1'").fetchone()[0] == 1
        assert {row[0] for row in conn.execute("SELECT name FROM execution_queues")} == {"codex", "claude", "non_llm"}
        assert {row[0] for row in conn.execute("SELECT name FROM worker_pools")} == {"codex_workers", "claude_workers", "non_llm_workers"}
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

        dead = fabric.retry_task(conn, doomed["id"], error="provider unavailable", now="2026-01-01T00:00:30Z")
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

        waiting = fabric.enqueue_task(conn, queue_name="llm", worker_pool="codex", kind="manual")
        cancelled = fabric.cancel_task(conn, waiting["id"], reason="operator cancelled")
        assert cancelled["status"] == "cancelled"
        assert cancelled["error"] == "operator cancelled"
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
            lease_seconds=60,
            now="2026-01-01T00:00:22Z",
        )
        second_claim = fabric.claim_next(
            conn,
            worker_id="worker-a",
            worker_token=second_worker["lease_token"],
            now="2026-01-01T00:00:23Z",
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
                now="2026-01-01T00:00:24Z",
            )
        with pytest.raises(fabric.ExecutionFabricError, match="active fenced lease"):
            fabric.complete_task(
                conn,
                task["id"],
                worker_id="worker-a",
                worker_token=second_worker["lease_token"],
                lease_token=first_claim["lease_token"],
                now="2026-01-01T00:00:24Z",
            )
        completed = fabric.complete_task(
            conn,
            task["id"],
            worker_id="worker-a",
            worker_token=second_worker["lease_token"],
            lease_token=second_claim["lease_token"],
            now="2026-01-01T00:00:24Z",
        )
        assert completed["status"] == "done"
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
