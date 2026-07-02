"""Fixture-backed Linear adapter for Auto Dev v2 contract tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any

try:
    from .base import TrackerError, WorkItem, load_fixture, parse_acceptance_criteria
except ImportError:  # pragma: no cover
    from base import TrackerError, WorkItem, load_fixture, parse_acceptance_criteria


class LinearFixtureAdapter:
    kind = "linear"

    def __init__(self, payload: dict[str, Any]):
        self.payload = payload

    @classmethod
    def from_file(cls, path: Path) -> "LinearFixtureAdapter":
        return cls(load_fixture(path))

    def fetch(self, tracker_id: str) -> WorkItem:
        identifier = self.payload.get("identifier")
        if identifier != tracker_id:
            raise TrackerError(f"fixture identifier {identifier} does not match requested {tracker_id}")
        description = str(self.payload.get("description") or "")
        state = self.payload.get("state") or {}
        item = WorkItem(
            tracker_kind="linear",
            tracker_id=str(identifier),
            url=self.payload.get("url"),
            title=str(self.payload.get("title") or identifier),
            description=description,
            acceptance_criteria=parse_acceptance_criteria(description),
            workflow_state=str(state.get("type") or state.get("name") or "unknown"),
            assignee=(self.payload.get("assignee") or {}).get("email"),
            labels=[label.get("name") for label in self.payload.get("labels", {}).get("nodes", [])],
            raw=self.payload,
        )
        item.require_acceptance_criteria()
        return item

    def claim(self, tracker_id: str, owner: str, label: str, in_progress_state: str) -> WorkItem:
        self.fetch(tracker_id)
        payload = dict(self.payload)
        labels = list(payload.get("labels", {}).get("nodes", []))
        if label not in [entry.get("name") for entry in labels]:
            labels.append({"name": label})
        payload["labels"] = {"nodes": labels}
        payload["assignee"] = {"email": owner}
        payload["state"] = {"type": in_progress_state}
        self.payload = payload
        reread = self.fetch(tracker_id)
        if reread.assignee != owner or label not in reread.labels:
            raise TrackerError("claim re-read did not confirm assignee+label")
        return reread

    def transition(self, tracker_id: str, state: str, note: str | None = None) -> WorkItem:
        self.fetch(tracker_id)
        payload = dict(self.payload)
        payload["state"] = {"type": state}
        if note:
            payload.setdefault("comments", []).append({"body": note})
        self.payload = payload
        return self.fetch(tracker_id)

