"""Read-only generalized adjudication queue over the existing state plane.

AGE-49 deliberately defines a domain contract and read model only.  It does
not register workers, replay tasks, or alter the state schema.  Producers can
use :func:`review_payload` with the established ``run_queue`` interface; the
queue itself remains the authority for lifecycle, priority, and leases.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Iterable, Mapping

from .state import db as state_db
from .state import queue as state_queue


SCHEMA_VERSION = "agentic-os-review-queue/v1"
REVIEW_KINDS = ("finding", "pull_request", "proposal")
QUEUE_KINDS = {kind: f"review.{kind}.v1" for kind in REVIEW_KINDS}

# The existing Team PR task is a valid pull-request review source.  It remains
# owned by its current worker and durability work; this read-model adapter does
# not claim, change, or replay it.
LEGACY_QUEUE_KINDS = {"los.team_pr.ai_review.v1": "pull_request"}


class ReviewQueueContractError(ValueError):
    """Raised when a producer supplies an invalid generalized-review payload."""


def queue_kind(review_kind: str) -> str:
    """Return the state-plane ``run_queue.kind`` for one review subject kind."""

    try:
        return QUEUE_KINDS[review_kind]
    except KeyError as exc:
        raise ReviewQueueContractError(f"unsupported review kind: {review_kind!r}") from exc


def review_payload(
    review_kind: str,
    *,
    title: str,
    summary: str,
    url: str | None = None,
    subject: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the versioned payload accepted by the generalized review queue.

    This is intentionally a pure contract helper.  Callers that are authorized
    to create work submit the result through the existing state-plane queue;
    this module never performs provider work or task delivery itself.
    """

    queue_kind(review_kind)
    if not isinstance(title, str) or not title.strip():
        raise ReviewQueueContractError("review title must be a non-empty string")
    if not isinstance(summary, str) or not summary.strip():
        raise ReviewQueueContractError("review summary must be a non-empty string")
    if url is not None and (not isinstance(url, str) or not url.strip()):
        raise ReviewQueueContractError("review url must be a non-empty string when supplied")
    if subject is not None and (not isinstance(subject, str) or not subject.strip()):
        raise ReviewQueueContractError("review subject must be a non-empty string when supplied")
    if metadata is not None and not isinstance(metadata, Mapping):
        raise ReviewQueueContractError("review metadata must be a mapping when supplied")
    return {
        "review": {
            "schema_version": SCHEMA_VERSION,
            "kind": review_kind,
            "title": title.strip(),
            "summary": summary.strip(),
            **({"url": url.strip()} if url else {}),
            **({"subject": subject.strip()} if subject else {}),
            **({"metadata": dict(metadata)} if metadata else {}),
        }
    }


def _review_kind(row: Mapping[str, Any]) -> str | None:
    kind = str(row.get("kind") or "")
    for review_kind, registered_kind in QUEUE_KINDS.items():
        if kind == registered_kind:
            return review_kind
    return LEGACY_QUEUE_KINDS.get(kind)


def _legacy_pull_request_details(payload: Mapping[str, Any], ref: str | None) -> tuple[str, str, str | None, str | None]:
    repository = str(payload.get("repository") or "").strip()
    number = payload.get("pull_request")
    suffix = f" #{number}" if number is not None else ""
    title = f"Review {repository}{suffix}".strip() if repository else "Review pull request"
    subject = f"{repository}{suffix}".strip() or ref
    summary = str(payload.get("summary") or "Queued pull-request review.").strip()
    url = str(payload.get("pull_request_url") or "").strip() or None
    return title, summary, url, subject


def review_item(row: Mapping[str, Any]) -> dict[str, Any] | None:
    """Normalize one existing state-plane row for the cockpit/API read model."""

    review_kind = _review_kind(row)
    if review_kind is None:
        return None
    payload = row.get("payload")
    payload = payload if isinstance(payload, Mapping) else {}
    contract = payload.get("review")
    contract = contract if isinstance(contract, Mapping) else {}
    if str(row.get("kind")) in LEGACY_QUEUE_KINDS:
        title, summary, url, subject = _legacy_pull_request_details(payload, row.get("ref"))
    else:
        title = str(contract.get("title") or "").strip() or f"Review {review_kind.replace('_', ' ')}"
        summary = str(contract.get("summary") or "").strip() or "Queued for adjudication."
        url = str(contract.get("url") or "").strip() or None
        subject = str(contract.get("subject") or row.get("ref") or "").strip() or None
    item_id = str(row.get("id") or "")
    return {
        "id": f"review-queue:{item_id}",
        "queue_item_id": item_id,
        "title": title,
        "summary": summary,
        "detail": f"{review_kind.replace('_', ' ')} adjudication is {row.get('status') or 'unknown'}.",
        "status": str(row.get("status") or "unknown"),
        "review_kind": review_kind,
        "subject": subject,
        "url": url,
        "source": f"state-plane:run_queue/{item_id}",
        "updated_at": str(row.get("updated_at") or row.get("created_at") or ""),
        "created_at": str(row.get("created_at") or ""),
        "priority": int(row.get("priority") or 0),
        "approval_state": str(row.get("approval_state") or "not_required"),
        "tags": ["review-queue", review_kind, str(row.get("status") or "unknown")],
    }


def list_review_queue(
    connection: sqlite3.Connection,
    *,
    statuses: Iterable[str] | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Read generalized review work via the existing state queue query API."""

    allowed_statuses = set(statuses or ())
    rows: dict[str, dict[str, Any]] = {}
    for registered_kind in (*QUEUE_KINDS.values(), *LEGACY_QUEUE_KINDS):
        for row in state_queue.query(connection, kind=registered_kind, limit=max(1, limit)):
            if allowed_statuses and row.get("status") not in allowed_statuses:
                continue
            item = review_item(row)
            if item is not None:
                rows[item["id"]] = item
    return sorted(rows.values(), key=lambda item: (-item["priority"], item["created_at"], item["id"]))[: max(0, limit)]


def read_review_queue(root: str | Path, *, statuses: Iterable[str] | None = None, limit: int = 100) -> list[dict[str, Any]]:
    """Read the installed state plane without creating a database or changing it."""

    db_path = state_db.default_db_path(root)
    if not db_path.is_file():
        return []
    connection = sqlite3.connect(f"file:{db_path.resolve()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        return list_review_queue(connection, statuses=statuses, limit=limit)
    finally:
        connection.close()
