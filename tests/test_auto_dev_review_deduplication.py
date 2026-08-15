"""Regression tests for CC-422's paid-review single-flight contract."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import threading
import time

import jsonschema
import pytest

from genomes_agentic_os.review_coordination import (
    ReviewBudgetExceeded,
    ReviewCoordinationError,
    ReviewCoordinator,
    ReviewSubject,
    assert_exact_head_review_receipt,
    canonical_review_purpose,
    load_review_receipt,
    provider_review_marker,
    review_chain_key,
    review_family_key,
    shared_review_coordination_root,
    stable_review_key,
)
from genomes_agentic_os.validate import SCHEMA_TARGETS


POLICY = "b" * 64
BASE = "a" * 40


def _subject(
    head: str = "1" * 40,
    *,
    policy: str = POLICY,
    base: str = BASE,
) -> ReviewSubject:
    return ReviewSubject(
        repository="acme/widgets",
        pull_request="42",
        base_branch="main",
        base_sha=base,
        head_sha=head,
        policy_fingerprint=policy,
        purpose="review_self",
    )


def _clean() -> dict[str, str]:
    return {"outcome": "clean", "summary": "No blocking findings."}


def test_exact_head_gate_accepts_canonical_github_repository_alias(
    tmp_path: Path,
) -> None:
    completed = ReviewCoordinator(tmp_path / "auto-dev-review").execute(
        _subject(), _clean
    )

    receipt = assert_exact_head_review_receipt(
        completed.receipt_path,
        head_sha="1" * 40,
        repository="git:github.com/acme/widgets",
        pull_request="42",
        policy_fingerprint=POLICY,
    )

    assert receipt["key"] == completed.key


def test_same_key_reuses_receipt_without_second_external_call(tmp_path: Path) -> None:
    coordinator = ReviewCoordinator(tmp_path / "auto-dev-review")
    calls = 0

    def review() -> dict[str, str]:
        nonlocal calls
        calls += 1
        return _clean()

    first = coordinator.execute(_subject(), review)
    second = coordinator.execute(_subject(), review)

    assert calls == 1
    assert not first.reused
    assert second.reused
    assert second.receipt_path == first.receipt_path
    assert second.key == stable_review_key(_subject())


def test_concurrent_same_key_is_single_flight(tmp_path: Path) -> None:
    coordinator = ReviewCoordinator(tmp_path / "auto-dev-review")
    calls = 0
    guard = threading.Lock()

    def review() -> dict[str, str]:
        nonlocal calls
        with guard:
            calls += 1
        time.sleep(0.05)
        return _clean()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: coordinator.execute(_subject(), review), range(2)))

    assert calls == 1
    assert sorted(result.reused for result in results) == [False, True]
    assert results[0].key == results[1].key


def test_concurrent_terminal_posts_share_the_family_single_flight(tmp_path: Path) -> None:
    coordinator = ReviewCoordinator(tmp_path / "auto-dev-review")
    coordinator.execute(_subject(), _clean)
    calls = 0
    guard = threading.Lock()

    def post(_marker: str, _receipt: dict[str, object]) -> dict[str, object]:
        nonlocal calls
        with guard:
            calls += 1
        time.sleep(0.05)
        return {"readback_verified": True, "comment_id": 99}

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                lambda _: coordinator.post_terminal(
                    _subject(), post, scrub_passed=True
                ),
                range(2),
            )
        )

    assert calls == 1
    assert sorted(result.reused for result in results) == [False, True]
    assert all(result.receipt["provider_post"]["status"] == "posted" for result in results)


def test_changed_heads_use_one_full_then_three_delta_reviews(tmp_path: Path) -> None:
    coordinator = ReviewCoordinator(tmp_path / "auto-dev-review")
    first = coordinator.execute(_subject("1" * 40), _clean)
    parent = first.key
    for digit in ("2", "3", "4"):
        result = coordinator.execute(
            _subject(digit * 40), _clean, mode="delta", parent_key=parent
        )
        parent = result.key

    called = False

    def forbidden() -> dict[str, str]:
        nonlocal called
        called = True
        return _clean()

    with pytest.raises(ReviewBudgetExceeded, match="delta-review budget"):
        coordinator.execute(_subject("5" * 40), forbidden, mode="delta", parent_key=parent)
    assert not called, "budget circuit breaker must run before the external reviewer"


def test_policy_or_base_drift_permits_only_one_additional_full_review(tmp_path: Path) -> None:
    coordinator = ReviewCoordinator(tmp_path / "auto-dev-review")
    coordinator.execute(_subject(), _clean)
    coordinator.execute(_subject("2" * 40, policy="c" * 64), _clean)

    called = False

    def forbidden() -> dict[str, str]:
        nonlocal called
        called = True
        return _clean()

    with pytest.raises(ReviewBudgetExceeded, match="absolute full-review budget"):
        coordinator.execute(_subject("3" * 40, base="d" * 40), forbidden)
    assert not called


def test_provider_post_is_terminal_marked_and_reused_once(tmp_path: Path) -> None:
    coordinator = ReviewCoordinator(tmp_path / "auto-dev-review")
    review_calls = 0
    post_calls = 0

    def review() -> dict[str, str]:
        nonlocal review_calls
        review_calls += 1
        return _clean()

    def post(marker: str, receipt: dict[str, object]) -> dict[str, object]:
        nonlocal post_calls
        post_calls += 1
        assert receipt["status"] == "completed"
        assert marker == provider_review_marker(str(receipt["key"]))
        return {"readback_verified": True, "comment_id": 99}

    coordinator.execute(_subject(), review)
    first = coordinator.post_terminal(_subject(), post, scrub_passed=True)
    second = coordinator.post_terminal(_subject(), post, scrub_passed=True)

    assert review_calls == 1
    assert post_calls == 1
    assert first.receipt["provider_post"]["status"] == "posted"
    assert second.reused


def test_provider_post_budget_fails_before_new_review_call(tmp_path: Path) -> None:
    coordinator = ReviewCoordinator(tmp_path / "auto-dev-review")
    coordinator.execute(_subject(), _clean)
    coordinator.post_terminal(
        _subject(),
        lambda _marker, _receipt: {"readback_verified": True},
        scrub_passed=True,
    )
    second = coordinator.execute(_subject("2" * 40), _clean, mode="delta")

    with pytest.raises(ReviewBudgetExceeded, match="provider-post budget"):
        coordinator.post_terminal(
            _subject("2" * 40),
            lambda _marker, _receipt: {"readback_verified": True},
            scrub_passed=True,
        )
    assert second.receipt["provider_post"]["status"] == "not_requested"


def test_unavailable_attempt_is_retryable_free_and_not_a_delta_parent(
    tmp_path: Path,
) -> None:
    coordinator = ReviewCoordinator(tmp_path / "auto-dev-review")
    calls = 0

    def unavailable() -> dict[str, object]:
        nonlocal calls
        calls += 1
        return {"outcome": "unavailable", "exit_code": 1}

    first = coordinator.execute(_subject(), unavailable)
    second = coordinator.execute(_subject(), unavailable)
    assert calls == 2
    assert first.receipt["budget"]["full_reviews_used"] == 0
    assert second.receipt["budget"]["absolute_full_reviews_used"] == 0
    with pytest.raises(ReviewCoordinationError, match="successful parent"):
        coordinator.execute(
            _subject("2" * 40), _clean, mode="delta", parent_key=first.key
        )


def test_failed_scrub_is_retryable_unavailable_and_does_not_burn_budget(
    tmp_path: Path,
) -> None:
    coordinator = ReviewCoordinator(tmp_path / "auto-dev-review")
    calls = 0

    def scrub_failure() -> dict[str, object]:
        nonlocal calls
        calls += 1
        return {
            "outcome": "clean",
            "scrub_passed": False,
            "scrub_hits": ["internal-path"],
            "exit_code": 0,
        }

    first = coordinator.execute(_subject(), scrub_failure)
    second = coordinator.execute(_subject(), scrub_failure)
    assert calls == 2
    assert first.receipt["outcome"] == second.receipt["outcome"] == "unavailable"
    assert first.receipt["budget"]["full_reviews_used"] == 0
    assert second.receipt["budget"]["absolute_full_reviews_used"] == 0


def test_scrub_failing_findings_remain_canonical_and_budget_counted(
    tmp_path: Path,
) -> None:
    coordinator = ReviewCoordinator(tmp_path / "auto-dev-review")
    calls = 0

    def findings() -> dict[str, object]:
        nonlocal calls
        calls += 1
        return {
            "outcome": "findings",
            "scrub_passed": False,
            "scrub_hits": ["internal-path"],
            "findings": [
                {
                    "id": "finding-scrubbed-evidence",
                    "severity": "high",
                    "summary": "Real finding cites scrubbed evidence",
                    "evidence": ["internal-path:42"],
                }
            ],
        }

    first = coordinator.execute(_subject(), findings)
    replay = coordinator.execute(_subject(), findings)
    assert calls == 1
    assert first.receipt["outcome"] == "findings"
    assert first.receipt["budget"]["full_reviews_used"] == 1
    assert first.receipt_path.parent == coordinator.receipts
    serialized = first.receipt_path.read_text(encoding="utf-8")
    assert "internal-path" not in serialized
    assert first.receipt["review"]["consumer_safe"] is True
    assert first.receipt["review"]["scrub_hit_count"] == 1
    assert replay.reused
    with pytest.raises(ReviewCoordinationError, match="clean review"):
        coordinator.post_terminal(
            _subject(),
            lambda _marker, _receipt: {"readback_verified": True},
            scrub_passed=False,
        )


def test_legacy_clean_scrub_failure_is_archived_and_retried_not_reused(
    tmp_path: Path,
) -> None:
    coordinator = ReviewCoordinator(tmp_path / "auto-dev-review")
    original = coordinator.execute(_subject(), _clean)
    legacy = json.loads(original.receipt_path.read_text(encoding="utf-8"))
    legacy["review"]["scrub_passed"] = False
    legacy["review"]["scrub_hits"] = ["internal-path"]
    legacy["provider_post"]["status"] = "pending"
    original.receipt_path.write_text(
        json.dumps(legacy, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    calls = 0

    def clean_retry() -> dict[str, object]:
        nonlocal calls
        calls += 1
        return {"outcome": "clean", "scrub_passed": True}

    retried = coordinator.execute(_subject(), clean_retry)
    assert calls == 1
    assert not retried.reused
    assert retried.receipt["outcome"] == "clean"
    assert retried.receipt["budget"]["full_reviews_used"] == 1
    archived = list(coordinator.attempts.glob(f"{original.key}-*.json"))
    assert len(archived) == 1
    preserved = json.loads(archived[0].read_text(encoding="utf-8"))
    assert preserved["outcome"] == "clean"
    assert preserved["review"]["scrub_passed"] is False


def test_clean_delta_preserves_unresolved_parent_without_explicit_refs(
    tmp_path: Path,
) -> None:
    coordinator = ReviewCoordinator(tmp_path / "auto-dev-review")
    first = coordinator.execute(
        _subject(),
        lambda: {
            "outcome": "findings",
            "findings": [
                {
                    "id": "finding-auth-boundary",
                    "severity": "high",
                    "summary": "Missing authority check",
                    "evidence": ["src/auth.py:42"],
                }
            ],
        },
    )
    delta = coordinator.execute(
        _subject("2" * 40), _clean, mode="delta", parent_key=first.key
    )
    assert delta.receipt["outcome"] == "findings"
    assert delta.receipt["findings_ledger"][0]["status"] == "open"
    assert "coordination_warning" in delta.receipt["review"]


def test_clean_delta_requires_and_records_explicit_resolution_refs(tmp_path: Path) -> None:
    coordinator = ReviewCoordinator(tmp_path / "auto-dev-review")
    first = coordinator.execute(
        _subject(),
        lambda: {
            "outcome": "findings",
            "findings": [
                {
                    "id": "finding-auth-boundary",
                    "severity": "high",
                    "summary": "Missing authority check",
                    "evidence": ["src/auth.py:42"],
                }
            ],
        },
    )
    delta = coordinator.execute(
        _subject("2" * 40),
        lambda: {"outcome": "clean", "resolution_refs": ["finding-auth-boundary"]},
        mode="delta",
        parent_key=first.key,
    )
    assert delta.receipt["outcome"] == "clean"
    assert delta.receipt["findings_ledger"][0]["status"] == "resolved"
    assert delta.receipt["findings_ledger"][0]["resolution"]["refs"]


def test_failed_or_unverified_provider_post_does_not_consume_cap(tmp_path: Path) -> None:
    coordinator = ReviewCoordinator(tmp_path / "auto-dev-review")
    coordinator.execute(_subject(), _clean)
    with pytest.raises(ReviewCoordinationError, match="verified readback"):
        coordinator.post_terminal(
            _subject(), lambda _marker, _receipt: {}, scrub_passed=True
        )
    posted = coordinator.post_terminal(
        _subject(),
        lambda _marker, _receipt: {"readback_verified": True, "comment_id": 7},
        scrub_passed=True,
    )
    assert posted.receipt["provider_post"]["status"] == "posted"
    assert posted.receipt["budget"]["provider_posts_used"] == 1


def test_provider_post_refuses_findings_unavailable_or_unscrubbed(tmp_path: Path) -> None:
    coordinator = ReviewCoordinator(tmp_path / "auto-dev-review")
    coordinator.execute(
        _subject(),
        lambda: {"outcome": "findings", "findings": ["Blocking finding"]},
    )
    with pytest.raises(ReviewCoordinationError, match="clean review"):
        coordinator.post_terminal(
            _subject(),
            lambda _marker, _receipt: {"readback_verified": True},
            scrub_passed=True,
        )
    clean_subject = _subject("2" * 40, policy="c" * 64)
    coordinator.execute(clean_subject, _clean)
    with pytest.raises(ReviewCoordinationError, match="scrub_passed"):
        coordinator.post_terminal(
            clean_subject,
            lambda _marker, _receipt: {"readback_verified": True},
            scrub_passed=False,
        )


def test_corrupt_family_receipt_is_quarantined_and_budget_fails_closed(
    tmp_path: Path,
) -> None:
    coordinator = ReviewCoordinator(tmp_path / "auto-dev-review")
    completed = coordinator.execute(_subject(), _clean)
    corrupt = json.loads(completed.receipt_path.read_text(encoding="utf-8"))
    corrupt["key"] = "0" * 64
    completed.receipt_path.write_text(json.dumps(corrupt), encoding="utf-8")
    with pytest.raises(ReviewCoordinationError, match="quarantined"):
        coordinator.execute(_subject("2" * 40), _clean, mode="delta")
    assert not completed.receipt_path.exists()
    assert list(coordinator.quarantine.glob("*.meta.json"))


def test_unidentifiable_corrupt_receipt_isolated_without_blocking_other_family(
    tmp_path: Path,
) -> None:
    coordinator = ReviewCoordinator(tmp_path / "auto-dev-review")
    affected = coordinator.execute(_subject(), _clean)
    affected.receipt_path.write_text("{broken", encoding="utf-8")
    unrelated = ReviewSubject(
        repository="acme/other",
        pull_request="99",
        base_branch="main",
        base_sha="a" * 40,
        head_sha="9" * 40,
        policy_fingerprint=POLICY,
    )
    unrelated_result = coordinator.execute(unrelated, _clean)
    assert unrelated_result.receipt["outcome"] == "clean"
    assert not affected.receipt_path.exists()
    assert list(coordinator.quarantine.glob("*.meta.json"))

    called = False

    def forbidden() -> dict[str, str]:
        nonlocal called
        called = True
        return _clean()

    with pytest.raises(ReviewCoordinationError, match="failed closed"):
        coordinator.execute(_subject(), forbidden)
    assert not called


def test_unparseable_receipt_tombstone_preserves_same_chain_budget(tmp_path: Path) -> None:
    coordinator = ReviewCoordinator(tmp_path / "auto-dev-review")
    completed = coordinator.execute(_subject(), _clean)
    completed.receipt_path.write_text("{broken", encoding="utf-8")
    called = False

    def forbidden() -> dict[str, str]:
        nonlocal called
        called = True
        return _clean()

    with pytest.raises(ReviewBudgetExceeded, match="full-review budget"):
        coordinator.execute(_subject("2" * 40), forbidden)
    assert not called
    metadata = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in coordinator.quarantine.glob("*.meta.json")
    ]
    assert metadata[0]["budget_consumed"] is True
    assert metadata[0]["mode"] == "full"
    assert metadata[0]["chain_key"] == completed.receipt["chain_key"]


def test_unindexed_unparseable_receipt_fails_all_budgets_closed(tmp_path: Path) -> None:
    coordinator = ReviewCoordinator(tmp_path / "auto-dev-review")
    unknown_key = "e" * 64
    coordinator.receipts.mkdir(parents=True)
    (coordinator.receipts / f"{unknown_key}.json").write_text(
        "{broken", encoding="utf-8"
    )
    called = False

    def forbidden() -> dict[str, str]:
        nonlocal called
        called = True
        return _clean()

    with pytest.raises(ReviewCoordinationError, match="all review budgets fail closed"):
        coordinator.execute(_subject(), forbidden)
    assert not called
    with pytest.raises(ReviewCoordinationError, match="failed closed"):
        coordinator.execute(_subject("2" * 40), forbidden)
    assert not called
    subject = _subject()
    coordinator.classify_quarantine_tombstone(
        unknown_key,
        family_key=review_family_key(subject),
        chain_key=review_chain_key(subject),
        mode="full",
        outcome="clean",
        approval_ref="approval:quarantine-classification",
    )
    with pytest.raises(ReviewBudgetExceeded, match="full-review budget"):
        coordinator.execute(_subject("2" * 40), forbidden)
    unrelated = ReviewSubject(
        repository="acme/unrelated",
        pull_request="100",
        base_branch="main",
        base_sha="a" * 40,
        head_sha="7" * 40,
        policy_fingerprint=POLICY,
    )
    assert coordinator.execute(unrelated, _clean).receipt["outcome"] == "clean"


def test_review_subject_requires_full_commit_shas() -> None:
    with pytest.raises(ReviewCoordinationError, match="full 40-hex"):
        _subject("1234567")


def test_mixed_case_revision_hex_canonicalizes_before_stable_key() -> None:
    lower = _subject(head="abcdef1234" * 4, policy="ab" * 32, base="cd" * 20)
    upper = _subject(
        head=("abcdef1234" * 4).upper(),
        policy=("ab" * 32).upper(),
        base=("cd" * 20).upper(),
    )
    assert stable_review_key(lower) == stable_review_key(upper)
    assert upper.head_sha == lower.head_sha
    assert upper.base_sha == lower.base_sha
    assert upper.policy_fingerprint == lower.policy_fingerprint


def test_precanonicalization_uppercase_receipt_remains_loadable(tmp_path: Path) -> None:
    coordinator = ReviewCoordinator(tmp_path / "auto-dev-review")
    completed = coordinator.execute(_subject(), _clean)
    legacy = json.loads(completed.receipt_path.read_text(encoding="utf-8"))
    legacy_subject = dict(legacy["subject"])
    for field in ("base_sha", "head_sha", "policy_fingerprint"):
        legacy_subject[field] = str(legacy_subject[field]).upper()

    def digest(value: dict[str, object]) -> str:
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()

    legacy_key = digest(legacy_subject)
    legacy_chain = dict(legacy_subject)
    legacy_chain.pop("head_sha")
    legacy_chain.pop("purpose")
    legacy["key"] = legacy_key
    legacy["chain_key"] = digest(legacy_chain)
    legacy["subject"] = legacy_subject
    legacy["provider_post"]["marker"] = provider_review_marker(legacy_key)
    legacy_path = coordinator.receipts / f"{legacy_key}.json"
    completed.receipt_path.unlink()
    legacy_path.write_text(
        json.dumps(legacy, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    loaded = load_review_receipt(legacy_path)
    assert loaded["key"] == legacy_key
    assert loaded["chain_key"] == review_chain_key(
        ReviewSubject.from_mapping(legacy_subject)
    )
    called = False

    def forbidden() -> dict[str, str]:
        nonlocal called
        called = True
        return _clean()

    reused = coordinator.execute(_subject(), forbidden)
    assert reused.reused
    assert reused.key == legacy_key
    assert not called


def test_entrypoint_purpose_aliases_produce_the_same_stable_key() -> None:
    crossreview = ReviewSubject(
        **{**_subject().__dict__, "purpose": canonical_review_purpose("finalize")}
    )
    opposing = ReviewSubject(
        **{
            **_subject().__dict__,
            "purpose": canonical_review_purpose("review_self:full_pr"),
        }
    )
    assert stable_review_key(crossreview) == stable_review_key(opposing)


def test_shared_root_rejects_disagreement_with_canonical_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    canonical = tmp_path / "canonical-os"
    monkeypatch.setenv("AGENTIC_OS_ROOT", str(canonical))
    assert shared_review_coordination_root(canonical) == (
        canonical / "state/review-coordination"
    )
    with pytest.raises(ReviewCoordinationError, match="disagrees with canonical"):
        shared_review_coordination_root(tmp_path / "second-os")


def test_purpose_cannot_bypass_chain_or_family_budgets(tmp_path: Path) -> None:
    coordinator = ReviewCoordinator(tmp_path / "auto-dev-review")
    first = coordinator.execute(_subject(), _clean)
    alternate = ReviewSubject(**{**first.receipt["subject"], "purpose": "finalize:wide"})
    assert review_family_key(alternate) == review_family_key(_subject())
    with pytest.raises(ReviewBudgetExceeded, match="full-review budget"):
        coordinator.execute(alternate, _clean)
    assert canonical_review_purpose("finalize:any-scope") == "review_self"
    assert shared_review_coordination_root(tmp_path) == tmp_path / "state/review-coordination"


def test_successful_unavailable_artifact_recovers_without_reviewer_rerun(
    tmp_path: Path,
) -> None:
    coordinator = ReviewCoordinator(tmp_path / "auto-dev-review")
    unavailable = coordinator.execute(
        _subject(),
        lambda: {
            "outcome": "unavailable",
            "exit_code": 0,
            "text": "Full review found a missing gate.",
            "scrub_passed": False,
        },
    )
    evidence = tmp_path / "review.txt"
    evidence.write_text("review evidence", encoding="utf-8")
    recovered = coordinator.recover_successful_unavailable(
        unavailable.receipt_path,
        {
            "findings": [
                {
                    "id": "finding-missing-gate",
                    "severity": "blocking",
                    "summary": "Missing gate",
                    "evidence": [str(evidence)],
                }
            ]
        },
        evidence_ref=str(evidence),
    )
    assert recovered.receipt["outcome"] == "findings"
    assert recovered.receipt["budget"]["full_reviews_used"] == 1
    assert Path(recovered.receipt["recovery"]["source_attempt_ref"]).is_file()


def test_all_advisory_findings_derive_immutable_same_head_clean_child(
    tmp_path: Path,
) -> None:
    coordinator = ReviewCoordinator(tmp_path / "auto-dev-review")
    response = """```json
[{"id":"F-advice","severity":"low","category":"tests","file":"tests/test_x.py","line":7,"title":"Clarify test name","detail":"The current assertion is sufficient.","suggested_fix":"Optionally rename it.","blocking":false}]
```
AGENTIC_OS_REVIEW_VERDICT: FINDINGS"""
    source = coordinator.execute(
        _subject(),
        lambda: {
            "outcome": "findings",
            "response": response,
            "findings": [
                {
                    "id": "F-advice",
                    "severity": "low",
                    "summary": "Clarify test name",
                    "evidence": ["tests/test_x.py:7 The current assertion is sufficient."],
                }
            ],
        },
    )
    original = source.receipt_path.read_bytes()
    evidence = tmp_path / "reviewer-response.md"
    evidence.write_text(response + "\n", encoding="utf-8")
    recovered = coordinator.derive_same_head_advisory_clean(
        source.receipt_path,
        evidence_path=evidence,
        findings=[
            {
                "id": "F-advice",
                "severity": "low",
                "summary": "Clarify test name",
                "evidence": ["tests/test_x.py:7 The current assertion is sufficient."],
                "blocking": False,
            }
        ],
    )

    assert source.receipt_path.read_bytes() == original
    assert recovered.receipt["mode"] == "advisory_recovery"
    assert recovered.receipt["outcome"] == "clean"
    assert recovered.receipt["parent_key"] == source.key
    assert recovered.receipt["findings_ledger"][0]["status"] == "resolved"
    assert assert_exact_head_review_receipt(
        recovered.receipt_path,
        head_sha=_subject().head_sha,
        repository="acme/widgets",
        pull_request="42",
        policy_fingerprint=POLICY,
    )["outcome"] == "clean"
    assert coordinator.derive_same_head_advisory_clean(
        source.receipt_path,
        evidence_path=evidence,
        findings=[
            {
                "id": "F-advice",
                "severity": "low",
                "summary": "Clarify test name",
                "evidence": ["tests/test_x.py:7 The current assertion is sufficient."],
                "blocking": False,
            }
        ],
    ).reused


def test_finalize_reuses_exact_head_and_refuses_drift(tmp_path: Path) -> None:
    coordinator = ReviewCoordinator(tmp_path / "auto-dev-review")
    completed = coordinator.execute(_subject(), _clean)

    finalized = coordinator.finalize(_subject())
    assert finalized.reused
    assert finalized.key == completed.key
    with pytest.raises(ReviewCoordinationError, match="exact-head"):
        coordinator.finalize(_subject("2" * 40))


def test_ready_gate_accepts_only_clean_exact_head_receipt(tmp_path: Path) -> None:
    completed = ReviewCoordinator(tmp_path / "auto-dev-review").execute(_subject(), _clean)

    payload = assert_exact_head_review_receipt(
        completed.receipt_path,
        head_sha=_subject().head_sha,
        repository="acme/widgets",
        pull_request="42",
        policy_fingerprint=POLICY,
    )
    assert payload["outcome"] == "clean"
    with pytest.raises(ReviewCoordinationError, match="head_sha"):
        assert_exact_head_review_receipt(completed.receipt_path, head_sha="2" * 40)


def test_pr19_replay_caps_paid_reviews_at_four(tmp_path: Path) -> None:
    fixture = json.loads(
        (Path(__file__).parent / "fixtures/auto_dev_review_pr19_replay.json").read_text(
            encoding="utf-8"
        )
    )
    coordinator = ReviewCoordinator(tmp_path / "auto-dev-review")
    review_calls = 0
    parent: str | None = None

    def review() -> dict[str, str]:
        nonlocal review_calls
        review_calls += 1
        return _clean()

    for attempt in fixture["attempts"]:
        subject = ReviewSubject(
            repository=fixture["repository"],
            pull_request=fixture["pull_request"],
            base_branch=fixture["base_branch"],
            base_sha=fixture["base_sha"],
            head_sha=attempt["head_sha"],
            policy_fingerprint=fixture["policy_fingerprint"],
            purpose="review_self",
        )
        try:
            result = coordinator.execute(
                subject,
                review,
                mode="full" if parent is None else "delta",
                parent_key=parent,
            )
        except ReviewBudgetExceeded:
            continue
        parent = result.key

    assert len(fixture["attempts"]) == 20
    assert len({row["head_sha"] for row in fixture["attempts"]}) == 19
    assert review_calls == 4


def _capped_findings_chain(coordinator: ReviewCoordinator) -> object:
    def findings() -> dict[str, object]:
        return {
            "outcome": "findings",
            "findings": [
                {
                    "id": "finding-capped-chain",
                    "severity": "blocking",
                    "summary": "Capped finding needs operator evidence",
                    "evidence": ["src/gate.py:42"],
                }
            ],
        }

    result = coordinator.execute(_subject("1" * 40), findings)
    for digit in ("2", "3", "4"):
        result = coordinator.execute(
            _subject(digit * 40), findings, mode="delta", parent_key=result.key
        )
    return result


def test_operator_resolution_cannot_bypass_uncapped_chain(tmp_path: Path) -> None:
    coordinator = ReviewCoordinator(tmp_path / "auto-dev-review")
    parent = coordinator.execute(
        _subject(),
        lambda: {"outcome": "findings", "findings": ["Needs repair"]},
    )
    new_head = "2" * 40
    with pytest.raises(ReviewCoordinationError, match="capped findings chain"):
        coordinator.resolve_capped_findings(
            _subject(new_head),
            parent_key=parent.key,
            approval_ref="approval:CC-422",
            test_evidence={"head_sha": new_head, "verified": True, "refs": ["test:1"]},
            ci_evidence={"head_sha": new_head, "verified": True, "refs": ["ci:1"]},
            resolutions={
                parent.receipt["findings_ledger"][0]["id"]: ["commit:repair"]
            },
        )


def test_operator_resolution_requires_exact_evidence_and_resolves_capped_chain(
    tmp_path: Path,
) -> None:
    coordinator = ReviewCoordinator(tmp_path / "auto-dev-review")
    parent = _capped_findings_chain(coordinator)
    new_head = "5" * 40
    with pytest.raises(ReviewCoordinationError, match="exact-head"):
        coordinator.resolve_capped_findings(
            _subject(new_head),
            parent_key=parent.key,
            approval_ref="approval:CC-422",
            test_evidence={"head_sha": "6" * 40, "verified": True, "refs": ["test:1"]},
            ci_evidence={"head_sha": new_head, "verified": True, "refs": ["ci:1"]},
            resolutions={"finding-capped-chain": ["commit:repair"]},
        )
    with pytest.raises(ReviewCoordinationError, match="every and only"):
        coordinator.resolve_capped_findings(
            _subject(new_head),
            parent_key=parent.key,
            approval_ref="approval:CC-422",
            test_evidence={"head_sha": new_head, "verified": True, "refs": ["test:1"]},
            ci_evidence={"head_sha": new_head, "verified": True, "refs": ["ci:1"]},
            resolutions={"wrong-finding": ["commit:repair"]},
        )

    resolved = coordinator.resolve_capped_findings(
        _subject(new_head),
        parent_key=parent.key,
        approval_ref="approval:CC-422",
        test_evidence={"head_sha": new_head, "verified": True, "refs": ["test:1"]},
        ci_evidence={"head_sha": new_head, "verified": True, "refs": ["ci:1"]},
        resolutions={
            "finding-capped-chain": {
                "refs": ["commit:repair", "test:1", "ci:1"],
                "summary": "Repair verified at the exact new head.",
            }
        },
    )
    assert resolved.receipt["operator_override"] is True
    assert resolved.receipt["mode"] == "operator_resolution"
    assert resolved.receipt["outcome"] == "clean"
    assert resolved.receipt["budget"]["full_reviews_used"] == 1
    assert resolved.receipt["budget"]["delta_reviews_used"] == 3
    assert all(
        row["status"] == "resolved" for row in resolved.receipt["findings_ledger"]
    )
    schema = json.loads(
        (Path(__file__).parents[1] / "schemas/auto-dev-review-receipt.schema.json").read_text(
            encoding="utf-8"
        )
    )
    jsonschema.validate(resolved.receipt, schema)
    provider_called = False

    def forbidden_post(_marker: str, _receipt: dict[str, object]) -> dict[str, object]:
        nonlocal provider_called
        provider_called = True
        return {"readback_verified": True}

    with pytest.raises(ReviewCoordinationError, match="cannot be posted"):
        coordinator.post_terminal(
            _subject(new_head), forbidden_post, scrub_passed=True
        )
    assert not provider_called


def test_receipt_schema_is_registered_strict_and_accepts_generated_receipt(
    tmp_path: Path,
) -> None:
    completed = ReviewCoordinator(tmp_path / "auto-dev-review").execute(_subject(), _clean)
    repository = Path(__file__).parents[1]
    schema_path = repository / "schemas/auto-dev-review-receipt.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    receipt = json.loads(completed.receipt_path.read_text(encoding="utf-8"))

    jsonschema.validate(receipt, schema)
    assert SCHEMA_TARGETS[schema_path.name] == [
        "**/work-items/*/*/artifacts/auto-dev-review/receipts/*.json"
    ]
    receipt["unexpected"] = True
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(receipt, schema)
