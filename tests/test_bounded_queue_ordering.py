from __future__ import annotations

from pathlib import Path
import shlex

import pytest
import yaml

from genomes_agentic_os import runtime_ops
from genomes_agentic_os.runtime_backend import apply_queue_mode
from genomes_agentic_os.state import db, execution_fabric as fabric, queue

NOW = "2026-07-01T01:00:00.500Z"
CONSUMERS = ("queue", "fabric", "filesystem", "runtime", "batch", "mismatch")


def _selected(tmp_path: Path, monkeypatch, consumer: str, records: list[dict]) -> str:
    monkeypatch.setattr(db, "utc_now_iso", lambda: NOW)
    if consumer == "filesystem":
        selected = runtime_ops._dispatchable_item(records, None, now=NOW)
        assert selected is not None
        return selected["id"]
    if consumer in {"queue", "fabric"}:
        conn = db.connect(":memory:")
        try:
            fabric.configure_queue(conn, "non_llm", max_concurrency=1)
            fabric.configure_worker_pool(conn, "non_llm_workers", queue_name="non_llm", max_workers=1, max_concurrency=1)
            worker = fabric.register_worker(conn, "fixture-worker", pool_name="non_llm_workers", now=NOW)
            for record in records:
                fabric.enqueue_task(conn, queue_name="non_llm", worker_pool="non_llm_workers", **record)
            selected = (
                queue.claim_next(conn, worker_id="fixture-worker", now=NOW)
                if consumer == "queue" else
                fabric.claim_next(conn, worker_id="fixture-worker", worker_token=worker["lease_token"], now=NOW)
            )
            assert selected is not None
            return selected["id"]
        finally:
            conn.close()
    root = tmp_path / "fixture-root"
    control = root / "harness/shared_factory/00-control-plane"
    control.mkdir(parents=True)
    (control / "runtime-registry.yml").write_text(yaml.safe_dump({"version": "0.1.0", "execution_targets": []}))
    (control / "run-queue.yml").write_text(yaml.safe_dump({"version": "0.1.0", "items": []}))
    apply_queue_mode(root, "execution_fabric", dry_run=False)
    conn = db.connect(db.default_db_path(root))
    try:
        for record in records:
            queue.enqueue(conn, queue_name="non_llm", worker_pool="other_workers" if consumer == "mismatch" else "non_llm_workers", execution_target="script", **record)
    finally:
        conn.close()
    if consumer == "batch":
        result = runtime_ops.runtime_run_batch(root, dry_run=True, max_tasks=1)["results"][0]
    elif consumer == "mismatch":
        result = runtime_ops._prepare_execution_fabric_dispatch(root, dry_run=True, item_id=None, queue_name="non_llm", worker_pool="non_llm_workers")["result"]
    else:
        result = runtime_ops.runtime_run_next(root, dry_run=True)
    return result["queue_item"]["id"]


def _item(identifier: str, created: str, priority: int = 0, **extra) -> dict:
    return {"id": identifier, "kind": "schedule", "status": "queued", "created_at": created, "priority": priority, **extra}


@pytest.mark.parametrize("consumer", CONSUMERS)
@pytest.mark.parametrize(("created", "expected"), [
    ("2026-07-01T00:00:00.501Z", "fresh"),
    ("2026-07-01T00:00:00.500Z", "boundary"),
    ("2026-07-01T00:00:00.499Z", "boundary"),
    ("2026-07-01T00:00:00.500001Z", "fresh"),
    ("2026-07-01T00:00:00.500400Z", "fresh"),
    ("2026-07-01T00:00:00.499999Z", "boundary"),
])
def test_cutoff_equality_and_both_sides_across_actual_consumers(tmp_path, monkeypatch, consumer, created, expected):
    records = [_item("fresh", "2026-07-01T00:59:00Z", 10000), _item("boundary", created)]
    assert _selected(tmp_path, monkeypatch, consumer, records) == expected


@pytest.mark.parametrize("consumer", CONSUMERS)
def test_oldest_aged_item_wins_despite_priority_and_same_hour(tmp_path, monkeypatch, consumer):
    records = [
        _item("newer-high", "2026-06-30T23:40:00Z", 10000),
        _item("oldest-low", "2026-06-30T23:10:00Z", -10),
        *[_item(f"fresh-{n}", "2026-07-01T00:59:00Z", 100000 + n) for n in range(20)],
    ]
    assert _selected(tmp_path, monkeypatch, consumer, records) == "oldest-low"


@pytest.mark.parametrize("consumer", CONSUMERS)
def test_aged_microsecond_order_and_future_due_parity(tmp_path, monkeypatch, consumer):
    records = [
        _item("future-high", "2026-06-30T20:00:00Z", 100000, due_at="2026-07-01T01:00:00.500001Z"),
        _item("newer-high", "2026-07-01T00:00:00.499999Z", 10000),
        _item("oldest-low", "2026-07-01T00:00:00.499998Z", -10),
    ]
    assert _selected(tmp_path, monkeypatch, consumer, records) == "oldest-low"


