"""Canonical review identities remain immutable at selected-catalog readiness."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest
import yaml

import genomes_agentic_os.development_delivery as delivery
from genomes_agentic_os.review_coordination import (
    ReviewCoordinationError,
    ReviewCoordinator,
    ReviewSubject,
)
from test_development_delivery import (
    _git,
    _project,
    _provider_authority,
    _record_standalone_stage,
    _repository,
    _stage_receipt,
)


def _fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple:
    repo, base = _repository(tmp_path)
    branch = "feature/cc-55"
    _git("checkout", "-b", branch, cwd=repo)
    _git("commit", "--allow-empty", "-m", "fix: reviewed catalog source", cwd=repo)
    head = _git("rev-parse", "HEAD", cwd=repo)
    _git("remote", "set-url", "origin", "git@github.com:acme/app.git", cwd=repo)
    root = tmp_path / "os"
    project = _project(root, repo, repository_id="user_app")
    profile_path = project / "config/development.yml"
    profile = yaml.safe_load(profile_path.read_text())
    row = {"id": "user_app", "root": str(repo), "github": "acme/app", "base_branch": "main"}
    profile["repository"] = {"selection_required": True, "catalog": [row]}
    profile_path.write_text(yaml.safe_dump(profile), encoding="utf-8")
    delivery.register_project_worktree(root, "acme", "app", "cc-55", path=repo)
    registered = delivery.worktree_entries_for_project(project)[0]["id"]
    profile_path.write_text(yaml.safe_dump(profile), encoding="utf-8")
    monkeypatch.setattr(delivery, "create_isolated_worktree", lambda **kwargs: {
        "name": registered, "path": str(repo), "branch": branch,
        "base_sha": base, "repository_id": "user_app",
    })
    run = delivery.start_development_run(
        root, "acme", "app", ["CC-55"], repository_id="user_app",
        run_id="catalog-review", auto_dev_mode="everything", apply=True,
    )
    task = delivery.TaskState(Path(run["tasks"][0]["state_ref"]))
    work_item = Path(task.read()["work_item"])
    delivery.run_development_stage(
        task.path, stage="readiness",
        receipts={"planned": _stage_receipt(work_item, "planned")},
        idempotency_prefix="catalog:readiness",
    )
    delivery.run_development_stage(
        task.path, stage="implementation",
        receipts={name: _stage_receipt(work_item, name) for name in ("implementing", "local_validation")},
        idempotency_prefix="catalog:implementation",
    )
    for name in ("groom", "detective", "create_artifacts", "document"):
        _record_standalone_stage(task, name)
    evidence = {
        **_provider_authority(task, pull_request="user_app#55"),
        "github_repository": "acme/app", "base_sha": base,
        "source_branch": branch, "source_head_sha": head, "subject_revision": head,
        "checks_verified": True, "reviews_verified": True,
        "provider_observed": {
            "repository": "acme/app", "pull_request": "github:acme/app#55",
            "base_branch": "main", "base_sha": base, "source_branch": branch,
            "head_sha": head, "state": "OPEN", "is_draft": False,
        },
        "repository_alias_authority": {
            "schema": "development-repository-alias-authority/v1", "kind": "current_catalog",
            "profile_source": str(profile_path),
            "profile_sha256": hashlib.sha256(profile_path.read_bytes()).hexdigest(),
            "catalog_entry_sha256": delivery._json_sha256(row),
            "repository_id": "user_app", "root": str(repo), "base_branch": "main",
            "github_repository": "acme/app", "canonical_origin": "git:github.com/acme/app",
            "worktree_path": str(repo),
        },
    }
    delivery.run_development_stage(
        task.path, stage="release_propagation",
        receipts={"release_propagation": _stage_receipt(
            work_item / "artifacts/delivery", "release_propagation", evidence=evidence,
        )}, idempotency_prefix="catalog:pr-create",
    )
    subject = ReviewSubject(
        repository="acme/app", pull_request="github:acme/app#55", base_branch="main",
        base_sha=base, head_sha=head, policy_fingerprint=task.read()["policy_fingerprint"],
    )
    canonical = ReviewCoordinator(work_item / "artifacts/canonical-review").execute(
        subject, lambda: {"outcome": "clean"},
    )
    _bind_review(evidence, canonical)
    return task, repo, evidence, canonical


def _bind_review(evidence: dict, canonical: object) -> None:
    evidence.update({
        "review_coordination_receipt": str(canonical.receipt_path),
        "review_policy_fingerprint": canonical.receipt["subject"]["policy_fingerprint"],
        "canonical_review_key": canonical.key,
        "canonical_review_receipt_sha256": hashlib.sha256(canonical.receipt_path.read_bytes()).hexdigest(),
        "canonical_subject": deepcopy(canonical.receipt["subject"]),
    })


def _assert_review(task: delivery.TaskState, evidence: dict) -> dict:
    return delivery._assert_exact_catalog_alias_review_receipt(
        Path(evidence["review_coordination_receipt"]), evidence=evidence, task=task.read(),
        policy_fingerprint=task.read()["policy_fingerprint"],
    )


def test_catalog_review_records_only_new_provenance_and_exact_replay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    task, _, evidence, canonical = _fixture(tmp_path, monkeypatch)
    original = canonical.receipt_path.read_bytes()
    work_item = Path(task.read()["work_item"])
    old_receipts = {
        Path(item["ref"]): Path(item["ref"]).read_bytes()
        for item in task.read()["receipts"] if Path(item["ref"]).is_file()
    }
    with pytest.raises(ReviewCoordinationError, match="pull_request, repository"):
        delivery.assert_exact_head_review_receipt(
            canonical.receipt_path, head_sha=evidence["subject_revision"],
            repository="user_app", pull_request="user_app#55",
        )
    receipts = {name: _stage_receipt(work_item, name) for name in (
        "pre_pr_review", "ci_repair", "review_repair", "post_pr_review",
    )}
    receipts["pr_open"] = _stage_receipt(work_item, "pr_open", evidence=evidence)
    receipts["ready_for_merge"] = _stage_receipt(work_item, "ready_for_merge", evidence=evidence)
    missing_authority = deepcopy(evidence)
    missing_authority.pop("repository_alias_authority")
    refused = {**receipts, "ready_for_merge": _stage_receipt(
        work_item / "missing-alias-authority", "ready_for_merge", evidence=missing_authority,
    )}
    before = {path: path.read_bytes() for path in (task.path, task.ledger, Path(task.read()["autodev_path"]))}
    with pytest.raises(delivery.DevelopmentDeliveryError, match="pull_request, repository"):
        delivery.run_development_stage(
            task.path, stage="review", receipts=refused, idempotency_prefix="catalog:review:refused",
        )
    assert all(path.read_bytes() == raw for path, raw in before.items())
    raw_ready = Path(receipts["ready_for_merge"]).read_bytes()
    result = delivery.run_development_stage(
        task.path, stage="review", receipts=receipts, idempotency_prefix="catalog:review",
    )
    assert result["state"] == "ready_for_merge"
    ready = next(item for item in reversed(task.read()["receipts"]) if item["state"] == "ready_for_merge")
    stored = json.loads(Path(ready["ref"]).read_bytes())["evidence"]
    provenance = stored["review_identity_normalization"]
    assert provenance["authority_kind"] == "current_catalog"
    assert provenance["canonical_review_key"] == canonical.key
    assert provenance["canonical_review_receipt_sha256"] == hashlib.sha256(original).hexdigest()
    assert provenance["canonical_subject"] == canonical.receipt["subject"]
    assert provenance["selected_identity"] == {"repository": "user_app", "pull_request": "user_app#55"}
    assert stored["canonical_subject"] == canonical.receipt["subject"]
    assert delivery.run_development_stage(
        task.path, stage="review", receipts=receipts, idempotency_prefix="catalog:review",
    )["state"] == "ready_for_merge"
    assert canonical.receipt_path.read_bytes() == original
    assert Path(receipts["ready_for_merge"]).read_bytes() == raw_ready
    assert all(path.read_bytes() == raw for path, raw in old_receipts.items())


def test_catalog_review_rejects_actual_canonical_subject_and_outcome_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    task, _, evidence, canonical = _fixture(tmp_path, monkeypatch)
    unchanged = {path: path.read_bytes() for path in (task.path, task.ledger, canonical.receipt_path)}
    mutations = {
        "repository": {"repository": "acme/other"},
        "pr": {"pull_request": "github:acme/app#56"},
        "unqualified_pr": {"pull_request": "acme/app#55"},
        "base": {"base_sha": "a" * 40},
        "branch": {"base_branch": "release"},
        "head": {"head_sha": "b" * 40},
        "purpose": {"purpose": "review_others"},
        "policy": {"policy_fingerprint": "c" * 64},
        "findings": {}, "unavailable": {},
    }
    for name, changed in mutations.items():
        subject = ReviewSubject(**{**canonical.receipt["subject"], **changed})
        outcome = name if name in {"findings", "unavailable"} else "clean"
        actual = ReviewCoordinator(tmp_path / name).execute(subject, lambda: {"outcome": outcome})
        candidate = deepcopy(evidence)
        _bind_review(candidate, actual)
        raw = actual.receipt_path.read_bytes()
        with pytest.raises((delivery.DevelopmentDeliveryError, ReviewCoordinationError)):
            _assert_review(task, candidate)
        assert actual.receipt_path.read_bytes() == raw
        assert all(path.read_bytes() == before for path, before in unchanged.items())


def test_catalog_review_rejects_forged_current_authority_and_dirty_stale_worktree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    task, repo, evidence, canonical = _fixture(tmp_path, monkeypatch)
    original = {path: path.read_bytes() for path in (task.path, task.ledger, canonical.receipt_path)}
    mutations = (
        (("canonical_review_receipt_sha256",), "0" * 64),
        (("canonical_review_key",), "0" * 64),
        (("canonical_subject", "repository"), "acme/other"),
        (("readback_verified",), False),
        (("repository_alias_authority",), None),
        (("repository_alias_authority", "profile_sha256"), "0" * 64),
        (("provider_observed", "source_branch"), "feature/other"),
        (("provider_observed", "head_sha"), "d" * 40),
        (("provider_observed", "base_sha"), "d" * 40),
        (("provider_observed", "is_draft"), True),
        (("provider_observed", "state"), "CLOSED"),
    )
    for keys, replacement in mutations:
        candidate = deepcopy(evidence)
        value = candidate
        for key in keys[:-1]:
            value = value[key]
        value[keys[-1]] = replacement
        with pytest.raises(delivery.DevelopmentDeliveryError):
            _assert_review(task, candidate)
        assert all(path.read_bytes() == before for path, before in original.items())
    (repo / "untracked.txt").write_text("dirty\n")
    with pytest.raises(delivery.DevelopmentDeliveryError, match="clean registered"):
        _assert_review(task, evidence)
    (repo / "untracked.txt").unlink()
    _git("commit", "--allow-empty", "-m", "fix: later unchecked source", cwd=repo)
    with pytest.raises(delivery.DevelopmentDeliveryError, match="head is stale"):
        _assert_review(task, evidence)
    _git("reset", "--hard", evidence["source_head_sha"], cwd=repo)
    _git("remote", "set-url", "origin", "git@github.com:acme/other.git", cwd=repo)
    with pytest.raises(delivery.DevelopmentDeliveryError, match="canonical origin"):
        _assert_review(task, evidence)
    _git("remote", "set-url", "origin", "git@github.com:acme/app.git", cwd=repo)
    task_value = task.read()
    task_value["repository"]["id"] = "git:github.com/acme/app"
    with pytest.raises(delivery.DevelopmentDeliveryError, match="exact selected GitHub"):
        delivery._assert_exact_catalog_alias_review_receipt(
            canonical.receipt_path, evidence=evidence, task=task_value,
            policy_fingerprint=task.read()["policy_fingerprint"],
        )
    assert all(path.read_bytes() == before for path, before in original.items())


def test_catalog_review_rejects_receipt_replacement_during_comparison(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    task, _, evidence, canonical = _fixture(tmp_path, monkeypatch)
    raw = canonical.receipt_path.read_bytes()
    original = delivery._normalize_exact_catalog_alias_github_identity

    def replace_during_proof(*args: object) -> tuple:
        result = original(*args)
        canonical.receipt_path.write_bytes(raw + b"\n")
        return result

    monkeypatch.setattr(delivery, "_normalize_exact_catalog_alias_github_identity", replace_during_proof)
    with pytest.raises(delivery.DevelopmentDeliveryError, match="changed during validation"):
        _assert_review(task, evidence)
    canonical.receipt_path.write_bytes(raw)
    assert task.read()["state"] == "local_validation"


def test_catalog_review_accepts_genuine_capped_operator_resolution_without_relabeling(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    task, _, evidence, canonical = _fixture(tmp_path, monkeypatch)
    coordinator = ReviewCoordinator(tmp_path / "operator")

    def findings() -> dict:
        return {"outcome": "findings", "findings": [{
            "id": "fixture-repair", "severity": "blocking", "summary": "Fixture source needs repair",
            "evidence": ["source:fixture"],
        }]}

    parent = None
    for digit in ("1", "2", "3", "4"):
        subject = ReviewSubject(**{**canonical.receipt["subject"], "head_sha": digit * 40})
        parent = coordinator.execute(
            subject, findings, mode="full" if parent is None else "delta",
            parent_key=None if parent is None else parent.key,
        )
    resolved = coordinator.resolve_capped_findings(
        ReviewSubject(**canonical.receipt["subject"]), parent_key=parent.key,
        approval_ref="fixture:explicit-operator-approval",
        test_evidence={"head_sha": evidence["source_head_sha"], "verified": True, "refs": ["fixture:test"]},
        ci_evidence={"head_sha": evidence["source_head_sha"], "verified": True, "refs": ["fixture:ci"]},
        resolutions={"fixture-repair": ["fixture:source-repair", "fixture:test", "fixture:ci"]},
    )
    assert resolved.receipt["mode"] == "operator_resolution"
    assert resolved.receipt["outcome"] == "clean"
    _bind_review(evidence, resolved)
    raw = resolved.receipt_path.read_bytes()
    provenance = _assert_review(task, evidence)
    assert provenance["canonical_review_key"] == resolved.key
    assert provenance["canonical_subject"] == resolved.receipt["subject"]
    assert resolved.receipt_path.read_bytes() == raw
