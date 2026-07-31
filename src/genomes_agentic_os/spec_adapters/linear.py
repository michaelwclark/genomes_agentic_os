"""Linear Spec adapter composed over the shared Linear subprocess port."""

from __future__ import annotations

import os
from typing import Any, Mapping

from ..linear_bridge import (
    LinearBridgeClient,
    LinearBridgeError,
    auth_from_environment,
    command_from_environment,
)
from .base import GuardedProviderAdapter, SpecTransport
from ..spec_engine import AdapterReceipt, Spec


def _description(spec: Mapping[str, Any], marker: str) -> str:
    parts = [str(spec.get("summary") or "").strip()]
    criteria = spec.get("acceptance_criteria")
    if isinstance(criteria, list) and criteria:
        parts.append("Acceptance criteria:\n" + "\n".join(f"- {item}" for item in criteria))
    parts.append(marker)
    return "\n\n".join(part for part in parts if part)


def _has_exact_marker(description: object, marker: str) -> bool:
    return any(line.strip() == marker for line in str(description or "").splitlines())


class LinearBridgeSpecTransport:
    """Compose the guarded Spec workflow onto the shared Linear port."""

    def __init__(self, client: LinearBridgeClient):
        self.client = client

    @staticmethod
    def _target(payload: Mapping[str, Any]) -> dict[str, Any]:
        target = payload.get("target")
        return dict(target) if isinstance(target, Mapping) else {}

    @staticmethod
    def _team(target: Mapping[str, Any]) -> str:
        team_id = str(target.get("team_id") or target.get("team") or "").strip()
        if not team_id:
            raise LinearBridgeError("CONFIGURATION_ERROR", "Linear target team is not configured")
        return team_id

    @staticmethod
    def _provider_record(issue: Mapping[str, Any]) -> dict[str, Any]:
        provider_id = str(issue.get("id") or "").strip()
        if not provider_id:
            raise LinearBridgeError("BRIDGE_INVALID_RESPONSE", "Linear issue readback has no id")
        return {"ok": True, "provider_id": provider_id, "id": provider_id, "url": issue.get("url")}

    def _state_id(self, team_id: str, name: object) -> str | None:
        if not name:
            return None
        states = self.client.request("listWorkflowStates", {"teamId": team_id})
        matches = [
            state for state in states
            if isinstance(state, Mapping) and str(state.get("name", "")).lower() == str(name).lower()
        ]
        if len(matches) != 1:
            raise LinearBridgeError("CONFIGURATION_ERROR", "Linear target state is missing or ambiguous")
        return str(matches[0]["id"])

    def _blocked_label_id(self, team_id: str) -> str:
        labels = self.client.request("listLabels", {"teamId": team_id})
        matches = [
            label
            for label in labels
            if isinstance(label, Mapping)
            and label.get("teamId") in (None, team_id)
            and str(label.get("name", "")).lower() == "blocked"
        ]
        if len(matches) > 1:
            raise LinearBridgeError(
                "CONFLICT", "Linear blocked label is ambiguous for the target team"
            )
        if matches:
            return str(matches[0]["id"])
        created = self.client.request(
            "createLabel",
            {"input": {"name": "blocked", "teamId": team_id, "color": "#EB5757"}},
        )
        if not isinstance(created, Mapping) or not created.get("id"):
            raise LinearBridgeError(
                "BRIDGE_INVALID_RESPONSE", "Linear blocked label creation returned no id"
            )
        return str(created["id"])

    def request(self, action: str, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        target = self._target(payload)
        team_id = self._team(target)
        if action == "verify_target":
            identity = self.client.request(
                "preflightIdentity",
                {
                    "teamId": team_id,
                    **({"workspaceId": str(target["workspace_id"])} if target.get("workspace_id") else {}),
                    **({"viewerId": str(target["viewer_id"])} if target.get("viewer_id") else {}),
                },
            )
            return {"ok": True, "identity": identity}
        if action == "find_by_idempotency":
            marker = str(payload["idempotency_key"])
            teams = self.client.request("listTeams", {})
            team_ids = list(
                dict.fromkeys(
                    [team_id]
                    + [
                        str(team.get("id"))
                        for team in teams
                        if isinstance(team, Mapping) and team.get("id")
                    ]
                )
            )
            matches = []
            for visible_team_id in team_ids:
                issues = self.client.request(
                    "listIssuesByTeam",
                    {"teamId": visible_team_id, "includeArchived": True},
                )
                matches.extend(
                    issue
                    for issue in issues
                    if isinstance(issue, Mapping)
                    and _has_exact_marker(issue.get("description"), marker)
                )
            if len(matches) > 1:
                raise LinearBridgeError("CONFLICT", "Linear idempotency marker matched multiple issues")
            return self._provider_record(matches[0]) if matches else {}
        if action in {"create_spec", "update_spec"}:
            spec = payload.get("spec")
            if not isinstance(spec, Mapping):
                raise LinearBridgeError("INVALID_REQUEST", "Spec payload is missing")
            marker = str(payload["idempotency_key"])
            state_id = self._state_id(team_id, payload.get("native_status"))
            provider_id = str(payload.get("provider_id") or "").strip()
            current = None
            if action == "update_spec":
                if not provider_id:
                    raise LinearBridgeError("INVALID_REQUEST", "Linear update requires provider_id")
                current = self.client.request("getIssue", {"issue": provider_id})
                if not isinstance(current, Mapping):
                    raise LinearBridgeError("NOT_FOUND", "Linear issue was not found")
                if "labels" not in current or not isinstance(current.get("labels"), list):
                    raise LinearBridgeError(
                        "BRIDGE_INVALID_RESPONSE",
                        "Linear update pre-read returned invalid labels",
                    )
            labels = current.get("labels") if isinstance(current, Mapping) else []
            label_ids = [
                str(label["id"])
                for label in labels or []
                if isinstance(label, Mapping)
                and label.get("id")
                and str(label.get("name", "")).lower() != "blocked"
            ]
            if payload.get("blocked_label"):
                label_ids.append(self._blocked_label_id(team_id))
            issue_input = {
                "title": str(spec.get("title") or spec.get("id") or "Agentic OS spec"),
                "description": _description(spec, marker),
                **({"projectId": str(target["project_id"])} if target.get("project_id") else {}),
                **({"stateId": state_id} if state_id else {}),
                **({"labelIds": list(dict.fromkeys(label_ids))} if current is not None or label_ids else {}),
            }
            if action == "create_spec":
                reconciled = self.client.request(
                    "findOrCreateIssueByMarker",
                    {
                        "marker": marker,
                        "input": {"teamId": team_id, **issue_input},
                    },
                )
                issue = reconciled.get("issue") if isinstance(reconciled, Mapping) else None
            else:
                issue = self.client.request(
                    "updateIssue", {"issue": provider_id, "input": issue_input}
                )
            if not isinstance(issue, Mapping):
                raise LinearBridgeError("BRIDGE_INVALID_RESPONSE", "Linear write returned invalid issue")
            return self._provider_record(issue)
        if action == "get_spec":
            issue = self.client.request("getIssue", {"issue": str(payload["provider_id"])})
            if not isinstance(issue, Mapping):
                raise LinearBridgeError("NOT_FOUND", "Linear issue was not found")
            return self._provider_record(issue)
        if action == "get_by_spec_id":
            return {}
        if action == "list_specs":
            # A normalized Spec cannot be reconstructed from LinearIssue alone
            # without inventing its type, lifecycle status, or authority.
            return {"items": []}
        raise LinearBridgeError("UNSUPPORTED_OPERATION", "Unsupported Linear Spec transport action")


def transport_from_environment(
    environ: Mapping[str, str] | None = None,
) -> SpecTransport | None:
    values = os.environ if environ is None else environ
    configured = any(
        values.get(name)
        for name in (
            "GENOMES_LINEAR_BRIDGE_COMMAND",
            "LINEAR_TOKEN",
            "LINEAR_API_KEY",
            "LINEAR_API_TOKEN",
        )
    )
    if not configured:
        return None
    try:
        command = command_from_environment(values)
        auth = auth_from_environment(values)
    except LinearBridgeError as exc:
        return _LinearBridgeConfigurationTransport(str(exc))
    if not command:
        return _LinearBridgeConfigurationTransport("Linear bridge command must be configured")
    return LinearBridgeSpecTransport(LinearBridgeClient(command, auth))


class _LinearBridgeConfigurationTransport:
    def __init__(self, error: str):
        self.error = error

    def request(self, action: str, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        del action, payload
        raise LinearBridgeError("CONFIGURATION_ERROR", self.error)


class LinearSpecAdapter(GuardedProviderAdapter):
    name = "linear"

    def __init__(self, policy: Mapping[str, Any] | None = None, transport: SpecTransport | None = None):
        super().__init__(policy, transport)

    def _plan(self, spec: Spec, operation: str, *, extra: Mapping[str, Any] | None = None) -> dict[str, Any]:
        plan = super()._plan(spec, operation, extra=extra)
        mapping = self.policy.get("status_map") if isinstance(self.policy.get("status_map"), Mapping) else {}
        native_status = mapping.get(spec.status)
        if not native_status:
            native_status = {"idea": "Backlog", "grooming": "Backlog", "ready": "Todo", "in_progress": "In Progress", "built": "Done"}.get(spec.status)
        plan.update({"mode": str(self.policy.get("mode") or "backlog"), "native_status": native_status, "blocked_label": "blocked" if spec.status == "blocked" else None})
        return plan

    def doctor(self) -> AdapterReceipt:
        receipt = super().doctor()
        target = self._target()
        if receipt.ok and self.policy.get("enabled") and not (target.get("team_id") or target.get("team")):
            receipt.ok = False
            receipt.status = "blocked"
            receipt.error = "Linear target requires team or team_id"
        return receipt
