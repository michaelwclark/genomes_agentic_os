"""Separate native successor policy review from ordinary validated review authority."""

from __future__ import annotations

from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from typing import Any

import pytest
import yaml

from genomes_agentic_os import auto_dev_orchestration as orchestration
from genomes_agentic_os import development_delivery as delivery
from genomes_agentic_os.development_validation_refresh import refresh_development_validation
from genomes_agentic_os.review_coordination import (
    SUCCESSOR_POLICY_REVIEW_PURPOSE,
    ReviewBudgetExceeded,
    ReviewCoordinationError,
    ReviewCoordinator,
    ReviewSubject,
    assert_exact_head_review_receipt,
    canonical_review_purpose,
    load_review_receipt,
    review_chain_key,
    review_family_key,
)
from test_development_delivery import _git, _provider_authority, _stage_receipt
from test_development_successor_binding import (
    _bind,
    _metadata,
    _renew_assertions,
    candidate as candidate,
)
from test_development_validation_refresh import _bound, _command_proof, _now, _write
from test_opposing_model_review_runner import _completed, _load_runner


def _subject(*, purpose: str = "review_self", policy: str = "c" * 64) -> ReviewSubject:
    """Name an exact scratch PR without changing its family identity."""
    return ReviewSubject("acme/app", "github:acme/app#236", "main", "a" * 40, "b" * 40, policy, purpose)


