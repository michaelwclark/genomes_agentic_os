from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import subprocess

import pytest
import yaml

import genomes_agentic_os.development_delivery as delivery
from genomes_agentic_os.cli import main
from genomes_agentic_os.development_delivery import (
    DevelopmentDeliveryError,
    TaskState,
    append_event,
    classify_validation,
    create_isolated_worktree,
    load_development_profile,
    required_test_layers,
    validate_workflow_contracts,
)
from genomes_agentic_os.scaffold import create_project


def _git(*args: str, cwd: Path | None = None) -> str:
    completed = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=True
    )
    return completed.stdout.strip()


def _project(root: Path, repo: Path, *, canonical: bool = True) -> Path:
    create_project(root, "acme", "app", repo=str(repo))
    project = root / "acme" / "02-projects" / "app"
    profile = {
        "version": 1,
        "enabled": True,
        "tracker": {"primary": "linear"},
        "repository": {"root": str(repo), "base_branch": "main"},
        "worktrees": {"directory": "worktrees", "branch_template": "feature/{ticket}-{slug}"},
        "work_items": {"active_status": "building"},
        "validation": {
            "commands": ["python3 -m pytest tests -q"],
            "test_policy": "risk_based_triangle",
            "ci_fallback_on_environment_failure": True,
        },
        "review": {"opposing_harness": {"required": True}},
        "merge": {"policy": "never_auto"},
        "recovery": {"max_attempts": 3, "lease_minutes": 30, "stale_after_minutes": 45},
    }
    if canonical:
        (project / "config" / "development.yml").write_text(yaml.safe_dump(profile, sort_keys=False), encoding="utf-8")
    else:
        # Simulate an installed pre-vNext project where only dev_factory exists.
        (project / "config" / "development.yml").unlink()
        data = yaml.safe_load((project / "project.yml").read_text(encoding="utf-8")) or {}
        data["dev_factory"] = {
            "enabled": True,
            "tracker": {"primary": "linear"},
            "repo": {
                "root": str(repo),
                "default_base_branch": "main",
                "branch_template": "feature/{tracker_id}-{slug}",
            },
            "validation": {"commands": {"local_validation": "python3 -m pytest tests -q"}},
            "merge": {"policy": "never_auto"},
        }
        (project / "project.yml").write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return project


def _repository(tmp_path: Path) -> tuple[Path, str]:
    remote = tmp_path / "remote.git"
    _git("init", "--bare", str(remote))
    repo = tmp_path / "repo"
    _git("init", "-b", "main", str(repo))
    _git("config", "user.email", "test@example.com", cwd=repo)
    _git("config", "user.name", "Test", cwd=repo)
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    _git("add", "README.md", cwd=repo)
    _git("commit", "-m", "base", cwd=repo)
    _git("remote", "add", "origin", str(remote), cwd=repo)
    _git("push", "-u", "origin", "main", cwd=repo)
    return repo, _git("rev-parse", "HEAD", cwd=repo)


def _state(tmp_path: Path, *, max_attempts: int = 3) -> TaskState:
    path = tmp_path / "run" / "tasks" / "cc-1" / "state.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "schema": "development-task/v1",
                "run_id": "run-1",
                "ticket": "CC-1",
                "state": "discovered",
                "attempts": {},
                "max_attempts": max_attempts,
                "lease": {"until": None},
                "receipts": [],
                "failure": None,
            }
        ),
        encoding="utf-8",
    )
    return TaskState(path)


def test_profile_prefers_canonical_and_translates_legacy(tmp_path: Path) -> None:
    repo, _ = _repository(tmp_path)
    project = _project(tmp_path / "canonical", repo)
    profile, source = load_development_profile(tmp_path / "canonical", "acme", "app")
    assert source == project / "config" / "development.yml"
    assert profile["validation"]["test_policy"] == "risk_based_triangle"

    legacy_project = _project(tmp_path / "legacy", repo, canonical=False)
    legacy, legacy_source = load_development_profile(tmp_path / "legacy", "acme", "app")
    assert legacy_source == legacy_project / "project.yml"
    assert legacy["compatibility"]["source"] == "project.yml#dev_factory"
    assert legacy["repository"]["base_branch"] == "main"
    assert legacy["worktrees"]["branch_template"] == "feature/{ticket}-{slug}"
    assert legacy["validation"]["commands"] == ["python3 -m pytest tests -q"]


