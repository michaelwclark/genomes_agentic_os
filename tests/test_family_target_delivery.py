"""Real two-base sibling authority, immutable proof, and lifecycle isolation."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path

import pytest

from genomes_agentic_os.auto_dev_orchestration import (
    AutoDevStateError, record_auto_dev_family_target_finalize, record_auto_dev_stage,
    validate_auto_dev_readiness_authority,
)
from genomes_agentic_os.cli import main
from genomes_agentic_os.development_delivery import (
    TaskState, record_development_family_target_merge, start_development_run, run_development_stage,
)
from genomes_agentic_os.review_coordination import ReviewCoordinator, ReviewSubject
from genomes_agentic_os.family_target_delivery import _provider
from test_development_delivery import (
    _advance_auto_dev_task_to_ready, _complete_pre_merge_auto_dev,
    _git, _project, _repository,
    _stage_receipt,
    _readiness_authority,
)


def write(path: Path, payload: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return path


def bound(path: Path) -> dict[str, str]:
    return {"ref": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def canonical_sha(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def attach_pr_runs(provider: dict, target: dict) -> None:
    jobs = []
    for index, check in enumerate(provider["pr"]["statusCheckRollup"], start=101):
        url = f"https://github.com/acme/app/actions/runs/91/job/{index}"
        check["detailsUrl"] = url
        jobs.append({"id": index, "run_id": 91, "name": check["name"], "head_sha": target["subject_revision"],
                     "status": check["status"].lower(), "conclusion": check["conclusion"].lower(), "html_url": url})
    provider["workflow_runs"] = {"total_count": 1, "complete": True, "workflow_runs": [{
        "id": 91, "path": ".github/workflows/ci.yml", "event": "pull_request", "head_sha": target["subject_revision"],
        "head_branch": target["source_branch"], "head_repository": {"full_name": "acme/app"},
        "html_url": "https://github.com/acme/app/actions/runs/91", "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "completed", "conclusion": "success", "pull_requests": [{"number": 2,
            "head": {"sha": target["subject_revision"]}, "base": {"sha": target["base_sha"], "ref": target["base_branch"]}}],
    }]}
    provider["workflow_jobs"] = {"91": {"total_count": len(jobs), "jobs": jobs}}


@pytest.fixture
def family(tmp_path: Path) -> dict:
    repo, initial = _repository(tmp_path)
    root = tmp_path / "os"
    _project(root, repo)
    run = start_development_run(root, "acme", "app", ["CC-1"], titles={"CC-1": "Family"},
                                run_id="family", auto_dev_mode="everything", goal="delivery_complete", apply=True)
    task = TaskState(Path(run["tasks"][0]["state_ref"]))
    primary_source = Path(task.read()["worktree"]["path"])
    (primary_source / "primary.txt").write_text("primary source\n")
    _git("add", ".", cwd=primary_source)
    _git("commit", "-m", "feat: primary", cwd=primary_source)
    primary_head = _git("rev-parse", "HEAD", cwd=primary_source)
    primary_pr = "github:acme/app#1"
    _advance_auto_dev_task_to_ready(task, subject_revision=primary_head, pull_request=primary_pr)
    primary_authority = _complete_pre_merge_auto_dev(task, subject_revision=primary_head, pull_request=primary_pr)
    packet = Path(task.read()["work_item"])
    state = Path(task.read()["autodev_path"])

    # The sibling has an actual different base/tree, not a copied primary head.
    (repo / "legacy.txt").write_text("legacy stable baseline\n")
    _git("add", ".", cwd=repo)
    _git("commit", "-m", "feat: stable baseline", cwd=repo)
    base = _git("rev-parse", "HEAD", cwd=repo)
    _git("branch", "release", base, cwd=repo)
    sibling = tmp_path / "sibling"
    _git("worktree", "add", "-b", "feature/sibling", str(sibling), "release", cwd=repo)
    (sibling / "sibling.txt").write_text("sibling source\n")
    ci = sibling / ".github/workflows/ci.yml"
    ci.parent.mkdir(parents=True)
    ci.write_text("name: CI\non: [push, pull_request]\njobs:\n  tests:\n    name: tests\n    runs-on: ubuntu-latest\n    steps: [{run: 'true'}]\n  security:\n    name: security\n    runs-on: ubuntu-latest\n    steps: [{run: 'true'}]\n")
    _git("add", ".", cwd=sibling)
    _git("commit", "-m", "feat: sibling", cwd=sibling)
    head = _git("rev-parse", "HEAD", cwd=sibling)
    _git("remote", "set-url", "origin", "git@github.com:acme/app.git", cwd=repo)
    primary = {"provider": "github", "repository": "github:acme/app", "pull_request": primary_pr,
               "base_branch": "main", "base_sha": initial, "source_head": primary_head,
               "source_branch": task.read()["worktree"]["branch"], "classification": "pr_required", "readback_verified": True}
    target = {"provider": "github", "repository": "github:acme/app", "pull_request": "github:acme/app#2",
              "base_branch": "release", "base_sha": base, "source_branch": "feature/sibling",
              "subject_revision": head, "author_identity": "github:michaelwclark", "author_kind": "ours"}
    sibling_row = {k: v for k, v in target.items() if k not in {"subject_revision", "author_identity", "author_kind"}}
    sibling_row.update(source_head=head, classification="pr_required", readback_verified=True)
    family_payload = {"schema": "development-stage-evidence/v1", "state": "release_propagation", "status": "completed",
                      "evidence": {**primary, "subject_revision": primary_head, "family": [primary, sibling_row]}}
    family_evidence = write(packet / "artifacts/family-evidence.json", family_payload)
    wrapper = write(task.path.parent / "stages/release-propagation/family.json",
                    {"schema": "development-stage-receipt/v1", "stage": "release_propagation", "idempotency_key": "test-family",
                     "receipt": family_evidence.relative_to(packet).as_posix(), "evidence_sha256": canonical_sha(family_payload)})
    value = task.read()
    value["stage_receipts"]["release_propagation"] = bound(wrapper)
    write(task.path, value)
    projected = json.loads(state.read_text())
    projected["stages"]["pr_create"] = {"status": "completed", "run_ref": str(wrapper), "receipt_refs": [str(wrapper)]}
    write(state, projected)
    # Record a current native primary decision rather than relying on the
    # historical fixture helper's fixed timestamp for a live freshness gate.
    prior_finalize = json.loads((packet / primary_authority["ref"]).read_text())["evidence_snapshot"]
    prior_finalize["verified_at"] = datetime.now(timezone.utc).isoformat()
    current_primary = write(packet / "artifacts/current-primary-finalize.json", prior_finalize)
    record_auto_dev_stage(state, stage="finalize", evidence_file=current_primary, idempotency_key="current-primary-finalize")
    primary_authority = _readiness_authority(task, subject_revision=primary_head, pull_request=primary_pr)

    provider = {"observed_at": datetime.now(timezone.utc).isoformat(), "readback_verified": True,
                "pr": {"number": 2, "url": "https://github.com/acme/app/pull/2", "baseRefName": "release", "baseRefOid": base,
                       "headRefName": "feature/sibling", "headRefOid": head, "state": "OPEN", "isDraft": False,
                       "author": {"login": "michaelwclark"}, "mergeable": "MERGEABLE",
                       "statusCheckRollup": [{"__typename": "CheckRun", "name": name, "status": "COMPLETED", "conclusion": "SUCCESS"} for name in ("tests", "security")]},
                "review_threads": {"pageInfo": {"hasNextPage": False}, "nodes": []}}
    attach_pr_runs(provider, target)
    provider_path = write(packet / "artifacts/provider.json", provider)
    policy = task.read()["policy_fingerprint"]
    subject = ReviewSubject(repository="acme/app", pull_request="acme/app#2", base_branch="release", base_sha=base,
                            head_sha=head, policy_fingerprint=policy)
    reviewed = ReviewCoordinator(packet / "artifacts/canonical-review").execute(subject, lambda: {"outcome": "clean"})
    terminal = write(packet / "artifacts/actual-test-terminal.json", {"exit_code": 0, "status": "passed", "test": "fixture source"})
    scoped = {"schema": "auto-dev-stage-evidence/v1", "status": "completed", "subject_revision": head,
              "summary": "Exact sibling source qualification", "verified_at": datetime.now(timezone.utc).isoformat(),
              "evidence": {**target, "readback_verified": True, "readiness_decision": "ready_for_merge", "receipt_refs": [bound(terminal)]}}
    acceptance = write(packet / "artifacts/acceptance.json", {**scoped, "stage": "document"})
    qa = write(packet / "artifacts/qa.json", {**scoped, "stage": "qa"})
    secondary = write(packet / "artifacts/secondary.json", {**scoped, "stage": "review_self"})
    release = deepcopy(scoped)
    release["stage"] = "validate_production_release"
    release["evidence"].update(
        check_matrix=[{"check_id": name, "status": "pass", "evidence_ref": str(terminal)} for name in ("jira_github_alignment", "exact_release_identity", "qa_per_jira", "whole_diff_policy", "risk_gates", "artifact_rollback_observability", "runtime_consumer_contracts")],
        qa_runs=[bound(qa)], consumer_contract_matrix=[{"consumer_id": "source-cli", "status": "pass", "evidence_ref": str(terminal)}],
        tenant_impact_matrix=[{"tenant": "isolated", "status": "pass", "evidence_ref": str(terminal)}],
        compatibility_strategy="source qualification only; distribution and runtime gates remain separate",
        contract_test_runs=[bound(terminal)], runtime_readbacks=[bound(terminal)],
        policy_fingerprint=policy, provider_readbacks=[bound(provider_path)],
    )
    release_path = write(packet / "artifacts/release-validation.json", release)
    import subprocess
    diff = subprocess.run(["git", "-C", str(sibling), "diff", "--binary", base, head, "--"], capture_output=True, check=True).stdout
    payload = {"schema": "auto-dev-stage-evidence/v1", "stage": "finalize", "status": "completed", "subject_revision": head,
               "summary": "Own exact sibling source ready for merge", "verified_at": datetime.now(timezone.utc).isoformat(),
               "evidence": {**target, "readback_verified": True, "readiness_decision": "ready_for_merge", "readiness_scope": "source",
                            "source_scope": {"worktree": str(sibling), "tree_sha": _git("rev-parse", "HEAD^{tree}", cwd=sibling), "full_diff_sha256": hashlib.sha256(diff).hexdigest()},
                            "provider_readback": bound(provider_path), "canonical_review": bound(Path(reviewed.receipt_path)),
                            "review_policy_fingerprint": policy, "acceptance": bound(acceptance), "qa": bound(qa),
                            "secondary_review": bound(secondary), "release_validation": bound(release_path)}}
    evidence = write(packet / "artifacts/finalize-sibling.json", payload)
    return {"state": state, "task": task, "target": target, "evidence": evidence, "payload": payload,
            "provider": provider_path, "packet": packet, "sibling": sibling, "repo": repo,
            "family_evidence": family_evidence, "family_wrapper": wrapper,
            "primary_authority": primary_authority, "primary_head": primary_head}


def finalize(family: dict, key: str = "sibling-finalize") -> dict:
    return record_auto_dev_family_target_finalize(family["state"], evidence_file=family["evidence"], idempotency_key=key)


def validate(family: dict, authority: dict) -> dict:
    return validate_auto_dev_readiness_authority(family["state"], authority,
        expected_subject=family["target"]["subject_revision"], expected_pull_request=family["target"])


def test_two_base_finalize_is_immutable_and_does_not_retarget_primary(family: dict) -> None:
    before_task = family["task"].path.read_bytes()
    before_state = json.loads(family["state"].read_text())
    authority = finalize(family)
    assert finalize(family) == authority
    assert validate(family, authority) == authority
    after = json.loads(family["state"].read_text())
    assert family["task"].path.read_bytes() == before_task
    assert after["subject_revision"] == before_state["subject_revision"] == family["primary_head"]
    assert after["stages"] == before_state["stages"]
    assert family["target"]["subject_revision"] != family["primary_head"]
    wrapper = json.loads(Path(authority["ref"]).read_text())
    assert wrapper["authority"]["base_branch"] == "release"
    validate_auto_dev_readiness_authority(family["state"], family["primary_authority"],
        expected_subject=family["primary_head"], expected_pull_request=family["primary_authority"])


def test_primary_cannot_merge_while_required_sibling_has_no_own_decision(family: dict) -> None:
    with pytest.raises(AutoDevStateError, match="required sibling"):
        validate_auto_dev_readiness_authority(family["state"], family["primary_authority"],
            expected_subject=family["primary_head"], expected_pull_request=family["primary_authority"])


@pytest.mark.parametrize("target_policy", ["task", "historical_primary"])
def test_siblings_keep_their_actual_distinct_frozen_review_policy(family: dict, target_policy: str) -> None:
    # Model the existing accepted historical primary review while the sibling
    # legitimately uses the task's frozen policy, or that same historical policy.
    historical = "d" * 64
    task_value = family["task"].read()
    ready_row = next(row for row in reversed(task_value["receipts"]) if row.get("state") == "ready_for_merge")
    ready_path = Path(ready_row["ref"])
    ready = json.loads(ready_path.read_text())
    primary_review = ReviewCoordinator(family["packet"] / "artifacts/historical-primary-review").execute(
        ReviewSubject(repository="acme/app", pull_request="github:acme/app#1", base_branch="main",
                      base_sha=family["primary_head"], head_sha=family["primary_head"], policy_fingerprint=historical),
        lambda: {"outcome": "clean"},
    )
    ready["evidence"].update(review_policy_fingerprint=historical,
                             review_coordination_receipt=str(primary_review.receipt_path))
    write(ready_path, ready)
    ready_row["sha256"] = bound(ready_path)["sha256"]
    write(family["task"].path, task_value)
    if target_policy == "historical_primary":
        target = family["target"]
        review = ReviewCoordinator(family["packet"] / "artifacts/historical-sibling-review").execute(
            ReviewSubject(repository="acme/app", pull_request="github:acme/app#2", base_branch=target["base_branch"],
                          base_sha=target["base_sha"], head_sha=target["subject_revision"], policy_fingerprint=historical),
            lambda: {"outcome": "clean"},
        )
        payload = deepcopy(family["payload"])
        payload["evidence"].update(review_policy_fingerprint=historical, canonical_review=bound(Path(review.receipt_path)))
        write(family["evidence"], payload)
    authority = finalize(family)
    assert validate(family, authority) == authority
    wrapper = json.loads(Path(authority["ref"]).read_text())
    assert wrapper["primary_ready_binding"] == bound(ready_path)
    assert wrapper["policy_binding"]["sha256"] == bound(Path(task_value["policy_receipt"]))["sha256"]


def test_real_primary_merge_transition_keeps_sibling_authority_and_records_second_merge(family: dict) -> None:
    authority = finalize(family)
    primary_branch = family["task"].read()["worktree"]["branch"]
    _git("merge", "--no-ff", primary_branch, "-m", "merge: reviewed primary", cwd=family["repo"])
    primary_merge = _git("rev-parse", "HEAD", cwd=family["repo"])
    primary_payload = {k: v for k, v in family["primary_authority"].items() if k not in {"owner", "ref", "sha256", "subject_revision"}}
    primary_payload.update(source_head_sha=family["primary_head"], merge_sha=primary_merge,
                           readback_verified=True, readiness_authority=family["primary_authority"])
    receipt = _stage_receipt(family["packet"] / "artifacts/actual-primary-merge", "merged", evidence=primary_payload, status="completed")
    run_development_stage(family["task"].path, stage="merge", receipts={"merged": receipt}, idempotency_prefix="real-primary-merged")
    primary_after = family["task"].read()
    assert primary_after["state"] == "merged"
    assert primary_after["terminal_revision"] == primary_merge
    assert primary_after["subject_revision"] == family["primary_head"]
    assert validate(family, authority) == authority
    # The stable branch advances in real git. Readback must not pretend its
    # post-merge baseRefOid is the old reviewed base SHA.
    stable = family["repo"].parent / "stable-target"
    _git("worktree", "add", str(stable), "release", cwd=family["repo"])
    _git("merge", "--no-ff", "feature/sibling", "-m", "merge: reviewed sibling", cwd=stable)
    merge_sha = _git("rev-parse", "HEAD", cwd=stable)
    provider = json.loads(family["provider"].read_text())
    provider["pr"].update(state="MERGED", mergeCommit={"oid": merge_sha}, mergedAt=datetime.now(timezone.utc).isoformat(), baseRefOid=merge_sha)
    readback = write(family["packet"] / "artifacts/second-provider-merge.json", provider)
    evidence = write(family["packet"] / "artifacts/second-merge.json", {
        "schema": "development-stage-evidence/v1", "state": "merged", "status": "completed",
        "summary": "Second provider merge after actual primary native transition", "verified_at": datetime.now(timezone.utc).isoformat(),
        "evidence": {**family["target"], "source_head_sha": family["target"]["subject_revision"], "merge_sha": merge_sha,
                     "readback_verified": True, "readiness_authority": authority, "provider_readback": bound(readback)},
    })
    record_development_family_target_merge(family["state"], evidence_file=evidence, idempotency_key="second-real-merge")
    after = family["task"].read()
    assert len(after.pop("family_merges")) == 1
    assert after == primary_after


@pytest.mark.parametrize("field,value", [
    ("pull_request", "github:acme/app#3"), ("repository", "github:other/app"), ("base_branch", "main"),
    ("base_sha", "b" * 40), ("source_branch", "feature/unrelated"), ("author_identity", "github:someoneelse"),
    ("author_kind", "others"), ("readiness_decision", "pending"), ("review_policy_fingerprint", "c" * 64),
])
def test_finalize_refuses_target_or_policy_substitution_without_writes(family: dict, field: str, value: str) -> None:
    before = family["state"].read_bytes()
    payload = deepcopy(family["payload"])
    payload["evidence"][field] = value
    write(family["evidence"], payload)
    with pytest.raises(AutoDevStateError):
        finalize(family)
    assert family["state"].read_bytes() == before
    assert not (family["packet"] / "artifacts/auto-dev-orchestration/family-targets").exists()


@pytest.mark.parametrize("change", ["pending", "failure", "skip", "missing_required", "threads", "pagination", "draft", "conflict", "head", "base", "stale"])
def test_finalize_refuses_current_provider_failures(family: dict, change: str) -> None:
    provider = json.loads(family["provider"].read_text())
    check = provider["pr"]["statusCheckRollup"][0]
    if change == "pending": check["status"] = "IN_PROGRESS"
    if change == "failure": check["conclusion"] = "FAILURE"
    if change == "skip": check["conclusion"] = "SKIPPED"
    if change == "missing_required": provider["pr"]["statusCheckRollup"].pop()
    if change == "threads": provider["review_threads"]["nodes"] = [{"isResolved": False, "isOutdated": False}]
    if change == "pagination": provider["review_threads"]["pageInfo"]["hasNextPage"] = True
    if change == "draft": provider["pr"]["isDraft"] = True
    if change == "conflict": provider["pr"]["mergeable"] = "CONFLICTING"
    if change == "head": provider["pr"]["headRefOid"] = "c" * 40
    if change == "base": provider["pr"]["baseRefOid"] = "c" * 40
    if change == "stale": provider["observed_at"] = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    write(family["provider"], provider)
    payload = deepcopy(family["payload"])
    payload["evidence"]["provider_readback"] = bound(family["provider"])
    release_path = Path(payload["evidence"]["release_validation"]["ref"])
    release = json.loads(release_path.read_text())
    release["evidence"]["provider_readbacks"] = [bound(family["provider"])]
    write(release_path, release)
    payload["evidence"]["release_validation"] = bound(release_path)
    write(family["evidence"], payload)
    with pytest.raises(AutoDevStateError): finalize(family)


@pytest.mark.parametrize("label", ["acceptance", "qa", "secondary_review", "release_validation", "canonical_review"])
def test_proof_mutation_cannot_be_hidden_by_a_recorded_decision(family: dict, label: str) -> None:
    authority = finalize(family)
    path = Path(family["payload"]["evidence"][label]["ref"])
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(AutoDevStateError, match="hash changed"):
        validate(family, authority)


@pytest.mark.parametrize("field", ["full_diff_sha256", "tree_sha", "worktree"])
def test_source_scope_requires_the_actual_complete_sibling_checkout(family: dict, field: str) -> None:
    payload = deepcopy(family["payload"])
    payload["evidence"]["source_scope"][field] = "0" * 64
    write(family["evidence"], payload)
    with pytest.raises(AutoDevStateError): finalize(family)


def test_different_descriptor_and_conflicting_retry_are_refused(family: dict) -> None:
    authority = finalize(family)
    wrong = {**authority, "subject_revision": family["primary_head"]}
    with pytest.raises(AutoDevStateError): validate(family, wrong)
    payload = deepcopy(family["payload"])
    payload["summary"] = "different evidence with reused key"
    write(family["evidence"], payload)
    with pytest.raises(AutoDevStateError, match="idempotency"):
        finalize(family)


def test_family_wrapper_and_nested_proof_drift_are_refused(family: dict) -> None:
    authority = finalize(family)
    family["family_wrapper"].write_text("{}")
    with pytest.raises(AutoDevStateError, match="hash changed"): validate(family, authority)


@pytest.mark.parametrize("change", ["findings", "unavailable", "pr", "base", "head", "policy", "purpose"])
def test_actual_canonical_review_must_be_clean_and_exact(family: dict, change: str) -> None:
    target = family["target"]
    values = dict(repository="acme/app", pull_request="github:acme/app#2", base_branch=target["base_branch"],
                  base_sha=target["base_sha"], head_sha=target["subject_revision"],
                  policy_fingerprint=family["payload"]["evidence"]["review_policy_fingerprint"])
    if change == "pr": values["pull_request"] = "github:acme/app#3"
    if change == "base": values["base_sha"] = "a" * 40
    if change == "head": values["head_sha"] = "b" * 40
    if change == "policy": values["policy_fingerprint"] = "c" * 64
    if change == "purpose": values["purpose"] = "other_review"
    result = {"outcome": change if change in {"findings", "unavailable"} else "clean"}
    reviewed = ReviewCoordinator(family["packet"] / ("artifacts/review-" + change)).execute(ReviewSubject(**values), lambda: result)
    payload = deepcopy(family["payload"])
    payload["evidence"]["canonical_review"] = bound(Path(reviewed.receipt_path))
    write(family["evidence"], payload)
    with pytest.raises(AutoDevStateError): finalize(family)


@pytest.mark.parametrize("change", ["head", "base", "pending", "nested", "release"])
def test_target_proof_status_scope_and_nested_bytes_are_checked(family: dict, change: str) -> None:
    payload = deepcopy(family["payload"])
    label = "release_validation" if change == "release" else "qa"
    path = Path(payload["evidence"][label]["ref"])
    proof = json.loads(path.read_text())
    if change == "head": proof["subject_revision"] = family["primary_head"]
    if change == "base": proof["evidence"]["base_sha"] = "a" * 40
    if change == "pending": proof["status"] = "pending"
    if change == "nested": Path(proof["evidence"]["receipt_refs"][0]["ref"]).write_text("changed")
    if change == "release": proof["evidence"]["check_matrix"][0]["status"] = "pending"
    write(path, proof)
    payload["evidence"][label] = bound(path)
    write(family["evidence"], payload)
    with pytest.raises(AutoDevStateError): finalize(family)


@pytest.mark.parametrize("label", ["qa", "secondary_review"])
def test_acceptance_document_cannot_substitute_for_qa_or_secondary(family: dict, label: str) -> None:
    payload = deepcopy(family["payload"])
    payload["evidence"][label] = payload["evidence"]["acceptance"]
    write(family["evidence"], payload)
    with pytest.raises(AutoDevStateError, match="wrong proof kind"):
        finalize(family)


@pytest.mark.parametrize("field", ["qa_runs", "contract_test_runs", "runtime_readbacks", "provider_readbacks", "consumer_contract_matrix", "tenant_impact_matrix", "check_matrix"])
def test_every_required_release_reference_is_hash_bound(family: dict, field: str) -> None:
    payload = deepcopy(family["payload"])
    path = Path(payload["evidence"]["release_validation"]["ref"])
    release = json.loads(path.read_text())
    if field.endswith("matrix"):
        release["evidence"][field][0]["evidence_ref"] = str(family["packet"] / "missing-proof.json")
    else:
        release["evidence"][field][0] = {"ref": str(family["packet"] / "missing-proof.json"), "sha256": "a" * 64}
    write(path, release)
    payload["evidence"]["release_validation"] = bound(path)
    write(family["evidence"], payload)
    with pytest.raises(AutoDevStateError): finalize(family)


@pytest.mark.parametrize("primary_first", [True, False])
def test_all_unmerged_members_must_be_fresh_before_either_first_merge(family: dict, monkeypatch, primary_first: bool) -> None:
    import genomes_agentic_os.family_target_delivery as target_delivery

    provider = json.loads(family["provider"].read_text())
    now = datetime.now(timezone.utc)
    provider["observed_at"] = (now - timedelta(seconds=500)).isoformat()
    write(family["provider"], provider)
    payload = deepcopy(family["payload"])
    payload["evidence"]["provider_readback"] = bound(family["provider"])
    release_path = Path(payload["evidence"]["release_validation"]["ref"])
    release = json.loads(release_path.read_text())
    release["evidence"]["provider_readbacks"] = [bound(family["provider"])]
    write(release_path, release)
    payload["evidence"]["release_validation"] = bound(release_path)
    write(family["evidence"], payload)
    authority = finalize(family)

    class Later(datetime):
        @classmethod
        def now(cls, tz=None):
            return (now + timedelta(seconds=120)).astimezone(tz)

    monkeypatch.setattr(target_delivery, "datetime", Later)
    with pytest.raises(AutoDevStateError, match="stale"):
        if primary_first:
            validate_auto_dev_readiness_authority(family["state"], family["primary_authority"],
                expected_subject=family["primary_head"], expected_pull_request=family["primary_authority"])
        else:
            validate(family, authority)


def test_provider_skip_requires_the_real_main_event_and_frozen_condition(family: dict) -> None:
    workflow = family["sibling"] / ".github/workflows/ci.yml"
    workflow.parent.mkdir(parents=True, exist_ok=True)
    condition = "github.event_name == 'pull_request' && github.base_ref != 'main'"
    workflow.write_text("on: [pull_request]\njobs:\n  convention:\n    name: Conventional Commits\n    if: \"" + condition + "\"\n")
    _git("add", ".", cwd=family["sibling"])
    _git("commit", "-m", "ci: conditional conventional check", cwd=family["sibling"])
    head = _git("rev-parse", "HEAD", cwd=family["sibling"])
    target = {**family["target"], "base_branch": "main", "subject_revision": head}
    provider = json.loads(family["provider"].read_text())
    provider["pr"].update(baseRefName="main", headRefOid=head)
    provider["pr"]["statusCheckRollup"][0].update(name="Conventional Commits", conclusion="SKIPPED")
    provider["pr"]["statusCheckRollup"] = provider["pr"]["statusCheckRollup"][:1]
    attach_pr_runs(provider, target)
    proof = write(family["packet"] / "artifacts/skip-proof.json", {
        "schema": "auto-dev-ci-applicability/v1", "event_name": "pull_request", "base_branch": "main",
        "subject_revision": head, "status": "not_applicable", "workflow_path": ".github/workflows/ci.yml",
        "job_id": "convention", "condition": condition,
    })
    provider["allowed_skips"] = [{"name": "Conventional Commits", "reason": "Explicit main exclusion", "proof": bound(proof)}]
    path = write(family["packet"] / "artifacts/provider-skip.json", provider)
    _provider(family["packet"], bound(path), target, github_repository="acme/app", author_identity="github:michaelwclark", fresh=True, worktree=family["sibling"])
    bad = json.loads(proof.read_text())
    bad["event_name"] = "workflow_dispatch"
    write(proof, bad)
    provider["allowed_skips"][0]["proof"] = bound(proof)
    write(path, provider)
    with pytest.raises(AutoDevStateError, match="exact PR event"):
        _provider(family["packet"], bound(path), target, github_repository="acme/app", author_identity="github:michaelwclark", fresh=True, worktree=family["sibling"])


@pytest.mark.parametrize("change", ["push_only", "latest_pr_pending", "push_green_pr_pending", "wrong_pr", "wrong_base", "wrong_head", "missing_job", "wrong_run", "wrong_job_url", "push_rollup"])
def test_green_push_namesakes_cannot_replace_exact_pr_event_jobs(family: dict, change: str) -> None:
    provider = json.loads(family["provider"].read_text())
    run = provider["workflow_runs"]["workflow_runs"][0]
    jobs = provider["workflow_jobs"]["91"]["jobs"]
    if change == "push_only":
        run["event"] = "push"
    elif change in {"latest_pr_pending", "push_green_pr_pending"}:
        latest = deepcopy(run)
        latest.update(id=92, created_at=(datetime.now(timezone.utc) + timedelta(seconds=1)).isoformat(),
                      html_url="https://github.com/acme/app/actions/runs/92", status="queued", conclusion=None)
        if change == "push_green_pr_pending":
            run["event"] = "push"
        provider["workflow_runs"]["workflow_runs"].append(latest)
        provider["workflow_runs"]["total_count"] = 2
    elif change == "wrong_pr":
        run["pull_requests"][0]["number"] = 3
    elif change == "wrong_base":
        run["pull_requests"][0]["base"]["sha"] = "a" * 40
    elif change == "wrong_head":
        run["head_sha"] = family["primary_head"]
    elif change == "missing_job":
        jobs.pop()
    elif change == "wrong_run":
        jobs[0]["run_id"] = 92
    elif change == "wrong_job_url":
        jobs[0]["html_url"] = "https://github.com/acme/app/actions/runs/92/job/101"
    elif change == "push_rollup":
        # Same green names, different run/job IDs: the actual PR job is absent.
        for check in provider["pr"]["statusCheckRollup"]:
            check["detailsUrl"] = check["detailsUrl"].replace("/runs/91/", "/runs/92/")
    path = write(family["packet"] / "artifacts/provider-event-negative.json", provider)
    with pytest.raises(AutoDevStateError):
        _provider(family["packet"], bound(path), family["target"], github_repository="acme/app",
                  author_identity="github:michaelwclark", fresh=True, worktree=family["sibling"])


def test_actual_green_pr_run_is_accepted_with_separate_green_push_namesakes(family: dict) -> None:
    provider = json.loads(family["provider"].read_text())
    pushed = deepcopy(provider["workflow_runs"]["workflow_runs"][0])
    pushed.update(id=92, event="push", pull_requests=[], html_url="https://github.com/acme/app/actions/runs/92")
    provider["workflow_runs"]["workflow_runs"].append(pushed)
    provider["workflow_runs"]["total_count"] = 2
    for check in list(provider["pr"]["statusCheckRollup"]):
        provider["pr"]["statusCheckRollup"].append({**check, "detailsUrl": check["detailsUrl"].replace("/runs/91/", "/runs/92/")})
    path = write(family["packet"] / "artifacts/provider-two-events.json", provider)
    _provider(family["packet"], bound(path), family["target"], github_repository="acme/app",
              author_identity="github:michaelwclark", fresh=True, worktree=family["sibling"])


def test_merge_records_provider_result_separately_and_exact_retry_is_safe(family: dict) -> None:
    authority = finalize(family)
    before_task = family["task"].read()
    before_state = family["state"].read_bytes()
    provider = json.loads(family["provider"].read_text())
    provider["pr"].update(state="MERGED", mergeCommit={"oid": "d" * 40}, mergedAt=datetime.now(timezone.utc).isoformat(), baseRefOid="d" * 40)
    readback = write(family["packet"] / "artifacts/provider-merged.json", provider)
    payload = {"schema": "development-stage-evidence/v1", "state": "merged", "status": "completed",
               "summary": "Actual sibling provider merge", "verified_at": datetime.now(timezone.utc).isoformat(),
               "evidence": {**family["target"], "source_head_sha": family["target"]["subject_revision"],
                            "merge_sha": "d" * 40, "readback_verified": True,
                            "readiness_authority": authority, "provider_readback": bound(readback)}}
    evidence = write(family["packet"] / "artifacts/merged.json", payload)
    result = record_development_family_target_merge(family["state"], evidence_file=evidence, idempotency_key="actual-sibling-merge")
    assert record_development_family_target_merge(family["state"], evidence_file=evidence, idempotency_key="actual-sibling-merge") == result
    after = family["task"].read()
    assert after.pop("family_merges") == {authority["target_key"]: result}
    assert after == before_task
    assert family["state"].read_bytes() == before_state
    record = json.loads(Path(result["ref"]).read_text())
    assert record["source_head_sha"] == family["target"]["subject_revision"]
    assert record["merge_sha"] == "d" * 40
    payload["evidence"]["merge_sha"] = "e" * 40
    write(evidence, payload)
    with pytest.raises(AutoDevStateError):
        record_development_family_target_merge(family["state"], evidence_file=evidence, idempotency_key="actual-sibling-merge")


def test_real_sibling_first_merge_then_native_primary_merge_retains_both_records(family: dict) -> None:
    authority = finalize(family)
    stable = family["repo"].parent / "stable-first"
    _git("worktree", "add", str(stable), "release", cwd=family["repo"])
    _git("merge", "--no-ff", "feature/sibling", "-m", "merge: sibling first", cwd=stable)
    sibling_merge = _git("rev-parse", "HEAD", cwd=stable)
    provider = json.loads(family["provider"].read_text())
    provider["pr"].update(state="MERGED", mergeCommit={"oid": sibling_merge},
                          mergedAt=datetime.now(timezone.utc).isoformat(), baseRefOid=sibling_merge)
    readback = write(family["packet"] / "artifacts/sibling-first-provider.json", provider)
    evidence = write(family["packet"] / "artifacts/sibling-first-merged.json", {
        "schema": "development-stage-evidence/v1", "state": "merged", "status": "completed",
        "summary": "Actual sibling merge before primary", "verified_at": datetime.now(timezone.utc).isoformat(),
        "evidence": {**family["target"], "source_head_sha": family["target"]["subject_revision"],
                     "merge_sha": sibling_merge, "readback_verified": True, "readiness_authority": authority,
                     "provider_readback": bound(readback)},
    })
    sibling_record = record_development_family_target_merge(family["state"], evidence_file=evidence,
                                                           idempotency_key="sibling-first-real-merge")
    validate_auto_dev_readiness_authority(family["state"], family["primary_authority"],
        expected_subject=family["primary_head"], expected_pull_request=family["primary_authority"])
    primary_branch = family["task"].read()["worktree"]["branch"]
    _git("merge", "--no-ff", primary_branch, "-m", "merge: primary second", cwd=family["repo"])
    primary_merge = _git("rev-parse", "HEAD", cwd=family["repo"])
    primary_payload = {k: v for k, v in family["primary_authority"].items()
                       if k not in {"owner", "ref", "sha256", "subject_revision"}}
    primary_payload.update(source_head_sha=family["primary_head"], merge_sha=primary_merge,
                           readback_verified=True, readiness_authority=family["primary_authority"])
    receipt = _stage_receipt(family["packet"] / "artifacts/primary-second-merge", "merged",
                             evidence=primary_payload, status="completed")
    run_development_stage(family["task"].path, stage="merge", receipts={"merged": receipt},
                          idempotency_prefix="primary-second-real-merge")
    after = family["task"].read()
    assert after["state"] == "merged"
    assert after["terminal_revision"] == primary_merge
    assert after["subject_revision"] == family["primary_head"]
    assert after["family_merges"][authority["target_key"]] == sibling_record
    projected = json.loads(family["state"].read_text())
    assert projected["family_targets"][authority["target_key"]]["finalize"] == authority
    assert validate(family, authority) == authority


def test_native_cli_uses_exact_target_recorder_and_read_only_validator(family: dict, capsys) -> None:
    assert main(["auto-dev", "family-target", "finalize", str(family["state"]), "--evidence", str(family["evidence"]), "--idempotency-key", "cli-target", "--json"]) == 0
    authority = json.loads(capsys.readouterr().out)
    path = write(family["packet"] / "artifacts/authority.json", authority)
    before = family["state"].read_bytes()
    args = ["auto-dev", "family-target", "validate", str(family["state"]), "--authority", str(path)]
    for field in ("provider", "pull_request", "repository", "base_branch", "subject_revision", "author_identity", "author_kind"):
        args.extend(["--" + field.replace("_", "-"), family["target"][field]])
    assert main([*args, "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == authority
    assert family["state"].read_bytes() == before