@pytest.mark.parametrize("consumer", CONSUMERS)
@pytest.mark.parametrize(("due_at", "expected"), [
    ("2026-07-01T01:00:00.499999Z", "boundary-high"),
    ("2026-07-01T01:00:00.500Z", "boundary-high"),
    ("2026-07-01T01:00:00.500001Z", "eligible-low"),
    ("2026-07-01T01:00:00.500400Z", "eligible-low"),
])
def test_due_boundary_with_fresh_eligible_competitor(tmp_path, monkeypatch, consumer, due_at, expected):
    records = [
        _item("eligible-low", "2026-07-01T00:59:00Z", 0),
        _item("boundary-high", "2026-07-01T00:59:00Z", 100000, due_at=due_at),
    ]
    assert _selected(tmp_path, monkeypatch, consumer, records) == expected


@pytest.mark.parametrize("value", [None, "", "invalid", "2026-02-30T01:00:00Z", 42, True])
def test_invalid_timestamps_have_no_normalized_date(value):
    assert db.normalized_timestamp_us(value) is None


def test_exact_normalized_timestamp_is_shared_by_sql_and_filesystem(tmp_path):
    value = "2026-07-01 02:00:00.500001+02:00"
    expected = db.normalized_timestamp_us("2026-07-01T00:00:00.500001Z")
    assert expected == db.normalized_timestamp_us(value)
    assert expected == db.normalized_timestamp_us("2026-07-01T00:00:00.500001")
    path = tmp_path / "state.db"
    conn = db.connect(path)
    assert conn.execute("SELECT agentic_timestamp_us(?)", (value,)).fetchone()[0] == expected
    conn.close()
    readonly = db.connect_readonly(path)
    assert readonly.execute("SELECT agentic_timestamp_us(?)", (value,)).fetchone()[0] == expected
    readonly.close()


@pytest.mark.parametrize("consumer", CONSUMERS)
@pytest.mark.parametrize("spelling", ["2026-07-01T02:00:00.500+02:00", "2026-07-01 00:00:00.500+00:00"])
def test_due_and_age_comparisons_normalize_offsets_and_spaces(tmp_path, monkeypatch, consumer, spelling):
    records = [
        _item("future-offset", "2026-06-30T20:00:00Z", 100000, due_at="2026-06-30T23:30:00-03:00"),
        _item("fresh", "2026-07-01T00:59:00Z", 10000),
        _item("aged-normalized", "2026-07-01T00:59:00Z", due_at=spelling),
    ]
    assert _selected(tmp_path, monkeypatch, consumer, records) == "aged-normalized"


@pytest.mark.parametrize("command", [
    "aos validate --root '{root}'",
    "/fixture/bin/agentic-os\tvalidate --root '{root}'",
    "agentic-os validate --root '{root}' --json",
    "agentic-os self-improvement morning-report --root '{root}' --apply",
    "agentic-os thread stale-finalize --apply --root '{root}' --older-than-days 3",
    "aos project worktree cleanup-closed --root '{root}' --apply",
])
def test_inline_command_structure_and_aliases_reserve_long_lease(tmp_path, command):
    root = tmp_path / "root with spaces"
    item = runtime_ops._materialize_inline_script_lease(root, {"command": command.format(root=root)})
    assert item["lease_seconds"] == runtime_ops.INLINE_SCRIPT_LEASE_SECONDS


@pytest.mark.parametrize("command", ["agentic-os validate-extra --root <root>", "other-agentic-os validate --root <root>", "agentic-os self-improvement morning-report-extra --root <root>"])
def test_lease_recognition_uses_exact_verbs_and_executables(tmp_path, command):
    assert "lease_seconds" not in runtime_ops._materialize_inline_script_lease(tmp_path, {"command": command})


def test_declarative_nested_lease_survives_command_materialization(tmp_path):
    command = "bash -c " + shlex.quote("agentic-os validate --root " + shlex.quote(str(tmp_path)))
    item = {"command": command, "runtime_policy": {"lease_seconds": 2400}}
    assert runtime_ops._materialize_inline_script_lease(tmp_path, item) == item
    assert "lease_seconds" not in item
    assert runtime_ops._dispatch_lease_seconds(item, 900) == 2400


@pytest.mark.parametrize("value", [True, False, 0, -1, 1.5, "invalid-secret-value", 86401])
@pytest.mark.parametrize("nested", [False, True])
def test_invalid_explicit_lease_refuses_sanitized_without_short_fallback(value, nested):
    item = {"runtime_policy": {"lease_seconds": value}} if nested else {"lease_seconds": value}
    with pytest.raises(ValueError, match="lease_seconds must be a positive integer") as error:
        runtime_ops._dispatch_lease_seconds(item, 900)
    assert "invalid-secret-value" not in str(error.value)


def test_order_helper_keeps_values_bound():
    sql, params = queue.dispatch_order(NOW)
    assert sql.count("?") == len(params) == 2
    assert params[0] == params[1] == "2026-07-01T00:00:00.500000Z"
    assert NOW not in sql
