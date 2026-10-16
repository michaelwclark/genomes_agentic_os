"""Offline regressions for explicit delta closure and immutable advisory recovery."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest

from genomes_agentic_os import review_coordination as coordination_core
from genomes_agentic_os.review_coordination import (
    ReviewCoordinationError,
    ReviewCoordinator,
    ReviewSubject,
    assert_exact_head_review_receipt,
    load_review_receipt,
)


PARENT_IDS = ("finding-0b1ae8ec5ed19379", "finding-9734784dece486d3")
POLICY = "c" * 64
BASE = "a" * 40


def subject(head: str = "1" * 40) -> ReviewSubject:
    return ReviewSubject("acme/widgets", "github:acme/widgets#42", "main", BASE, head, POLICY)


def runner_module():
    path = Path(__file__).parents[1] / "harness/skills/auto-dev-review-self-opposing-model/scripts/run_opposing_model_review.py"
    spec = importlib.util.spec_from_file_location("review_parent_resolution_runner", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def parent_review(coordinator: ReviewCoordinator):
    return coordinator.execute(
        subject(),
        lambda: {
            "outcome": "findings",
            "findings": [
                {"id": finding_id, "severity": "high", "summary": summary, "evidence": ["src/authority.py:42"]}
                for finding_id, summary in zip(PARENT_IDS, ("Archive proof is unreadable", "Recorded defer cannot hand off"))
            ],
        },
    )


def parent_ref(parent) -> dict[str, str]:
    return {"ref": str(parent.receipt_path), "sha256": hashlib.sha256(parent.receipt_path.read_bytes()).hexdigest()}


def advice() -> list[dict]:
    return [
        {"id": f"F{index}", "severity": "low", "category": "tests", "file": "tests/test_authority.py", "line": index,
         "title": f"New unrelated advice {index}", "detail": "The original blocking issue is a different finding.",
         "suggested_fix": "Optional clarification.", "blocking": False}
        for index in range(1, 6)
    ]


def resolution(parent, **changes) -> dict:
    return {"schema": "auto-dev-review-parent-resolutions/v1", "parent_key": parent.key,
            "parent_receipt_sha256": parent_ref(parent)["sha256"], "resolution_refs": list(PARENT_IDS), **changes}


def response(rows: list[dict], resolved: dict | None = None) -> str:
    text = "```json\n" + json.dumps(rows) + "\n```\n"
    if resolved is not None:
        text += "```json\n" + json.dumps(resolved) + "\n```\n"
    return text + "AGENTIC_OS_REVIEW_VERDICT: FINDINGS"


def legacy_delta(coordinator: ReviewCoordinator, parent, text: str):
    runner = runner_module()
    return coordinator.execute(
        subject("2" * 40),
        lambda: {"outcome": "clean", "response": text, "findings": runner.coordination_findings(advice())},
        mode="delta", parent_key=parent.key,
    )


def request(parent) -> dict:
    return {"work_item_id": "AGE-262", "mode": "post_pr", "base_sha": BASE, "head_sha": "2" * 40,
            "review_mode": "delta", "parent_key": parent.key, "parent_receipt": parent_ref(parent),
            "delta_base_sha": "1" * 40, "spec_source": "Repair the inherited authority defects"}


def resolved_parent(coordinator: ReviewCoordinator, refs=PARENT_IDS):
    parent = parent_review(coordinator)
    return coordinator.execute(subject("2" * 40), lambda: {
        "outcome": "clean", "resolution_refs": list(refs),
    }, mode="delta", parent_key=parent.key)


@pytest.mark.parametrize("opt_in", [False, None, "true", 1])
def test_ordinary_resolution_parser_refuses_already_resolved_ids(tmp_path: Path, opt_in) -> None:
    parent = resolved_parent(ReviewCoordinator(tmp_path / "coordination"))
    with pytest.raises(ReviewCoordinationError, match="unique open parent"):
        coordination_core.parse_parent_resolution_refs(
            response(advice(), resolution(parent)), parent_key=parent.key,
            parent_receipt_sha256=parent_ref(parent)["sha256"],
            parent_ledger=parent.receipt["findings_ledger"], allow_resolved_noop=opt_in,
        )


def test_recovery_resolution_parser_returns_only_open_ids(tmp_path: Path) -> None:
    parent = resolved_parent(ReviewCoordinator(tmp_path / "coordination"), PARENT_IDS[:1])
    before = parent.receipt_path.read_bytes()
    refs = coordination_core.parse_parent_resolution_refs(
        response(advice(), resolution(parent)), parent_key=parent.key,
        parent_receipt_sha256=parent_ref(parent)["sha256"],
        parent_ledger=parent.receipt["findings_ledger"], allow_resolved_noop=True,
    )
    assert refs == list(PARENT_IDS[1:])
    assert parent.receipt_path.read_bytes() == before


@pytest.mark.parametrize("changes", [
    {"parent_key": "f" * 64}, {"parent_receipt_sha256": "f" * 64},
    {"resolution_refs": ["finding-not-in-parent"]},
    {"resolution_refs": [PARENT_IDS[0], PARENT_IDS[0]]},
    {"resolution_refs": [" " + PARENT_IDS[0]]}, {"resolution_refs": PARENT_IDS[0]},
])
def test_recovery_noop_still_rejects_invalid_parent_declarations(tmp_path: Path, changes: dict) -> None:
    parent = resolved_parent(ReviewCoordinator(tmp_path / "coordination"))
    before = parent.receipt_path.read_bytes()
    with pytest.raises(ReviewCoordinationError, match="resolution|parent"):
        coordination_core.parse_parent_resolution_refs(
            response(advice(), resolution(parent, **changes)), parent_key=parent.key,
            parent_receipt_sha256=parent_ref(parent)["sha256"],
            parent_ledger=parent.receipt["findings_ledger"], allow_resolved_noop=True,
        )
    assert parent.receipt_path.read_bytes() == before


@pytest.mark.parametrize("open_survivor", [False, True])
def test_advisory_recovery_treats_known_resolved_refs_as_noops(tmp_path: Path, open_survivor: bool) -> None:
    coordinator = ReviewCoordinator(tmp_path / "coordination")
    parent = resolved_parent(coordinator, PARENT_IDS[:1] if open_survivor else PARENT_IDS)
    text = response(advice(), resolution(parent, resolution_refs=list(PARENT_IDS[:1])))
    with pytest.raises(ReviewCoordinationError) as strict_error:
        coordination_core.parse_parent_resolution_refs(
            text, parent_key=parent.key, parent_receipt_sha256=parent_ref(parent)["sha256"],
            parent_ledger=parent.receipt["findings_ledger"],
        )
    delta = coordinator.execute(subject("3" * 40), lambda: {
        "outcome": "findings", "response": text,
        "findings": runner_module().coordination_findings(advice()),
        "resolution_refs": [], "resolution_warning": str(strict_error.value),
    }, mode="delta", parent_key=parent.key)
    evidence = tmp_path / "reviewer-response.md"
    evidence.write_text(text)
    originals = {p: p.read_bytes() for p in coordinator.receipts.glob("*.json")}
    assert delta.receipt["review"]["resolution_refs"] == []
    assert delta.receipt["review"]["resolution_warning"]
    if open_survivor:
        with pytest.raises(ReviewCoordinationError, match="unresolved inherited"):
            coordinator.derive_same_head_advisory_clean(delta.receipt_path, evidence_path=evidence, findings=advice())
        assert set(coordinator.receipts.glob("*.json")) == set(originals)
    else:
        child = coordinator.derive_same_head_advisory_clean(delta.receipt_path, evidence_path=evidence, findings=advice())
        loaded = load_review_receipt(child.receipt_path)
        assert loaded["outcome"] == "clean" and loaded["review"]["resolution_refs"] == []
        ledger = {row["id"]: row for row in loaded["findings_ledger"]}
        assert all(ledger[finding_id] == next(row for row in parent.receipt["findings_ledger"]
                                             if row["id"] == finding_id) for finding_id in PARENT_IDS)
        assert loaded["budget"] == delta.receipt["budget"]
        assert loaded["budget"]["full_reviews_used"] == 1
        assert loaded["budget"]["delta_reviews_used"] == 2
        again = coordinator.derive_same_head_advisory_clean(delta.receipt_path, evidence_path=evidence, findings=advice())
        assert again.reused and again.key == child.key
        assert assert_exact_head_review_receipt(child.receipt_path, head_sha="3" * 40,
            repository="acme/widgets", pull_request="github:acme/widgets#42",
            policy_fingerprint=POLICY)["outcome"] == "clean"
    assert all(p.read_bytes() == raw for p, raw in originals.items())
    assert evidence.read_text() == text


def test_delta_prompt_renders_verified_parent_ids_and_resolution_contract(tmp_path: Path) -> None:
    runner = runner_module()
    parent = parent_review(ReviewCoordinator(tmp_path / "coordination"))
    prompt = runner.render_prompt(request(parent), {"url": "https://example.test/pull/42", "statusCheckRollup": []})
    for finding_id in PARENT_IDS:
        assert finding_id in prompt
    assert parent.key in prompt and parent_ref(parent)["sha256"] in prompt
    assert "auto-dev-review-parent-resolutions/v1" in prompt
    assert "resolution_refs" in prompt
    assert f"git diff {'1' * 40}..{'2' * 40}" in prompt
    assert parent.receipt["findings_ledger"][0]["summary"] in prompt


@pytest.mark.parametrize("changed", ["hash", "key", "head"])
def test_delta_prompt_rejects_changed_parent_binding(tmp_path: Path, changed: str) -> None:
    runner = runner_module()
    parent = parent_review(ReviewCoordinator(tmp_path / "coordination"))
    value = request(parent)
    if changed == "hash":
        value["parent_receipt"]["sha256"] = "f" * 64
    elif changed == "key":
        value["parent_key"] = "f" * 64
    else:
        value["delta_base_sha"] = "f" * 40
    with pytest.raises((runner.ReviewError, ReviewCoordinationError), match="parent"):
        runner.render_prompt(value, {"url": "https://example.test/pull/42", "statusCheckRollup": []})


def test_advisory_recovery_preserves_unresolved_inherited_blockers(tmp_path: Path) -> None:
    coordinator = ReviewCoordinator(tmp_path / "coordination")
    parent = parent_review(coordinator)
    text = response(advice())
    delta = legacy_delta(coordinator, parent, text)
    original = delta.receipt_path.read_bytes()
    evidence = tmp_path / "reviewer-response.md"
    evidence.write_text(text)
    before = {path.name: path.read_bytes() for path in coordinator.receipts.glob("*.json")}
    assert delta.receipt["outcome"] == "findings"
    assert {row["id"] for row in delta.receipt["findings_ledger"] if row["status"] == "open"} == set(PARENT_IDS)
    with pytest.raises(ReviewCoordinationError, match="unresolved"):
        coordinator.derive_same_head_advisory_clean(delta.receipt_path, evidence_path=evidence, findings=advice())
    assert delta.receipt_path.read_bytes() == original
    assert {path.name: path.read_bytes() for path in coordinator.receipts.glob("*.json")} == before
    assert delta.receipt["budget"]["delta_reviews_used"] == 1


def test_advisory_recovery_retains_explicit_bound_parent_resolutions(tmp_path: Path) -> None:
    coordinator = ReviewCoordinator(tmp_path / "coordination")
    parent = parent_review(coordinator)
    text = response(advice(), resolution(parent))
    delta = legacy_delta(coordinator, parent, text)
    original = delta.receipt_path.read_bytes()
    evidence = tmp_path / "reviewer-response.md"
    evidence.write_text(text)
    recovered = coordinator.derive_same_head_advisory_clean(delta.receipt_path, evidence_path=evidence, findings=advice())
    ledger = {row["id"]: row for row in recovered.receipt["findings_ledger"]}
    assert all(ledger[finding_id]["status"] == "resolved" for finding_id in PARENT_IDS)
    assert recovered.receipt["review"]["resolution_refs"] == list(PARENT_IDS)
    assert delta.receipt_path.read_bytes() == original
    assert recovered.receipt["budget"] == delta.receipt["budget"]
    assert assert_exact_head_review_receipt(recovered.receipt_path, head_sha="2" * 40,
                                           repository="acme/widgets", pull_request="github:acme/widgets#42",
                                           policy_fingerprint=POLICY)["outcome"] == "clean"


@pytest.mark.parametrize("changes", [
    {"parent_key": "f" * 64}, {"parent_receipt_sha256": "f" * 64},
    {"resolution_refs": ["finding-not-in-parent"]}, {"resolution_refs": ["fake-patch-ref"]},
    {"resolution_refs": [PARENT_IDS[0], PARENT_IDS[0]]}, {"resolution_refs": PARENT_IDS[0]},
])
def test_advisory_recovery_rejects_forged_parent_resolution(tmp_path: Path, changes: dict) -> None:
    coordinator = ReviewCoordinator(tmp_path / "coordination")
    parent = parent_review(coordinator)
    text = response(advice(), resolution(parent, **changes))
    delta = legacy_delta(coordinator, parent, text)
    evidence = tmp_path / "reviewer-response.md"
    evidence.write_text(text)
    before = delta.receipt_path.read_bytes()
    with pytest.raises(ReviewCoordinationError, match="resolution|parent"):
        coordinator.derive_same_head_advisory_clean(delta.receipt_path, evidence_path=evidence, findings=advice())
    assert delta.receipt_path.read_bytes() == before


def test_advisory_recovery_rejects_old_receipt_copy(tmp_path: Path) -> None:
    coordinator = ReviewCoordinator(tmp_path / "coordination")
    parent = parent_review(coordinator)
    text = response(advice(), resolution(parent))
    delta = legacy_delta(coordinator, parent, text)
    copied = tmp_path / "old-receipt.json"
    copied.write_bytes(delta.receipt_path.read_bytes())
    evidence = tmp_path / "reviewer-response.md"
    evidence.write_text(text)
    with pytest.raises(ReviewCoordinationError, match="canonical"):
        coordinator.derive_same_head_advisory_clean(copied, evidence_path=evidence, findings=advice())


def test_same_id_advice_cannot_resolve_a_different_inherited_blocker(tmp_path: Path) -> None:
    coordinator = ReviewCoordinator(tmp_path / "coordination")
    parent = parent_review(coordinator)
    delta = coordinator.execute(subject("2" * 40), lambda: {
        "outcome": "clean", "findings": [{"id": PARENT_IDS[0], "severity": "low", "summary": "Unrelated new advice",
        "evidence": ["tests/advice.py:7"], "status": "resolved", "advisory": True,
        "resolution_refs": ["reviewer-nonblocking-advisory:" + PARENT_IDS[0]]}],
        "resolution_refs": [PARENT_IDS[1]],
    }, mode="delta", parent_key=parent.key)
    ledger = {row["id"]: row for row in delta.receipt["findings_ledger"]}
    assert delta.receipt["outcome"] == "findings"
    assert ledger[PARENT_IDS[0]]["status"] == "open" and ledger[PARENT_IDS[0]]["severity"] == "high"
    assert ledger[PARENT_IDS[0]]["summary"] == parent.receipt["findings_ledger"][0]["summary"]


def test_explicit_resolution_cannot_erase_a_current_open_replacement(tmp_path: Path) -> None:
    coordinator = ReviewCoordinator(tmp_path / "coordination")
    parent = parent_review(coordinator)
    delta = coordinator.execute(subject("2" * 40), lambda: {
        "outcome": "clean", "resolution_refs": list(PARENT_IDS),
        "findings": [{"id": PARENT_IDS[0], "severity": "high", "status": "open",
                      "summary": "The original defect still blocks", "evidence": ["src/authority.py:42"],
                      "resolution_refs": ["unverified-patch-ref"]}],
    }, mode="delta", parent_key=parent.key)
    ledger = {row["id"]: row for row in delta.receipt["findings_ledger"]}
    assert delta.receipt["outcome"] == "findings" and ledger[PARENT_IDS[0]]["status"] == "open"


def legacy_recovery_receipt(coordinator, original, text, rows, ledger):
    evidence_sha = hashlib.sha256(text.encode()).hexdigest()
    findings_sha = hashlib.sha256(json.dumps(rows, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    key = coordination_core.advisory_recovery_key(original.key, evidence_sha, findings_sha)
    payload = {**original.receipt, "key": key, "mode": "advisory_recovery", "outcome": "clean",
               "parent_key": original.key, "findings_ledger": ledger,
               "review": {"outcome": "clean", "response": text, "structured_findings": rows},
               "recovery": {"source_receipt_ref": str(original.receipt_path),
                            "source_receipt_sha256": parent_ref(original)["sha256"],
                            "evidence_sha256": evidence_sha, "findings_sha256": findings_sha}}
    path = coordinator.receipts / (key + ".json")
    path.write_text(json.dumps(payload))
    return path


def test_loading_old_recovery_child_cannot_discard_inherited_blockers(tmp_path: Path) -> None:
    coordinator = ReviewCoordinator(tmp_path / "coordination")
    parent = parent_review(coordinator)
    rows, text = advice(), response(advice())
    delta = legacy_delta(coordinator, parent, text)
    _, ledger, _ = coordination_core.normalize_findings_ledger({
        "outcome": "clean", "findings": runner_module().coordination_findings(rows)})
    child = legacy_recovery_receipt(coordinator, delta, text, rows, ledger)
    before = child.read_bytes()
    with pytest.raises(ReviewCoordinationError, match="unresolved inherited"):
        load_review_receipt(child)
    assert child.read_bytes() == before


def test_loading_valid_legacy_full_advice_keeps_its_original_ledger_shape(tmp_path: Path) -> None:
    coordinator = ReviewCoordinator(tmp_path / "coordination")
    rows, text = advice(), response(advice())
    original = coordinator.execute(subject(), lambda: {
        "outcome": "findings", "response": text, "findings": runner_module().coordination_findings(rows)})
    # Older recovery preserved raw titles without the runner's file/detail
    # evidence rendering. The immutable response still proves all advice.
    _, ledger, _ = coordination_core.normalize_findings_ledger({"outcome": "clean", "findings": [
        {**row, "status": "resolved", "resolution_refs": ["reviewer-nonblocking-advisory:" + row["id"]]}
        for row in rows]})
    child = legacy_recovery_receipt(coordinator, original, text, rows, ledger)
    before = child.read_bytes()
    assert load_review_receipt(child)["outcome"] == "clean"
    assert child.read_bytes() == before


@pytest.mark.parametrize("known_blocker", [False, True])
def test_legacy_full_placeholder_recovery_preserves_known_blockers(tmp_path: Path, known_blocker: bool) -> None:
    coordinator = ReviewCoordinator(tmp_path / "coordination")
    rows, text = advice(), response(advice())
    review = {"outcome": "findings", "response": text}
    if known_blocker:
        review["findings"] = [{"id": PARENT_IDS[0], "severity": "high", "summary": "Known blocking issue",
                               "evidence": ["src/authority.py:42"]}]
    original = coordinator.execute(subject(), lambda: review)
    before = original.receipt_path.read_bytes()
    evidence = tmp_path / "reviewer-response.md"
    evidence.write_text(text)
    if known_blocker:
        with pytest.raises(ReviewCoordinationError, match="unresolved"):
            coordinator.derive_same_head_advisory_clean(original.receipt_path, evidence_path=evidence, findings=rows)
    else:
        recovered = coordinator.derive_same_head_advisory_clean(original.receipt_path, evidence_path=evidence, findings=rows)
        assert load_review_receipt(recovered.receipt_path)["outcome"] == "clean"
        assert recovered.receipt["budget"] == original.receipt["budget"]
    assert original.receipt_path.read_bytes() == before


def test_advisory_recovery_rejects_changed_raw_response(tmp_path: Path) -> None:
    coordinator = ReviewCoordinator(tmp_path / "coordination")
    parent = parent_review(coordinator)
    text = response(advice(), resolution(parent))
    delta = legacy_delta(coordinator, parent, text)
    evidence = tmp_path / "reviewer-response.md"
    evidence.write_text(text + "\nchanged raw evidence")
    original = delta.receipt_path.read_bytes()
    with pytest.raises(ReviewCoordinationError, match="does not match"):
        coordinator.derive_same_head_advisory_clean(delta.receipt_path, evidence_path=evidence, findings=advice())
    assert delta.receipt_path.read_bytes() == original


def test_advisory_recovery_rechecks_source_bytes_under_lock(monkeypatch, tmp_path: Path) -> None:
    coordinator = ReviewCoordinator(tmp_path / "coordination")
    parent = parent_review(coordinator)
    text = response(advice(), resolution(parent))
    delta = legacy_delta(coordinator, parent, text)
    evidence = tmp_path / "reviewer-response.md"
    evidence.write_text(text)
    original = delta.receipt_path.read_bytes()
    parse = coordination_core._immutable_structured_findings

    def change_source(value):
        parsed = parse(value)
        delta.receipt_path.write_bytes(original + b"\n")
        return parsed

    monkeypatch.setattr(coordination_core, "_immutable_structured_findings", change_source)
    with pytest.raises(ReviewCoordinationError, match="changed before admission"):
        coordinator.derive_same_head_advisory_clean(delta.receipt_path, evidence_path=evidence, findings=advice())
    assert delta.receipt_path.read_bytes() == original + b"\n"
    assert len(list(coordinator.receipts.glob("*.json"))) == 2


def test_duplicate_resolution_declarations_do_not_grant_recovery(tmp_path: Path) -> None:
    coordinator = ReviewCoordinator(tmp_path / "coordination")
    parent = parent_review(coordinator)
    text = response(advice(), resolution(parent)).replace(
        "AGENTIC_OS_REVIEW_VERDICT:", "```json\n" + json.dumps(resolution(parent)) + "\n```\nAGENTIC_OS_REVIEW_VERDICT:")
    delta = legacy_delta(coordinator, parent, text)
    evidence = tmp_path / "reviewer-response.md"
    evidence.write_text(text)
    with pytest.raises(ReviewCoordinationError, match="unambiguous"):
        coordinator.derive_same_head_advisory_clean(delta.receipt_path, evidence_path=evidence, findings=advice())


def test_explicit_delta_retains_already_resolved_parent_history(tmp_path: Path) -> None:
    coordinator = ReviewCoordinator(tmp_path / "coordination")
    parent = coordinator.execute(subject(), lambda: {"outcome": "findings", "findings": [
        {"id": PARENT_IDS[0], "summary": "Blocking authority gap", "severity": "high", "evidence": ["src/authority.py:42"]},
        {"id": "finding-prior-advice", "summary": "Prior advice", "severity": "low", "evidence": ["tests/authority.py:7"],
         "status": "resolved", "resolution_refs": ["reviewer-nonblocking-advisory:finding-prior-advice"]}]})
    delta = coordinator.execute(subject("2" * 40), lambda: {"outcome": "clean", "resolution_refs": [PARENT_IDS[0]]},
                                mode="delta", parent_key=parent.key)
    ledger = {row["id"]: row for row in delta.receipt["findings_ledger"]}
    assert delta.receipt["outcome"] == "clean" and ledger[PARENT_IDS[0]]["status"] == "resolved"
    assert ledger["finding-prior-advice"] == parent.receipt["findings_ledger"][1]


@pytest.mark.parametrize("closure", ["omitted", "explicit", "forged-hash", "forged-ref"])
def test_runner_callback_passes_only_explicit_verified_parent_resolution_refs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, closure: str,
) -> None:
    runner = runner_module()
    coordination = ReviewCoordinator(tmp_path / "coordination")
    parent = parent_review(coordination)
    parent_original = parent.receipt_path.read_bytes()
    work_item, worktree = tmp_path / "work-item", tmp_path / "worktree"
    work_item.mkdir()
    worktree.mkdir()
    head = "2" * 40
    source = {"work_item_id": "AGE-262", "worktree": str(worktree), "repo_path": str(worktree),
              "implementation_summary": "Verify inherited repair", "spec_source": "AGE-262", "builder_model": "gpt-6-sol",
              "selected_reviewer_model": "opus", "reviewer_selection_source": "policy", "target_branch": "main",
              "base_sha": BASE, "head_sha": head, "diff_hash": "d" * 64, "pr_number": 42, "mode": "post_pr"}
    provider = {"number": 42, "url": "https://example.test/acme/widgets/pull/42", "state": "OPEN",
                "headRefOid": head, "baseRefOid": BASE, "baseRefName": "main", "statusCheckRollup": []}
    block = None if closure == "omitted" else resolution(parent)
    if closure == "forged-hash":
        block["parent_receipt_sha256"] = "f" * 64
    if closure == "forged-ref":
        block["resolution_refs"] = ["fake-patch-ref"]
    text = response(advice(), block)
    calls = []

    def fake_model(argv, **_kwargs):
        assert argv[0] == "claude", "test must never invoke a real subprocess transport"
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, text, "")

    monkeypatch.setattr(runner, "resolve_os_root", lambda _explicit: tmp_path)
    monkeypatch.setattr(runner, "prior_request", lambda *_args: source)
    monkeypatch.setattr(runner, "project_identity", lambda *_args: ("acme", "widgets"))
    monkeypatch.setattr(runner, "load_development_profile", lambda *_args: ({"repository": {"root": str(worktree), "base_branch": "main"}}, tmp_path / "development.yml"))
    monkeypatch.setattr(runner, "provider_pr", lambda *_args: provider)
    monkeypatch.setattr(runner, "git_head", lambda _worktree: head)
    monkeypatch.setattr(runner, "git_repository", lambda _worktree: "acme/widgets")
    monkeypatch.setattr(runner, "policy_fingerprint", lambda _source: POLICY)
    monkeypatch.setattr(runner, "validated_delta_hash", lambda *_args: "d" * 64)
    monkeypatch.setattr(runner, "shared_review_coordination_root", lambda _root: tmp_path / "coordination")
    monkeypatch.setattr(runner.shutil, "which", lambda _name: "claude")
    monkeypatch.setattr(runner, "run", fake_model)
    monkeypatch.setattr(runner, "decide", lambda _run_dir: {"decision": "ready_post_pr_checks"})
    monkeypatch.setattr(sys, "argv", ["run_opposing_model_review.py", "AGE-262", "--os-root", str(tmp_path),
                                    "--work-item", str(work_item), "--worktree", str(worktree),
                                    "--mode", "delta", "--parent-key", parent.key])
    assert runner.main() == (0 if closure == "explicit" else 2)
    completed = load_review_receipt(coordination.receipts / (runner.stable_review_key(subject(head)) + ".json"))
    assert len(calls) == 1
    assert completed["review"].get("resolution_refs", []) == (list(PARENT_IDS) if closure == "explicit" else [])
    assert {row["id"] for row in completed["findings_ledger"] if row["status"] == "open"} == (set() if closure == "explicit" else set(PARENT_IDS))
    assert completed["budget"]["full_reviews_used"] == completed["budget"]["delta_reviews_used"] == 1
    if closure.startswith("forged"):
        assert completed["review"]["resolution_warning"]
    assert parent.receipt_path.read_bytes() == parent_original
