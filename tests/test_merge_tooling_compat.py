"""Offline regressions for exact receipt compatibility; no provider writes."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest
import yaml

import genomes_agentic_os.auto_dev_orchestration as auto_dev
import genomes_agentic_os.development_delivery as delivery
from genomes_agentic_os.review_coordination import (
    ReviewCoordinationError, assert_exact_head_review_receipt, load_review_receipt,
)
from test_development_delivery import (
    _advance_auto_dev_task_to_ready, _project, _record_standalone_stage,
    _repository, _stage_receipt, _git, _provider_authority,
)
from test_opposing_model_review_runner import _load_runner


def _task(tmp_path, monkeypatch, *, review_policy="continue_with_receipt",
          profile_base="main", task_base=None):
    repo, base = _repository(tmp_path)
    _git("checkout", "-b", "feature/cc-54", cwd=repo)
    root = tmp_path / "os"
    project = _project(root, repo, repository_id="git:github.com/acme/app")
    profile_path = project / "config/development.yml"
    profile = yaml.safe_load(profile_path.read_text())
    profile["repository"]["base_branch"] = profile_base
    profile["review"]["opposing_harness"].update({
        "model": "claude-fable-5", "transport": "claude_cli",
        "unavailable_policy": review_policy,
    })
    profile_path.write_text(yaml.safe_dump(profile))
    for branch in {profile_base, task_base} - {None, "main"}:
        _git("branch", branch, cwd=repo)
    monkeypatch.setattr(delivery, "create_isolated_worktree", lambda **_kwargs: {
        "name": "compat", "path": str(repo), "branch": "feature/cc-54", "base_sha": base,
    })
    run = delivery.start_development_run(
        root, "acme", "app", ["CC-54"], run_id="compat",
        auto_dev_mode="everything", base_branch=task_base, apply=True,
    )
    return delivery.TaskState(Path(run["tasks"][0]["state_ref"])), root, repo, base


def test_develop_health_consumes_only_bound_frozen_infrastructure_deferral(tmp_path, monkeypatch):
    task, _root, _repo, _base = _task(tmp_path, monkeypatch)
    for stage in ("groom", "detective", "create_artifacts"):
        _record_standalone_stage(task, stage)
    delivery.run_development_stage(task.path, stage="readiness", receipts={
        "planned": _stage_receipt(tmp_path, "planned"),
    }, idempotency_prefix="compat:readiness")
    raw = _stage_receipt(tmp_path, "local_validation", status="deferred_to_ci", evidence={
        "compile": "passed", "unavailable_check": {
            "command": "pytest tests", "classification": "infrastructure",
            "reason": "isolated database fixture unavailable",
        },
    })
    delivery.run_development_stage(task.path, stage="implementation", receipts={
        "implementing": _stage_receipt(tmp_path, "implementing"),
        "local_validation": raw,
    }, idempotency_prefix="compat:implementation")
    work_item = Path(task.read()["work_item"])
    recorded = Path(next(row["ref"] for row in reversed(task.read()["receipts"]) if row["state"] == "local_validation"))
    immutable = recorded.read_bytes()
    result = auto_dev._validate_health_stage_source(work_item, "develop", "completed", recorded)
    assert result["status"] == "deferred_to_ci"
    assert recorded.read_bytes() == immutable
    with pytest.raises(auto_dev.AutoDevStateError, match="malformed or not terminal"):
        auto_dev._validate_health_stage_source(work_item, "review_self", "completed", recorded)
    frozen = Path(task.read()["policy_receipt"])
    frozen.write_text(frozen.read_text().replace('"ci_fallback_on_environment_failure": true', '"ci_fallback_on_environment_failure": false'))
    with pytest.raises(auto_dev.AutoDevStateError, match="selected repository authority|fingerprint"):
        auto_dev._validate_health_stage_source(work_item, "develop", "completed", recorded)


def _flat_family(tmp_path):
    head = "a" * 40
    native = tmp_path / "native.json"
    native.write_text(json.dumps({
        "number": 54, "url": "https://github.com/acme/app/pull/54", "state": "OPEN",
        "headRefName": "feature/cc-54", "headRefOid": head, "baseRefName": "main",
    }))
    identity = {"ticket": "CC-54", "repository": "acme/app", "base_branch": "main",
                "pull_request": 54, "head_sha": head, "source_sha": head,
                "pull_request_url": "https://github.com/acme/app/pull/54"}
    details = {**identity, "schema": "auto-dev-pr-create-family/v1",
               "subject_revision": head, "family_complete": True,
               "readback_verified": True, "receipt_refs": [str(native)],
               "targets": [{**identity, "provider_readback_refs": [str(native)]}]}
    return details, native


def _normalize(details):
    return delivery._normalize_exact_legacy_flat_family_identity(
        details, task={"ticket": "CC-54"},
        expected_repository="git:github.com/acme/app", expected_base_branch="main",
        expected_source_branch="feature/cc-54", pull_request_prefix="github:acme/app#",
    )


def _family_fixture_copy(task_value, destination, details):
    """Copy an immutable fixture to exercise consumer checks without state writes."""

    current = deepcopy(task_value)
    wrapper = json.loads(Path(current["stage_receipts"]["release_propagation"]["ref"]).read_text())
    source = Path(task_value["work_item"]) / wrapper["receipt"]
    payload = json.loads(source.read_text())
    payload["evidence"] = deepcopy(details)
    destination.mkdir(parents=True)
    evidence_path = destination / "evidence.json"
    evidence_path.write_text(json.dumps(payload))
    wrapper["receipt"] = str(evidence_path)
    wrapper["evidence_sha256"] = delivery._json_sha256(payload)
    wrapper_path = destination / "wrapper.json"
    wrapper_path.write_text(json.dumps(wrapper))
    current["stage_receipts"]["release_propagation"] = {
        "ref": str(wrapper_path), "sha256": hashlib.sha256(wrapper_path.read_bytes()).hexdigest(),
    }
    return current


def test_flat_family_requires_native_identity_and_keeps_original_bytes(tmp_path):
    details, native = _flat_family(tmp_path)
    before = deepcopy(details)
    raw = native.read_bytes()
    normalized, provenance = _normalize(details)
    assert normalized["source_head_sha"] == "a" * 40
    assert normalized["provider"] == "github"
    assert normalized["source_branch"] == "feature/cc-54"
    assert normalized["pull_request"] == "github:acme/app#54"
    assert details == before and native.read_bytes() == raw
    assert provenance["native_readback"]["sha256"] == hashlib.sha256(raw).hexdigest()


@pytest.mark.parametrize("mutation", [
    "alias", "extra_target", "flag", "schema", "repository", "missing_refs",
    "ambiguous_refs", "native_head", "native_number", "native_base", "native_branch",
    "native_url", "ticket", "mixed_provider", "target_head",
    "target_provider", "target_branch", "target_source_head", "target_readback",
])
def test_flat_family_rejects_conflicting_or_missing_provenance(tmp_path, mutation):
    details, native = _flat_family(tmp_path)
    if mutation == "alias": details["subject_revision"] = "b" * 40
    elif mutation == "extra_target": details["targets"].append(deepcopy(details["targets"][0]))
    elif mutation == "flag": details["family_complete"] = False
    elif mutation == "schema": details["schema"] = "another/v1"
    elif mutation == "repository": details["repository"] = "foreign/app"
    elif mutation == "ticket": details["ticket"] = "CC-55"
    elif mutation == "mixed_provider": details["provider"] = "gitlab"
    elif mutation == "target_head": details["targets"][0]["head_sha"] = "b" * 40
    elif mutation.startswith("target_"):
        key, value = {
            "target_provider": ("provider", "gitlab"),
            "target_branch": ("source_branch", "foreign"),
            "target_source_head": ("source_head_sha", "b" * 40),
            "target_readback": ("readback_verified", False),
        }[mutation]
        details["targets"][0][key] = value
    elif mutation == "missing_refs": details["receipt_refs"] = []
    elif mutation == "ambiguous_refs":
        second = tmp_path / "native-2.json"
        second.write_bytes(native.read_bytes())
        details["receipt_refs"].append(str(second))
        details["targets"][0]["provider_readback_refs"].append(str(second))
    else:
        value = json.loads(native.read_text())
        key = {"native_head": "headRefOid", "native_number": "number", "native_base": "baseRefName",
               "native_branch": "headRefName", "native_url": "url"}[mutation]
        value[key] = 55 if key == "number" else "foreign"
        native.write_text(json.dumps(value))
    with pytest.raises(delivery.DevelopmentDeliveryError, match="legacy flat family"):
        _normalize(details)


@pytest.mark.parametrize("successor", ["valid", "unqualified", "same_head", "wrong_supersedes", "wrong_branch"])
def test_flat_family_refresh_integrates_with_immutable_wrapper(tmp_path, monkeypatch, successor):
    task, _root, _repo, base = _task(tmp_path, monkeypatch)
    _advance_auto_dev_task_to_ready(task, subject_revision=base, pull_request="github:acme/app#54")
    for stage in ("groom", "detective", "create_artifacts", "document"):
        _record_standalone_stage(task, stage)
    value = task.read()
    value["state"] = "local_validation"
    task.path.write_text(json.dumps(value))
    details, native = _flat_family(tmp_path)
    prior = _stage_receipt(tmp_path / "old", "release_propagation", evidence=details)
    delivery.run_development_stage(task.path, stage="release_propagation",
                                  receipts={"release_propagation": prior}, idempotency_prefix="family:old")
    wrapper = Path(task.read()["stage_receipts"]["release_propagation"]["ref"])
    original = (Path(prior).read_bytes(), wrapper.read_bytes())
    refreshed = {
        "repository": "git:github.com/acme/app", "base_branch": "main", "provider": "github",
        "pull_request": "github:acme/app#54", "source_branch": "feature/cc-54",
        "source_head_sha": "b" * 40, "readback_verified": True,
        "provider_observed": {"head_sha": "b" * 40},
        "supersession": {"supersedes_source_head_sha": "a" * 40, "reason": "verified new provider head"},
    }
    if successor == "unqualified": refreshed["pull_request"] = "acme/app#54"
    elif successor == "same_head":
        refreshed["source_head_sha"] = "a" * 40
        refreshed["provider_observed"]["head_sha"] = "a" * 40
    elif successor == "wrong_supersedes": refreshed["supersession"]["supersedes_source_head_sha"] = "c" * 40
    elif successor == "wrong_branch": refreshed["source_branch"] = "foreign"
    new = _stage_receipt(tmp_path / "new", "release_propagation", evidence=refreshed)
    before = task.path.read_bytes()
    call = lambda: delivery.run_development_stage(task.path, stage="release_propagation",
                                                 receipts={"release_propagation": new}, idempotency_prefix="family:new")
    if successor == "valid":
        result = call()
        assert result["supersedes"]["legacy_identity_normalization"]["source"] == "exact_flat_family_with_native_readback"
    else:
        with pytest.raises(delivery.DevelopmentDeliveryError, match="release propagation refresh"):
            call()
        assert task.path.read_bytes() == before
    assert (Path(prior).read_bytes(), wrapper.read_bytes()) == original


@pytest.mark.parametrize("policy,profile_base,task_base,review_number,review_base", [
    ("continue_with_receipt", "main", None, 54, "main"),
    ("block", "main", None, 54, "main"),
    ("continue_with_receipt", "develop", "hotfix/v10.0.1", 54, "hotfix/v10.0.1"),
    ("continue_with_receipt", "develop", "hotfix/v10.0.1", 55, "develop"),
])
def test_real_runner_and_downstream_keep_unavailable_honest(
    tmp_path, monkeypatch, policy, profile_base, task_base, review_number, review_base,
):
    task, root, repo, base = _task(tmp_path, monkeypatch, review_policy=policy,
                                 profile_base=profile_base, task_base=task_base)
    runner = _load_runner()
    work_item = Path(task.read()["work_item"])
    head = "b" * 40
    for stage in ("groom", "detective", "create_artifacts"):
        _record_standalone_stage(task, stage)
    delivery.run_development_stage(task.path, stage="readiness", receipts={
        "planned": _stage_receipt(tmp_path / "planned", "planned"),
    }, idempotency_prefix="review-setup:readiness")
    delivery.run_development_stage(task.path, stage="implementation", receipts={
        "implementing": _stage_receipt(tmp_path / "implementing", "implementing"),
        "local_validation": _stage_receipt(tmp_path / "local", "local_validation"),
    }, idempotency_prefix="review-setup:implementation")
    _record_standalone_stage(task, "document")
    targets = [{
            "number": review_number, "url": f"https://github.com/acme/app/pull/{review_number}",
            "base_branch": review_base, "head_sha": head,
            "source_branch": "feature/cc-54", "classification": "pr_required",
            "provider_readback_verified": True,
        }]
    if review_number != 54:
        targets.append({**targets[0], "number": 54, "url": "https://github.com/acme/app/pull/54",
                        "base_branch": task_base, "head_sha": "c" * 40,
                        "source_branch": "feature/primary"})
    family = _stage_receipt(tmp_path / "family", "release_propagation", evidence={"targets": targets})
    delivery.run_development_stage(task.path, stage="release_propagation",
                                  receipts={"release_propagation": family},
                                  idempotency_prefix="review-setup:family")
    source = {
        "work_item_id": "CC-54", "builder_model": "gpt-6", "selected_reviewer_model": "opus",
        "mode": "post_pr", "base_sha": base, "head_sha": head, "pr_number": 54,
        "implementation_summary": "review configured model", "spec_source": "test",
        "policy_fingerprint": task.read()["policy_fingerprint"],
        "reviewer_selection_source": "project-policy", "repo_path": str(repo),
        "target_branch": task_base or profile_base,
    }
    provider = {
        "number": review_number, "url": f"https://github.com/acme/app/pull/{review_number}", "state": "OPEN",
        "headRefOid": head, "headRefName": "feature/cc-54", "baseRefOid": base, "baseRefName": review_base,
        "baseRefTargetOid": base,
        "statusCheckRollup": [{"conclusion": "SUCCESS"}],
    }
    provider["current_target_readback"] = {
        **{key: provider[key] for key in ("number", "url", "state", "headRefOid", "headRefName", "baseRefName", "baseRefOid")},
        "baseRef": {"name": review_base, "target": {"oid": base}},
    }
    monkeypatch.setattr(delivery, "read_current_github_review_target", lambda *_args, **_kwargs: {
        "schema": "unavailable-review-current-target/v1", "read_at": "test-native-read",
        "native": provider["current_target_readback"],
    })
    monkeypatch.setattr(runner, "resolve_os_root", lambda _explicit: root)
    monkeypatch.setattr(runner, "prior_request", lambda *_args: source)
    monkeypatch.setattr(runner, "provider_pr", lambda *_args: provider)
    monkeypatch.setattr(runner, "git_head", lambda *_args: head)
    monkeypatch.setattr(runner, "git_repository", lambda *_args: "acme/app")
    monkeypatch.setattr(runner, "diff_hash", lambda *_args: "d" * 64)
    monkeypatch.setattr(runner, "full_pr_merge_base", lambda *_args: base)
    monkeypatch.setattr(runner.shutil, "which", lambda _name: "/test/claude")
    original_run = runner.run
    invoked = []
    def fake_cli(command, **kwargs):
        if command[0] == "/test/claude":
            invoked.append(command)
            return subprocess.CompletedProcess(command, 1, "", "offline fixture CLI unavailable")
        return original_run(command, **kwargs)
    monkeypatch.setattr(runner, "run", fake_cli)
    monkeypatch.setattr(sys, "argv", [
        "runner", "CC-54", "--os-root", str(root),
        "--work-item", str(work_item), "--worktree", str(repo),
    ])
    assert runner.main() == 2  # unavailable is never presented as CLEAN
    receipt_path = next((root / "state/review-coordination/attempts").glob("*.json"))
    receipt = load_review_receipt(receipt_path)
    assert receipt["outcome"] == "unavailable"
    assert receipt["review"]["selected_reviewer_model"] == "claude-fable-5"
    assert receipt["subject"]["pull_request"] == f"github:acme/app#{review_number}"
    assert receipt["subject"]["base_branch"] == review_base
    request = json.loads((Path(receipt["review"]["review_run_dir"]) / "review-request.json").read_text())
    assert request["selected_review_authority"]["task_primary_base_branch"] == (task_base or profile_base)
    assert request["source_family_authority"]["number"] == review_number
    assert invoked[0][invoked[0].index("--model") + 1] == "claude-fable-5"
    assert "claude-fable-5" in invoked[0][-1]
    assert receipt["budget"]["full_reviews_used"] == 0
    with pytest.raises(ReviewCoordinationError, match="clean exact-head"):
        assert_exact_head_review_receipt(receipt_path, head_sha=head)
    if policy == "block":
        with pytest.raises(delivery.DevelopmentDeliveryError, match="typed policy-approved"):
            delivery.validate_policy_approved_unavailable_review(receipt, task.read())
    else:
        delivery.validate_policy_approved_unavailable_review(receipt, task.read())
        # Metadata-only updates keep the original immutable selected provenance,
        # while the newly recorded current family is still checked for identity.
        original_wrapper = Path(request["source_family_authority"]["wrapper_ref"])
        old_wrapper_bytes = original_wrapper.read_bytes()
        refreshed_task = _family_fixture_copy(task.read(), tmp_path / "family-refresh", {
            "targets": [{**member, "checks_verified": True, "reviews_verified": True} for member in targets],
        })
        assert original_wrapper.read_bytes() == old_wrapper_bytes
        delivery.validate_policy_approved_unavailable_review(receipt, refreshed_task)
        if review_number != 54:
            return  # One canonical delivery task; do not invent a sibling task.
        first_dir = Path(receipt["review"]["review_run_dir"])
        first_bytes = {
            name: (first_dir / name).read_bytes()
            for name in receipt["review"]["unavailable_review_artifacts"]
        }
        assert runner.main() == 2
        attempts = [load_review_receipt(p) for p in (root / "state/review-coordination/attempts").glob("*.json")]
        assert len(attempts) == 2
        assert len({p["subject"]["head_sha"] for p in attempts}) == 1
        assert len({p["key"] for p in attempts}) == 1
        assert len({p["review"]["review_run_dir"] for p in attempts}) == 2
        assert all(p["budget"]["full_reviews_used"] == 0 for p in attempts)
        assert all((first_dir / name).read_bytes() == data for name, data in first_bytes.items())
        delivery.validate_policy_approved_unavailable_review(receipt, task.read())
        # Exercise the supported delivery recorder and its downstream health
        # predecessor, rather than relying only on the pure proof validator.
        task.transition("pre_pr_review", receipt=_stage_receipt(tmp_path / "pre-pr", "pre_pr_review"),
                        idempotency_key="review-proof:pre-pr")
        task.transition("pr_open", receipt=_stage_receipt(tmp_path / "pr-open", "pr_open", evidence={
            **_provider_authority(task, pull_request="github:acme/app#54"), "readback_verified": True,
        }), idempotency_key="review-proof:pr-open")
        task.transition("ci_repair", receipt=_stage_receipt(tmp_path / "ci", "ci_repair"),
                        idempotency_key="review-proof:ci")
        task.transition("review_repair", receipt=_stage_receipt(tmp_path / "repair", "review_repair"),
                        idempotency_key="review-proof:repair")
        task.transition("post_pr_review", receipt=_stage_receipt(tmp_path / "post-pr", "post_pr_review"),
                        idempotency_key="review-proof:post-pr")
        ready_input = _stage_receipt(tmp_path / "ready", "ready_for_merge", evidence={
            **_provider_authority(task, pull_request="github:acme/app#54"),
            "subject_revision": head, "checks_verified": True, "reviews_verified": True,
            "review_coordination_receipt": str(receipt_path),
        })
        original_input = Path(ready_input).read_bytes()
        delivery.run_development_stage(task.path, stage="review",
                                      receipts={"ready_for_merge": ready_input},
                                      idempotency_prefix="review-proof:ready")
        ready_row = next(row for row in reversed(task.read()["receipts"]) if row["state"] == "ready_for_merge")
        ready_snapshot = Path(ready_row["ref"])
        assert json.loads(ready_snapshot.read_text())["evidence"]["review_current_target_readback"]["schema"] == "unavailable-review-current-target/v1"
        assert Path(ready_input).read_bytes() == original_input
        auto_dev._validate_health_stage_source(work_item, "review_self", "completed", ready_snapshot)
        def changed_target(*_args, **_kwargs):
            raise delivery.DevelopmentDeliveryError("unavailable review current provider target or head changed")
        monkeypatch.setattr(delivery, "read_current_github_review_target", changed_target)
        with pytest.raises(auto_dev.AutoDevStateError, match="current provider target"):
            auto_dev._validate_health_stage_source(work_item, "review_self", "completed", ready_snapshot)
        profile_path = Path(task.read()["profile_source"])
        profile_path.write_text(profile_path.read_text() + "\n# drift\n")
        with pytest.raises(delivery.DevelopmentDeliveryError, match="authority or exact subject"):
            delivery.validate_policy_approved_unavailable_review(receipt, task.read())


def test_review_family_selects_only_one_integrity_bound_member(tmp_path, monkeypatch):
    task, _root, _repo, _base = _task(tmp_path, monkeypatch)
    for stage in ("groom", "detective", "create_artifacts"):
        _record_standalone_stage(task, stage)
    delivery.run_development_stage(task.path, stage="readiness", receipts={
        "planned": _stage_receipt(tmp_path / "planned", "planned"),
    }, idempotency_prefix="family-select:readiness")
    delivery.run_development_stage(task.path, stage="implementation", receipts={
        "implementing": _stage_receipt(tmp_path / "implementing", "implementing"),
        "local_validation": _stage_receipt(tmp_path / "local", "local_validation"),
    }, idempotency_prefix="family-select:implementation")
    _record_standalone_stage(task, "document")
    head = "b" * 40
    details = {"readback_verified": True, "targets": [{
        "repository": "git:github.com/acme/app", "provider": "github", "ticket": "CC-54",
        "pull_request": "github:acme/app#54", "pull_request_url": "https://github.com/acme/app/pull/54",
        "base_branch": "main", "head_sha": head, "source_head_sha": head, "source_sha": head,
        "source_branch": "feature/cc-54", "classification": "pr_required",
        "terminal_disposition": "provider_verified_pr_exists",
    }]}
    evidence = _stage_receipt(tmp_path / "family", "release_propagation", evidence=details)
    delivery.run_development_stage(task.path, stage="release_propagation",
                                  receipts={"release_propagation": evidence},
                                  idempotency_prefix="family-select:record")
    original = task.read()
    state_bytes = task.path.read_bytes()
    selected = delivery.verified_review_family_member(original, head_sha=head, source_branch="feature/cc-54")
    assert selected["number"] == 54 and selected["base_branch"] == "main"
    split_branches = deepcopy(details)
    split_branches["targets"].append({**details["targets"][0], "source_branch": "feature/sibling",
                                     "pull_request": "github:acme/app#55",
                                     "pull_request_url": "https://github.com/acme/app/pull/55"})
    copied = _family_fixture_copy(original, tmp_path / "same-head-different-branches", split_branches)
    assert delivery.verified_review_family_member(copied, head_sha=head, source_branch="feature/cc-54")["number"] == 54
    for label in ("missing", "ambiguous", "branch", "head_alias", "number_alias", "repository", "provider", "readback", "target_readback"):
        altered = deepcopy(details)
        member = altered["targets"][0]
        if label == "missing": altered["targets"] = []
        elif label == "ambiguous": altered["targets"].append(deepcopy(member))
        elif label == "branch": member["source_branch"] = "foreign"
        elif label == "head_alias": member["source_sha"] = "c" * 40
        elif label == "number_alias": member["number"] = 55
        elif label == "repository": member["repository"] = "git:github.com/acme/foreign"
        elif label == "provider": member["provider"] = "gitlab"
        elif label == "readback": altered["readback_verified"] = False
        elif label == "target_readback": member["provider_readback_verified"] = False
        copied = _family_fixture_copy(original, tmp_path / label, altered)
        with pytest.raises(delivery.DevelopmentDeliveryError, match="review family"):
            delivery.verified_review_family_member(copied, head_sha=head, source_branch="feature/cc-54")
    corrupted = deepcopy(original)
    corrupted["stage_receipts"]["release_propagation"]["sha256"] = "0" * 64
    with pytest.raises(delivery.DevelopmentDeliveryError, match="wrapper is missing or changed"):
        delivery.verified_review_family_member(corrupted, head_sha=head, source_branch="feature/cc-54")
    copy = _family_fixture_copy(original, tmp_path / "hash-corruption", details)
    wrapper = Path(copy["stage_receipts"]["release_propagation"]["ref"])
    payload_path = Path(json.loads(wrapper.read_text())["receipt"])
    payload_path.write_text(payload_path.read_text().replace('"main"', '"foreign"'))
    with pytest.raises(delivery.DevelopmentDeliveryError, match="immutable evidence binding"):
        delivery.verified_review_family_member(copy, head_sha=head, source_branch="feature/cc-54")
    assert task.path.read_bytes() == state_bytes


def test_routed_policy_rejects_contradictions_and_transport():
    runner = _load_runner()
    selected = {"review": {"opposing_harness": {
        "unavailable_policy": "continue_with_receipt", "model": "claude-fable-5",
        "transport": "claude_cli",
    }}}
    assert runner.review_unavailable_policy({}, selected) == "continue_with_receipt"
    with pytest.raises(runner.ReviewError, match="contradictory"):
        runner.review_unavailable_policy({"review_unavailable_policy": "block"}, selected)
    with pytest.raises(runner.ReviewError, match="transport"):
        runner.review_model(selected, {"reviewer_transport": "api"})
    selected["review"]["opposing_harness"]["transport"] = "api"
    with pytest.raises(runner.ReviewError, match="transport"):
        runner.review_model(selected)


def test_native_provider_binds_current_target_instead_of_historical_pr_base(tmp_path, monkeypatch):
    runner = _load_runner()
    historical, current, head = "a" * 40, "c" * 40, "b" * 40
    cli = {
        "number": 54, "url": "https://github.com/acme/app/pull/54", "state": "OPEN",
        "baseRefName": "main", "baseRefOid": historical, "headRefOid": head,
    }
    observed = {**cli, "baseRef": {"name": "main", "target": {"oid": current}}}
    calls = []
    def fake_provider(command, **_kwargs):
        calls.append(command)
        payload = cli if command[1] == "pr" else {"data": {"repository": {"pullRequest": observed}}}
        return subprocess.CompletedProcess(command, 0, json.dumps(payload), "")
    monkeypatch.setattr(runner, "run", fake_provider)
    monkeypatch.setattr(runner, "git_repository", lambda *_args: "acme/app")
    provider = runner.provider_pr(54, tmp_path)
    assert provider["baseRefOid"] == historical
    assert provider["baseRefTargetOid"] == current
    assert "baseRef{name target{oid}}" in calls[1][4]
    observed["headRefOid"] = "d" * 40
    with pytest.raises(runner.ReviewError, match="does not bind"):
        runner.provider_pr(54, tmp_path)


def test_full_pr_diff_uses_common_ancestor_when_target_advanced(tmp_path):
    runner = _load_runner()
    repo, common = _repository(tmp_path)
    (repo / "target-only.txt").write_text("unrelated target change")
    _git("add", "target-only.txt", cwd=repo)
    _git("commit", "-m", "test: target advance", cwd=repo)
    current_target = _git("rev-parse", "HEAD", cwd=repo)
    _git("checkout", "-b", "feature/change", common, cwd=repo)
    (repo / "source-only.txt").write_text("own source change")
    _git("add", "source-only.txt", cwd=repo)
    _git("commit", "-m", "test: source change", cwd=repo)
    head = _git("rev-parse", "HEAD", cwd=repo)
    merge_base = runner.full_pr_merge_base(repo, current_target, head)
    assert merge_base == common
    diff = _git("diff", "--name-only", f"{merge_base}..{head}", cwd=repo)
    assert diff == "source-only.txt"
    assert "target-only.txt" in _git("diff", "--name-only", f"{current_target}..{head}", cwd=repo)


@pytest.mark.parametrize("current_base", ["a" * 40, "c" * 40])
def test_unavailable_live_guard_rejects_target_only_movement(monkeypatch, current_base):
    subject = {"head_sha": "b" * 40, "base_sha": "a" * 40, "base_branch": "main"}
    task = {"repository": {"id": "git:github.com/acme/app", "base_branch": "main"}}
    native = {"data": {"repository": {
        "nameWithOwner": "acme/app", "pullRequest": {
            "number": 54, "url": "https://github.com/acme/app/pull/54", "state": "OPEN",
            "headRefOid": subject["head_sha"], "baseRefName": "main",
            "baseRef": {"name": "main", "target": {"oid": current_base}},
        },
    }}}
    monkeypatch.setattr(delivery.subprocess, "run", lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, json.dumps(native), ""))
    if current_base == subject["base_sha"]:
        proof = delivery.read_current_github_review_target(task, subject, 54)
        assert proof["native"]["pullRequest"]["baseRef"]["target"]["oid"] == current_base
    else:
        with pytest.raises(delivery.DevelopmentDeliveryError, match="target or head changed"):
            delivery.read_current_github_review_target(task, subject, 54)


def test_unavailable_live_guard_fails_closed_on_provider_failure(monkeypatch):
    task = {"repository": {"id": "git:github.com/acme/app", "base_branch": "main"}}
    monkeypatch.setattr(delivery.subprocess, "run", lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 1, "", "private error"))
    with pytest.raises(delivery.DevelopmentDeliveryError, match="readback failed"):
        delivery.read_current_github_review_target(task, {"head_sha": "b" * 40, "base_sha": "a" * 40, "base_branch": "main"}, 54)
