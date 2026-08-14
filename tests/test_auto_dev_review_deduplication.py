"""Regression tests for CC-422's paid-review single-flight contract."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
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
    provider_review_marker,
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
    completed.receipt_path.write_text("{broken", encoding="utf-8")
    with pytest.raises(ReviewCoordinationError, match="quarantined"):
        coordinator.execute(_subject("2" * 40), _clean, mode="delta")
    assert list((coordinator.root / "quarantine").glob("*.json"))


def test_review_subject_requires_full_commit_shas() -> None:
    with pytest.raises(ReviewCoordinationError, match="full 40-hex"):
        _subject("1234567")


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
