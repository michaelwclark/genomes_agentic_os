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
