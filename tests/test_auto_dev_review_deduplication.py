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
    provider_review_marker,
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

    first = coordinator.execute(_subject(), review, provider_post=post)
    second = coordinator.execute(_subject(), review, provider_post=post)

    assert review_calls == 1
    assert post_calls == 1
    assert first.receipt["provider_post"]["status"] == "posted"
    assert second.reused


def test_provider_post_budget_fails_before_new_review_call(tmp_path: Path) -> None:
    coordinator = ReviewCoordinator(tmp_path / "auto-dev-review")
    first = coordinator.execute(
        _subject(), _clean, provider_post=lambda _marker, _receipt: {"readback_verified": True}
    )
    called = False

    def forbidden() -> dict[str, str]:
        nonlocal called
        called = True
        return _clean()

    with pytest.raises(ReviewBudgetExceeded, match="provider-post budget"):
        coordinator.execute(
            _subject("2" * 40),
            forbidden,
            mode="delta",
            parent_key=first.key,
            provider_post=lambda _marker, _receipt: {},
        )
    assert not called


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