def test_profile_derives_safe_defaults_for_existing_project(tmp_path: Path) -> None:
    repo, _ = _repository(tmp_path)
    root = tmp_path / "os"
    project = _project(root, repo)
    (project / "config" / "development.yml").unlink()
    profile, source = load_development_profile(root, "acme", "app")
    assert source == project / "project.yml"
    assert profile["compatibility"]["source"] == "project.yml#sources"
    assert profile["repository"] == {"root": str(repo), "base_branch": "main"}
    assert profile["worktrees"]["directory"] == "worktrees"
    assert profile["merge"]["policy"] == "never_auto"


def test_transition_requires_receipt_is_forward_only_and_idempotent(tmp_path: Path) -> None:
    task = _state(tmp_path)
    claimed = task.transition("claimed", receipt="tracker:CC-1", idempotency_key="claim")
    assert claimed["state"] == "claimed"
    replay = task.transition("claimed", receipt="tracker:CC-1", idempotency_key="claim")
    assert len(replay["receipts"]) == 1
    with pytest.raises(DevelopmentDeliveryError, match="illegal transition"):
        task.transition("worktree_ready", receipt="worktree", idempotency_key="skip")
    with pytest.raises(DevelopmentDeliveryError, match="requires a receipt"):
        task.transition("groom_check", receipt="", idempotency_key="no-receipt")


def test_failure_retries_then_blocks_and_recovery_resumes_owner_state(tmp_path: Path) -> None:
    task = _state(tmp_path, max_attempts=2)
    task.transition("claimed", receipt="tracker", idempotency_key="claim")
    failed = task.fail(
        kind="provider_unavailable", detail="timeout", receipt="logs/timeout", idempotency_key="fail-1"
    )
    assert failed["state"] == "claimed"
    assert failed["failure"]["recoverable"] is True
    replay = task.fail(
        kind="provider_unavailable", detail="timeout", receipt="logs/timeout", idempotency_key="fail-1"
    )
    assert replay["attempts"]["provider_unavailable"] == 1
    recovered = task.recover(receipt="provider healthy", idempotency_key="recover-1")
    assert recovered["state"] == "claimed"
    blocked = task.fail(
        kind="provider_unavailable", detail="timeout", receipt="logs/timeout-2", idempotency_key="fail-2"
    )
    assert blocked["state"] == "blocked"
    assert blocked["failure"]["recoverable"] is False