def test_policy_partition_retains_ordinary_chain_and_absolute_family_budget(tmp_path: Path) -> None:
    """Only policy admission gets a separate chain; ordinary aliases and the paid cap remain shared."""
    runner = _load_runner()
    ordinary = _subject()
    expected = asdict(ordinary)
    expected.pop("purpose")
    expected.pop("head_sha")
    assert review_chain_key(ordinary) == hashlib.sha256(
        json.dumps(expected, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    policy = replace(ordinary, purpose=SUCCESSOR_POLICY_REVIEW_PURPOSE)
    assert review_chain_key(policy) != review_chain_key(ordinary)
    assert review_family_key(policy) == review_family_key(ordinary)
    assert canonical_review_purpose(SUCCESSOR_POLICY_REVIEW_PURPOSE) == SUCCESSOR_POLICY_REVIEW_PURPOSE
    coordinator = ReviewCoordinator(tmp_path / "shared")
    calls: list[str] = []

    def policy_review() -> dict[str, Any]:
        """Stand in for the policy reviewer edge in this coordinator unit control."""
        calls.append("policy")
        return {"outcome": "clean", "policy_delta_sha256": "d" * 64,
                "decision": "blocked_validation", "validation_status": "not_started",
                "pr_check_status": "not_applicable"}

    def ordinary_review() -> dict[str, Any]:
        """Use the real coordinator to create an ordinary receipt from its reviewer boundary."""
        calls.append("ordinary")
        return {"outcome": "clean", "decision": "ready_for_merge",
                "validation_status": "passed", "pr_check_status": "passed"}

    first = coordinator.execute(policy, policy_review)
    second = coordinator.execute(ordinary, ordinary_review)
    assert not first.reused and not second.reused and first.key != second.key
    assert second.receipt["budget"]["absolute_full_reviews_used"] == 2
    for alias in runner.PURPOSE_ALIASES:
        purpose, _scope = runner.normalize_review_purpose(alias, "full-pr")
        reused = coordinator.execute(replace(ordinary, purpose=purpose), ordinary_review)
        assert reused.reused and reused.key == second.key
    with pytest.raises(ReviewBudgetExceeded, match="absolute full-review"):
        coordinator.execute(replace(ordinary, policy_fingerprint="e" * 64), ordinary_review)
    assert calls == ["policy", "ordinary"]
    assert coordinator.budget.full_reviews_per_chain == 1
    assert coordinator.budget.delta_reviews_per_chain == 3
    assert coordinator.budget.absolute_full_reviews_per_family == 2
    assert coordinator.budget.provider_posts_per_family == 1


@pytest.mark.parametrize(
    "purpose,review",
    [
        (SUCCESSOR_POLICY_REVIEW_PURPOSE, {}),
        ("review_self", {"policy_delta_sha256": "d" * 64}),
        ("review_self", {"policy_delta_sha256": None}),
        ("review_self", {"decision": "blocked_validation"}),
        ("review_self", {"validation_status": "not_started"}),
        ("review_self", {"validation_status": "failed"}),
        ("review_self", {"pr_check_status": "not_applicable"}),
        ("review_self", {"pr_check_status": "pending"}),
    ],
    ids=["dedicated", "legacy-policy-key", "malformed-policy", "blocked", "not-started", "failed", "not-applicable", "pending"],
)
def test_ready_gate_refuses_policy_or_explicit_nonvalidated_receipts(
    tmp_path: Path, purpose: str, review: dict[str, Any]
) -> None:
    """A real receipt's clean outcome cannot replace its authority or explicit gate status."""
    subject = _subject(purpose=purpose)
    completed = ReviewCoordinator(tmp_path / "shared").execute(subject, lambda: {"outcome": "clean", **review})
    original = completed.receipt_path.read_bytes()
    with pytest.raises(ReviewCoordinationError, match="ready_for_merge"):
        assert_exact_head_review_receipt(
            completed.receipt_path, head_sha=subject.head_sha, repository=subject.repository,
            pull_request=subject.pull_request, policy_fingerprint=subject.policy_fingerprint,
        )
    assert completed.receipt_path.read_bytes() == original


def test_generic_historical_review_does_not_invent_passed_metadata(tmp_path: Path) -> None:
    """Other canonical producers retain their original API without fabricated runner statuses."""
    subject = _subject()
    completed = ReviewCoordinator(tmp_path / "shared").execute(
        subject, lambda: {"outcome": "clean", "summary": "Generic canonical review"}
    )
    accepted = assert_exact_head_review_receipt(completed.receipt_path, head_sha=subject.head_sha)
    assert "validation_status" not in accepted["review"] and "pr_check_status" not in accepted["review"]


def _arguments(fixture: dict[str, Any], *, policy: bool = False, purpose: str = "review_self") -> list[str]:
    """Use the real CLI and exact scratch task/worktree references."""
    arguments = [
        "run_opposing_model_review.py", fixture["task"].read()["ticket"],
        "--os-root", str(fixture["root"]), "--work-item", str(fixture["packet"]),
        "--worktree", str(fixture["candidate"]), "--purpose", purpose,
    ]
    if policy:
        arguments += ["--successor-policy-request", str(fixture["binding_request"])]
    return arguments


def _complete_native_epoch(fixture: dict[str, Any]) -> None:
    """Execute frozen native validation and real document/family transitions in the successor."""
    current = fixture["task"].read()
    head = _git("rev-parse", "HEAD", cwd=fixture["candidate"])
    predecessor = Path(next(row["ref"] for row in reversed(current["receipts"]) if row["state"] == "local_validation"))
    run = _command_proof(
        fixture["root"], fixture["packet"], fixture["candidate"],
        fixture["command"], head, current["policy_fingerprint"],
    )
    evidence = {
        "ticket": current["ticket"], "canonical_work_id": current["canonical_work_id"],
        "repository_id": current["repository"]["id"], "repository": "acme/app",
        "task_state_ref": str(fixture["task"].path), "worktree": str(fixture["candidate"]),
        "source_branch": current["worktree"]["branch"], "head_sha": head,
        "policy_fingerprint": current["policy_fingerprint"],
        "policy_sha256": _bound(Path(current["policy_receipt"]))["sha256"], "validation_runs": [run],
        "repair_lineage": {
            "predecessor": _bound(predecessor), "from_head_sha": fixture["old_head"],
            "to_head_sha": head, "reason": "Actual native command after successor admission",
        },
        **_metadata(current),
    }
    path = _write(fixture["packet"] / "artifacts/review-native-validation.json", {
        "schema": "development-stage-evidence/v1", "state": "local_validation", "status": "passed",
        "summary": "The actual frozen native command passed", "verified_at": _now(), "evidence": evidence,
    })
    refresh_development_validation(
        fixture["task"].path, evidence_file=path, idempotency_key="review-native-validation"
    )
    current = fixture["task"].read()
    proof = fixture["packet"] / "artifacts/review-document-readback.txt"
    proof.write_text("Committed README sha256=" + hashlib.sha256(
        (fixture["candidate"] / "README.md").read_bytes()
    ).hexdigest())
    document = _write(fixture["packet"] / "artifacts/review-document.json", {
        "schema": "auto-dev-stage-evidence/v1", "stage": "document", "status": "completed",
        "summary": "Read back the actual committed document", "verified_at": _now(),
        "subject_revision": head, "evidence": {"receipt_refs": [str(proof)], **_metadata(current)},
    })
    orchestration.record_auto_dev_stage(
        fixture["packet"] / "autodev.json", stage="document", evidence_file=document,
        idempotency_key="review-document",
    )
    family = json.loads(fixture["family"].read_text())
    family["evidence"].update({
        **_metadata(current), "policy_fingerprint": current["policy_fingerprint"],
        "source_branch": current["pull_request_subject"]["source_branch"],
        "source_head_sha": head, "subject_revision": head,
        "provider_observed": {"head_sha": fixture["provider"]["head"], "pull_request": "github:acme/app#236"},
        "supersession": {"supersedes_source_head_sha": fixture["old_head"],
                        "reason": "The scratch remote publishes the admitted successor"},
    })
    family["evidence"]["targets"][0]["head_sha"] = head
    path = _write(fixture["packet"] / "artifacts/review-family.json", family)
    delivery.run_development_stage(
        fixture["task"].path, stage="release_propagation",
        receipts={"release_propagation": str(path)}, idempotency_prefix="review-family",
    )
    delivery.start_development_run(
        fixture["root"], "acme", "app", [current["ticket"]], run_id=current["run_id"],
        requested_stage="review_self", provision_worktree=False, apply=True,
    )


def test_ordinary_runner_after_native_binding_validation_executes_a_distinct_review(
    candidate: dict[str, Any], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Real scratch Git/state/coordinator and validation distinguish reviewer calls and reject policy gates."""
    tree = candidate["candidate"]
    (tree / "AGENTS.md").write_text("Preserve 95 coverage and all account identity checks.\n")
    _git("add", "AGENTS.md", cwd=tree)
    _git("commit", "-m", "docs: retain inherited safety controls", cwd=tree)
    _git("push", str(candidate["remote"]), "HEAD:refs/heads/" + candidate["provider"]["source_branch"], cwd=tree)
    candidate["provider"]["head"] = _git("rev-parse", "HEAD", cwd=tree)
    path = delivery.project_root(candidate["root"], "acme", "app") / "config/development.yml"
    profile = yaml.safe_load(path.read_text())
    profile.setdefault("review", {})["opposing_harness"] = {
        "model": "claude-fable-5", "transport": "claude_cli", "unavailable_policy": "continue_with_receipt",
    }
    path.write_text(yaml.safe_dump(profile))
    _renew_assertions(candidate)
    runner = _load_runner()
    provider = candidate["provider"]
    monkeypatch.setattr(runner, "provider_pr", lambda *_args: {
        "number": 236, "url": provider["url"], "state": "OPEN", "headRefOid": provider["head"],
        "baseRefName": "main", "baseRefOid": provider["base_sha"], "statusCheckRollup": [{"conclusion": "SUCCESS"}],
    })
    monkeypatch.setattr(runner, "git_repository", lambda _tree: "acme/app")
    original_run = runner.run
    calls: list[list[str]] = []

    def reviewer_edge(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        """Replace the paid reviewer only; native Git and readiness helper subprocesses remain real."""
        if command[0] == "/synthetic-successor-reviewer":
            calls.append(command)
            assert command[command.index("--model") + 1] == "claude-fable-5"
            assert command[command.index("--permission-mode") + 1] == "dontAsk"
            assert command[command.index("--allowedTools") + 1] == runner.CLAUDE_TOOLS
            return _completed(0, "```json\n[]\n```\nAGENTIC_OS_REVIEW_VERDICT: CLEAN\n")
        return original_run(command, **kwargs)

    monkeypatch.setattr(runner, "run", reviewer_edge)
    monkeypatch.setattr(runner.shutil, "which", lambda _name: "/synthetic-successor-reviewer")
    monkeypatch.setattr(sys, "argv", _arguments(candidate, policy=True))
    assert runner.main() == 0
    result = json.loads(capsys.readouterr().out)
    policy_path = Path(result["coordination_receipt"])
    policy = load_review_receipt(policy_path)
    assert policy["subject"]["purpose"] == SUCCESSOR_POLICY_REVIEW_PURPOSE
    assert policy["review"]["validation_status"] == "not_started"
    assert policy["review"]["pr_check_status"] == "not_applicable"
    assert len(calls) == 1
    monkeypatch.setattr(sys, "argv", _arguments(candidate))
    assert runner.main() == 2
    assert "not an ordinary merge-readiness" in json.loads(capsys.readouterr().out)["error"]
    assert len(calls) == 1
    _renew_assertions(candidate, {"canonical_review_sha256": hashlib.sha256(policy_path.read_bytes()).hexdigest()})
    assert _bind(candidate)["status"] == "bound_validation_pending"
    with pytest.raises(ReviewCoordinationError, match="policy"):
        assert_exact_head_review_receipt(policy_path, head_sha=provider["head"])
    monkeypatch.setattr(sys, "argv", _arguments(candidate))
    assert runner.main() == 2
    assert "fresh native validation" in json.loads(capsys.readouterr().out)["error"]
    assert len(calls) == 1
    _complete_native_epoch(candidate)
    native = candidate["task"].read()
    assert native["validation_head_sha"] == provider["head"]
    assert "validation_pending_binding" not in native
    source = runner.successor_request(candidate["packet"], native["ticket"], tree)
    assert source is not None and "successor_policy_source" not in source
    metadata = _metadata(native)
    authority = {
        **_provider_authority(candidate["task"], pull_request="github:acme/app#236"),
        **metadata, "checks_verified": True, "reviews_verified": True,
        "subject_revision": provider["head"], "review_coordination_receipt": str(policy_path),
    }
    receipt_root = candidate["packet"] / "artifacts/review-negative"
    receipts = {
        state: _stage_receipt(
            receipt_root, state,
            evidence={**metadata, **(authority if state in {"pr_open", "ready_for_merge"} else {})},
        )
        for state in ("pre_pr_review", "pr_open", "ci_repair", "review_repair", "post_pr_review", "ready_for_merge")
    }
    with pytest.raises(delivery.DevelopmentDeliveryError, match="successor policy|pre-validation"):
        delivery.run_development_stage(
            candidate["task"].path, stage="review", receipts=receipts, idempotency_prefix="policy-is-not-ready"
        )
    assert candidate["task"].read()["state"] != "ready_for_merge"
    monkeypatch.setattr(sys, "argv", _arguments(candidate))
    assert runner.main() == 0
    result = json.loads(capsys.readouterr().out)
    ordinary = load_review_receipt(result["coordination_receipt"])
    assert result["reused"] is False and len(calls) == 2
    assert ordinary["key"] != policy["key"]
    assert ordinary["subject"]["purpose"] == "review_self"
    assert ordinary["family_key"] == policy["family_key"] and ordinary["chain_key"] != policy["chain_key"]
    assert ordinary["review"]["validation_status"] == ordinary["review"]["pr_check_status"] == "passed"
    assert "policy_delta_sha256" not in ordinary["review"]
    assert ordinary["review"]["decision"].startswith("ready_")
    assert assert_exact_head_review_receipt(
        result["coordination_receipt"], head_sha=provider["head"]
    )["outcome"] == "clean"
    assert load_review_receipt(policy_path) == policy
    assert ordinary["budget"]["absolute_full_reviews_used"] == 2


def test_requested_alias_reaches_its_real_stage_and_refuses_as_structured_json(
    candidate: dict[str, Any], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Each ordinary CLI alias selects its canonical predecessor target and handles AutoDevStateError."""
    _bind(candidate)
    runner = _load_runner()
    stages: list[str] = []

    def refuse_boundary(_path: Path, stage: str) -> dict[str, Any]:
        """Record the real target and exercise its typed negative workflow boundary."""
        stages.append(stage)
        raise orchestration.AutoDevStateError(f"{stage} is outside this Auto-Dev workflow boundary")

    def forbidden(*_args: Any, **_kwargs: Any) -> Any:
        """Reject any provider work after a known predecessor refusal."""
        raise AssertionError("an inadmissible workflow reached a provider edge")

    monkeypatch.setattr(orchestration, "require_auto_dev_predecessors", refuse_boundary)
    monkeypatch.setattr(runner, "provider_pr", forbidden)
    before = candidate["task"].path.read_bytes()
    aliases = {
        "review-self": "review_self", "review_self": "review_self",
        "review-repair": "review_self", "review_repair": "review_self",
        "review-others": "review_others", "review_others": "review_others",
        "finalize": "finalize", "merge-readiness": "finalize",
    }
    for alias, expected in aliases.items():
        monkeypatch.setattr(sys, "argv", _arguments(candidate, purpose=alias))
        assert runner.main() == 2
        assert json.loads(capsys.readouterr().out) == {
            "ok": False, "error": f"{expected} is outside this Auto-Dev workflow boundary",
        }
        assert stages[-1] == expected
        assert runner.normalize_review_purpose(alias, "full-pr")[0] == "review_self"
    assert candidate["task"].path.read_bytes() == before


@pytest.mark.parametrize("lookup_mode", ["exact", "family", "finalize"])
@pytest.mark.parametrize(
    "review",
    [
        {"policy_delta_sha256": "d" * 64},
        {"decision": "blocked_validation"},
        {"validation_status": "not_started"},
        {"pr_check_status": "not_applicable"},
    ],
    ids=["policy-digest", "pre-validation-decision", "unvalidated", "unchecked"],
)
def test_legacy_ordinary_key_cannot_reuse_policy_authority_or_purchase_a_free_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, lookup_mode: str, review: dict[str, str]
) -> None:
    """Both genuine coordinator lookup routes retain old receipts and spent budgets before refusing reuse."""
    coordinator = ReviewCoordinator(tmp_path / "shared")
    subject = _subject()
    calls: list[str] = []

    def legacy_review() -> dict[str, Any]:
        """Produce the historical valid-schema receipt through the real coordinator."""
        calls.append("original-paid-review")
        return {"outcome": "clean", **review}

    original = coordinator.execute(subject, legacy_review)
    before = {str(p.relative_to(coordinator.root)): p.read_bytes()
              for p in coordinator.root.rglob("*") if p.is_file()}
    if lookup_mode == "family":
        actual_path = coordinator._path
        lookups = 0

        def missing_exact_index(key: str) -> Path:
            """Simulate only the first absent exact-key storage index; family inventory/files remain real."""
            nonlocal lookups
            lookups += 1
            return tmp_path / "absent-exact-index" / (key + ".json") if lookups == 1 else actual_path(key)

        monkeypatch.setattr(coordinator, "_path", missing_exact_index)

    with pytest.raises(ReviewCoordinationError, match="ordinary (review|finalize) reuse"):
        if lookup_mode == "finalize":
            coordinator.finalize(subject)
        else:
            coordinator.execute(subject, legacy_review)

    assert calls == ["original-paid-review"]
    assert load_review_receipt(original.receipt_path) == original.receipt
    assert original.receipt["budget"]["full_reviews_used"] == 1
    assert original.receipt["budget"]["absolute_full_reviews_used"] == 1
    assert {str(p.relative_to(coordinator.root)): p.read_bytes()
            for p in coordinator.root.rglob("*") if p.is_file()} == before


@pytest.mark.parametrize("purpose", ["policy_audit:full-pr", "documentation_only", "security-research"])
def test_non_merge_review_purpose_can_reuse_its_explicit_not_applicable_status(
    tmp_path: Path, purpose: str
) -> None:
    """A legitimate non-merge review remains reusable without misrepresenting it as ready-for-merge."""
    coordinator = ReviewCoordinator(tmp_path / "shared")
    subject = _subject(purpose=purpose)
    calls: list[str] = []

    def review() -> dict[str, Any]:
        """Create the non-merge reviewer result through its real canonical producer boundary."""
        calls.append("review")
        return {"outcome": "clean", "validation_status": "not_started", "pr_check_status": "not_applicable"}

    original = coordinator.execute(subject, review)
    assert coordinator.execute(subject, review).reused
    assert coordinator.finalize(subject).reused
    assert calls == ["review"]
    with pytest.raises(ReviewCoordinationError, match="ready_for_merge"):
        assert_exact_head_review_receipt(original.receipt_path, head_sha=subject.head_sha)


@pytest.mark.parametrize("purpose", ["review-self", "review_repair:full-pr", "review-others:full_pr", "finalize", "merge-readiness"])
def test_legacy_merge_stage_labels_cannot_hide_prevalidation_authority(
    tmp_path: Path, purpose: str
) -> None:
    """Legacy spelling and scope provenance cannot turn pre-validation data into reusable ordinary authority."""
    coordinator = ReviewCoordinator(tmp_path / "shared")
    subject = _subject(purpose=purpose)
    original = coordinator.execute(subject, lambda: {"outcome": "clean", "pr_check_status": "not_applicable"})
    before = original.receipt_path.read_bytes()
    with pytest.raises(ReviewCoordinationError, match="ordinary review reuse"):
        coordinator.execute(subject, lambda: pytest.fail("legacy status purchased another review"))
    assert original.receipt_path.read_bytes() == before
