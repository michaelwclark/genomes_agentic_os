"""Fixture-backed Jira adapter for Auto Dev v2 contract tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any

try:
    from .base import TrackerError, WorkItem, load_fixture, parse_acceptance_criteria
except ImportError:  # pragma: no cover - allows direct script execution.
    from base import TrackerError, WorkItem, load_fixture, parse_acceptance_criteria


class JiraFixtureAdapter:
    kind = "jira"

    def __init__(self, payload: dict[str, Any]):
        self.payload = payload

    @classmethod
    def from_file(cls, path: Path) -> "JiraFixtureAdapter":
        return cls(load_fixture(path))

    def fetch(self, tracker_id: str) -> WorkItem:
        key = self.payload.get("key")
        if key != tracker_id:
            raise TrackerError(f"fixture key {key} does not match requested {tracker_id}")
        fields = self.payload.get("fields") or {}
        description = str(fields.get("description") or "")
        item = WorkItem(
            tracker_kind="jira",
            tracker_id=str(key),
            url=self.payload.get("url"),
            title=str(fields.get("summary") or key),
            description=description,
            acceptance_criteria=parse_acceptance_criteria(description),
            workflow_state=str((fields.get("status") or {}).get("name") or "unknown"),
            assignee=(fields.get("assignee") or {}).get("name"),
            labels=list(fields.get("labels") or []),
            raw=self.payload,
        )
        item.require_acceptance_criteria()
        return item

    def claim(self, tracker_id: str, owner: str, label: str, in_progress_state: str) -> WorkItem:
        item = self.fetch(tracker_id)
        labels = set(item.labels)
        labels.add(label)
        claimed = dict(self.payload)
        fields = dict(claimed.get("fields") or {})
        fields["assignee"] = {"name": owner}
        fields["labels"] = sorted(labels)
        fields["status"] = {"name": in_progress_state}
        claimed["fields"] = fields
        self.payload = claimed
        reread = self.fetch(tracker_id)
        if reread.assignee != owner or label not in reread.labels:
            raise TrackerError("claim re-read did not confirm assignee+label")
        return reread

    def transition(self, tracker_id: str, state: str, note: str | None = None) -> WorkItem:
        self.fetch(tracker_id)
        updated = dict(self.payload)
        fields = dict(updated.get("fields") or {})
        fields["status"] = {"name": state}
        updated["fields"] = fields
        if note:
            updated.setdefault("comments", []).append({"body": note})
        self.payload = updated
        return self.fetch(tracker_id)