def test_stale_lease_is_classified_for_recovery(tmp_path: Path) -> None:
    task = _state(tmp_path)
    state = task.read()
    state["lease"] = {"until": (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()}
    task.path.write_text(json.dumps(state), encoding="utf-8")
    result = task.recover_stale_lease()
    assert result == {"recovered": True, "reason": "lease_expired"}
    assert task.read()["failure"]["kind"] == "lease_expired"


def test_heartbeat_renews_worker_lease_without_changing_state(tmp_path: Path) -> None:
    task = _state(tmp_path)
    state = task.heartbeat(owner="worker-1", lease_minutes=10, idempotency_key="heartbeat-1")
    assert state["state"] == "discovered"
    assert state["lease"]["owner"] == "worker-1"
    assert state["lease"]["heartbeat_at"] < state["lease"]["until"]
    replay = task.heartbeat(owner="worker-1", lease_minutes=99, idempotency_key="heartbeat-1")
    assert replay["lease"] == state["lease"]


def test_event_append_is_idempotent(tmp_path: Path) -> None:
    ledger = tmp_path / "events.jsonl"
    assert append_event(ledger, event_type="x", idempotency_key="same", payload={})["appended"] is True
    assert append_event(ledger, event_type="x", idempotency_key="same", payload={})["appended"] is False
    assert len(ledger.read_text(encoding="utf-8").splitlines()) == 1


def test_risk_based_testing_and_environment_classification() -> None:
    assert required_test_layers("micro") == ["unit"]
    assert required_test_layers("standard") == ["unit", "integration"]
    assert required_test_layers("high") == ["unit", "integration", "end_to_end"]
    assert classify_validation(returncode=0) == "passed"
    assert classify_validation(returncode=1) == "code_failed"
    assert classify_validation(returncode=1, environment_evidence="docker unavailable") == "environment_unavailable"


def test_real_worktree_uses_exact_remote_base_and_project_storage(tmp_path: Path) -> None:
    repo, base_sha = _repository(tmp_path)
    root = tmp_path / "os"
    project = _project(root, repo)
    profile, _ = load_development_profile(root, "acme", "app")
    result = create_isolated_worktree(
        os_root=root,
        domain="acme",
        project="app",
        profile=profile,
        ticket="CC-9",
        title="Safe delivery",
    )
    worktree = Path(result["path"])
    assert worktree.parent == project / "worktrees"
    assert result["base_sha"] == base_sha
    assert _git("rev-parse", "HEAD", cwd=worktree) == base_sha
    registry = yaml.safe_load((project / "worktrees" / "index.yml").read_text(encoding="utf-8"))
    assert any(row["id"] == result["name"] for row in registry["worktrees"])


def test_cli_dry_run_is_non_mutating_and_multi_ticket(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo, _ = _repository(tmp_path)
    root = tmp_path / "os"
    project = _project(root, repo)
    before = sorted((project / "worktrees").iterdir())
    assert main(["develop", "start", "acme", "app", "CC-1", "CC-2", "--root", str(root)]) == 0
    output = capsys.readouterr().out
    assert "CC-1" in output and "CC-2" in output
    assert not (project / "state" / "development-runs").exists()
    assert sorted((project / "worktrees").iterdir()) == before


def test_multi_ticket_provisioning_preserves_success_and_auto_recovers_retryable_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, base_sha = _repository(tmp_path)
    root = tmp_path / "os"
    _project(root, repo)

    def first_attempt(**kwargs):
        if kwargs["ticket"] == "CC-1":
            raise DevelopmentDeliveryError("git fetch provider unavailable")
        return {"name": "cc-2", "path": "/tmp/cc-2", "branch": "feature/cc-2", "base_sha": base_sha}

    monkeypatch.setattr(delivery, "create_isolated_worktree", first_attempt)
    first = delivery.start_development_run(
        root, "acme", "app", ["CC-1", "CC-2"], run_id="portfolio-recovery", apply=True
    )
    assert first["state"] == "partial"
    first_states = {row["ticket"]: TaskState(Path(row["state_ref"])).read() for row in first["tasks"]}
    assert first_states["CC-1"]["failure"]["recoverable"] is True
    assert first_states["CC-2"]["state"] == "worktree_ready"

    monkeypatch.setattr(
        delivery,
        "create_isolated_worktree",
        lambda **kwargs: {
            "name": kwargs["ticket"].lower(),
            "path": f"/tmp/{kwargs['ticket'].lower()}",
            "branch": f"feature/{kwargs['ticket'].lower()}",
            "base_sha": base_sha,
        },
    )
    resumed = delivery.start_development_run(
        root, "acme", "app", ["CC-1", "CC-2"], run_id="portfolio-recovery", apply=True
    )
    assert resumed["state"] == "dispatching"
    resumed_states = {row["ticket"]: TaskState(Path(row["state_ref"])).read() for row in resumed["tasks"]}
    assert all(state["state"] == "worktree_ready" for state in resumed_states.values())
    assert resumed_states["CC-1"]["attempts"]["provider_unavailable"] == 1
    rollup = root / "harness" / "shared_factory" / "00-control-plane" / "development-runs.jsonl"
    assert rollup.is_file()
    rollup_events = [json.loads(line) for line in rollup.read_text(encoding="utf-8").splitlines()]
    assert any(event["type"] == "development.task.failed" for event in rollup_events)
    assert any(event["type"] == "development.task.recovered" for event in rollup_events)
    for state in resumed_states.values():
        receipt = Path(state["work_item"]) / "artifacts" / "development-delivery" / "run.json"
        assert json.loads(receipt.read_text(encoding="utf-8"))["run_id"] == "portfolio-recovery"


def test_workflow_docs_are_complete_and_shallow() -> None:
    repository = Path(__file__).resolve().parents[1]
    assert validate_workflow_contracts(repository) == []
