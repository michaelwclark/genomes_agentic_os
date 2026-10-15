"""Real two-base sibling authority, immutable proof, and lifecycle isolation."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path

import pytest

from genomes_agentic_os.auto_dev_orchestration import (
    AutoDevStateError, record_auto_dev_family_target_finalize,
    validate_auto_dev_readiness_authority,
)
from genomes_agentic_os.cli import main
from genomes_agentic_os.development_delivery import (
    TaskState, record_development_family_target_merge, start_development_run,
)
from genomes_agentic_os.review_coordination import ReviewCoordinator, ReviewSubject
from genomes_agentic_os.family_target_delivery import _provider
from test_development_delivery import (
    _advance_auto_dev_task_to_ready, _complete_pre_merge_auto_dev,
    _git, _project, _repository,
)


def write(path: Path, payload: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return path


def bound(path: Path) -> dict[str, str]:
    return {"ref": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def canonical_sha(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


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

    provider = {"observed_at": datetime.now(timezone.utc).isoformat(), "readback_verified": True,
                "pr": {"number": 2, "url": "https://github.com/acme/app/pull/2", "baseRefName": "release", "baseRefOid": base,
                       "headRefName": "feature/sibling", "headRefOid": head, "state": "OPEN", "isDraft": False,
                       "author": {"login": "michaelwclark"}, "mergeable": "MERGEABLE",
                       "statusCheckRollup": [{"__typename": "CheckRun", "name": "tests", "status": "COMPLETED", "conclusion": "SUCCESS"}]},
                "review_threads": {"pageInfo": {"hasNextPage": False}, "nodes": []}}
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
        check_matrix=[{"check_id": name, "status": "pass"} for name in ("jira_github_alignment", "exact_release_identity", "qa_per_jira", "whole_diff_policy", "risk_gates", "artifact_rollback_observability", "runtime_consumer_contracts")],
        qa_runs=[bound(qa)], consumer_contract_matrix=[{"consumer_id": "source-cli", "status": "pass", "evidence_ref": str(terminal)}],
        tenant_impact_matrix=[{"tenant": "isolated", "status": "pass", "evidence_ref": str(terminal)}],
        compatibility_strategy="source qualification only; distribution and runtime gates remain separate",
        contract_test_runs=[bound(terminal)], runtime_readbacks=[{"environment": "isolated fixture", "status": "pass"}],
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


@pytest.mark.parametrize("change", ["pending", "failure", "skip", "threads", "pagination", "draft", "conflict", "head", "base", "stale"])
def test_finalize_refuses_current_provider_failures(family: dict, change: str) -> None:
    provider = json.loads(family["provider"].read_text())
    check = provider["pr"]["statusCheckRollup"][0]
    if change == "pending": check["status"] = "IN_PROGRESS"
    if change == "failure": check["conclusion"] = "FAILURE"
    if change == "skip": check["conclusion"] = "SKIPPED"
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


def test_provider_skip_requires_the_real_main_event_and_frozen_condition(family: dict) -> None:
    workflow = family["sibling"] / ".github/workflows/ci.yml"
    workflow.parent.mkdir(parents=True)
    condition = "github.event_name == 'pull_request' && github.base_ref != 'main'"
    workflow.write_text("jobs:\n  convention:\n    name: Conventional Commits\n    if: \"" + condition + "\"\n")
    _git("add", ".", cwd=family["sibling"])
    _git("commit", "-m", "ci: conditional conventional check", cwd=family["sibling"])
    head = _git("rev-parse", "HEAD", cwd=family["sibling"])
    target = {**family["target"], "base_branch": "main", "subject_revision": head}
    provider = json.loads(family["provider"].read_text())
    provider["pr"].update(baseRefName="main", headRefOid=head)
    provider["pr"]["statusCheckRollup"][0].update(name="Conventional Commits", conclusion="SKIPPED")
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
