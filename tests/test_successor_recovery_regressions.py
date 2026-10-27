"""Real scratch Git/SQLite controls for pending recovery and receipt boundaries."""
from __future__ import annotations

from copy import deepcopy
import fcntl
import hashlib
import json
import os
from pathlib import Path
from typing import Any

import pytest

from genomes_agentic_os import auto_dev_orchestration as orchestration
from genomes_agentic_os import development_delivery as delivery
from genomes_agentic_os import development_successor_binding as admission
from genomes_agentic_os import development_successor_state as binding
from genomes_agentic_os import development_validation_refresh as refresh
from genomes_agentic_os.cli import main
from genomes_agentic_os.state import work_items
from genomes_agentic_os.state.db import connect, default_db_path
from test_development_successor_binding import candidate, _bind, _metadata
from test_development_delivery import _git
from test_development_validation_refresh import _bound, _command_proof, _now, _write


def _interrupt_binding(fixture: dict[str, Any], monkeypatch: pytest.MonkeyPatch,
                       effect: str = "event") -> dict[str, Any]:
    """Commit a genuine effect, then simulate interruption at its return boundary."""
    owner, name = {
        "event": (binding, "append_event"),
        "portfolio": (binding, "_atomic_json"),
        "sqlite": (work_items, "bind_development_successor"),
        "active_projection": (work_items, "write_active_projection"),
    }[effect]
    original = getattr(owner, name)
    def interrupted(*args: Any, **kwargs: Any) -> Any:
        """Retain the collaborator's real durable write before the process failure."""
        original(*args, **kwargs)
        raise RuntimeError("pending binding interruption")
    with monkeypatch.context() as patch:
        patch.setattr(owner, name, interrupted)
        with pytest.raises(RuntimeError, match="pending binding interruption"):
            _bind(fixture)
    current = json.loads(fixture["task"].path.read_text())
    assert current["active_successor_binding"]["status"] == "projections_pending"
    return current


def _abandon(fixture: dict[str, Any], pending_sha: str, *, apply: bool = True) -> dict[str, Any]:
    """Use the public typed operation with one stable, explicit pending-state CAS."""
    return binding.abandon_development_successor(
        fixture["task"].path, expect_state_sha256=pending_sha,
        idempotency_key="abandon-pending-source",
        reason="A legitimate source push advanced during interrupted projection", apply=apply)


def _validate_bound(fixture: dict[str, Any]) -> dict[str, Any]:
    """Execute the actual frozen scratch command and refresh its immutable evidence."""
    before = fixture["task"].read()
    predecessor = Path([row for row in before["receipts"] if row["state"] == "local_validation"][-1]["ref"])
    _bind(fixture)
    current = fixture["task"].read()
    head = _git("rev-parse", "HEAD", cwd=fixture["candidate"])
    run = _command_proof(fixture["root"], fixture["packet"], fixture["candidate"],
                         fixture["command"], head, current["policy_fingerprint"])
    evidence = {"ticket": current["ticket"], "canonical_work_id": current["canonical_work_id"],
        "repository_id": current["repository"]["id"], "repository": "acme/app",
        "task_state_ref": str(fixture["task"].path), "worktree": str(fixture["candidate"]),
        "source_branch": current["worktree"]["branch"], "head_sha": head,
        "policy_fingerprint": current["policy_fingerprint"],
        "policy_sha256": _bound(Path(current["policy_receipt"]))["sha256"],
        "validation_runs": [run],
        "repair_lineage": {"predecessor": _bound(predecessor), "from_head_sha": fixture["old_head"],
                           "to_head_sha": head, "reason": "Actual current binding validation"},
        **_metadata(current)}
    path = _write(fixture["packet"] / "artifacts/recovery-regression-validation.json", {
        "schema": "development-stage-evidence/v1", "state": "local_validation", "status": "passed",
        "summary": "Actual frozen native command", "verified_at": _now(), "evidence": evidence})
    return refresh.refresh_development_validation(
        fixture["task"].path, evidence_file=path, idempotency_key="recovery-native-validation")["task"]


