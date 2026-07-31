"""Shared tracker adapter contracts for Auto Dev v2."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any, Protocol


class TrackerError(Exception):
    """Raised when a tracker adapter cannot satisfy the normalized contract."""


@dataclass(frozen=True)
class WorkItem:
    """Normalized tracker work item consumed by the Auto Dev state machine."""

    tracker_kind: str
    tracker_id: str
    url: str | None
    title: str
    description: str
    acceptance_criteria: list[str]
    workflow_state: str
    assignee: str | None = None
    labels: list[str] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)

    def require_acceptance_criteria(self) -> None:
        if not self.acceptance_criteria:
            raise TrackerError("acceptance criteria are missing or unparseable")


class TrackerAdapter(Protocol):
    """Minimal adapter behavior required before live provider integration."""

    kind: str

    def fetch(self, tracker_id: str) -> WorkItem:
        """Fetch and normalize one work item."""

    def claim(self, tracker_id: str, owner: str, label: str, in_progress_state: str) -> WorkItem:
        """Claim by assignee+label+state and return the re-read item."""

    def transition(self, tracker_id: str, state: str, note: str | None = None) -> WorkItem:
        """Transition a work item by configured workflow state."""


def load_fixture(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TrackerError(f"{path} must contain a JSON object")
    return payload


def parse_acceptance_criteria(text: str) -> list[str]:
    """Parse common AC bullets from tracker descriptions without inventing them."""

    ac: list[str] = []
    in_ac_section = False
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        lower = line.lower().rstrip(":")
        if lower in {"acceptance criteria", "acceptance", "ac"}:
            in_ac_section = True
            continue
        if in_ac_section and line.startswith(("-", "*")):
            ac.append(line[1:].strip())
            continue
        if in_ac_section and line[:2].isdigit() and "." in line[:4]:
            ac.append(line.split(".", 1)[1].strip())
            continue
        if in_ac_section and line.startswith("#"):
            break
    return [item for item in ac if item]


class StructuredFixtureAdapter:
    """Provider-neutral mutable fixture used only by offline tracker tests."""

    def __init__(self, payload: dict[str, Any], *, kind: str):
        self.payload = payload
        self.kind = kind

    @classmethod
    def from_file(cls, path: Path, *, kind: str) -> "StructuredFixtureAdapter":
        return cls(load_fixture(path), kind=kind)

    def fetch(self, tracker_id: str) -> WorkItem:
        identifier = self.payload.get("identifier")
        if identifier != tracker_id:
            raise TrackerError(
                f"fixture identifier {identifier} does not match requested {tracker_id}"
            )
        description = str(self.payload.get("description") or "")
        state = self.payload.get("state") or {}
        item = WorkItem(
            tracker_kind=self.kind,
            tracker_id=str(identifier),
            url=self.payload.get("url"),
            title=str(self.payload.get("title") or identifier),
            description=description,
            acceptance_criteria=parse_acceptance_criteria(description),
            workflow_state=str(state.get("type") or state.get("name") or "unknown"),
            assignee=(self.payload.get("assignee") or {}).get("email"),
            labels=[
                label.get("name")
                for label in self.payload.get("labels", {}).get("nodes", [])
            ],
            raw=self.payload,
        )
        item.require_acceptance_criteria()
        return item

    def claim(
        self, tracker_id: str, owner: str, label: str, in_progress_state: str
    ) -> WorkItem:
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

    def transition(
        self, tracker_id: str, state: str, note: str | None = None
    ) -> WorkItem:
        self.fetch(tracker_id)
        payload = dict(self.payload)
        payload["state"] = {"type": state}
        if note:
            payload.setdefault("comments", []).append({"body": note})
        self.payload = payload
        return self.fetch(tracker_id)
