from __future__ import annotations

import pytest

from genomes_agentic_os.review_queue import (
    ReviewQueueContractError,
    list_review_queue,
    queue_kind,
    read_review_queue,
    review_payload,
)
from genomes_agentic_os.state import db, queue


def test_contract_builds_versioned_payload_for_each_review_subject() -> None:
    for review_kind in ("finding", "pull_request", "proposal"):
        payload = review_payload(
            review_kind,
            title=f"Review {review_kind}",
            summary="A bounded adjudication request.",
            subject="AGE-49",
            metadata={"source": "test"},
        )
        assert queue_kind(review_kind) == f"review.{review_kind}.v1"
        assert payload["review"] == {
            "schema_version": "agentic-os-review-queue/v1",
            "kind": review_kind,
            "title": f"Review {review_kind}",
            "summary": "A bounded adjudication request.",
            "subject": "AGE-49",
            "metadata": {"source": "test"},
        }


def test_contract_rejects_unknown_or_incomplete_review_requests() -> None:
    with pytest.raises(ReviewQueueContractError, match="unsupported"):
        queue_kind("behavior_validation")
    with pytest.raises(ReviewQueueContractError, match="title"):
        review_payload("finding", title="", summary="Needs a decision.")


def test_read_model_uses_existing_queue_rows_and_keeps_legacy_prs_visible() -> None:
    connection = db.connect()
    try:
        finding = queue.enqueue(
            connection,
            id="finding-1",
            kind=queue_kind("finding"),
            priority=7,
            payload=review_payload("finding", title="Resolve retry gap", summary="A retry finding needs adjudication."),
        )
        queue.enqueue(
            connection,
            id="proposal-1",
            kind=queue_kind("proposal"),
            status="approval-needed",
            payload=review_payload("proposal", title="Adopt queue policy", summary="A policy proposal needs approval."),
        )
        queue.enqueue(
            connection,
            id="legacy-pr-1",
            kind="los.team_pr.ai_review.v1",
            payload={"repository": "example/repo", "pull_request": 42, "pull_request_url": "https://example.test/pr/42"},
        )
        queue.enqueue(connection, id="unrelated", kind="schedule")

        items = list_review_queue(connection)
    finally:
        connection.close()

    assert [item["queue_item_id"] for item in items] == [finding["id"], "legacy-pr-1", "proposal-1"]
    assert {item["review_kind"] for item in items} == {"finding", "pull_request", "proposal"}
    legacy = next(item for item in items if item["queue_item_id"] == "legacy-pr-1")
    assert legacy["title"] == "Review example/repo #42"
    assert legacy["url"] == "https://example.test/pr/42"


def test_root_read_model_does_not_create_a_missing_state_database(tmp_path) -> None:
    root = tmp_path / "agentic_os"
    root.mkdir()
    path = db.default_db_path(root)

    assert read_review_queue(root) == []
    assert not path.exists()
