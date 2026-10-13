"""Real runner/delivery composition with offline native provider fixtures."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys

import pytest

import genomes_agentic_os.auto_dev_orchestration as auto_dev
import genomes_agentic_os.development_delivery as delivery
import genomes_agentic_os.review_eligibility as eligibility
from genomes_agentic_os.review_coordination import load_review_receipt
from test_merge_tooling_compat import _task, _completed_transition_fixture
from test_development_delivery import (
    _git,
    _stage_receipt,
    _record_standalone_stage,
    _provider_authority,
)
from test_opposing_model_review_runner import _load_runner


@pytest.fixture
def late_review(tmp_path, monkeypatch):
    task, root, repo, base = _task(tmp_path, monkeypatch)
    (repo / "capacity.py").write_text("capacity = 500\n")
    _git("add", "capacity.py", cwd=repo)
    _git("commit", "-m", "cohort capacity", cwd=repo)
    head = _git("rev-parse", "HEAD", cwd=repo)
    packet = Path(task.read()["work_item"])
    for stage in ("groom", "detective", "create_artifacts"):
        _record_standalone_stage(task, stage)
    delivery.run_development_stage(
        task.path,
        stage="readiness",
        receipts={
            "planned": _stage_receipt(tmp_path / "plan", "planned"),
        },
        idempotency_prefix="late:readiness",
    )
    delivery.run_development_stage(
        task.path,
        stage="implementation",
        receipts={
            "implementing": _stage_receipt(tmp_path / "impl", "implementing"),
            "local_validation": _stage_receipt(tmp_path / "local", "local_validation"),
        },
        idempotency_prefix="late:implementation",
    )
    _record_standalone_stage(task, "document")
    family = _stage_receipt(
        tmp_path / "family",
        "release_propagation",
        evidence={
            "targets": [
                {
                    "number": 54,
                    "url": "https://github.com/acme/app/pull/54",
                    "base_branch": "main",
                    "head_sha": head,
                    "source_branch": "feature/cc-54",
                    "classification": "pr_required",
                    "provider_readback_verified": True,
                }
            ]
        },
    )
    delivery.run_development_stage(
        task.path,
        stage="release_propagation",
        receipts={
            "release_propagation": family,
        },
        idempotency_prefix="late:family",
    )
    runner = _load_runner()
    provider = {
        "number": 54,
        "url": "https://github.com/acme/app/pull/54",
        "state": "OPEN",
        "headRefOid": head,
        "headRefName": "feature/cc-54",
        "baseRefOid": base,
        "baseRefName": "main",
        "baseRefTargetOid": base,
        "statusCheckRollup": [
            {"name": "Pytest", "status": "IN_PROGRESS", "conclusion": None}
        ],
    }
    provider["current_target_readback"] = {
        **{
            k: provider[k]
            for k in (
                "number",
                "url",
                "state",
                "headRefOid",
                "headRefName",
                "baseRefName",
                "baseRefOid",
            )
        },
        "baseRef": {"name": "main", "target": {"oid": base}},
    }
    source = {
        "work_item_id": "CC-54",
        "builder_model": "codex",
        "selected_reviewer_model": "opus",
        "mode": "post_pr",
        "base_sha": base,
        "head_sha": head,
        "pr_number": 54,
        "implementation_summary": "bounded cohort renewal",
        "spec_source": "fixture",
        "policy_fingerprint": task.read()["policy_fingerprint"],
        "repo_path": str(repo),
        "reviewer_selection_source": "project-policy",
        "target_branch": "main",
    }
    monkeypatch.setattr(runner, "resolve_os_root", lambda _: root)
    monkeypatch.setattr(runner, "prior_request", lambda *_: source)
    monkeypatch.setattr(runner, "provider_pr", lambda *_: provider)
    monkeypatch.setattr(runner, "git_repository", lambda *_: "acme/app")
    original_which = runner.shutil.which
    monkeypatch.setattr(
        runner.shutil,
        "which",
        lambda n: "/fixture/claude" if n == "claude" else original_which(n),
    )
    original_run = runner.run
    model_calls = []

    def timed_out(argv, **kwargs):
        if argv[0] == "/fixture/claude":
            model_calls.append(argv)
            raise subprocess.TimeoutExpired(argv, 5)
        return original_run(argv, **kwargs)

    monkeypatch.setattr(runner, "run", timed_out)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "runner",
            "CC-54",
            "--os-root",
            str(root),
            "--work-item",
            str(packet),
            "--worktree",
            str(repo),
            "--timeout-seconds",
            "5",
        ],
    )
    assert runner.main() == 2
    original = next((root / "state/review-coordination/attempts").glob("*.json"))
    review = load_review_receipt(original)
    assert review["review"]["decision"] == "pending_checks"
    assert review["review"]["deterministic_review_downgraded"] is False
    assert review["review"]["failure_code"] == "cli_timeout"
    native = {
        "data": {
            "repository": {
                "id": "native-repo-id",
                "nameWithOwner": "acme/app",
                "url": "https://github.com/acme/app",
                "pullRequest": {
                    "number": 54,
                    "url": provider["url"],
                    "state": "OPEN",
                    "author": {
                        "login": task.read()["authorship"]["ours"][0].split(":", 1)[1]
                    },
                    "headRefOid": head,
                    "headRefName": "feature/cc-54",
                    "baseRefName": "main",
                    "baseRef": {"name": "main", "target": {"oid": base}},
                    "mergeable": "MERGEABLE",
                    "reviewDecision": "REVIEW_REQUIRED",
                    "reviewThreads": {
                        "pageInfo": {"hasNextPage": False, "endCursor": None},
                        "nodes": [],
                    },
                    "commits": {
                        "nodes": [
                            {
                                "commit": {
                                    "oid": head,
                                    "statusCheckRollup": {
                                        "contexts": {
                                            "pageInfo": {
                                                "hasNextPage": False,
                                                "endCursor": None,
                                            },
                                            "nodes": [
                                                {
                                                    "__typename": "CheckRun",
                                                    "name": "Pytest",
                                                    "status": "COMPLETED",
                                                    "conclusion": "SUCCESS",
                                                }
                                            ],
                                        }
                                    },
                                }
                            }
                        ]
                    },
                },
            }
        }
    }
    native_calls = []
    native_run = subprocess.run

    def read_native(argv, **kwargs):
        if argv[0] == "gh":
            native_calls.append(argv)
            return subprocess.CompletedProcess(argv, 0, json.dumps(native), "")
        return native_run(argv, **kwargs)

    monkeypatch.setattr(eligibility.subprocess, "run", read_native)
    return task, packet, original, review, native, model_calls, native_calls


def _produce(fixture):
    task, packet, original, *_ = fixture
    return eligibility.produce_unavailable_review_eligibility(
        task.path, original, packet / "artifacts/review-eligibility"
    )


def _rewrite(descriptor, mutate):
    path = Path(descriptor["ref"])
    payload = json.loads(path.read_text())
    mutate(payload)
    # Test-only distinct adversarial candidate; never alter the original proof.
    candidate = path.with_name("adversarial.json")
    candidate.write_text(json.dumps(payload))
    return {
        "ref": str(candidate),
        "sha256": hashlib.sha256(candidate.read_bytes()).hexdigest(),
    }


def test_late_ci_qualifies_without_model_budget_or_historical_writes(late_review):
    task, packet, original, review, native, model_calls, native_calls = late_review
    run = Path(review["review"]["review_run_dir"])
    before = {
        str(p): p.read_bytes()
        for p in [original, task.path, packet / "autodev.json", *run.iterdir()]
    }
    with pytest.raises(
        delivery.DevelopmentDeliveryError, match="typed policy-approved"
    ):
        delivery.validate_policy_approved_unavailable_review(review, task.read())
    descriptor = _produce(late_review)
    result = delivery.validate_policy_approved_unavailable_review(
        review, task.read(), eligibility_receipt=descriptor
    )
    assert (
        result["original_outcome"] == "unavailable"
        and result["original_decision"] == "pending_checks"
    )
    assert len(model_calls) == 1 and len(native_calls) == 2
    assert all(Path(p).read_bytes() == data for p, data in before.items())
    assert json.loads(Path(descriptor["ref"]).read_text())["budget"] == review["budget"]


@pytest.mark.parametrize(
    "mutation",
    [
        "head",
        "base",
        "branch",
        "repository",
        "url",
        "number",
        "state",
        "author",
        "mergeable",
        "review_changes",
        "missing_check",
        "renamed_check",
        "duplicate_check",
        "pending_check",
        "failed_check",
        "skipped_check",
        "extra_failed",
        "truncated_checks",
        "unresolved_thread",
        "truncated_threads",
        "duplicate_thread",
        "errors",
    ],
)
def test_native_current_gates_fail_closed(late_review, mutation):
    _task_value, _packet, _original, _review, raw, *_ = late_review
    repo = raw["data"]["repository"]
    pr = repo["pullRequest"]
    connection = pr["commits"]["nodes"][0]["commit"]["statusCheckRollup"]["contexts"]
    if mutation == "head":
        pr["headRefOid"] = "f" * 40
    elif mutation == "base":
        pr["baseRef"]["target"]["oid"] = "f" * 40
    elif mutation == "branch":
        pr["headRefName"] = "foreign"
    elif mutation == "repository":
        repo["nameWithOwner"] = "foreign/app"
    elif mutation == "url":
        pr["url"] = "https://github.com/foreign/app/pull/54"
    elif mutation == "number":
        pr["number"] = 55
    elif mutation == "state":
        pr["state"] = "MERGED"
    elif mutation == "author":
        pr["author"]["login"] = "foreign"
    elif mutation == "mergeable":
        pr["mergeable"] = "CONFLICTING"
    elif mutation == "review_changes":
        pr["reviewDecision"] = "CHANGES_REQUESTED"
    elif mutation == "missing_check":
        connection["nodes"] = []
    elif mutation == "renamed_check":
        connection["nodes"][0]["name"] = "Other"
    elif mutation == "duplicate_check":
        connection["nodes"].append(deepcopy(connection["nodes"][0]))
    elif mutation == "pending_check":
        connection["nodes"][0]["status"] = "IN_PROGRESS"
    elif mutation in {"failed_check", "skipped_check"}:
        connection["nodes"][0]["conclusion"] = (
            "FAILURE" if mutation == "failed_check" else "SKIPPED"
        )
    elif mutation == "extra_failed":
        connection["nodes"].append(
            {
                "__typename": "CheckRun",
                "name": "Other",
                "status": "COMPLETED",
                "conclusion": "FAILURE",
            }
        )
    elif mutation == "truncated_checks":
        connection["pageInfo"]["hasNextPage"] = True
    elif mutation == "unresolved_thread":
        pr["reviewThreads"]["nodes"] = [{"id": "thread", "isResolved": False}]
    elif mutation == "duplicate_thread":
        pr["reviewThreads"]["nodes"] = [{"id": "thread", "isResolved": True}] * 2
    elif mutation == "truncated_threads":
        pr["reviewThreads"]["pageInfo"]["hasNextPage"] = True
    elif mutation == "errors":
        raw["errors"] = [{"message": "provider failure"}]
    with pytest.raises(delivery.DevelopmentDeliveryError, match="eligibility"):
        _produce(late_review)


@pytest.mark.parametrize(
    "mutation",
    [
        "schema",
        "budget",
        "task",
        "subject",
        "source",
        "runner",
        "required",
        "clean",
        "retry",
        "stale",
        "future",
        "original_hash",
        "repository_id",
    ],
)
def test_derived_proof_cannot_counterfeit_authority(late_review, mutation):
    task, _packet, _original, review, *_ = late_review
    descriptor = _produce(late_review)

    def change(p):
        if mutation == "schema":
            p["schema"] = "other/v1"
        elif mutation == "budget":
            p["budget"]["full_reviews_used"] = 1
        elif mutation == "task":
            p["task_binding"]["ticket"] = "OTHER"
        elif mutation == "subject":
            p["subject"]["head_sha"] = "f" * 40
        elif mutation == "source":
            p["source"]["diff_sha256"] = "f" * 64
        elif mutation == "runner":
            p["runner_artifacts"]["model-receipt.md"] = "f" * 64
        elif mutation == "required":
            p["required_checks"] = []
        elif mutation == "clean":
            p["model_outcome"] = "clean"
        elif mutation == "retry":
            p["model_retry"] = True
        elif mutation == "original_hash":
            p["original_review"]["sha256"] = "f" * 64
        elif mutation == "repository_id":
            p["native_current_gates"]["pages"][0]["data"]["repository"][
                "id"
            ] = "foreign-id"
        elif mutation in {"stale", "future"}:
            seconds = -901 if mutation == "stale" else 60
            p["qualified_at"] = (
                datetime.now(timezone.utc) + timedelta(seconds=seconds)
            ).isoformat()
            p["native_current_gates"]["read_at"] = p["qualified_at"]

    forged = _rewrite(descriptor, change)
    with pytest.raises(delivery.DevelopmentDeliveryError, match="eligibility"):
        delivery.validate_policy_approved_unavailable_review(
            review, task.read(), eligibility_receipt=forged
        )


def test_ready_and_downstream_revalidate_late_ci_without_rewriting_attempt(
    late_review, tmp_path
):
    task, packet, original, review, native, model_calls, *_ = late_review
    original_bytes = original.read_bytes()
    descriptor = _produce(late_review)
    authority = _provider_authority(task, pull_request="github:acme/app#54")
    receipts = {
        name: _stage_receipt(
            tmp_path / name, name, evidence=authority if name == "pr_open" else None
        )
        for name in (
            "pre_pr_review",
            "pr_open",
            "ci_repair",
            "review_repair",
            "post_pr_review",
        )
    }
    receipts["ready_for_merge"] = _stage_receipt(
        tmp_path / "ready",
        "ready_for_merge",
        evidence={
            **authority,
            "subject_revision": review["subject"]["head_sha"],
            "checks_verified": True,
            "reviews_verified": True,
            "review_coordination_receipt": str(original),
            "unavailable_review_eligibility": descriptor,
        },
    )
    delivery.run_development_stage(
        task.path, stage="review", receipts=receipts, idempotency_prefix="late:review"
    )
    ready = Path(
        next(
            row["ref"]
            for row in reversed(task.read()["receipts"])
            if row["state"] == "ready_for_merge"
        )
    )
    assert task.read()["state"] == "ready_for_merge"
    auto_dev._validate_health_stage_source(packet, "review_self", "completed", ready)
    assert original.read_bytes() == original_bytes and len(model_calls) == 1
    native["data"]["repository"]["pullRequest"]["baseRef"]["target"]["oid"] = "f" * 40
    with pytest.raises(auto_dev.AutoDevStateError, match="eligibility"):
        auto_dev._validate_health_stage_source(
            packet, "review_self", "completed", ready
        )


@pytest.mark.parametrize(
    "mutation",
    [
        "block",
        "non_timeout",
        "findings",
        "corrupt_runner",
        "missing_family",
        "dirty_source",
        "task_blocked",
    ],
)
def test_original_authority_and_source_still_block(late_review, mutation):
    task, _packet, original, review, *_ = late_review
    if mutation in {"block", "non_timeout", "findings"}:
        raw = json.loads(original.read_text())
        if mutation == "block":
            raw["review"]["review_unavailable_policy"] = "block"
        elif mutation == "non_timeout":
            raw["review"]["failure_code"] = "cli_runtime_failed"
        else:
            raw["review"]["findings"] = [
                {"summary": "blocking finding", "severity": "high", "blocking": True}
            ]
        original.write_text(json.dumps(raw))
    elif mutation == "corrupt_runner":
        (Path(review["review"]["review_run_dir"]) / "model-receipt.md").write_text(
            "corrupt"
        )
    elif mutation in {"missing_family", "task_blocked"}:
        raw = task.read()
        if mutation == "missing_family":
            raw["stage_receipts"].pop("release_propagation")
        else:
            raw["state"] = "blocked"
        task.path.write_text(json.dumps(raw))
    elif mutation == "dirty_source":
        (Path(task.read()["worktree"]["path"]) / "capacity.py").write_text(
            "capacity = -1\n"
        )
    with pytest.raises(delivery.DevelopmentDeliveryError):
        _produce(late_review)


def test_full_thread_pagination_and_native_cli_are_supported(
    late_review, tmp_path, monkeypatch
):
    task, packet, original, _review, raw, model_calls, *_ = late_review
    first, second = deepcopy(raw), deepcopy(raw)
    first["data"]["repository"]["pullRequest"]["reviewThreads"] = {
        "pageInfo": {"hasNextPage": True, "endCursor": "next"},
        "nodes": [{"id": "first", "isResolved": True}],
    }
    second["data"]["repository"]["pullRequest"]["reviewThreads"]["nodes"] = [
        {"id": "second", "isResolved": True}
    ]
    prior = subprocess.run

    def paginated(argv, **kwargs):
        if argv[0] == "gh":
            return subprocess.CompletedProcess(
                argv, 0, json.dumps(second if "cursor=next" in argv else first), ""
            )
        return prior(argv, **kwargs)

    monkeypatch.setattr(eligibility.subprocess, "run", paginated)
    proof = _produce(late_review)
    assert (
        len(json.loads(Path(proof["ref"]).read_text())["native_current_gates"]["pages"])
        == 2
    )

    native_json = tmp_path / "native.json"
    native_json.write_text(json.dumps(raw))
    binary_dir = tmp_path / "bin"
    binary_dir.mkdir()
    fake = binary_dir / "gh"
    fake.write_text("#!/bin/sh\ncat " + shlex.quote(str(native_json)) + "\n")
    fake.chmod(0o755)
    before = {
        str(f): f.read_bytes() for f in [task.path, packet / "autodev.json", original]
    }
    result = prior(
        [
            sys.executable,
            "-m",
            "genomes_agentic_os.cli",
            "develop",
            "review-eligibility",
            str(task.path),
            "--coordination-receipt",
            str(original),
            "--output-dir",
            str(packet / "artifacts/review-eligibility/cli"),
            "--json",
        ],
        env={**os.environ, "PATH": str(binary_dir) + os.pathsep + os.environ["PATH"]},
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert (
        json.loads(Path(json.loads(result.stdout)["ref"]).read_text())["model_outcome"]
        == "unavailable"
    )
    assert (
        all(Path(p).read_bytes() == data for p, data in before.items())
        and len(model_calls) == 1
    )


def test_output_cannot_modify_original_attempt(late_review):
    task, _packet, original, review, *_ = late_review
    with pytest.raises(
        delivery.DevelopmentDeliveryError, match="separate review-eligibility"
    ):
        eligibility.produce_unavailable_review_eligibility(
            task.path, original, review["review"]["review_run_dir"]
        )


@pytest.mark.parametrize(
    "mutation",
    [
        None,
        "qualified_after_merge",
        "future",
        "parent",
        "unmerged",
        "native_hash",
        "repository_id",
    ],
)
def test_late_ci_historical_completed_transition_still_requires_native_proof(
    late_review, tmp_path, monkeypatch, mutation
):
    task, _packet, original, review, _raw, model_calls, *_ = late_review
    descriptor = _produce(late_review)
    now = datetime.now(timezone.utc)
    qualified = now - timedelta(hours=1)
    merged = now - timedelta(minutes=30)
    # Explicit historical fixture: the original eligibility precedes the actual
    # completed transition, and is old enough to fail the open-PR TTL.
    if mutation == "qualified_after_merge":
        qualified = now - timedelta(minutes=10)
    if mutation == "future":
        qualified = now + timedelta(minutes=1)
    descriptor = _rewrite(
        descriptor,
        lambda p: p.update(
            qualified_at=qualified.isoformat(),
            native_current_gates={
                **p["native_current_gates"],
                "read_at": qualified.isoformat(),
            },
        ),
    )
    authority = _provider_authority(task, pull_request="github:acme/app#54")
    receipts = {
        name: _stage_receipt(
            tmp_path / name, name, evidence=authority if name == "pr_open" else None
        )
        for name in (
            "pre_pr_review",
            "pr_open",
            "ci_repair",
            "review_repair",
            "post_pr_review",
        )
    }
    # Record genuine fixture Ready with the fresh original descriptor first.
    fresh = _produce(late_review)
    receipts["ready_for_merge"] = _stage_receipt(
        tmp_path / "ready",
        "ready_for_merge",
        evidence={
            **authority,
            "subject_revision": review["subject"]["head_sha"],
            "checks_verified": True,
            "reviews_verified": True,
            "review_coordination_receipt": str(original),
            "unavailable_review_eligibility": fresh,
        },
    )
    delivery.run_development_stage(
        task.path,
        stage="review",
        receipts=receipts,
        idempotency_prefix="historical:review",
    )
    _, _, completion, native = _completed_transition_fixture(
        tmp_path,
        monkeypatch,
        existing_task=task,
        existing_subject=review["subject"]["head_sha"],
        existing_base=review["subject"]["base_sha"],
    )
    merged_at = merged.isoformat()
    completion["evidence"]["merged_at"] = merged_at
    after_path = Path(completion["evidence"]["native_provider_readback"]["ref"])
    after = json.loads(after_path.read_text())
    after["pull_request"]["mergedAt"] = merged_at
    after_path.write_text(json.dumps(after))
    completion["evidence"]["native_provider_readback"]["sha256"] = hashlib.sha256(
        after_path.read_bytes()
    ).hexdigest()
    native["pullRequest"]["mergedAt"] = merged_at
    native["id"] = "native-repo-id"
    native["url"] = "https://github.com/acme/app"
    if mutation == "repository_id":
        native["id"] = "other-repository-id"
    if mutation == "parent":
        native["object"]["parents"]["nodes"][0]["oid"] = "f" * 40
    if mutation == "unmerged":
        native["pullRequest"]["state"] = "OPEN"
    if mutation == "native_hash":
        after_path.write_text("{}")
    prior = subprocess.run

    def provider(argv, **kwargs):
        if argv[0] == "gh":
            return subprocess.CompletedProcess(
                argv, 0, json.dumps({"data": {"repository": native}}), ""
            )
        return prior(argv, **kwargs)

    monkeypatch.setattr(eligibility.subprocess, "run", provider)
    before = original.read_bytes()
    if mutation is None:
        result = delivery.validate_policy_approved_unavailable_review(
            review,
            task.read(),
            eligibility_receipt=descriptor,
            post_provider_merge=completion,
        )
        assert result["schema"] == "unavailable-review-completed-transition/v1"
    else:
        with pytest.raises(delivery.DevelopmentDeliveryError):
            delivery.validate_policy_approved_unavailable_review(
                review,
                task.read(),
                eligibility_receipt=descriptor,
                post_provider_merge=completion,
            )
    assert original.read_bytes() == before and len(model_calls) == 1
