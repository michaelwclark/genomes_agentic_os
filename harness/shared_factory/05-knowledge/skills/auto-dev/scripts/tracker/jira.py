"""Fixture and shared-bridge Jira adapters for Auto Dev v2."""

from __future__ import annotations

import hashlib
import os
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from genomes_agentic_os.jira_bridge import JiraBridgeClient

try:
    from .base import TrackerError, WorkItem, load_fixture, parse_acceptance_criteria
except ImportError:  # pragma: no cover - allows direct script execution.
    from base import TrackerError, WorkItem, load_fixture, parse_acceptance_criteria


class JiraFixtureAdapter:
    kind = "jira"

    def __init__(self, payload: dict[str, Any]):
        self.payload = payload

    @classmethod
    def from_file(cls, path: Path) -> JiraFixtureAdapter:
        return cls(load_fixture(path))

    def fetch(self, tracker_id: str) -> WorkItem:
        key = self.payload.get("key")
        if key != tracker_id:
            raise TrackerError(
                f"fixture key {key} does not match requested {tracker_id}"
            )
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

    def claim(
        self, tracker_id: str, owner: str, label: str, in_progress_state: str
    ) -> WorkItem:
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

    def transition(
        self, tracker_id: str, state: str, note: str | None = None
    ) -> WorkItem:
        self.fetch(tracker_id)
        updated = dict(self.payload)
        fields = dict(updated.get("fields") or {})
        fields["status"] = {"name": state}
        updated["fields"] = fields
        if note:
            updated.setdefault("comments", []).append({"body": note})
        self.payload = updated
        return self.fetch(tracker_id)


def _adf_text(value: Any) -> str:
    if not isinstance(value, Mapping):
        return str(value or "")
    parts: list[str] = []
    text = value.get("text")
    if isinstance(text, str):
        parts.append(text)
    content = value.get("content")
    if isinstance(content, list):
        for child in content:
            rendered = _adf_text(child).strip()
            if rendered:
                parts.append(rendered)
    return "\n".join(parts)


