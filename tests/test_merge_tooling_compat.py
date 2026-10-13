"""Offline regressions for exact receipt compatibility; no provider writes."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
import yaml

import genomes_agentic_os.auto_dev_orchestration as auto_dev
import genomes_agentic_os.development_delivery as delivery
from genomes_agentic_os.artifact_contracts import _load_governance_receipt, record_artifact_readback
from genomes_agentic_os.review_coordination import (
    ReviewCoordinationError, assert_exact_head_review_receipt, load_review_receipt,
)
from test_development_delivery import (
    _advance_auto_dev_task_to_ready, _project, _record_standalone_stage,
    _repository, _stage_receipt, _git, _provider_authority,
    _readiness_authority,
)
from test_opposing_model_review_runner import _load_runner


def _task(tmp_path, monkeypatch, *, review_policy="continue_with_receipt",
          profile_base="main", task_base=None, touched_paths=(), subjects=()):
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
        touched_paths=touched_paths, subjects=subjects,
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


def _targets_only_refresh_fixture(tmp_path, monkeypatch, *, change_legacy=None,
                                  native_output=True):
    """Seal the real legacy producer shape through the normal offline recorder."""

    paths = ["src/genomes_agentic_os/development_delivery.py",
             "tests/test_merge_tooling_compat.py"]
    task, root, repo, old_head = _task(
        tmp_path, monkeypatch, touched_paths=paths, subjects=["development-delivery"]
    )
    for stage in ("groom", "detective", "create_artifacts"):
        _record_standalone_stage(task, stage)
    delivery.run_development_stage(task.path, stage="readiness", receipts={
        "planned": _stage_receipt(tmp_path / "planning", "planned"),
    }, idempotency_prefix="targets:readiness")
    delivery.run_development_stage(task.path, stage="implementation", receipts={
        "implementing": _stage_receipt(tmp_path / "implementation", "implementing"),
        "local_validation": _stage_receipt(tmp_path / "validation", "local_validation"),
    }, idempotency_prefix="targets:implementation")
    _record_standalone_stage(task, "document")
    current = task.read()
    packet = Path(current["work_item"])
    directory = packet / "artifacts" / "original-pr-create"
    directory.mkdir(parents=True)
    provider = directory / "PROVIDER-READBACK.json"
    applied = directory / "PR-APPLY.json"
    approval = directory / "APPROVAL.json"
    target_identity = "github:repo:acme/app:base:main"
    url = "https://github.com/acme/app/pull/54"
    content = {"title": "CC-54 qualify original receipt provenance",
               "body": "Offline fixture for the original pull-request producer.\n"}
    content_sha = delivery._json_sha256(content)
    observed = {
        "target_identity": target_identity, "rendered_content_hash": content_sha,
        "number_or_comment_id": "54", "repository": "acme/app",
        "rendered_body": content["body"], "pull_request_number": 54,
        "head_sha": old_head, "base_branch": "main", "base_sha": old_head,
        "draft": True, "state": "open", "author": "fixture-operator",
        "head_branch": "feature/cc-54", "repository_id": 123,
    }
    envelope = {
        "schema": "artifact-provider-readback/v1", "status": "verified",
        "provider": "github", "target": target_identity, "external_id": "54",
        "external_url": url, "verified_at": "2026-10-12T00:00:00Z",
        "transport": "composio_mcp", "account": "github_fixture",
        "log_id": "fixture-pr-create-54", "observed": observed, "content": content,
    }
    provider.write_text(json.dumps(envelope, indent=2), encoding="utf-8")
    approval_value = {
        "schema": "artifact-approval/v1", "status": "approved", "provider": "github",
        "target": target_identity, "artifact_type": "pull-request",
    }
    approval.write_text(json.dumps(approval_value), encoding="utf-8")
    applied.write_text(json.dumps({
        "schema": "artifact-apply/v1", "status": "awaiting_provider_adapter",
        "artifact_type": "pull-request", "provider": "github", "target": target_identity,
        "required_readback": list(observed), "expected_content_sha256": content_sha,
        "approval_receipt": _load_governance_receipt(
            root, approval, schema="artifact-approval/v1", label="approval",
        ),
        "target_verification": {
            "schema": "artifact-target-verification/v1", "status": "verified",
            "provider": "github", "target": target_identity, "repository": "acme/app",
            "repository_id": observed["repository_id"], "account": envelope["account"],
            "transport": envelope["transport"], "base_branch": "main", "base_sha": old_head,
            "log_id": "fixture-independent-target-verification-54",
        },
    }), encoding="utf-8")
    # Exercise the original producer's content hashing and completed readback shape.
    readback_output = record_artifact_readback(root, applied, readback_receipt=provider)
    refs = []
    for name in ("SOURCE-SNAPSHOT", "TARGET-VERIFICATION", "PR-VALIDATION"):
        path = directory / f"{name}.json"
        path.write_text(json.dumps({"schema": "fixture-observation/v1", "kind": name}),
                        encoding="utf-8")
        refs.append(str(path))
    refs.extend([str(applied), str(provider)])
    record = directory / "READBACK-RECORD.json"
    record.write_text(json.dumps(readback_output if native_output else {
        "native": "fixture-readback", "exit_code": 0, "result": readback_output,
    }), encoding="utf-8")
    refs.append(str(record))
    fingerprint = current["policy_fingerprint"]
    target = {
        "action_classification": "created_pull_request", "authority_snapshot": str(approval),
        "base_branch": "main", "base_sha": old_head, "draft": True,
        "effective_policy_fingerprint": fingerprint, "head_sha": old_head,
        "provider_log_id": envelope["log_id"], "provider_readback": str(provider),
        "pull_request_number": 54, "pull_request_url": url, "repository": "acme/app",
        "source_sha": old_head, "ticket": "CC-54",
    }
    details = {
        "complete_tracker_acceptance_claimed": False,
        "effective_policy_fingerprint": fingerprint, "family_status": "complete",
        "installed_primary_or_customer_acceptance_claim": False,
        "integration_dependency": "fixture family precedes review",
        "merge_authorized_by_this_packet": False, "receipt_refs": refs,
        "required_hosted_ci_pending": True, "required_reviews_pending": True,
        "targets": [target], "ticket": "CC-54",
    }
    if change_legacy is not None:
        change_legacy(details)
    prior = _stage_receipt(tmp_path / "original", "release_propagation", evidence=details)
    delivery.run_development_stage(task.path, stage="release_propagation", receipts={
        "release_propagation": prior,
    }, idempotency_prefix="targets:original")
    current = task.read()
    wrapper = Path(current["stage_receipts"]["release_propagation"]["ref"])
    sealed = json.loads(wrapper.read_text(encoding="utf-8"))
    prior_evidence = packet / sealed["receipt"]
    _git("commit", "--allow-empty", "-m", "fixture source successor", cwd=repo)
    new_head = _git("rev-parse", "HEAD", cwd=repo)
    binding = {
        "ticket": current["ticket"], "work_item": current["work_item"],
        "worktree": current["worktree"]["path"],
        "policy_fingerprint": current["policy_fingerprint"],
        "context_selection_sha256": current["context_selection"]["content_sha256"],
        "lease_owner": (current.get("lease") or {}).get("owner"),
    }
    successor = {
        "repository": "git:github.com/acme/app", "base_branch": "main", "provider": "github",
        "pull_request": "github:acme/app#54", "source_branch": "feature/cc-54",
        "source_head_sha": new_head, "readback_verified": True,
        "provider_observed": {"head_sha": new_head}, "selected_task_binding": binding,
        "supersession": {
            "supersedes_source_head_sha": old_head, "reason": "Verified successor fixture head",
            "original_readback": {
                "ref": str(provider), "raw_sha256": hashlib.sha256(provider.read_bytes()).hexdigest(),
                "prior_wrapper_sha256": hashlib.sha256(wrapper.read_bytes()).hexdigest(),
                "prior_evidence_sha256": sealed["evidence_sha256"],
            },
        },
    }
    return {"task": task, "root": root, "repo": repo, "packet": packet,
            "provider": provider, "applied": applied, "approval": approval,
            "readback_output": record, "native_output": native_output,
            "details": details, "successor": successor, "prior": Path(prior),
            "wrapper": wrapper, "prior_evidence": prior_evidence,
            "old_head": old_head, "new_head": new_head, "content_sha": content_sha}


def _normalize_targets_only(fixture):
    return delivery._normalize_exact_targets_only_family_identity(
        fixture["details"], task=fixture["task"].read(),
        refreshed_details=fixture["successor"], prior_wrapper_ref=fixture["wrapper"],
        prior_wrapper_sha256=hashlib.sha256(fixture["wrapper"].read_bytes()).hexdigest(),
        prior_evidence_sha256=json.loads(fixture["wrapper"].read_text())["evidence_sha256"],
        expected_repository="git:github.com/acme/app", expected_base_branch="main",
        expected_source_branch="feature/cc-54", pull_request_prefix="github:acme/app#",
    )


def _refresh_targets_only(fixture, tmp_path, *, key="targets:successor", installed_cli=None):
    receipt = _stage_receipt(tmp_path / "successor", "release_propagation",
                             evidence=fixture["successor"])
    if installed_cli:
        console = Path(installed_cli)
        assert console.is_absolute() and console.is_file()
        home = fixture["root"] / "console-home"
        home.mkdir(exist_ok=True)
        completed = subprocess.run([
            str(console), "develop", "stage", str(fixture["task"].path),
            "--stage", "release_propagation", "--receipt", f"release_propagation={receipt}",
            "--idempotency-prefix", key, "--json",
        ], cwd=fixture["root"], capture_output=True, text=True, check=False, env={
            "HOME": str(home),
            "PATH": os.pathsep.join([str(console.parent), "/opt/homebrew/bin", "/usr/bin", "/bin"]),
            "PYTHONDONTWRITEBYTECODE": "1",
        })
        assert completed.returncode == 0, completed.stderr
        return json.loads(completed.stdout)
    return delivery.run_development_stage(fixture["task"].path, stage="release_propagation",
                                         receipts={"release_propagation": receipt},
                                         idempotency_prefix=key)


def _canonical_refresh_snapshot(fixture):
    """Detect partial snapshots as well as state, projection and ledger effects."""

    paths = [fixture["packet"], fixture["task"].path.parents[2]]
    snapshot = {}
    for root in paths:
        for path in root.rglob("*"):
            if path.is_symlink():
                snapshot[str(path)] = ("symlink", str(path.readlink()))
            elif path.is_file():
                snapshot[str(path)] = ("file", path.read_bytes())
            elif path.is_dir():
                snapshot[str(path)] = ("directory",)
    return snapshot


@pytest.mark.parametrize("native_output", [True, False])
def test_targets_only_uses_genuine_provider_envelope_without_rewriting_history(
        tmp_path, monkeypatch, native_output):
    fixture = _targets_only_refresh_fixture(tmp_path, monkeypatch, native_output=native_output)
    before = _canonical_refresh_snapshot(fixture)
    original_details = deepcopy(fixture["details"])
    normalized, provenance = _normalize_targets_only(fixture)
    assert normalized["source_head_sha"] == fixture["old_head"]
    assert normalized["source_branch"] == "feature/cc-54"
    assert normalized["pull_request"] == "github:acme/app#54"
    assert provenance["source"] == "exact_targets_only_family_with_provider_envelope"
    assert provenance["original_readback"] == fixture["successor"]["supersession"]["original_readback"]
    assert provenance["rendered_content_sha256"] == fixture["content_sha"]
    assert provenance["original_readback"]["raw_sha256"] != fixture["content_sha"]
    applied = json.loads(fixture["applied"].read_text())
    assert applied["approval_receipt"] == {
        **json.loads(fixture["approval"].read_text()),
        "receipt_ref": fixture["approval"].relative_to(fixture["root"]).as_posix(),
    }
    assert provenance["original_apply"] == {
        "ref": str(fixture["applied"]),
        "raw_sha256": hashlib.sha256(fixture["applied"].read_bytes()).hexdigest(),
    }
    if native_output:
        assert json.loads(fixture["readback_output"].read_text()) == {
            **applied, "receipt_ref": fixture["applied"].relative_to(fixture["root"]).as_posix(),
        }
        assert provenance["original_apply_outputs"] == [{
            "ref": str(fixture["readback_output"]),
            "raw_sha256": hashlib.sha256(fixture["readback_output"].read_bytes()).hexdigest(),
            "canonical_ref": str(fixture["applied"]),
        }]
    else:
        assert set(json.loads(fixture["readback_output"].read_text())) == {
            "native", "exit_code", "result",
        }
        assert provenance["original_apply_outputs"] == []
    assert fixture["details"] == original_details
    assert not {"schema", "source", "source_head_sha", "head_sha", "source_branch"} & set(original_details)
    assert fixture["task"].read()["context_selection"]["selection"]["selected_documents"] == []
    assert _canonical_refresh_snapshot(fixture) == before


@pytest.mark.parametrize("native_output", [True, False])
def test_targets_only_normal_refresh_preserves_predecessor_and_replays_without_effect(
        tmp_path, monkeypatch, native_output):
    fixture = _targets_only_refresh_fixture(tmp_path, monkeypatch, native_output=native_output)
    task = fixture["task"]
    current = task.read()
    original_files = {path: path.read_bytes() for path in (
        fixture["wrapper"], fixture["prior_evidence"], fixture["prior"],
        fixture["provider"], fixture["applied"], fixture["approval"], fixture["readback_output"],
        Path(current["policy_receipt"]),
    )}
    installed_cli = os.environ.get("RUBICON_AGE248_INSTALLED_CLI")
    result = _refresh_targets_only(fixture, tmp_path, installed_cli=installed_cli)
    provenance = result["supersedes"]["legacy_identity_normalization"]
    assert provenance["source"] == "exact_targets_only_family_with_provider_envelope"
    assert provenance["normalized_identity"]["source_head_sha"] == fixture["old_head"]
    after = task.read()
    assert after["state"] == "local_validation"
    assert after["context_selection"] == current["context_selection"]
    assert after.get("owner") == current.get("owner")
    assert after.get("lease") == current.get("lease")
    assert after["receipts"][:len(current["receipts"])] == current["receipts"]
    assert all(path.read_bytes() == raw for path, raw in original_files.items())
    replay_before = _canonical_refresh_snapshot(fixture)
    replay = _refresh_targets_only(fixture, tmp_path, installed_cli=installed_cli)
    assert replay == result
    assert _canonical_refresh_snapshot(fixture) == replay_before



def _change_fixture_field(value, field, replacement):
    """Alter one input fact; '__drop__' represents a missing field."""

    parts = field.split(".")
    for part in parts[:-1]:
        value = value[int(part)] if isinstance(value, list) else value[part]
    leaf = parts[-1]
    if replacement == "__drop__":
        value.pop(int(leaf) if isinstance(value, list) else leaf)
    else:
        value[int(leaf) if isinstance(value, list) else leaf] = deepcopy(replacement)


def _assert_targets_only_refused(fixture, tmp_path, *, public=True,
                                key="targets:successor", match=None):
    before = _canonical_refresh_snapshot(fixture)
    with pytest.raises(delivery.DevelopmentDeliveryError, match=match):
        if public:
            _refresh_targets_only(fixture, tmp_path, key=key)
        else:
            _normalize_targets_only(fixture)
    assert _canonical_refresh_snapshot(fixture) == before


@pytest.mark.parametrize("field,replacement", [
    ("family_status", "pending"), ("ticket", "CC-55"),
    ("effective_policy_fingerprint", "not-a-fingerprint"),
    ("complete_tracker_acceptance_claimed", True),
    ("complete_tracker_acceptance_claimed", 0),
    ("installed_primary_or_customer_acceptance_claim", True),
    ("merge_authorized_by_this_packet", True),
    ("required_hosted_ci_pending", "true"), ("required_reviews_pending", 1),
    ("integration_dependency", "__drop__"),
    ("schema", "auto-dev-pr-create-family/v1"),
    ("source", {"head_sha": "a" * 40}), ("family", []),
    ("source_head_sha", "a" * 40), ("head_sha", "a" * 40),
    ("targets", []), ("targets", [None]), ("targets", [{}, {}]),
    ("targets.0.action_classification", "reused_pull_request"),
    ("targets.0.repository", "foreign/app"), ("targets.0.ticket", "CC-55"),
    ("targets.0.base_branch", "develop"),
    ("targets.0.effective_policy_fingerprint", "a" * 64),
    ("targets.0.pull_request_number", True), ("targets.0.pull_request_number", 0),
    ("targets.0.pull_request_number", "54"),
    ("targets.0.draft", 1), ("targets.0.head_sha", "a" * 39),
    ("targets.0.head_sha", 42), ("targets.0.source_sha", "b" * 40),
    ("targets.0.base_sha", "b" * 39), ("targets.0.provider_log_id", ""),
    ("targets.0.provider_log_id", 42),
    ("targets.0.pull_request_url", "https://github.com/foreign/app/pull/54"),
    ("targets.0.extra_alias", "unexpected"),
    ("receipt_refs", []), ("receipt_refs", "not-a-list"),
    ("receipt_refs.0", ""), ("receipt_refs.0", 42),
])
def test_targets_only_rejects_legacy_shape_conflicts_without_effect(
        tmp_path, monkeypatch, field, replacement):
    fixture = _targets_only_refresh_fixture(
        tmp_path, monkeypatch,
        change_legacy=lambda details: _change_fixture_field(details, field, replacement),
    )
    _assert_targets_only_refused(fixture, tmp_path)


@pytest.mark.parametrize("field,replacement", [
    ("supersession", None),
    ("supersession.original_readback", None),
    ("supersession.original_readback.extra", "unbound"),
    ("supersession.original_readback.ref", "PROVIDER-READBACK.json"),
    ("supersession.original_readback.raw_sha256", "malformed"),
    ("supersession.original_readback.raw_sha256", "a" * 64),
    ("supersession.original_readback.prior_wrapper_sha256", "a" * 64),
    ("supersession.original_readback.prior_evidence_sha256", "a" * 64),
    ("selected_task_binding", None), ("selected_task_binding.extra", "unbound"),
    ("selected_task_binding.ticket", "CC-55"),
    ("selected_task_binding.work_item", "/foreign/packet"),
    ("selected_task_binding.worktree", "/foreign/worktree"),
    ("selected_task_binding.policy_fingerprint", "a" * 64),
    ("selected_task_binding.context_selection_sha256", "a" * 64),
    ("selected_task_binding.lease_owner", "foreign-owner"),
    ("repository", "git:github.com/foreign/app"), ("base_branch", "develop"),
    ("provider", "gitlab"), ("pull_request", "github:acme/app#55"),
    ("source_branch", "feature/foreign"), ("source_head_sha", "b" * 40),
    ("readback_verified", False), ("provider_observed.head_sha", "b" * 40),
    ("supersession.supersedes_source_head_sha", "b" * 40),
    ("supersession.reason", ""),
])
def test_targets_only_rejects_successor_binding_conflicts_without_effect(
        tmp_path, monkeypatch, field, replacement):
    fixture = _targets_only_refresh_fixture(tmp_path, monkeypatch)
    _change_fixture_field(fixture["successor"], field, replacement)
    if field.startswith("selected_task_binding"):
        _assert_targets_only_refused(fixture, tmp_path, public=False)
    _assert_targets_only_refused(fixture, tmp_path)


@pytest.mark.parametrize("field,replacement", [
    ("status", "unverified"), ("provider", "gitlab"), ("target", "foreign"),
    ("external_id", "55"), ("external_url", "https://github.com/acme/app/pull/55"),
    ("log_id", "foreign-log"), ("verified_at", ""), ("verified_at", 42),
    ("transport", ""), ("account", ""), ("extra", "unbound"),
    ("observed", None), ("content", None), ("content.extra", "unbound"),
    ("content.title", ""), ("content.title", 42), ("content.body", ""),
    ("observed.extra", "unbound"), ("observed.target_identity", "foreign"),
    ("observed.number_or_comment_id", "55"), ("observed.repository", "foreign/app"),
    ("observed.pull_request_number", 55), ("observed.pull_request_number", True),
    ("observed.head_sha", "b" * 40), ("observed.head_branch", "feature/foreign"),
    ("observed.base_branch", "develop"), ("observed.base_sha", "b" * 40),
    ("observed.draft", 1), ("observed.state", "closed"),
    ("observed.rendered_content_hash", "a" * 64),
    ("observed.rendered_body", "foreign body"),
    ("observed.author", ""), ("observed.author", 42),
    ("observed.repository_id", True), ("observed.repository_id", 0),
])
def test_targets_only_rejects_original_envelope_conflicts_without_effect(
        tmp_path, monkeypatch, field, replacement):
    fixture = _targets_only_refresh_fixture(tmp_path, monkeypatch)
    value = json.loads(fixture["provider"].read_text())
    _change_fixture_field(value, field, replacement)
    fixture["provider"].write_text(json.dumps(value), encoding="utf-8")
    # Pin the altered bytes honestly so identity/body checks, not a stale digest, decide.
    fixture["successor"]["supersession"]["original_readback"]["raw_sha256"] = (
        hashlib.sha256(fixture["provider"].read_bytes()).hexdigest()
    )
    _assert_targets_only_refused(fixture, tmp_path)


@pytest.mark.parametrize("field,replacement", [
    ("status", "awaiting_provider_adapter"), ("provider", "gitlab"),
    ("target", "foreign"), ("artifact_type", "comment"), ("approval_receipt", {}),
    ("target_verification", None),
    ("target_verification.schema", "fixture-observation/v1"),
    ("target_verification.status", "unverified"),
    ("target_verification.provider", "gitlab"),
    ("target_verification.target", "foreign"),
    ("target_verification.repository", "foreign/app"),
    ("target_verification.repository_id", 999),
    ("target_verification.account", "foreign-account"),
    ("target_verification.transport", "foreign-transport"),
    ("target_verification.base_branch", "develop"),
    ("target_verification.base_sha", "b" * 40),
    ("target_verification.log_id", ""), ("target_verification.log_id", 42),
    ("expected_content_sha256", "a" * 64),
    ("readback", None), ("readback.verified", False), ("readback.verified", 1),
    ("readback.external_id", "55"),
    ("readback.external_url", "https://github.com/acme/app/pull/55"),
    ("readback.sha256", "a" * 64), ("readback.observed", {}),
    ("readback.receipt_ref", "foreign/PROVIDER-READBACK.json"),
])
def test_targets_only_rejects_original_apply_conflicts_without_effect(
        tmp_path, monkeypatch, field, replacement):
    fixture = _targets_only_refresh_fixture(tmp_path, monkeypatch, native_output=False)
    value = json.loads(fixture["applied"].read_text())
    _change_fixture_field(value, field, replacement)
    fixture["applied"].write_text(json.dumps(value), encoding="utf-8")
    _assert_targets_only_refused(fixture, tmp_path)


@pytest.mark.parametrize("field,replacement", [
    ("schema", "fixture-observation/v1"), ("status", "denied"),
    ("provider", "gitlab"), ("target", "foreign"), ("artifact_type", "comment"),
])
def test_targets_only_rejects_original_approval_conflicts_without_effect(
        tmp_path, monkeypatch, field, replacement):
    fixture = _targets_only_refresh_fixture(tmp_path, monkeypatch)
    value = json.loads(fixture["approval"].read_text())
    _change_fixture_field(value, field, replacement)
    fixture["approval"].write_text(json.dumps(value), encoding="utf-8")
    _assert_targets_only_refused(fixture, tmp_path)


@pytest.mark.parametrize("case", [
    "duplicate_ref", "absent_readback_ref", "foreign_ref", "traversal_ref",
    "symlink_ref", "missing_ref", "directory_ref", "array_json",
    "malformed_json", "duplicate_json_keys", "invalid_utf8",
    "second_envelope", "second_apply", "missing_envelope", "missing_apply",
])
def test_targets_only_rejects_unsafe_or_ambiguous_provenance_without_effect(
        tmp_path, monkeypatch, case):
    def change(details):
        refs = details["receipt_refs"]
        directory = Path(refs[0]).parent
        original = Path(refs[0])
        if case == "duplicate_ref":
            refs.append(refs[0])
        elif case == "absent_readback_ref":
            refs.remove(details["targets"][0]["provider_readback"])
        elif case == "foreign_ref":
            foreign = tmp_path / "foreign.json"
            foreign.write_text("{}")
            refs[0] = str(foreign)
        elif case == "traversal_ref":
            refs[0] = str(directory / ".." / directory.name / original.name)
        elif case == "symlink_ref":
            link = directory / "alias.json"
            link.symlink_to(original)
            refs[0] = str(link)
        elif case == "missing_ref":
            refs[0] = str(directory / "missing.json")
        elif case == "directory_ref":
            refs[0] = str(directory)
        elif case == "array_json":
            original.write_text("[]")
        elif case == "malformed_json":
            original.write_text("{")
        elif case == "duplicate_json_keys":
            original.write_text('{"schema":"a","schema":"b"}')
        elif case == "invalid_utf8":
            original.write_bytes(b"\\xff")
        elif case in {"second_envelope", "second_apply"}:
            source = Path(details["targets"][0]["provider_readback"]) if case == "second_envelope" else Path(refs[3])
            duplicate = directory / (case + ".json")
            duplicate.write_bytes(source.read_bytes())
            refs.append(str(duplicate))
        elif case == "missing_envelope":
            value = json.loads(Path(refs[4]).read_text())
            value["schema"] = "fixture-observation/v1"
            Path(refs[4]).write_text(json.dumps(value))
        elif case == "missing_apply":
            value = json.loads(Path(refs[3]).read_text())
            value["schema"] = "fixture-observation/v1"
            Path(refs[3]).write_text(json.dumps(value))
    fixture = _targets_only_refresh_fixture(tmp_path, monkeypatch, change_legacy=change)
    _assert_targets_only_refused(fixture, tmp_path)


def test_targets_only_rejects_content_digest_used_as_raw_digest_without_effect(tmp_path, monkeypatch):
    fixture = _targets_only_refresh_fixture(tmp_path, monkeypatch)
    fixture["successor"]["supersession"]["original_readback"]["raw_sha256"] = fixture["content_sha"]
    _assert_targets_only_refused(fixture, tmp_path)


def test_targets_only_rejects_boolean_verifier_repository_identity_without_effect(tmp_path, monkeypatch):
    fixture = _targets_only_refresh_fixture(tmp_path, monkeypatch, native_output=False)
    envelope = json.loads(fixture["provider"].read_text())
    envelope["observed"]["repository_id"] = 1
    fixture["provider"].write_text(json.dumps(envelope))
    fixture["successor"]["supersession"]["original_readback"]["raw_sha256"] = (
        hashlib.sha256(fixture["provider"].read_bytes()).hexdigest()
    )
    applied = json.loads(fixture["applied"].read_text())
    applied["readback"]["observed"] = envelope["observed"]
    applied["target_verification"]["repository_id"] = True
    fixture["applied"].write_text(json.dumps(applied))
    _assert_targets_only_refused(fixture, tmp_path)


def test_targets_only_rejects_absolute_apply_ref_even_with_matching_suffix(tmp_path, monkeypatch):
    fixture = _targets_only_refresh_fixture(tmp_path, monkeypatch, native_output=False)
    applied = json.loads(fixture["applied"].read_text())
    applied["readback"]["receipt_ref"] = str(fixture["provider"])
    fixture["applied"].write_text(json.dumps(applied))
    _assert_targets_only_refused(fixture, tmp_path)


@pytest.mark.parametrize("case", ["wrapper_schema", "wrapper_stage", "evidence_schema",
                                  "evidence_state", "evidence_details", "duplicate_wrapper"])
def test_targets_only_rejects_predecessor_integrity_conflicts_without_effect(
        tmp_path, monkeypatch, case):
    fixture = _targets_only_refresh_fixture(tmp_path, monkeypatch)
    if case.startswith("evidence_"):
        value = json.loads(fixture["prior_evidence"].read_text())
        value[{"evidence_schema": "schema", "evidence_state": "state",
               "evidence_details": "evidence"}[case]] = "foreign"
        fixture["prior_evidence"].write_text(json.dumps(value))
    else:
        value = json.loads(fixture["wrapper"].read_text())
        if case == "duplicate_wrapper":
            raw = json.dumps(value)[:-1] + ', "stage":"release_propagation"}'
        else:
            value["schema" if case == "wrapper_schema" else "stage"] = "foreign"
            raw = json.dumps(value)
        fixture["wrapper"].write_text(raw)
    # Preserve stale current-generation descriptor: the changed history cannot be adopted.
    _assert_targets_only_refused(fixture, tmp_path, public=False)
    _assert_targets_only_refused(fixture, tmp_path)



def test_targets_only_refuses_replay_after_normal_lease_owner_change(tmp_path, monkeypatch):
    fixture = _targets_only_refresh_fixture(tmp_path, monkeypatch)
    _refresh_targets_only(fixture, tmp_path)
    fixture["task"].heartbeat(owner="successor-worker", lease_minutes=5,
                              idempotency_key="targets:actual-owner-change")
    _assert_targets_only_refused(fixture, tmp_path)


@pytest.mark.parametrize("field,replacement", [
    ("context_selection.content_sha256", "a" * 64),
    ("context_selection", None), ("lease", {"owner": "foreign-owner"}),
    ("worktree.path", "/foreign/worktree"), ("worktree", None),
    ("policy_fingerprint", "a" * 64), ("ticket", "CC-55"),
])
def test_targets_only_refuses_replay_from_conflicting_external_task_copy(
        tmp_path, monkeypatch, field, replacement):
    fixture = _targets_only_refresh_fixture(tmp_path, monkeypatch)
    _refresh_targets_only(fixture, tmp_path)
    original_state = fixture["task"].path
    original_bytes = original_state.read_bytes()
    copied = fixture["task"].read()
    _change_fixture_field(copied, field, replacement)
    external = original_state.parent / "external-task-copy.json"
    external.write_text(json.dumps(copied))
    # A new state file needs its normal locking substrate before effect comparison.
    external.with_suffix(external.suffix + ".lock").touch()
    fixture["task"] = delivery.TaskState(external)
    _assert_targets_only_refused(fixture, tmp_path)
    assert original_state.read_bytes() == original_bytes


@pytest.mark.parametrize("contents", ["{", "{}"])
def test_targets_only_refuses_immutable_successor_snapshot_collision_without_effect(
        tmp_path, monkeypatch, contents):
    fixture = _targets_only_refresh_fixture(tmp_path, monkeypatch)
    receipt = Path(_stage_receipt(tmp_path / "successor", "release_propagation",
                                 evidence=fixture["successor"]))
    digest = delivery._json_sha256(json.loads(receipt.read_text()))
    snapshot = (fixture["packet"] / "artifacts" / "development-delivery" / "evidence"
                / f"release_propagation-{digest[:20]}.json")
    snapshot.write_text(contents)
    _assert_targets_only_refused(fixture, tmp_path)


def test_targets_only_reuses_existing_successor_wrapper_for_external_task_copy(
        tmp_path, monkeypatch):
    fixture = _targets_only_refresh_fixture(tmp_path, monkeypatch)
    original_state = fixture["task"].path
    external = original_state.parent / "external-task-copy.json"
    external.write_bytes(original_state.read_bytes())
    result = _refresh_targets_only(fixture, tmp_path)
    canonical_after = original_state.read_bytes()
    original_provider = fixture["provider"].read_bytes()
    fixture["task"] = delivery.TaskState(external)
    repeated = _refresh_targets_only(fixture, tmp_path)
    assert repeated == result
    assert original_state.read_bytes() == canonical_after
    assert fixture["provider"].read_bytes() == original_provider
    assert fixture["task"].read()["stage_receipts"]["release_propagation"]["ref"] == (
        json.loads(canonical_after)["stage_receipts"]["release_propagation"]["ref"]
    )



@pytest.mark.parametrize("keep_legacy_descriptor", [True, False])
def test_targets_only_serial_modern_refresh_requires_correct_provenance(
        tmp_path, monkeypatch, keep_legacy_descriptor):
    fixture = _targets_only_refresh_fixture(tmp_path, monkeypatch)
    first = _refresh_targets_only(fixture, tmp_path)
    predecessor = {path: path.read_bytes() for path in (
        fixture["wrapper"], fixture["prior_evidence"], fixture["provider"], fixture["applied"],
    )}
    _git("commit", "--allow-empty", "-m", "fixture second source successor", cwd=fixture["repo"])
    next_head = _git("rev-parse", "HEAD", cwd=fixture["repo"])
    fixture["successor"]["source_head_sha"] = next_head
    fixture["successor"]["provider_observed"]["head_sha"] = next_head
    fixture["successor"]["supersession"]["supersedes_source_head_sha"] = fixture["new_head"]
    if keep_legacy_descriptor:
        _assert_targets_only_refused(
            fixture, tmp_path, key="targets:second-successor",
            match="original readback requires its genuine active predecessor",
        )
    else:
        fixture["successor"]["supersession"].pop("original_readback")
        result = _refresh_targets_only(fixture, tmp_path, key="targets:second-successor")
        assert result["supersedes"]["source_head_sha"] == fixture["new_head"]
        assert result["evidence_sha256"] != first["evidence_sha256"]
        assert "legacy_identity_normalization" not in result["supersedes"]
    assert all(path.read_bytes() == raw for path, raw in predecessor.items())



@pytest.mark.parametrize("field,replacement", [
    ("receipt_ref", "__drop__"), ("receipt_ref", ""),
    ("receipt_ref", None), ("receipt_ref", 42),
    ("receipt_ref", "/foreign/APPROVAL.json"),
    ("receipt_ref", "../APPROVAL.json"),
    ("receipt_ref", "foreign/APPROVAL.json"),
    ("status", "__drop__"), ("status", "denied"), ("extra", "unbound"),
])
def test_targets_only_rejects_native_approval_projection_conflicts_without_effect(
        tmp_path, monkeypatch, field, replacement):
    fixture = _targets_only_refresh_fixture(tmp_path, monkeypatch, native_output=False)
    applied = json.loads(fixture["applied"].read_text())
    _change_fixture_field(applied["approval_receipt"], field, replacement)
    fixture["applied"].write_text(json.dumps(applied))
    _assert_targets_only_refused(fixture, tmp_path, match="original apply content readback conflicts")


@pytest.mark.parametrize("field,replacement", [
    ("receipt_ref", "__drop__"), ("receipt_ref", ""), ("receipt_ref", None),
    ("receipt_ref", 42), ("receipt_ref", "/foreign/PR-APPLY.json"),
    ("receipt_ref", "../PR-APPLY.json"), ("receipt_ref", "foreign/PR-APPLY.json"),
    ("status", "awaiting_provider_adapter"), ("target", "foreign"),
    ("readback.sha256", "a" * 64), ("extra", "unbound"),
])
def test_targets_only_rejects_native_apply_alias_conflicts_without_effect(
        tmp_path, monkeypatch, field, replacement):
    fixture = _targets_only_refresh_fixture(tmp_path, monkeypatch)
    output = json.loads(fixture["readback_output"].read_text())
    _change_fixture_field(output, field, replacement)
    fixture["readback_output"].write_text(json.dumps(output))
    _assert_targets_only_refused(fixture, tmp_path)


def test_targets_only_rejects_absolute_native_projection_refs_even_with_exact_suffix(
        tmp_path, monkeypatch):
    fixture = _targets_only_refresh_fixture(tmp_path, monkeypatch)
    output = json.loads(fixture["readback_output"].read_text())
    output["receipt_ref"] = str(fixture["applied"])
    fixture["readback_output"].write_text(json.dumps(output))
    _assert_targets_only_refused(fixture, tmp_path, match="native apply output")


@pytest.mark.parametrize("case", ["second_alias", "independent_apply", "symlink_output"])
def test_targets_only_rejects_duplicate_or_unsafe_native_outputs_without_effect(
        tmp_path, monkeypatch, case):
    def change(details):
        directory = Path(details["receipt_refs"][0]).parent
        output = Path(details["receipt_refs"][-1])
        if case == "symlink_output":
            raw = output.read_bytes()
            actual = directory / "actual-output.json"
            actual.write_bytes(raw)
            output.unlink()
            output.symlink_to(actual)
        else:
            source = output if case == "second_alias" else Path(details["receipt_refs"][3])
            duplicate = directory / (case + ".json")
            duplicate.write_bytes(source.read_bytes())
            details["receipt_refs"].append(str(duplicate))
    fixture = _targets_only_refresh_fixture(tmp_path, monkeypatch, change_legacy=change)
    _assert_targets_only_refused(fixture, tmp_path)


def test_targets_only_refuses_producer_outside_declared_os_root_without_effect(
        tmp_path, monkeypatch):
    fixture = _targets_only_refresh_fixture(tmp_path, monkeypatch)
    original_state = fixture["task"].path
    original_raw = original_state.read_bytes()
    copied = fixture["task"].read()
    copied["os_root"] = str(tmp_path / "foreign-os")
    external = original_state.parent / "external-task-copy.json"
    external.write_text(json.dumps(copied))
    external.with_suffix(external.suffix + ".lock").touch()
    fixture["task"] = delivery.TaskState(external)
    _assert_targets_only_refused(fixture, tmp_path, public=False,
                                match="producer paths do not bind the declared OS root")
    _assert_targets_only_refused(fixture, tmp_path)
    assert original_state.read_bytes() == original_raw



@pytest.mark.parametrize("policy,profile_base,task_base,review_number,review_base,seed_kind", [
    ("continue_with_receipt", "main", None, 54, "main", None),
    ("block", "main", None, 54, "main", None),
    ("continue_with_receipt", "develop", "hotfix/v10.0.1", 54, "hotfix/v10.0.1", None),
    ("continue_with_receipt", "develop", "hotfix/v10.0.1", 55, "develop", None),
    ("continue_with_receipt", "main", None, 54, "main", "prior_request"),
    ("continue_with_receipt", "develop", "hotfix/v10.0.1", 55, "develop", "initial_pr_create"),
])
def test_real_runner_and_downstream_keep_unavailable_honest(
    tmp_path, monkeypatch, policy, profile_base, task_base, review_number, review_base, seed_kind,
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
    native_seed = None
    seed_bytes = None
    if seed_kind == "prior_request":
        source.update({"head_sha": "c" * 40, "policy_fingerprint": "d" * 64,
                       "review_policy": {"reviewer_mode": "reciprocal_model_family",
                                         "reviewer_transport": "claude_cli", "review_unavailable_policy": "block"}})
        native_seed = work_item / "artifacts/finishing-touches/canonical-seed/review-request.json"
        native_seed.parent.mkdir(parents=True)
        native_seed.write_text(json.dumps(source))
        seed_bytes = native_seed.read_bytes()
    elif seed_kind == "initial_pr_create":
        native_seed = work_item / "artifacts/auto-dev-pr-create/pull-request-provider-readback.json"
        native_seed.parent.mkdir(parents=True, exist_ok=True)
        original_provider = {"number": 54, "url": "https://github.com/acme/app/pull/54", "state": "OPEN",
                             "baseRefName": task_base, "headRefOid": "c" * 40,
                             "headRefName": "feature/cc-54"}
        native_provider = native_seed.parent / "original-primary.json"
        native_provider.write_text(json.dumps(original_provider))
        native_seed.write_text(json.dumps({
            "number": 54, "url": original_provider["url"], "state": "OPEN", "repository": "acme/app",
            "base_branch": task_base, "base_sha": base, "head_sha": "c" * 40,
            "provider_readback": {"path": "auto-dev-pr-create/original-primary.json",
                                  "sha256": hashlib.sha256(native_provider.read_bytes()).hexdigest()},
        }))
        seed_bytes = native_seed.read_bytes()
        manifest_path = work_item / "autodev.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["subject_revision"] = head  # Fixture: current packet, historical primary.
        manifest_path.write_text(json.dumps(manifest))
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
    if seed_kind is None:
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
    if seed_kind is not None:
        provenance = request["source_seed_provenance"]
        assert provenance["kind"] == seed_kind
        assert provenance["sha256"] == hashlib.sha256(seed_bytes).hexdigest()
        assert Path(provenance["ref"]).read_bytes() == seed_bytes
        assert provenance["original_request"]["head_sha"] == "c" * 40
        assert request["policy_fingerprint"] == task.read()["policy_fingerprint"]
        if seed_kind == "prior_request":
            assert provenance["original_request"]["review_policy"]["review_unavailable_policy"] == "block"
            assert provenance["original_policy_fingerprint"] == "d" * 64
            assert "review_policy" not in request
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
        if seed_kind is None and task_base is None and profile_base == "main":
            # Actual owner recording after a genuine provider transition must
            # retain historical Ready, policy, coordination and attempt budgets.
            _, completed_subject, completion, completed_native = _completed_transition_fixture(
                tmp_path, monkeypatch, existing_task=task, existing_subject=head, existing_base=base,
            )
            monkeypatch.setattr(delivery.subprocess, "run", lambda command, **kwargs:
                subprocess.CompletedProcess(command, 0, json.dumps({"data": {"repository": completed_native}}), ""))
            historical_ready = ready_snapshot.read_bytes()
            historical_attempt = receipt_path.read_bytes()
            delivery.validate_policy_approved_unavailable_review(
                receipt, task.read(), post_provider_merge=completion,
            )
            auto_dev._validate_health_stage_source(
                work_item, "review_self", "completed", ready_snapshot, post_provider_merge=completion,
            )
            for completed_stage in ("qa", "validate_production_release"):
                _record_standalone_stage(task, completed_stage, revision=head)
            _record_standalone_stage(task, "review_others", revision=head, status="not_required")
            merge_input = work_item / "artifacts/actual-transition-fixture.json"
            merge_input.write_text(json.dumps({**completion, "summary": "Native fixture squash completed",
                                               "verified_at": "2026-10-08T00:11:31Z"}))
            delivery.run_development_stage(task.path, stage="merge", receipts={"merged": str(merge_input)},
                                           idempotency_prefix="actual-transition:merge")
            assert task.read()["state"] == "merged"
            assert task.read()["subject_revision"] == head
            assert task.read()["terminal_revision"] == completion["evidence"]["merge_sha"]
            assert ready_snapshot.read_bytes() == historical_ready and receipt_path.read_bytes() == historical_attempt
            assert load_review_receipt(receipt_path)["budget"]["full_reviews_used"] == 0
            # Later health consumers use the hash-bound recorded Merge.
            auto_dev._validate_health_stage_source(work_item, "review_self", "completed", ready_snapshot)
            _record_standalone_stage(task, "release", revision=completion["evidence"]["merge_sha"])
            auto_dev.require_auto_dev_predecessors(task.read()["autodev_path"], "deploy")
            with pytest.raises(auto_dev.AutoDevStateError, match="restricted to Merge recording"):
                auto_dev.require_auto_dev_predecessors(task.read()["autodev_path"], "deploy", post_provider_merge=completion)
            recorded_merge = next(row for row in reversed(task.read()["receipts"]) if row["state"] == "merged")
            Path(recorded_merge["ref"]).write_text("{}")
            with pytest.raises(auto_dev.AutoDevStateError, match="immutable merged evidence changed"):
                auto_dev._validate_health_stage_source(work_item, "review_self", "completed", ready_snapshot)
            return
        def changed_target(*_args, **_kwargs):
            raise delivery.DevelopmentDeliveryError("unavailable review current provider target or head changed")
        monkeypatch.setattr(delivery, "read_current_github_review_target", changed_target)
        with pytest.raises(auto_dev.AutoDevStateError, match="current provider target"):
            auto_dev._validate_health_stage_source(work_item, "review_self", "completed", ready_snapshot)
        profile_path = Path(task.read()["profile_source"])
        profile_path.write_text(profile_path.read_text() + "\n# drift\n")
        with pytest.raises(delivery.DevelopmentDeliveryError, match="authority or exact subject"):
            delivery.validate_policy_approved_unavailable_review(receipt, task.read())


def test_legacy_seed_requires_native_hash_identity_and_primary_provider_link(tmp_path, monkeypatch):
    task, _root, repo, base = _task(tmp_path, monkeypatch)
    value = task.read()
    packet = Path(value["work_item"])
    seed = {"work_item_id": "CC-54", "head_sha": "c" * 40, "base_sha": base,
            "target_branch": "main", "pr_number": 54, "repo_path": str(repo),
            "policy_fingerprint": "d" * 64,
            "review_policy": {"reviewer_mode": "reciprocal_model_family", "reviewer_transport": "claude_cli",
                              "review_unavailable_policy": "block"}}
    member = {"repository": value["repository"]["id"], "number": 54, "head_sha": "b" * 40}
    def native_source(original, label):
        path = packet / "artifacts/finishing-touches" / label / "review-request.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(original))
        return {**original, "_native_source": {"kind": "prior_request", "ref": str(path),
                                                "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}}
    original = native_source(seed, "original")
    immutable = Path(original["_native_source"]["ref"]).read_bytes()
    proof = delivery.historical_review_seed_provenance(original, value, member)
    assert proof["original_request"] == seed
    assert proof["original_policy_fingerprint"] == "d" * 64
    for key, wrong in {"work_item_id": "CC-55", "repository": "foreign/repo", "target_branch": "develop",
                       "source_branch": "foreign", "repo_path": str(tmp_path / "foreign"),
                       "reviewer_transport": "api", "selected_review_authority": {},
                       "source_family_authority": {}, "head_sha": "b" * 40}.items():
        source = native_source({**seed, key: wrong}, key)
        with pytest.raises(delivery.DevelopmentDeliveryError, match="historical review seed"):
            delivery.historical_review_seed_provenance(source, value, member)
    with pytest.raises(delivery.DevelopmentDeliveryError, match="historical review seed"):
        delivery.historical_review_seed_provenance({**seed}, value, member)
    corrupted = {**proof, "sha256": "0" * 64}
    with pytest.raises(delivery.DevelopmentDeliveryError, match="provenance or identity"):
        delivery.validate_historical_review_seed_provenance(corrupted, value, member)
    # Same-head explicit block remains current authority and is rejected by the
    # runner's ordinary policy resolution rather than being rematerialized.
    current = {**seed, "head_sha": member["head_sha"], "policy_fingerprint": value["policy_fingerprint"]}
    runner = _load_runner()
    with pytest.raises(runner.ReviewError, match="contradictory"):
        runner.review_unavailable_policy(current, {"review": {"opposing_harness": {"unavailable_policy": "continue_with_receipt"}}})
    provider = packet / "artifacts/auto-dev-pr-create/original-primary.json"
    provider.parent.mkdir(parents=True)
    provider.write_text(json.dumps({"number": 54, "url": "https://github.com/acme/app/pull/54", "state": "OPEN",
                                   "baseRefName": "main", "headRefOid": "c" * 40, "headRefName": "feature/cc-54"}))
    readback = provider.parent / "pull-request-provider-readback.json"
    readback.write_text(json.dumps({"repository": "acme/app", "number": 54, "url": "https://github.com/acme/app/pull/54",
                                   "state": "OPEN", "base_branch": "main", "base_sha": base, "head_sha": "c" * 40,
                                   "provider_readback": {"path": "auto-dev-pr-create/original-primary.json",
                                                         "sha256": hashlib.sha256(provider.read_bytes()).hexdigest()}}))
    sibling = {**member, "number": 55}
    sibling_proof = delivery.historical_review_seed_provenance(original, value, sibling)
    assert sibling_proof["original_primary_readback"]["provider_sha256"] == hashlib.sha256(provider.read_bytes()).hexdigest()
    foreign = native_source({**seed, "pr_number": 99}, "foreign-pr")
    with pytest.raises(delivery.DevelopmentDeliveryError, match="primary provider identity"):
        delivery.historical_review_seed_provenance(foreign, value, sibling)
    provider.write_text(provider.read_text().replace('"feature/cc-54"', '"foreign"'))
    with pytest.raises(delivery.DevelopmentDeliveryError, match="provider proof is missing or changed"):
        delivery.validate_historical_review_seed_provenance(sibling_proof, value, sibling)
    assert Path(original["_native_source"]["ref"]).read_bytes() == immutable


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


def _completed_transition_fixture(tmp_path, monkeypatch, *, existing_task=None, existing_subject=None, existing_base=None):
    if existing_task is None:
        task, _root, _repo, base = _task(tmp_path, monkeypatch)
    else:
        task, base = existing_task, existing_base
    head, merge, timestamp = existing_subject or "b" * 40, "d" * 40, "2026-10-08T00:11:31Z"
    if existing_task is None:
        _advance_auto_dev_task_to_ready(task, subject_revision=head, pull_request="github:acme/app#54")
    _record_standalone_stage(task, "finalize", revision=head, pull_request="github:acme/app#54")
    packet = Path(task.read()["work_item"])
    before = {"number": 54, "url": "https://github.com/acme/app/pull/54", "state": "OPEN",
              "headRefOid": head, "headRefName": "feature/cc-54", "baseRefName": "main",
              "author": {"login": "michaelwclark"}}
    native_before = {"nameWithOwner": "acme/app", "pullRequest": {
        **before, "baseRef": {"name": "main", "target": {"oid": base}}}}
    pr = {**before, "state": "MERGED", "mergedAt": timestamp, "mergeCommit": {"oid": merge}}
    artifacts = {
        "native_provider_readback": {"readback_verified": True, "provider": "github", "repository": "acme/app",
            "pull_request": pr, "accepted_source_head": head, "reviewed_target_before_merge": base,
            "merge_commit_sha": merge, "merge_commit_parents": [base], "method": "squash"},
        "native_premerge_guard": {"repository": "acme/app", "pull_request": 54, "source_head": head,
            "reviewed_base": base, "actor": {"login": "michaelwclark", "permission": "ADMIN"},
            "provider_before": before, "native_current_target_and_threads": native_before,
            "canonical_premerge_gates_verified": True, "all_threads_resolved": True, "quality_gate_waiver": False},
        "native_merge_command": {"exit_code": 0},
    }
    evidence = {**_provider_authority(task, pull_request="github:acme/app#54"),
        "source_head_sha": head, "merge_sha": merge, "reviewed_base_sha": base, "base_sha": base,
        "merge_parents": [base], "source_branch": "feature/cc-54", "merge_method": "squash",
        "provider_state_after": "MERGED", "merged_at": timestamp,
        "readiness_authority": _readiness_authority(task, subject_revision=head, pull_request="github:acme/app#54")}
    for name, payload in artifacts.items():
        path = packet / "artifacts" / (name + ".json")
        path.write_text(json.dumps(payload))
        evidence[name] = {"ref": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    completion = {"schema": "development-stage-evidence/v1", "state": "merged", "status": "completed",
                  "subject_revision": head, "evidence": evidence}
    native = {"nameWithOwner": "acme/app", "pullRequest": {
        **pr, "baseRef": {"name": "main", "target": {"oid": merge}}, "mergedBy": {"login": "michaelwclark"}},
        "object": {"oid": merge, "parents": {"nodes": [{"oid": base}], "pageInfo": {"hasNextPage": False}}}}
    return task, {"head_sha": head, "base_sha": base, "base_branch": "main"}, completion, native


@pytest.mark.parametrize("mutation", [None, "repository", "head", "base_branch", "source_branch", "parent", "extra_parent",
    "merge", "unmerged", "actor", "author", "diverged", "rewritten", "native_hash", "ready_hash", "finalize_hash",
    "completion_head", "completion_base", "completion_repository", "completion_merge", "policy", "descendant"])
def test_completed_transition_requires_exact_native_owned_merge(tmp_path, monkeypatch, mutation):
    task, subject, completion, native = _completed_transition_fixture(tmp_path, monkeypatch)
    if mutation == "repository": native["nameWithOwner"] = "wrong/app"
    if mutation == "head": native["pullRequest"]["headRefOid"] = "e" * 40
    if mutation == "base_branch": native["pullRequest"]["baseRefName"] = "develop"
    if mutation == "source_branch": native["pullRequest"]["headRefName"] = "wrong"
    if mutation == "parent": native["object"]["parents"]["nodes"][0]["oid"] = "e" * 40
    if mutation == "extra_parent": native["object"]["parents"]["pageInfo"]["hasNextPage"] = True
    if mutation == "merge": native["pullRequest"]["mergeCommit"]["oid"] = "e" * 40
    if mutation == "unmerged": native["pullRequest"]["state"] = "OPEN"
    if mutation == "actor": native["pullRequest"]["mergedBy"]["login"] = "wrong"
    if mutation == "author": native["pullRequest"]["author"]["login"] = "wrong"
    if mutation in {"descendant", "diverged", "rewritten"}: native["pullRequest"]["baseRef"]["target"]["oid"] = "e" * 40
    if mutation == "native_hash": Path(completion["evidence"]["native_provider_readback"]["ref"]).write_text("{}")
    if mutation == "ready_hash": Path(next(row["ref"] for row in reversed(task.read()["receipts"]) if row["state"] == "ready_for_merge")).write_text("{}")
    if mutation == "finalize_hash": completion["evidence"]["readiness_authority"]["sha256"] = "0" * 64
    if mutation == "completion_head": completion["evidence"]["source_head_sha"] = "e" * 40
    if mutation == "completion_base": completion["evidence"]["reviewed_base_sha"] = "e" * 40
    if mutation == "completion_repository": completion["evidence"]["repository"] = "git:github.com/wrong/app"
    if mutation == "completion_merge": completion["evidence"]["merge_sha"] = "e" * 40
    if mutation == "policy": Path(task.read()["policy_receipt"]).write_text("{}")
    calls = []
    def provider(command, **kwargs):
        calls.append(command)
        if "graphql" in command:
            return subprocess.CompletedProcess(command, 0, json.dumps({"data": {"repository": native}}), "")
        compare = {"status": "ahead", "behind_by": 0, "ahead_by": 1,
                   "base_commit": {"sha": "d" * 40}, "merge_base_commit": {"sha": "d" * 40}}
        if mutation == "diverged": compare["status"] = "diverged"
        if mutation == "rewritten": compare["merge_base_commit"]["sha"] = "f" * 40
        return subprocess.CompletedProcess(command, 0, json.dumps(compare), "")
    monkeypatch.setattr(delivery.subprocess, "run", provider)
    before = task.path.read_bytes()
    if mutation not in {None, "descendant"}:
        with pytest.raises(delivery.DevelopmentDeliveryError, match="post-provider completion|policy|fingerprint"):
            delivery.read_completed_github_review_transition(task.read(), subject, 54, "feature/cc-54", completion)
    else:
        proof = delivery.read_completed_github_review_transition(task.read(), subject, 54, "feature/cc-54", completion)
        assert proof["schema"] == "unavailable-review-completed-transition/v1"
        assert len(calls) == (2 if mutation == "descendant" else 1)
        # Default active readiness must still reject the genuine completed PR.
        with pytest.raises(delivery.DevelopmentDeliveryError, match="target or head changed"):
            delivery.read_current_github_review_target(task.read(), subject, 54, "feature/cc-54")
    assert task.path.read_bytes() == before


def test_unavailable_live_guard_fails_closed_on_provider_failure(monkeypatch):
    task = {"repository": {"id": "git:github.com/acme/app", "base_branch": "main"}}
    monkeypatch.setattr(delivery.subprocess, "run", lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 1, "", "private error"))
    with pytest.raises(delivery.DevelopmentDeliveryError, match="readback failed"):
        delivery.read_current_github_review_target(task, {"head_sha": "b" * 40, "base_sha": "a" * 40, "base_branch": "main"}, 54)
