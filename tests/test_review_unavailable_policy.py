"""Pinned policy controls native reviewer unavailability, never findings or CI."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest
import jsonschema

from genomes_agentic_os import development_delivery as delivery
from genomes_agentic_os.cli import main
from genomes_agentic_os.review_coordination import (
    ReviewCoordinationError, ReviewCoordinator, ReviewSubject,
    assert_exact_head_review_receipt, load_review_receipt,
)


def _task(tmp_path: Path, *, legacy: bool = False, policy: str = "continue_with_receipt",
          repository_id: str = "github:acme/widgets") -> Path:
    selected = delivery._selected_profile_policy_authority({
        "repository": {"id": repository_id},
        "review": {"opposing_harness": {"required": True, "unavailable_policy": policy}},
    })
    if legacy:
        selected.pop("review")
        selected["sha256"] = delivery._json_sha256({k: v for k, v in selected.items() if k != "sha256"})
    snapshot = {
        "schema": "development-effective-policies/v1",
        "planes": {name: {"sources": [], "fingerprint": hashlib.sha256(b"[]").hexdigest()}
                   for name in delivery.DEVELOPMENT_POLICY_PLANES},
        "selected_profile": selected,
    }
    snapshot["fingerprint"] = delivery._effective_policy_snapshot_fingerprint(snapshot)
    snapshot_path = tmp_path / "policy.json"
    snapshot_path.write_text(json.dumps(snapshot))
    path = tmp_path / "state.json"
    path.write_text(json.dumps({
        "state": "post_pr_review", "os_root": str(tmp_path), "domain": "acme", "project": "widgets",
        "repository": {"id": repository_id}, "work_item": str(tmp_path / "packet"),
        "policy_receipt": str(snapshot_path), "policy_fingerprint": snapshot["fingerprint"],
    }))
    return path


def _receipt(tmp_path: Path, authority: dict, **changes):
    subject = ReviewSubject(repository="acme/widgets", pull_request="42", base_branch="main",
                            base_sha="a" * 40, head_sha="b" * 40,
                            policy_fingerprint=authority["policy_fingerprint"])
    review = {
        "outcome": "unavailable", "reviewer_status": "runtime_failure",
        "failure_code": "cli_runtime_failed", "readback_verified": True,
        "reviewer_transport": "claude_cli", "reviewer_auth": "cli_native",
        "policy_authority": authority, **changes,
    }
    return ReviewCoordinator(tmp_path / "coordination").execute(subject, lambda: review).receipt_path


def _assert(path: Path, authority: dict, **kwargs):
    kwargs = {"base_branch": "main", "base_sha": "a" * 40, **kwargs}
    return assert_exact_head_review_receipt(path, head_sha="b" * 40, repository="github:acme/widgets",
                                          pull_request="42", policy_fingerprint=authority["policy_fingerprint"],
                                          unavailable_authority=authority, **kwargs)


def test_allowed_unavailable_remains_unavailable(tmp_path):
    authority = delivery.resolve_task_review_policy(_task(tmp_path))
    path = _receipt(tmp_path, authority)
    before = path.read_bytes()
    assert _assert(path, authority, base_branch="main", base_sha="a" * 40)["outcome"] == "unavailable"
    assert path.read_bytes() == before


@pytest.mark.parametrize("scrub_passed", [False, "false", "true", None, 0, 1, [], {}])
def test_unavailable_rejects_non_true_explicit_scrub_result(tmp_path, scrub_passed):
    authority = delivery.resolve_task_review_policy(_task(tmp_path))
    path = _receipt(tmp_path, authority, scrub_passed=scrub_passed)
    with pytest.raises(ReviewCoordinationError, match="pinned policy-authorized"):
        _assert(path, authority)


def test_unavailable_accepts_explicit_boolean_scrub_success(tmp_path):
    authority = delivery.resolve_task_review_policy(_task(tmp_path))
    path = _receipt(tmp_path, authority, scrub_passed=True)
    assert _assert(path, authority)["outcome"] == "unavailable"


@pytest.mark.parametrize("top_level", ["missing", "empty"])
def test_unavailable_cannot_hide_nested_open_finding(tmp_path, top_level):
    authority = delivery.resolve_task_review_policy(_task(tmp_path))
    path = _receipt(tmp_path, authority, findings=[{"summary": "Unresolved real defect"}])
    value = json.loads(path.read_text())
    assert value["review"]["findings_ledger"][0]["status"] == "open"
    if top_level == "missing":
        value.pop("findings_ledger")
    else:
        value["findings_ledger"] = []
    path.write_text(json.dumps(value))
    before = path.read_bytes()
    # Legacy normalization remains readable for recovery, never admission.
    assert load_review_receipt(path)["findings_ledger"] == []
    with pytest.raises(ReviewCoordinationError, match="explicit coherent findings ledgers"):
        _assert(path, authority)
    assert path.read_bytes() == before


@pytest.mark.parametrize("location,value", [
    ("top", None), ("nested", None), ("nested", {}), ("nested", "missing"),
])
def test_unavailable_requires_present_typed_ledgers_even_when_empty(tmp_path, location, value):
    authority = delivery.resolve_task_review_policy(_task(tmp_path))
    path = _receipt(tmp_path, authority)
    receipt = json.loads(path.read_text())
    ledger_owner = receipt if location == "top" else receipt["review"]
    if value == "missing":
        ledger_owner.pop("findings_ledger")
    else:
        ledger_owner["findings_ledger"] = value
    path.write_text(json.dumps(receipt))
    with pytest.raises(ReviewCoordinationError, match="explicit coherent findings ledgers"):
        _assert(path, authority)


@pytest.mark.parametrize("changes", [
    {"outcome": "findings", "findings": [{"summary": "Real defect"}]},
    {"findings": [{"summary": "Unresolved parent defect"}]},
    {"failure_code": "head_changed_after_review"}, {"readback_verified": False},
    {"scrub_passed": False}, {"policy_authority": {}}, {"reviewer_auth": "api_key"},
    {"reviewer_status": "available"}, {"failure_code": "unknown"},
])
def test_unavailable_never_waives_invalid_evidence(tmp_path, changes):
    authority = delivery.resolve_task_review_policy(_task(tmp_path))
    with pytest.raises(ReviewCoordinationError):
        _assert(_receipt(tmp_path, authority, **changes), authority)


@pytest.mark.parametrize("legacy", [True, False])
def test_block_and_legacy_policy_deny_unavailability_but_accept_clean(tmp_path, legacy):
    authority = delivery.resolve_task_review_policy(_task(tmp_path, legacy=legacy, policy="block"))
    with pytest.raises(ReviewCoordinationError, match="pinned policy-authorized"):
        _assert(_receipt(tmp_path, authority), authority)
    path = _receipt(tmp_path, authority, outcome="clean")
    assert _assert(path, authority)["outcome"] == "clean"


@pytest.mark.parametrize("field,value", [("head_sha", "c" * 40), ("policy_fingerprint", "d" * 64),
                                        ("base_sha", "e" * 40), ("repository", "acme/other")])
def test_subject_drift_rejected(tmp_path, field, value):
    authority = delivery.resolve_task_review_policy(_task(tmp_path))
    path = _receipt(tmp_path, authority)
    kwargs = {"head_sha": "b" * 40, "policy_fingerprint": authority["policy_fingerprint"], field: value}
    with pytest.raises(ReviewCoordinationError, match="drifted"):
        assert_exact_head_review_receipt(path, unavailable_authority=authority, **kwargs)


def _current_profile(tmp_path, monkeypatch, policy="continue_with_receipt"):
    profile = {"repository": {"id": "github:acme/widgets", "root": str(tmp_path)},
               "review": {"opposing_harness": {"unavailable_policy": policy}}}
    source = tmp_path / "development.yml"
    source.write_text(json.dumps(profile))
    monkeypatch.setattr(delivery, "load_development_profile", lambda *_: (profile, source))
    return profile, source


def test_explicit_legacy_binding_preserves_original_and_does_not_reread_config(tmp_path, monkeypatch):
    path = _task(tmp_path, legacy=True)
    original = path.read_bytes()
    snapshot = (tmp_path / "policy.json").read_bytes()
    profile, source = _current_profile(tmp_path, monkeypatch)
    fingerprint = json.loads(original)["policy_fingerprint"]
    args = ["develop", "bind-review-policy", str(path), "--expected-policy-fingerprint", fingerprint,
            "--reason", "Explicit migration of omitted review policy", "--json"]
    assert main(args) == 0
    assert not (tmp_path / "review-policy-binding.json").exists()
    assert main([*args, "--apply"]) == 0
    schema = json.loads((Path(__file__).parents[1] / "schemas/development-review-policy-binding.schema.json").read_text())
    jsonschema.validate(json.loads((tmp_path / "review-policy-binding.json").read_text()), schema)
    authority = delivery.resolve_task_review_policy(path)
    assert authority["policy_fingerprint"] == fingerprint
    assert authority["binding_sha256"] is not None
    assert authority["unavailable_policy"] == "continue_with_receipt"
    profile["review"]["opposing_harness"]["unavailable_policy"] = "block"
    source.unlink()
    assert delivery.resolve_task_review_policy(path) == authority
    assert delivery.bind_task_review_policy(path, expected_policy_fingerprint=fingerprint, reason="retry", apply=True)["reused"]
    assert path.read_bytes() == original
    assert (tmp_path / "policy.json").read_bytes() == snapshot
    assert len((tmp_path / "events.jsonl").read_text().splitlines()) == 1


@pytest.mark.parametrize("remote,configured_id,accepted", [
    ("git@github.com:acme/widgets.git", None, True),
    ("https://github.com/acme/widgets.git", None, True),
    ("git@github.com:acme/other.git", None, False),
    ("git@github.com:acme/widgets.git", "git:github.com/acme/other", False),
])
def test_legacy_binding_uses_same_repository_identity_as_task_creation(
    tmp_path, monkeypatch, remote, configured_id, accepted,
):
    repository_id = "git:github.com/acme/widgets"
    path = _task(tmp_path, legacy=True, repository_id=repository_id)
    profile, source = _current_profile(tmp_path, monkeypatch)
    checkout = tmp_path / "checkout"
    subprocess.run(["git", "init", str(checkout)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(checkout), "remote", "add", "origin", remote],
                   check=True, capture_output=True)
    profile["repository"] = {"root": str(checkout)}
    if configured_id is not None:
        profile["repository"]["id"] = configured_id
    source.write_text(json.dumps(profile))
    original = path.read_bytes()
    snapshot = (tmp_path / "policy.json").read_bytes()
    fingerprint = json.loads(original)["policy_fingerprint"]
    kwargs = {"expected_policy_fingerprint": fingerprint, "reason": "Migrate omitted policy"}
    if accepted:
        preview = delivery.bind_task_review_policy(path, **kwargs)
        assert preview["binding"]["repository_id"] == repository_id
        assert not (tmp_path / "review-policy-binding.json").exists()
        bound = delivery.bind_task_review_policy(path, **kwargs, apply=True)
        assert bound["authority"]["unavailable_policy"] == "continue_with_receipt"
        assert bound["authority"]["policy_fingerprint"] == fingerprint
    else:
        with pytest.raises(delivery.DevelopmentDeliveryError, match="repository does not match"):
            delivery.bind_task_review_policy(path, **kwargs, apply=True)
        assert not (tmp_path / "review-policy-binding.json").exists()
        assert not (tmp_path / "events.jsonl").exists()
    assert path.read_bytes() == original
    assert (tmp_path / "policy.json").read_bytes() == snapshot


@pytest.mark.parametrize("corruption", ["snapshot", "task", "binding_digest", "binding_subject", "source_provenance"])
def test_binding_provenance_drift_rejected(tmp_path, monkeypatch, corruption):
    path = _task(tmp_path, legacy=True)
    _current_profile(tmp_path, monkeypatch)
    fingerprint = json.loads(path.read_text())["policy_fingerprint"]
    delivery.bind_task_review_policy(path, expected_policy_fingerprint=fingerprint, reason="migration", apply=True)
    target = tmp_path / ("policy.json" if corruption == "snapshot" else "state.json" if corruption == "task" else "review-policy-binding.json")
    value = json.loads(target.read_text())
    if corruption == "snapshot":
        value["selected_profile"]["validation"]["forged"] = True
    elif corruption == "task":
        value["policy_fingerprint"] = "f" * 64
    elif corruption in {"binding_subject", "source_provenance"}:
        value["task_state_ref" if corruption == "binding_subject" else "profile_source_sha256"] = "/other/state.json"
        value["sha256"] = delivery._json_sha256({k: v for k, v in value.items() if k != "sha256"})
    else:
        value["review"]["opposing_harness"]["unavailable_policy"] = "block"
    target.write_text(json.dumps(value))
    with pytest.raises(delivery.DevelopmentDeliveryError):
        delivery.resolve_task_review_policy(path)


def test_new_snapshot_cannot_be_rebound(tmp_path):
    path = _task(tmp_path, policy="block")
    fingerprint = json.loads(path.read_text())["policy_fingerprint"]
    with pytest.raises(delivery.DevelopmentDeliveryError, match="already pins"):
        delivery.bind_task_review_policy(path, expected_policy_fingerprint=fingerprint, reason="cannot override", apply=True)


def test_review_change_is_in_snapshot_fingerprint(tmp_path):
    path = _task(tmp_path, policy="block")
    before = delivery.resolve_task_review_policy(path)
    path = _task(tmp_path, policy="continue_with_receipt")
    assert delivery.resolve_task_review_policy(path)["policy_fingerprint"] != before["policy_fingerprint"]


@pytest.mark.parametrize("state", ["ready_for_merge", "merged", "deployment_pending", "blocked"])
def test_binding_cannot_reopen_readiness_or_terminal_task(tmp_path, state):
    path = _task(tmp_path, legacy=True)
    task = json.loads(path.read_text())
    task["state"] = state
    path.write_text(json.dumps(task))
    with pytest.raises(delivery.DevelopmentDeliveryError, match="pre-readiness"):
        delivery.bind_task_review_policy(path, expected_policy_fingerprint=task["policy_fingerprint"], reason="late", apply=True)
    assert not (tmp_path / "review-policy-binding.json").exists()


def test_binding_rejects_wrong_original_fingerprint(tmp_path):
    path = _task(tmp_path, legacy=True)
    with pytest.raises(delivery.DevelopmentDeliveryError, match="original policy fingerprint"):
        delivery.bind_task_review_policy(path, expected_policy_fingerprint="f" * 64, reason="wrong", apply=True)


def test_binding_does_not_reset_provider_family_budget(tmp_path, monkeypatch):
    path = _task(tmp_path, legacy=True)
    old = delivery.resolve_task_review_policy(path)
    original = _receipt(tmp_path, old, outcome="findings", findings=[{"summary": "Real existing defect"}])
    original_bytes = original.read_bytes()
    _current_profile(tmp_path, monkeypatch)
    delivery.bind_task_review_policy(path, expected_policy_fingerprint=old["policy_fingerprint"], reason="migration", apply=True)
    new = delivery.resolve_task_review_policy(path)
    assert old["context_sha256"] != new["context_sha256"]
    assert _receipt(tmp_path, new) == original
    assert original.read_bytes() == original_bytes
    with pytest.raises(ReviewCoordinationError, match="pinned policy-authorized"):
        _assert(original, new)


@pytest.mark.parametrize("policy,exit_code", [("block", 2), ("continue_with_receipt", 0)])
def test_canonical_runner_propagates_pinned_policy_to_all_receipts(tmp_path, monkeypatch, policy, exit_code):
    runner_path = Path(__file__).parents[1] / "harness/skills/auto-dev-review-self-opposing-model/scripts/run_opposing_model_review.py"
    spec = importlib.util.spec_from_file_location("policy_test_runner", runner_path)
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    path = _task(tmp_path, policy=policy)
    task = json.loads(path.read_text())
    packet = Path(task["work_item"])
    packet.mkdir()
    worktree = tmp_path / "checkout"
    worktree.mkdir()
    task["worktree"] = {"path": str(worktree)}
    path.write_text(json.dumps(task))
    (packet / "autodev.json").write_text(json.dumps({"delivery": {
        "task_state_ref": str(path), "policy_fingerprint": task["policy_fingerprint"],
    }}))
    source = {"base_sha": "a" * 40, "policy_fingerprint": task["policy_fingerprint"],
              "pr_number": 42, "work_item_id": "TEST-1", "review_unavailable_policy": "continue_with_receipt"}
    provider = {"headRefOid": "b" * 40, "baseRefOid": "a" * 40, "baseRefName": "main",
                "url": "https://example.test/acme/widgets/pull/42", "statusCheckRollup": []}
    monkeypatch.setattr(runner, "resolve_os_root", lambda _: tmp_path)
    monkeypatch.setattr(runner, "project_identity", lambda *_: ("acme", "widgets"))
    monkeypatch.setattr(runner, "prior_request", lambda *_: source)
    monkeypatch.setattr(runner, "load_development_profile", lambda *_: ({"repository": {"root": str(worktree)}}, tmp_path / "config.yml"))
    monkeypatch.setattr(runner, "git_head", lambda *_: "b" * 40)
    monkeypatch.setattr(runner, "provider_pr", lambda *_: provider)
    monkeypatch.setattr(runner, "git_repository", lambda *_: "acme/widgets")
    monkeypatch.setattr(runner, "diff_hash", lambda *_: "d" * 64)
    monkeypatch.setattr(runner, "render_prompt", lambda *_: "read-only review")
    monkeypatch.setattr(runner.shutil, "which", lambda _: None)
    monkeypatch.setattr(runner, "decide", lambda *_: {"decision": "ready_with_unavailable_receipt"})
    monkeypatch.setattr(sys, "argv", [str(runner_path), "TEST-1", "--work-item", str(packet), "--worktree", str(worktree)])
    assert runner.main() == exit_code
    run_dir = next((packet / "artifacts/finishing-touches/review-runs").iterdir())
    request = json.loads((run_dir / "review-request.json").read_text())
    plan = json.loads((run_dir / "validation-plan.json").read_text())
    receipt = json.loads((run_dir / "opposing-model-review-receipt.json").read_text())
    assert request["policy_authority"] == delivery.resolve_task_review_policy(path)
    assert plan["review_unavailable_policy"] == policy
    assert policy in (run_dir / "model-receipt.md").read_text()
    assert receipt["outcome"] == "unavailable"
    assert receipt["policy_admitted"] is (exit_code == 0)
    assert receipt["failure_code"] == "cli_not_found"
    assert receipt["policy_authority"] == request["policy_authority"]
