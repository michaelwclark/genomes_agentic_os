"""Hybrid Jira/Linear fixture adapter.

Jira remains the spec and company workflow source; Linear is a personal mirror.
"""

from __future__ import annotations

try:
    from .base import WorkItem
    from .jira import JiraFixtureAdapter
    from .linear import LinearFixtureAdapter
except ImportError:  # pragma: no cover
    from base import WorkItem
    from jira import JiraFixtureAdapter
    from linear import LinearFixtureAdapter


class HybridFixtureAdapter:
    kind = "hybrid"

    def __init__(self, jira: JiraFixtureAdapter, linear: LinearFixtureAdapter):
        self.jira = jira
        self.linear = linear

    def fetch(self, tracker_id: str) -> WorkItem:
        return self.jira.fetch(tracker_id)

    def claim(self, tracker_id: str, owner: str, label: str, in_progress_state: str) -> WorkItem:
        return self.jira.claim(tracker_id, owner, label, in_progress_state)

    def transition(self, tracker_id: str, state: str, note: str | None = None) -> WorkItem:
        return self.jira.transition(tracker_id, state, note)

    def mirror_linear(self, linear_id: str, state: str) -> WorkItem:
        return self.linear.transition(linear_id, state, note=None)