class JiraBridgeAdapter:
    """Live Auto-Dev tracker adapter over the reviewed shared Jira bridge."""

    kind = "jira"

    def __init__(self, client: JiraBridgeClient, identity: Mapping[str, str]):
        self.client = client
        self.identity = {key: str(value) for key, value in identity.items() if value}

    @classmethod
    def from_environment(
        cls, environ: Mapping[str, str] | None = None
    ) -> JiraBridgeAdapter:
        try:
            from genomes_agentic_os.jira_bridge import (
                JiraBridgeClient,
                JiraBridgeError,
                auth_from_environment,
                command_from_environment,
            )
        except ImportError as exc:
            raise TrackerError(
                "live Jira tracking requires an installed Agentic OS shared bridge"
            ) from exc
        values = os.environ if environ is None else environ
        command = command_from_environment(values)
        base_url = values.get("JIRA_BASE_URL", "").strip()
        identity = {
            "siteUrl": values.get("JIRA_SITE_URL", "").strip(),
            "projectKey": values.get("JIRA_PROJECT_KEY", "").strip(),
            "issueTypeId": (
                values.get("JIRA_ISSUE_TYPE_ID")
                or values.get("JIRA_DEFAULT_ISSUE_TYPE_ID")
                or ""
            ).strip(),
            "cloudId": values.get("JIRA_CLOUD_ID", "").strip(),
            "accountId": values.get("JIRA_ACCOUNT_ID", "").strip(),
        }
        if not command or not base_url:
            raise TrackerError("live Jira bridge command and base URL are required")
        if not all(
            identity.get(key) for key in ("siteUrl", "projectKey", "issueTypeId")
        ):
            raise TrackerError(
                "live Jira site, project, and issue-type identity are required"
            )
        try:
            auth = auth_from_environment(values)
        except JiraBridgeError as exc:
            raise TrackerError(str(exc)) from exc
        return cls(JiraBridgeClient(command, base_url, auth), identity)

    def _request(self, operation: str, args: Mapping[str, Any]) -> Any:
        try:
            return self.client.request(operation, args)
        except RuntimeError as exc:
            code = str(getattr(exc, "code", "BRIDGE_OPERATION_FAILED"))
            raise TrackerError(f"Jira bridge {code}: {exc}") from exc

    def _preflight(self, tracker_id: str) -> None:
        project = tracker_id.partition("-")[0]
        if project != self.identity.get("projectKey"):
            raise TrackerError("tracker key does not match the configured Jira project")
        result = self._request("preflightIdentity", self.identity)
        if not isinstance(result, Mapping):
            raise TrackerError("Jira identity preflight returned invalid data")

    @staticmethod
    def _work_item(issue: Mapping[str, Any]) -> WorkItem:
        key = str(issue.get("key") or "").strip()
        fields = issue.get("fields") if isinstance(issue.get("fields"), Mapping) else {}
        status = issue.get("status") if isinstance(issue.get("status"), Mapping) else {}
        assignee = (
            fields.get("assignee")
            if isinstance(fields.get("assignee"), Mapping)
            else {}
        )
        labels = fields.get("labels") if isinstance(fields.get("labels"), list) else []
        description = _adf_text(issue.get("description"))
        return WorkItem(
            tracker_kind="jira",
            tracker_id=key,
            url=str(issue.get("url") or "") or None,
            title=str(issue.get("summary") or key),
            description=description,
            acceptance_criteria=parse_acceptance_criteria(description),
            workflow_state=str(status.get("name") or "unknown"),
            assignee=str(assignee.get("accountId") or assignee.get("displayName") or "")
            or None,
            labels=[str(label) for label in labels],
            raw=dict(issue),
        )

    def fetch(self, tracker_id: str) -> WorkItem:
        issue = self._request(
            "getIssue", {"key": tracker_id, "fields": ["assignee", "labels"]}
        )
        if not isinstance(issue, Mapping) or issue.get("key") != tracker_id:
            raise TrackerError(
                "Jira issue readback did not match the requested tracker key"
            )
        item = self._work_item(issue)
        item.require_acceptance_criteria()
        return item

    def _transition_if_needed(self, item: WorkItem, state: str) -> None:
        if item.workflow_state == state:
            return
        transitions = self._request("listTransitions", {"key": item.tracker_id})
        if not isinstance(transitions, list):
            raise TrackerError("Jira transitions read returned invalid data")
        matches = [
            transition
            for transition in transitions
            if isinstance(transition, Mapping)
            and (
                transition.get("name") == state
                or (
                    isinstance(transition.get("destination"), Mapping)
                    and transition["destination"].get("name") == state
                )
            )
        ]
        if len(matches) != 1 or not matches[0].get("id"):
            raise TrackerError("Jira workflow state did not resolve to one transition")
        self._request(
            "transitionIssue",
            {"key": item.tracker_id, "transitionId": str(matches[0]["id"])},
        )

    def claim(
        self, tracker_id: str, owner: str, label: str, in_progress_state: str
    ) -> WorkItem:
        self._preflight(tracker_id)
        current = self.fetch(tracker_id)
        labels = sorted({*current.labels, label})
        self._request(
            "updateIssue",
            {
                "key": tracker_id,
                "input": {
                    "fields": {
                        "assignee": {"accountId": owner},
                        "labels": labels,
                    }
                },
            },
        )
        self._transition_if_needed(current, in_progress_state)
        reread = self.fetch(tracker_id)
        if reread.assignee != owner or label not in reread.labels:
            raise TrackerError("claim re-read did not confirm assignee+label")
        if reread.workflow_state != in_progress_state:
            raise TrackerError("claim re-read did not confirm workflow state")
        return reread

    def transition(
        self, tracker_id: str, state: str, note: str | None = None
    ) -> WorkItem:
        self._preflight(tracker_id)
        current = self.fetch(tracker_id)
        self._transition_if_needed(current, state)
        if note:
            marker = (
                "agentic-os:auto-dev:"
                + hashlib.sha256(f"{tracker_id}:{state}:{note}".encode()).hexdigest()[
                    :16
                ]
            )
            body = {
                "version": 1,
                "type": "doc",
                "content": [
                    {
                        "type": "paragraph",
                        "content": [{"type": "text", "text": note}],
                    }
                ],
            }
            body["content"].append(
                {"type": "paragraph", "content": [{"type": "text", "text": marker}]}
            )
            self._request(
                "addComment",
                {
                    "key": tracker_id,
                    "input": {"body": body, "reconciliationMarker": marker},
                },
            )
        reread = self.fetch(tracker_id)
        if reread.workflow_state != state:
            raise TrackerError("transition re-read did not confirm workflow state")
        return reread