def test_pending_portfolio_replay_preserves_unrelated_updates(
    candidate: dict[str, Any], monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A sibling row or rollup update cannot wedge this ticket's pending pointer."""
    _interrupt_binding(candidate, monkeypatch)
    path = candidate["task"].path.parents[2] / "portfolio.json"
    portfolio = json.loads(path.read_text())
    portfolio["operator_annotation"] = {"preserve": "unrelated current write"}
    sibling = {"ticket": "OTHER-1", "state_ref": "/unrelated/sibling/state.json", "state": "building"}
    portfolio["tasks"].append(sibling)
    _write(path, portfolio)
    assert _bind(candidate)["replayed"] is True
    after = json.loads(path.read_text())
    assert after["operator_annotation"] == portfolio["operator_annotation"]
    assert after["tasks"][-1] == sibling
    assert after["active_successor_bindings"][candidate["task"].read()["ticket"]]


@pytest.mark.parametrize("foreign", ["pointer", "task"])
def test_pending_portfolio_replay_refuses_foreign_ticket_ownership(
    candidate: dict[str, Any], monkeypatch: pytest.MonkeyPatch, foreign: str,
) -> None:
    """Per-ticket fencing still rejects someone else's task path or binding."""
    current = _interrupt_binding(candidate, monkeypatch)
    path = candidate["task"].path.parents[2] / "portfolio.json"
    portfolio = json.loads(path.read_text())
    if foreign == "pointer":
        portfolio["active_successor_bindings"] = {current["ticket"]: {"foreign": True}}
    else:
        next(row for row in portfolio["tasks"] if row["ticket"] == current["ticket"])["state_ref"] = "/foreign/state.json"
    _write(path, portfolio)
    raw = path.read_bytes()
    with pytest.raises(delivery.DevelopmentDeliveryError, match="foreign|no longer owns"):
        _bind(candidate)
    assert path.read_bytes() == raw


@pytest.mark.parametrize("effect", ["event", "portfolio", "sqlite", "active_projection"])
def test_pending_abandonment_restores_predecessor_after_real_source_advance(
    candidate: dict[str, Any], monkeypatch: pytest.MonkeyPatch, effect: str,
) -> None:
    """All partially projected phases can restore authority after a real remote push."""
    original = candidate["task"].read()
    _interrupt_binding(candidate, monkeypatch, effect)
    tree = candidate["candidate"]
    (tree / "README.md").write_text("A genuine later source change\n")
    _git("add", "README.md", cwd=tree)
    _git("commit", "-m", "fix: later legitimate successor", cwd=tree)
    _git("push", str(candidate["remote"]), "HEAD:refs/heads/" + candidate["provider"]["source_branch"], cwd=tree)
    candidate["provider"]["head"] = _git("rev-parse", "HEAD", cwd=tree)
    with pytest.raises(delivery.DevelopmentDeliveryError, match="successor changed"):
        _bind(candidate)
    pending_sha = hashlib.sha256(candidate["task"].path.read_bytes()).hexdigest()
    raw = candidate["task"].path.read_bytes()
    assert _abandon(candidate, pending_sha, apply=False)["status"] == "read_only_plan"
    assert candidate["task"].path.read_bytes() == raw
    assert _abandon(candidate, pending_sha)["status"] == "abandoned"
    after = candidate["task"].read()
    for key in (*binding.BINDING_FIELDS, "receipts", "stage_receipts", "attempts", "lease", "max_attempts"):
        assert after.get(key) == original.get(key)
    assert after.get("active_successor_binding") == original.get("active_successor_binding")
    assert after.get("successor_bindings") == original.get("successor_bindings")
    assert after["successor_abandonment"]["status"] == "abandoned"
    assert len(after["abandoned_successor_bindings"]) == 1
    assert _git("rev-parse", "HEAD", cwd=tree) == candidate["provider"]["head"]
    portfolio = json.loads((candidate["task"].path.parents[2] / "portfolio.json").read_text())
    assert after["ticket"] not in portfolio.get("active_successor_bindings", {})
    connection = connect(default_db_path(candidate["root"]))
    try:
        row = work_items.get(connection, after["canonical_work_id"])
        assert row["worktree_path"] == original["worktree"]["path"]
        assert row["branch"] == original["worktree"]["branch"]
        assert "active_successor_binding" not in row["metadata"]
        assert len(row["metadata"]["abandoned_successor_bindings"]) == 1
    finally:
        connection.close()
    assert _abandon(candidate, pending_sha)["replayed"] is True
    events = [json.loads(line) for line in candidate["task"].ledger.read_text().splitlines()]
    assert sum(row["type"] == "development.successor.abandoned" for row in events) == 1


@pytest.mark.parametrize("effect", ["canonical", "active_projection", "event", "restored_task", "autodev"])
def test_abandonment_outbox_replays_each_durable_boundary(
    candidate: dict[str, Any], monkeypatch: pytest.MonkeyPatch, effect: str,
) -> None:
    """A crash in rollback has its own fence and never grants partial authority."""
    _interrupt_binding(candidate, monkeypatch, "sqlite")
    pending_sha = hashlib.sha256(candidate["task"].path.read_bytes()).hexdigest()
    owner, name = {"canonical": (work_items, "abandon_development_successor"),
                   "active_projection": (work_items, "write_active_projection"),
                   "event": (binding, "append_event"), "restored_task": (binding, "_commit_task"),
                   "autodev": (binding, "_sync_auto_dev_projection")}[effect]
    original = getattr(owner, name)
    def interrupted(*args: Any, **kwargs: Any) -> Any:
        """Preserve the real effect, then fail at the selected recovery boundary."""
        result = original(*args, **kwargs)
        if effect == "restored_task" and args[1].get("successor_abandonment", {}).get("status") != "abandoned":
            return result
        raise RuntimeError("abandonment interruption")
    with monkeypatch.context() as patch:
        patch.setattr(owner, name, interrupted)
        with pytest.raises(RuntimeError, match="abandonment interruption"):
            _abandon(candidate, pending_sha)
    if effect != "autodev":
        with pytest.raises(delivery.DevelopmentDeliveryError, match="pending|projection fence"):
            candidate["task"].read()
    assert _abandon(candidate, pending_sha)["status"] == "abandoned"
    assert candidate["task"].read()["successor_abandonment"]["status"] == "abandoned"
    connection = connect(default_db_path(candidate["root"]))
    try:
        count = connection.execute(
            "SELECT count(*) FROM work_item_history WHERE work_item_id = ? AND actor = ?",
            (candidate["task"].read()["canonical_work_id"], "development-successor-abandonment")).fetchone()[0]
        assert count == 1
    finally:
        connection.close()


def test_abandonment_refuses_stale_cas_changed_attempts_and_consumed_binding(
    candidate: dict[str, Any], monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Recovery cannot reset retries or abandon a binding after consumption."""
    pending = _interrupt_binding(candidate, monkeypatch)
    with pytest.raises(delivery.DevelopmentDeliveryError, match="exact unconsumed"):
        _abandon(candidate, "0" * 64)
    pending["attempts"]["validation"] = pending.get("attempts", {}).get("validation", 0) + 1
    _write(candidate["task"].path, pending)
    raw = candidate["task"].path.read_bytes()
    with pytest.raises(delivery.DevelopmentDeliveryError, match="discard changed"):
        _abandon(candidate, hashlib.sha256(raw).hexdigest())
    assert candidate["task"].path.read_bytes() == raw


def test_completed_binding_cannot_be_abandoned(candidate: dict[str, Any]) -> None:
    """Only pending outbox authority can be restored by this recovery entrypoint."""
    _bind(candidate)
    raw = candidate["task"].path.read_bytes()
    with pytest.raises(delivery.DevelopmentDeliveryError, match="exact unconsumed"):
        _abandon(candidate, hashlib.sha256(raw).hexdigest())
    assert candidate["task"].path.read_bytes() == raw


@pytest.mark.parametrize("change", ["lease", "attempts"])
def test_abandonment_replay_never_discards_post_cas_task_changes(
    candidate: dict[str, Any], monkeypatch: pytest.MonkeyPatch, change: str,
) -> None:
    """A later lease or retry update remains authoritative even in recovery."""
    _interrupt_binding(candidate, monkeypatch)
    pending_sha = hashlib.sha256(candidate["task"].path.read_bytes()).hexdigest()
    with monkeypatch.context() as patch:
        def interrupted(*_args: Any, **_kwargs: Any) -> None:
            """Interrupt after the abandonment intent CAS, before its SQLite effect."""
            raise RuntimeError("after abandonment CAS")
        patch.setattr(work_items, "abandon_development_successor", interrupted)
        with pytest.raises(RuntimeError, match="after abandonment CAS"):
            _abandon(candidate, pending_sha)
    current = json.loads(candidate["task"].path.read_text())
    if change == "lease":
        current["lease"] = {**current.get("lease", {}), "owner": "legitimate-later-owner"}
    else:
        current["attempts"]["validation"] = current["attempts"].get("validation", 0) + 1
    _write(candidate["task"].path, current)
    raw = candidate["task"].path.read_bytes()
    with pytest.raises(delivery.DevelopmentDeliveryError, match="discard changed"):
        _abandon(candidate, pending_sha)
    assert candidate["task"].path.read_bytes() == raw


@pytest.mark.parametrize("foreign", ["portfolio", "canonical"])
def test_abandonment_refuses_foreign_pointer_without_overwriting_it(
    candidate: dict[str, Any], monkeypatch: pytest.MonkeyPatch, foreign: str,
) -> None:
    """Recovery owns only its exact pointer and never repoints another delivery."""
    pending = _interrupt_binding(candidate, monkeypatch, "sqlite")
    pending_sha = hashlib.sha256(candidate["task"].path.read_bytes()).hexdigest()
    if foreign == "portfolio":
        path = candidate["task"].path.parents[2] / "portfolio.json"
        portfolio = json.loads(path.read_text())
        portfolio["active_successor_bindings"][pending["ticket"]] = {"foreign": True}
        _write(path, portfolio)
        before = path.read_bytes()
        with pytest.raises(delivery.DevelopmentDeliveryError, match="portfolio pointer is foreign"):
            _abandon(candidate, pending_sha)
        assert path.read_bytes() == before
    else:
        connection = connect(default_db_path(candidate["root"]))
        try:
            row = work_items.get(connection, pending["canonical_work_id"])
            metadata = deepcopy(row["metadata"])
            metadata["active_successor_binding"]["binding_id"] = "f" * 64
            with connection:
                connection.execute("UPDATE work_items SET metadata_json = ? WHERE id = ?",
                                   (json.dumps(metadata), row["id"]))
            before = work_items.get(connection, row["id"])
            with pytest.raises(work_items.WorkItemError, match="pointer is foreign"):
                _abandon(candidate, pending_sha)
            assert work_items.get(connection, row["id"]) == before
        finally:
            connection.close()


def test_successor_retains_proven_worktree_contract(candidate: dict[str, Any]) -> None:
    """Recovery consumers retain every provisioned field and the exact provider base."""
    before = candidate["task"].read()["worktree"]
    record = candidate["observation"]["registry"]["worktree"]
    assert set(before) <= set(record)
    assert record["base_sha"] == candidate["provider"]["base_sha"]
    assert _bind(candidate)["task"]["worktree"] == record


@pytest.mark.parametrize("history", [{}, {"unexpected": True}, 7, "invalid"])
def test_refresh_history_rejects_malformed_type_before_slicing(tmp_path: Path, history: Any) -> None:
    """Malformed state produces a typed refusal rather than Python slice errors."""
    with pytest.raises(delivery.DevelopmentDeliveryError, match="history/head binding"):
        refresh._refresh_epoch_history({"validation_refreshes": history}, tmp_path, history_offset=1)


def test_bound_projection_keeps_the_validation_head_fence(candidate: dict[str, Any]) -> None:
    """Projection never advertises an older reviewed head after current validation."""
    current = _validate_bound(candidate)
    current["subject_revision"] = candidate["old_head"]
    _write(candidate["task"].path, current)
    orchestration.sync_delivery_projection(candidate["task"].path)
    projected = json.loads((candidate["packet"] / "autodev.json").read_text())
    assert projected["subject_revision"] is None


@pytest.mark.parametrize("evidence", [[], ["bad"], "bad", 1])
def test_bound_transition_rejects_nonmapping_evidence(
    candidate: dict[str, Any], evidence: Any,
) -> None:
    """Direct transition callers receive typed errors without mutating the task."""
    _bind(candidate)
    path = _write(candidate["packet"] / "artifacts/malformed-transition.json", {"evidence": evidence})
    raw = candidate["task"].path.read_bytes()
    with pytest.raises(delivery.DevelopmentDeliveryError, match="evidence must be a mapping"):
        candidate["task"].transition("blocked", receipt=str(path), idempotency_key="bad-mapping")
    assert candidate["task"].path.read_bytes() == raw


def test_bound_transition_provider_reads_do_not_hold_heartbeat_lock(
    candidate: dict[str, Any], monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The actual file lock is available during provider observation, then CAS applies."""
    current = _validate_bound(candidate)
    actual = admission._provider
    observed: list[bool] = []
    def provider(*args: Any) -> dict[str, Any]:
        """Inspect lock availability at the declared external provider edge."""
        with candidate["task"].path.with_suffix(".json.lock").open("a+") as stream:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            observed.append(True)
            fcntl.flock(stream, fcntl.LOCK_UN)
        return actual(*args)
    monkeypatch.setattr(admission, "_provider", provider)
    path = _write(candidate["packet"] / "artifacts/transition-lock.json", {"evidence": _metadata(current)})
    result = candidate["task"].transition(
        "pre_pr_review", receipt=str(path.relative_to(candidate["packet"])), idempotency_key="unlocked-provider")
    assert observed == [True]
    assert result["state"] == "pre_pr_review"
    assert result["receipts"][-1]["ref"] == str(path)


@pytest.mark.parametrize("kind", ["symlink", "oversize", "fifo", "symlink_parent"])
def test_history_admission_refuses_unbounded_or_followed_files(
    tmp_path: Path, kind: str,
) -> None:
    """File-backed historical proofs use bounded, no-follow ordinary bytes."""
    path = tmp_path / "receipt"
    if kind == "symlink":
        target = tmp_path / "target"
        target.write_bytes(b"receipt")
        path.symlink_to(target)
    elif kind == "oversize":
        with path.open("wb") as stream:
            stream.truncate(admission.MAX_PROOF_BYTES + 1)
    elif kind == "fifo":
        os.mkfifo(path)
    else:
        parent = tmp_path / "real"
        parent.mkdir()
        (parent / "receipt").write_bytes(b"receipt")
        alias = tmp_path / "alias"
        alias.symlink_to(parent, target_is_directory=True)
        path = alias / "receipt"
    with pytest.raises(delivery.DevelopmentDeliveryError, match="ordinary|bound|observation failed"):
        admission.historical_inventory({"receipts": [{"ref": str(path)}]})


def test_history_keeps_binary_and_remote_receipts_without_invented_hashes(tmp_path: Path) -> None:
    """Opaque historical bytes remain valid and non-file strings remain unchanged."""
    path = tmp_path / "receipt.bin"
    path.write_bytes(b"\xff\x00opaque original evidence")
    raw = path.read_bytes()
    result = admission.historical_inventory({"receipts": [
        {"ref": str(path), "sha256": hashlib.sha256(raw).hexdigest()},
        {"ref": "https://provider.example/receipt/1"}]})
    assert result["files"] == [{"ref": str(path), "sha256": hashlib.sha256(raw).hexdigest()},
                               {"ref": "https://provider.example/receipt/1"}]
    assert path.read_bytes() == raw


def test_history_preserves_unhashed_provisioning_directory_and_empty_refs(tmp_path: Path) -> None:
    """Existing work-item/worktree directory references retain their original shape."""
    result = admission.historical_inventory({"receipts": [{"ref": str(tmp_path)}, {"ref": ""}]})
    assert result["files"] == [{"ref": str(tmp_path)}, {"ref": ""}]
    with pytest.raises(delivery.DevelopmentDeliveryError, match="hash-bound historical receipt is missing"):
        admission.historical_inventory({"receipts": [{"ref": str(tmp_path), "sha256": "a" * 64}]})


def test_abandon_cli_exposes_plan_without_a_force_override(
    candidate: dict[str, Any], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    """The native command offers an exact pending CAS, never a bypass or retry reset."""
    _interrupt_binding(candidate, monkeypatch)
    pending_sha = hashlib.sha256(candidate["task"].path.read_bytes()).hexdigest()
    argv = ["develop", "abandon-successor", str(candidate["task"].path),
            "--expect-state-sha256", pending_sha, "--idempotency-key", "cli-abandon",
            "--reason", "Changed source during interrupted projection", "--json"]
    assert main(argv) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "read_only_plan"
    with pytest.raises(SystemExit):
        main([*argv, "--force"])
