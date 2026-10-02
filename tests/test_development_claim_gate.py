"""Verify the lifecycle engine cannot admit a generic receipt past Jira claim."""

from datetime import datetime, timezone
import json
import subprocess

import pytest
import yaml

from genomes_agentic_os import development_delivery as delivery


@pytest.fixture
def task(tmp_path, monkeypatch):
    profile = tmp_path / "development.yml"
    profile.write_text(
        yaml.safe_dump(
            {
                "tracker": {
                    "primary": "jira",
                    "authority": "venturesgo.atlassian.net",
                    "implementation_gate": ["claim-check", "--ticket", "{ticket}"],
                }
            }
        )
    )
    path = tmp_path / "state.json"
    path.write_text(
        json.dumps(
            {
                "schema": "development-task/v1",
                "ticket": "FLYWL-5402",
                "domain": "los",
                "source": {"system": "jira"},
                "profile_source": str(profile),
                "state": "worktree_ready",
                "receipts": [],
                "run_id": "test",
            }
        )
    )
    for name in [
        "_refresh_portfolio_state",
        "_sync_auto_dev_projection",
        "_sync_canonical_task_progress",
    ]:
        monkeypatch.setattr(delivery, name, lambda *a, **k: None)
    monkeypatch.setattr(delivery.TaskState, "emit", lambda *a, **k: None)
    return delivery.TaskState(path)


def passing_claim():
    return {
        "schema": "jira-implementation-claim/v1",
        "status": "passed",
        "ticket": "FLYWL-5402",
        "site": "venturesgo.atlassian.net",
        "assignee_account_id": "michael",
        "developer_account_id": "michael",
        "workflow_status": "In Progress",
        "fix_versions": ["10.1"],
        "source": "live_acli_readback",
        "verified_at": datetime.now(timezone.utc).isoformat(),
    }


@pytest.mark.parametrize(
    "current,target", [("worktree_ready", "planned"), ("planned", "implementing")]
)
def test_failed_gate_cannot_mutate_state_or_accept_generic_receipt(
    task, monkeypatch, current, target
):
    value = task.read()
    value["state"] = current
    task.path.write_text(json.dumps(value))
    before = task.path.read_bytes()
    monkeypatch.setattr(
        delivery.subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(a, 2, "blocked", "private"),
    )
    with pytest.raises(
        delivery.DevelopmentDeliveryError, match="implementation gate blocked"
    ):
        task.transition(target, receipt="generic-local-plan", idempotency_key="attempt")
    assert task.path.read_bytes() == before


def test_success_is_ticket_bound_and_retained_in_state(task, monkeypatch):
    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, json.dumps(passing_claim()), "")

    monkeypatch.setattr(delivery.subprocess, "run", run)
    result = task.transition("planned", receipt="plan", idempotency_key="claim")
    assert calls == [["claim-check", "--ticket", "FLYWL-5402"]]
    assert result["implementation_claim"]["ticket"] == "FLYWL-5402"


@pytest.mark.parametrize(
    "change",
    [
        {"ticket": "FLYWL-1"},
        {"site": "wrong.site"},
        {"workflow_status": "Requirements"},
        {"verified_at": "2020-01-01T00:00:00Z"},
        {"verified_at": "invalid"},
        {"status": "blocked"},
        {"developer_account_id": "someone-else"},
        {"fix_versions": []},
        {"source": "cached"},
    ],
)
def test_invalid_receipt_cannot_unlock_coding(task, monkeypatch, change):
    claim = {**passing_claim(), **change}
    monkeypatch.setattr(
        delivery.subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(a, 0, json.dumps(claim), ""),
    )
    with pytest.raises(delivery.DevelopmentDeliveryError):
        task.transition("planned", receipt="plan", idempotency_key="claim")
    assert task.read()["state"] == "worktree_ready"


def test_los_jira_cannot_silently_omit_gate(task):
    profile = task.read()["profile_source"]
    from pathlib import Path

    Path(profile).write_text(yaml.safe_dump({"tracker": {"primary": "jira"}}))
    with pytest.raises(
        delivery.DevelopmentDeliveryError, match="requires tracker.implementation_gate"
    ):
        task.transition("planned", receipt="plan", idempotency_key="claim")


def test_content_ready_non_jira_task_is_unaffected():
    assert (
        delivery.verify_implementation_claim({"source": {"system": "linear"}}) is None
    )


def test_resume_does_not_reuse_old_live_claim(task, monkeypatch):
    monkeypatch.setattr(
        delivery.subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(
            a, 0, json.dumps(passing_claim()), ""
        ),
    )
    task.transition("planned", receipt="plan", idempotency_key="same")
    monkeypatch.setattr(
        delivery.subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(a, 2, "blocked", ""),
    )
    with pytest.raises(delivery.DevelopmentDeliveryError, match="gate blocked"):
        task.transition("planned", receipt="plan", idempotency_key="same")
    assert task.read()["state"] == "planned"
