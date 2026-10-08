"""Native prior-request authority stays historical across a new exact subject."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

import genomes_agentic_os.development_delivery as delivery
from genomes_agentic_os.review_coordination import ReviewSubject, review_family_key, stable_review_key
from test_merge_tooling_compat import _task
from test_opposing_model_review_runner import _load_runner


def _write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _bound_seed(tmp_path, monkeypatch, *, policy="continue_with_receipt"):
    state, _root, repo, base = _task(tmp_path, monkeypatch, review_policy=policy)
    task = state.read()
    packet = Path(task["work_item"])
    stages = Path(task["policy_receipt"]).parent / "tasks" / "cc-54" / "stages"

    def family(label, head, target):
        evidence = packet / "artifacts/development-delivery/evidence" / f"{label}.json"
        payload = {"schema": "development-stage-evidence/v1", "state": "release_propagation", "status": "completed",
                   "evidence": {"ticket": "CC-54", "repository": task["repository"]["id"],
                                "canonical_run_policy_fingerprint": task["policy_fingerprint"],
                                "targets": [{"repository": task["repository"]["id"], "provider": "github",
                                             "ticket": "CC-54", "number": 54, "url": "https://github.com/acme/app/pull/54",
                                             "base_branch": "main", "base_sha": target, "head_sha": head,
                                             "source_branch": "feature/cc-54", "classification": "pr_required",
                                             "provider_readback_verified": True}]}}
        _write_json(evidence, payload)
        wrapper = stages / f"{label}.json"
        checksum = _write_json(wrapper, {"schema": "development-stage-receipt/v1", "stage": "release_propagation",
                                         "receipt": str(evidence), "evidence_sha256": delivery._json_sha256(payload)})
        return {"ref": str(wrapper), "sha256": checksum}

    old_descriptor = family("historical", "c" * 40, base)
    # A legitimate task goal/family advance does not change frozen policy.
    task["goal"] = task["auto_dev_completion_stage"] = "merge"
    task.setdefault("stage_receipts", {})["release_propagation"] = family("current", "b" * 40, "e" * 40)
    member = delivery.verified_review_family_member(task, head_sha="b" * 40, source_branch="feature/cc-54")
    historical = delivery._verified_review_family_member_from_descriptor(
        task, old_descriptor, head_sha="c" * 40, source_branch="feature/cc-54",
    )
    profile_path = Path(task["profile_source"])
    selected = delivery.select_development_repository(delivery._read_mapping(profile_path), None)
    authority = delivery.selected_review_profile_authority(task, selected, profile_path, None)
    request = {"work_item_id": "CC-54", "head_sha": "c" * 40, "base_sha": base, "target_branch": "main",
               "pr_number": 54, "repo_path": str(repo), "repository": "acme/app",
               "source_worktree_branch": "feature/cc-54", "policy_fingerprint": task["policy_fingerprint"],
               "request_origin": "verified_current_pr_family", "reviewer_selection_source": "auto-dev-review-self-opposing-model",
               "reviewer_transport": "claude_cli", "review_unavailable_policy": policy,
               "reviewer_model": "claude-fable-5", "selected_reviewer_model": "claude-fable-5",
               "selected_review_authority": authority, "source_family_authority": historical,
               "review_key": "1" * 64, "parent_key": "2" * 64}
    native = packet / "artifacts/finishing-touches/historical/attempt-original/review-request.json"
    checksum = _write_json(native, request)
    proof = {"schema": "historical-review-seed-provenance/v1", "kind": "prior_request", "ref": str(native),
             "sha256": checksum, "original_request": request, "original_policy_fingerprint": request["policy_fingerprint"]}
    # The validator may read only the profile's local Git identity, never a
    # coordinator, provider, reviewer or lifecycle command.
    actual_run = delivery.subprocess.run
    def read_only(argv, **kwargs):
        assert argv == ["git", "-C", str(repo), "config", "--get", "remote.origin.url"]
        return actual_run(argv, **kwargs)
    monkeypatch.setattr(delivery.subprocess, "run", read_only)
    return state, task, member, proof


@pytest.mark.parametrize("policy", ["continue_with_receipt", "block"])
def test_native_seed_retains_immutable_old_authority_and_independent_current_subject(tmp_path, monkeypatch, policy):
    state, task, member, proof = _bound_seed(tmp_path, monkeypatch, policy=policy)
    paths = [state.path, Path(task["policy_receipt"]), Path(proof["ref"]),
             Path(proof["original_request"]["source_family_authority"]["wrapper_ref"]),
             Path(proof["original_request"]["source_family_authority"]["evidence_ref"])]
    before = {path: path.read_bytes() for path in paths}
    original = deepcopy(proof["original_request"])
    source = {**original, "_native_source": {key: proof[key] for key in ("kind", "ref", "sha256")}}
    result = delivery.historical_review_seed_provenance(source, task, member)
    assert result == proof
    assert result["original_request"]["selected_review_authority"] == original["selected_review_authority"]
    assert result["original_request"]["source_family_authority"]["head_sha"] == "c" * 40
    assert member["head_sha"] == "b" * 40
    assert result["original_request"]["base_sha"] != "e" * 40
    assert result["original_request"]["review_key"] == "1" * 64
    assert result["original_request"]["parent_key"] == "2" * 64
    old_subject = ReviewSubject("acme/app", "54", "main", original["base_sha"],
                                original["head_sha"], task["policy_fingerprint"], "review_self")
    current_subject = ReviewSubject("acme/app", "54", "main", "e" * 40,
                                    member["head_sha"], task["policy_fingerprint"], "review_self")
    assert review_family_key(old_subject) == review_family_key(current_subject)
    assert stable_review_key(old_subject) != stable_review_key(current_subject)
    assert _load_runner().review_unavailable_policy(original, delivery._read_mapping(Path(task["profile_source"]))) == policy
    assert {path: path.read_bytes() for path in paths} == before


def _refresh_native(proof):
    proof["sha256"] = _write_json(Path(proof["ref"]), proof["original_request"])


@pytest.mark.parametrize("mutation", [
    "partial_selected", "partial_family", "empty_selected", "empty_family", "selected_profile_hash",
    "selected_policy_hash", "selected_policy_ref", "selected_profile_ref", "selected_repo", "selected_base",
    "selected_policy", "selected_harness", "old_family_repo", "old_family_pr", "old_family_branch", "old_family_head",
    "wrapper_hash", "evidence_hash", "wrapper_other_task", "evidence_other_packet", "old_base", "same_head",
    "request_pr", "request_branch", "request_repository", "request_ticket", "request_policy", "request_origin",
    "request_model", "request_unavailable_policy", "request_transport", "raw_hash", "raw_request_mismatch",
    "current_member_hash", "current_member_head", "current_member_base", "current_descriptor_hash", "other_task_run",
    "other_task_ticket", "other_task_policy", "effective_policy",
])
def test_authority_bound_historical_seed_rejects_hostile_provenance(tmp_path, monkeypatch, mutation):
    state, task, member, proof = _bound_seed(tmp_path, monkeypatch)
    request = proof["original_request"]
    authority, family = request["selected_review_authority"], request["source_family_authority"]
    if mutation == "partial_selected": request.pop("source_family_authority")
    elif mutation == "partial_family": request.pop("selected_review_authority")
    elif mutation == "empty_selected": request["selected_review_authority"] = {}
    elif mutation == "empty_family": request["source_family_authority"] = {}
    elif mutation.startswith("selected_"):
        key = {"selected_profile_hash": "profile_sha256", "selected_policy_hash": "task_policy_sha256",
               "selected_policy_ref": "task_policy_ref", "selected_profile_ref": "profile_ref", "selected_repo": "repository",
               "selected_base": "task_primary_base_branch", "selected_policy": "task_policy_fingerprint"}.get(mutation)
        if key: authority[key] = "foreign"
        else: authority["opposing_harness"]["required"] = False
    elif mutation.startswith("old_family_"):
        key = {"old_family_repo": "repository", "old_family_pr": "number", "old_family_branch": "source_branch",
               "old_family_head": "head_sha"}[mutation]
        family[key] = 55 if key == "number" else "foreign"
    elif mutation == "wrapper_hash": family["wrapper_sha256"] = "0" * 64
    elif mutation == "evidence_hash": family["evidence_sha256"] = "0" * 64
    elif mutation == "wrapper_other_task":
        path = tmp_path / "other-task/stages/historical.json"
        path.parent.mkdir(parents=True); path.write_bytes(Path(family["wrapper_ref"]).read_bytes()); family["wrapper_ref"] = str(path)
    elif mutation == "evidence_other_packet":
        path = tmp_path / "other-packet/evidence.json"
        path.parent.mkdir(parents=True); path.write_bytes(Path(family["evidence_ref"]).read_bytes()); family["evidence_ref"] = str(path)
    elif mutation == "old_base": request["base_sha"] = "f" * 40
    elif mutation == "same_head": request["head_sha"] = member["head_sha"]
    elif mutation.startswith("request_"):
        key = {"request_pr": "pr_number", "request_branch": "source_worktree_branch", "request_repository": "repository",
               "request_ticket": "work_item_id", "request_policy": "policy_fingerprint", "request_origin": "request_origin",
               "request_model": "reviewer_model", "request_unavailable_policy": "review_unavailable_policy",
               "request_transport": "reviewer_transport"}[mutation]
        request[key] = 55 if key == "pr_number" else "foreign"
    elif mutation == "current_member_hash": member["wrapper_sha256"] = "0" * 64
    elif mutation == "current_member_head": member["head_sha"] = "f" * 40
    elif mutation == "current_member_base": member["base_branch"] = "foreign"
    elif mutation == "current_descriptor_hash": task["stage_receipts"]["release_propagation"]["sha256"] = "0" * 64
    elif mutation == "other_task_run": task["run_id"] = "foreign"
    elif mutation == "other_task_ticket": task["ticket"] = "CC-55"
    elif mutation == "other_task_policy": task["policy_fingerprint"] = "f" * 64
    elif mutation == "effective_policy": request["effective_policy"] = {"unavailable_policy": "continue_with_receipt"}
    _refresh_native(proof)
    if mutation == "raw_hash": proof["sha256"] = "0" * 64
    if mutation == "raw_request_mismatch": request["implementation_summary"] = "different bytes"
    state_before = state.path.read_bytes()
    with pytest.raises(delivery.DevelopmentDeliveryError):
        delivery.validate_historical_review_seed_provenance(proof, task, member)
    assert state.path.read_bytes() == state_before


@pytest.mark.parametrize("mutation", ["canonical_policy", "ticket", "repository", "base_alias", "duplicate_member", "corrupt_payload"])
def test_historical_family_rehashing_cannot_forge_semantic_authority(tmp_path, monkeypatch, mutation):
    _state, task, member, proof = _bound_seed(tmp_path, monkeypatch)
    family = proof["original_request"]["source_family_authority"]
    path = Path(family["evidence_ref"])
    payload = json.loads(path.read_text())
    details = payload["evidence"]
    if mutation == "canonical_policy": details["canonical_run_policy_fingerprint"] = "f" * 64
    elif mutation in ("ticket", "repository"): details[mutation] = "foreign"
    elif mutation == "base_alias": details["targets"][0]["actual_target_ref_sha"] = "f" * 40
    elif mutation == "duplicate_member": details["targets"].append(deepcopy(details["targets"][0]))
    _write_json(path, payload)
    if mutation != "corrupt_payload":
        wrapper_path = Path(family["wrapper_ref"])
        wrapper = json.loads(wrapper_path.read_text())
        wrapper["evidence_sha256"] = family["evidence_sha256"] = delivery._json_sha256(payload)
        family["wrapper_sha256"] = _write_json(wrapper_path, wrapper)
        _refresh_native(proof)
    else:
        payload["evidence"]["ticket"] = "unhashed change"
        _write_json(path, payload)
    with pytest.raises(delivery.DevelopmentDeliveryError):
        delivery.validate_historical_review_seed_provenance(proof, task, member)
