"""Native scratch-state regression for one accepted prior GitHub identity shape.

The provider observation is an explicit fixture boundary. Git repositories,
worktree registration, task transitions, CLI parsing, immutable wrappers and
idempotent projection behavior use their actual implementations. No reviewer,
provider service, production state or coverage result is represented by setup.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from typing import Any

import pytest

from genomes_agentic_os import development_delivery as delivery
from genomes_agentic_os.cli import main
from test_development_delivery import (
    _git, _project, _record_standalone_stage, _repository, _stage_receipt,
)


def _write_family(packet: Path, name: str, details: dict[str, Any]) -> Path:
    path = packet / "artifacts" / "compatibility-input" / f"{name}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "schema": "development-stage-evidence/v1", "state": "release_propagation",
        "status": "completed", "summary": "Explicit fixture provider-family observation",
        "verified_at": "2026-10-27T23:00:00Z", "evidence": details,
    }, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _record(task: delivery.TaskState, receipt: Path, key: str) -> int:
    return main([
        "develop", "stage", str(task.path), "--stage", "release_propagation",
        "--receipt", "release_propagation=" + str(receipt),
        "--idempotency-prefix", key, "--json",
    ])


def _fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
             prior_override: dict[str, Any] | None = None) -> dict[str, Any]:
    monkeypatch.delenv("AGENTIC_OS_ROOT", raising=False)
    repo, old_head = _repository(tmp_path)
    root = tmp_path / "os"
    _project(root, repo, repository_id="git:github.com/acme/app")
    run = delivery.start_development_run(
        root, "acme", "app", ["CC-59"],
        run_id="qualified-pr-prior-repository", auto_dev_mode="everything", apply=True,
    )
    task = delivery.TaskState(Path(run["tasks"][0]["state_ref"]))
    initial = task.read()
    tree = Path(initial["worktree"]["path"])
    branch = initial["worktree"]["branch"]
    assert tree.is_dir()
    assert _git("branch", "--show-current", cwd=tree) == branch
    assert _git("rev-parse", "HEAD", cwd=tree) == old_head
    packet = Path(initial["work_item"])
    check = subprocess.run(
        [sys.executable, "-c", "from pathlib import Path; assert Path('README.md').is_file()"],
        cwd=tree, capture_output=True, text=True, check=True,
    )
    for state_name in ("planned", "implementing", "local_validation"):
        task.transition(
            state_name,
            receipt=_stage_receipt(packet / "artifacts" / "fixture-transitions", state_name,
                evidence={"fixture_command": "assert actual scratch README exists",
                          "exit_code": check.returncode, "head_sha": old_head}),
            idempotency_key="fixture:" + state_name,
        )
    for stage_name in ("groom", "detective", "create_artifacts", "document"):
        _record_standalone_stage(task, stage_name)
    assert task.read()["state"] == "local_validation"
    assert "validation_refreshes" not in task.read()
    pull_request = "github:acme/app#59"
    url = "https://github.com/acme/app/pull/59"
    prior = {
        "ticket": "CC-59", "repository": "acme/app", "provider": "github",
        "base_branch": "main", "base_sha": old_head, "pull_request": pull_request,
        "source_branch": branch, "source_head_sha": old_head,
        "readback_verified": True,
        "family": [{"repository": "acme/app", "provider": "github",
                    "base_branch": "main", "base_sha": old_head,
                    "pull_request": pull_request, "source_branch": branch,
                    "head_sha": old_head, "number": 59, "url": url,
                    "readback_verified": True, "state": "OPEN", "draft": False}],
    }
    prior.update(prior_override or {})
    old = _write_family(packet, "prior", prior)
    assert _record(task, old, "cc-59:prior") == 0
    wrapper = Path(task.read()["stage_receipts"]["release_propagation"]["ref"])
    wrapper_value = json.loads(wrapper.read_text())
    prior_snapshot = packet / wrapper_value["receipt"]
    (tree / "README.md").write_text("actual committed refreshed scratch source\n", encoding="utf-8")
    _git("add", "README.md", cwd=tree)
    _git("commit", "-m", "fix: actual scratch family successor", cwd=tree)
    new_head = _git("rev-parse", "HEAD", cwd=tree)
    assert new_head != old_head
    observed = {
        "repository": "git:github.com/acme/app", "provider": "github",
        "base_branch": "main", "base_sha": old_head, "pull_request": pull_request,
        "source_branch": branch, "head_sha": new_head, "url": url,
        "readback_verified": True,
    }
    refreshed = {
        **{k: v for k, v in observed.items() if k != "head_sha"},
        "ticket": "CC-59", "source_head_sha": new_head,
        "provider_observed": observed,
        "supersession": {"supersedes_source_head_sha": old_head,
                         "reason": "The fixture provider observed the genuinely committed new head."},
    }
    local = [row for row in task.read()["receipts"] if row["state"] == "local_validation"][-1]
    retained = [old, wrapper, prior_snapshot, Path(local["ref"])]
    return {"task": task, "packet": packet, "old": old, "wrapper": wrapper,
            "retained": {str(p): p.read_bytes() for p in retained},
            "prior": prior, "refreshed": refreshed, "old_head": old_head,
            "new_head": new_head, "branch": branch}


def _assert_retained(fixture: dict[str, Any]) -> None:
    for name, contents in fixture["retained"].items():
        assert Path(name).read_bytes() == contents


def test_refreshes_selected_bare_repository_with_qualified_pr(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    """The actual old shape appends a normalized wrapper, preserving original bytes."""
    f = _fixture(tmp_path, monkeypatch)
    capsys.readouterr()
    before = f["task"].read()
    new = _write_family(f["packet"], "current", f["refreshed"])
    assert _record(f["task"], new, "cc-59:refresh") == 0
    result = json.loads(capsys.readouterr().out)
    assert result["supersedes"]["source_head_sha"] == f["old_head"]
    assert result["supersedes"]["legacy_identity_normalization"] == {
        "identity_shape": "bare_repository_qualified_github_pull_request",
        "field": "repository", "source": "prior_evidence.evidence.repository",
        "from": "acme/app", "value": "git:github.com/acme/app",
        "verified_by": "provider_observed.repository",
    }
    after = f["task"].read()
    assert after["stage_receipts"]["release_propagation"] != before["stage_receipts"]["release_propagation"]
    for key in ("state", "run_id", "ticket", "canonical_work_id", "work_item", "worktree",
                "receipts", "attempts", "max_attempts", "failure", "lease", "authorship"):
        assert after.get(key) == before.get(key)
    _assert_retained(f)
    state_bytes = f["task"].path.read_bytes()
    ledger_bytes = f["task"].ledger.read_bytes()
    assert _record(f["task"], new, "cc-59:refresh") == 0
    capsys.readouterr()
    assert f["task"].path.read_bytes() == state_bytes
    assert f["task"].ledger.read_bytes() == ledger_bytes
    _assert_retained(f)


@pytest.mark.parametrize("fault", [
    "prior_repository", "prior_pr", "prior_provider", "prior_base", "prior_branch",
    "prior_missing_branch", "prior_head", "prior_readback",
    "new_repository", "new_pr", "new_provider", "new_base", "new_branch",
    "new_head", "same_head", "missing_supersession", "wrong_supersession", "empty_reason",
    "observed_repository", "observed_pr", "observed_provider", "observed_base",
    "observed_base_sha", "missing_base_sha", "observed_branch", "observed_head",
    "observed_readback", "observed_url", "missing_observed_repository",
])
def test_foreign_or_incomplete_qualified_prior_identity_refuses_without_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], fault: str,
) -> None:
    """Only an exact task/prior/new/provider join can admit this compatibility shape."""
    prior = {
        "prior_repository": {"repository": "acme/other"},
        "prior_pr": {"pull_request": "github:acme/app#60"},
        "prior_provider": {"provider": "gitlab"},
        "prior_base": {"base_branch": "release"},
        "prior_branch": {"source_branch": "feature/foreign"},
        "prior_missing_branch": {"source_branch": None},
        "prior_head": {"source_head_sha": "invalid"},
        "prior_readback": {"readback_verified": False},
    }.get(fault, {})
    f = _fixture(tmp_path, monkeypatch, prior)
    capsys.readouterr()
    new = deepcopy(f["refreshed"])
    observed = new["provider_observed"]
    new.update({
        "new_repository": {"repository": "git:github.com/acme/other"},
        "new_pr": {"pull_request": "github:acme/app#60"},
        "new_provider": {"provider": "gitlab"},
        "new_base": {"base_branch": "release"},
        "new_branch": {"source_branch": "feature/foreign"},
        "new_head": {"source_head_sha": "invalid"},
        "same_head": {"source_head_sha": f["old_head"]},
    }.get(fault, {}))
    observed.update({
        "observed_repository": {"repository": "git:github.com/acme/other"},
        "observed_pr": {"pull_request": "github:acme/app#60"},
        "observed_provider": {"provider": "gitlab"},
        "observed_base": {"base_branch": "release"},
        "observed_base_sha": {"base_sha": "e" * 40},
        "observed_branch": {"source_branch": "feature/foreign"},
        "observed_head": {"head_sha": "e" * 40},
        "observed_readback": {"readback_verified": False},
        "observed_url": {"url": "https://github.com/acme/other/pull/59"},
    }.get(fault, {}))
    if fault == "missing_observed_repository":
        observed.pop("repository")
    elif fault == "missing_base_sha":
        new.pop("base_sha")
        observed.pop("base_sha")
    elif fault == "missing_supersession":
        new.pop("supersession")
    elif fault == "wrong_supersession":
        new["supersession"]["supersedes_source_head_sha"] = "e" * 40
    elif fault == "empty_reason":
        new["supersession"]["reason"] = ""
    receipt = _write_family(f["packet"], "foreign", new)
    task_bytes = f["task"].path.read_bytes()
    ledger_bytes = f["task"].ledger.read_bytes()
    projection = Path(f["task"].read()["autodev_path"])
    projection_bytes = projection.read_bytes()
    assert _record(f["task"], receipt, "cc-59:unsafe") == 2
    assert "release propagation refresh" in capsys.readouterr().err
    assert f["task"].path.read_bytes() == task_bytes
    assert f["task"].ledger.read_bytes() == ledger_bytes
    assert projection.read_bytes() == projection_bytes
    _assert_retained(f)
