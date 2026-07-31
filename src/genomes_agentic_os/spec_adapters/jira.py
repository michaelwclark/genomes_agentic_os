"""Jira Spec adapter with backlog-first and explicit active-sprint placement."""

from __future__ import annotations

import hashlib
import os
from collections.abc import Mapping
from typing import Any

from ..jira_bridge import (
    JiraBridgeClient,
    JiraBridgeError,
    auth_from_environment,
    base_url_from_environment,
    command_from_environment,
)
from ..spec_engine import AdapterReceipt, Spec
from .base import GuardedProviderAdapter, SpecTransport


def _marker_label(idempotency_key: str) -> str:
    return (
        f"agentic-os-spec-{hashlib.sha256(idempotency_key.encode()).hexdigest()[:16]}"
    )


def _spec_adf(spec: Mapping[str, Any], marker: str) -> dict[str, Any]:
    content: list[dict[str, Any]] = []
    summary = str(spec.get("summary") or "").strip()
    if summary:
        content.append(
            {"type": "paragraph", "content": [{"type": "text", "text": summary}]}
        )
    criteria = spec.get("acceptance_criteria")
    if isinstance(criteria, list) and criteria:
        content.append(
            {
                "type": "heading",
                "attrs": {"level": 2},
                "content": [{"type": "text", "text": "Acceptance criteria"}],
            }
        )
        content.append(
            {
                "type": "bulletList",
                "content": [
                    {
                        "type": "listItem",
                        "content": [
                            {
                                "type": "paragraph",
                                "content": [{"type": "text", "text": str(item)}],
                            }
                        ],
                    }
                    for item in criteria
                ],
            }
        )
    content.append({"type": "paragraph", "content": [{"type": "text", "text": marker}]})
    return {"version": 1, "type": "doc", "content": content}


class JiraBridgeSpecTransport:
    """Compose Spec Engine's guarded workflow onto the shared Jira port."""

    def __init__(self, client: JiraBridgeClient):
        self.client = client

    @staticmethod
    def _target(payload: Mapping[str, Any]) -> dict[str, Any]:
        target = payload.get("target")
        return dict(target) if isinstance(target, Mapping) else {}

    @staticmethod
    def _project(target: Mapping[str, Any]) -> str:
        project = str(target.get("project_key") or target.get("project") or "").strip()
        if not project:
            raise JiraBridgeError(
                "CONFIGURATION_ERROR", "Jira target project is not configured"
            )
        return project

    @staticmethod
    def _provider_record(issue: Mapping[str, Any]) -> dict[str, Any]:
        key = str(issue.get("key") or "").strip()
        if not key:
            raise JiraBridgeError(
                "BRIDGE_INVALID_RESPONSE", "Jira issue readback has no key"
            )
        return {"ok": True, "provider_id": key, "id": key, "url": issue.get("url")}

    def _transition_issue(self, provider_id: str, destination: str) -> Mapping[str, Any]:
        transitions = self.client.request("listTransitions", {"key": provider_id})
        if not isinstance(transitions, list):
            raise JiraBridgeError(
                "BRIDGE_INVALID_RESPONSE", "Jira transitions read returned invalid data"
            )
        matches = [
            transition
            for transition in transitions
            if isinstance(transition, Mapping)
            and transition.get("available") is not False
            and isinstance(transition.get("destination"), Mapping)
            and transition["destination"].get("name") == destination
        ]
        if len(matches) != 1 or not matches[0].get("id"):
            raise JiraBridgeError(
                "CONFLICT", "Jira workflow state did not resolve to one transition"
            )
        self.client.request(
            "transitionIssue",
            {"key": provider_id, "transitionId": str(matches[0]["id"])},
        )
        issue = self.client.request("getIssue", {"key": provider_id})
        if not isinstance(issue, Mapping):
            raise JiraBridgeError(
                "BRIDGE_INVALID_RESPONSE", "Jira transition readback was invalid"
            )
        status = issue.get("status")
        if not isinstance(status, Mapping) or status.get("name") != destination:
            raise JiraBridgeError(
                "PROVIDER_ERROR", "Jira transition readback did not match the requested state"
            )
        return issue

    def request(self, action: str, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        target = self._target(payload)
        project = self._project(target)
        if action == "verify_target":
            issue_type_id = str(target.get("issue_type_id") or "").strip()
            site_url = str(target.get("site_url") or target.get("site") or "").strip()
            if not issue_type_id or not site_url:
                raise JiraBridgeError(
                    "CONFIGURATION_ERROR",
                    "Jira target requires site_url and issue_type_id",
                )
            result = self.client.request(
                "preflightIdentity",
                {
                    "siteUrl": site_url,
                    "projectKey": project,
                    "issueTypeId": issue_type_id,
                    **(
                        {"cloudId": str(target["cloud_id"])}
                        if target.get("cloud_id")
                        else {}
                    ),
                    **(
                        {"accountId": str(target["account_id"])}
                        if target.get("account_id")
                        else {}
                    ),
                },
            )
            if not isinstance(result, Mapping):
                raise JiraBridgeError(
                    "BRIDGE_INVALID_RESPONSE",
                    "Jira identity preflight returned invalid data",
                )
            return {"ok": True, "identity": result}
        if action == "resolve_active_sprint":
            raise JiraBridgeError(
                "UNSUPPORTED_OPERATION", "Jira bridge does not expose sprint discovery"
            )
        if action == "find_by_idempotency":
            label = _marker_label(str(payload["idempotency_key"]))
            page = self.client.request(
                "searchIssues",
                {"jql": f'project = {project} AND labels = "{label}"', "limit": 2},
            )
            values = page.get("values") if isinstance(page, Mapping) else None
            if not isinstance(values, list):
                raise JiraBridgeError(
                    "BRIDGE_INVALID_RESPONSE", "Jira search returned invalid values"
                )
            if len(values) < 2 and page.get("complete") is not True:
                raise JiraBridgeError(
                    "BRIDGE_INVALID_RESPONSE",
                    "Jira idempotency search returned incomplete results",
                )
            if len(values) > 1:
                raise JiraBridgeError(
                    "CONFLICT", "Jira idempotency marker matched multiple issues"
                )
            return self._provider_record(values[0]) if values else {}
        if action in {"create_spec", "update_spec"}:
            spec = payload.get("spec")
            if not isinstance(spec, Mapping):
                raise JiraBridgeError("INVALID_REQUEST", "Spec payload is missing")
            destination = ""
            if payload.get("operation") == "transition":
                destination = str(payload.get("native_status") or "").strip()
                if not destination:
                    raise JiraBridgeError(
                        "CONFIGURATION_ERROR",
                        "Jira transition requires a mapped native status",
                    )
            marker = str(payload["idempotency_key"])
            label = _marker_label(marker)
            required_labels = ["agentic-os-spec", label]
            fields: dict[str, Any] = {"labels": required_labels}
            if payload.get("resolved_sprint_id"):
                fields["sprint"] = str(payload["resolved_sprint_id"])
            if action == "create_spec":
                issue = self.client.request(
                    "createIssue",
                    {
                        "project": project,
                        # The shared port accepts a Jira issue-type ID, not a
                        # display name. It is the same ID verified immediately
                        # before this write.
                        "issueType": str(target["issue_type_id"]),
                        "summary": str(
                            spec.get("title") or spec.get("id") or "Agentic OS spec"
                        ),
                        "description": _spec_adf(spec, marker),
                        "fields": fields,
                        "reconciliationJql": f'project = {project} AND labels = "{label}"',
                    },
                )
            else:
                provider_id = str(payload.get("provider_id") or "").strip()
                if not provider_id:
                    raise JiraBridgeError(
                        "INVALID_REQUEST", "Jira update requires provider_id"
                    )
                current = self.client.request(
                    "getIssue", {"key": provider_id, "fields": ["labels"]}
                )
                if current is None:
                    raise JiraBridgeError(
                        "NOT_FOUND", f"Jira issue {provider_id} was not found"
                    )
                if not isinstance(current, Mapping):
                    raise JiraBridgeError(
                        "BRIDGE_INVALID_RESPONSE",
                        "Jira update pre-read returned invalid issue data",
                    )
                current_fields = (
                    current.get("fields")
                    if isinstance(current.get("fields"), Mapping)
                    else {}
                )
                current_labels = current_fields.get("labels")
                if current_labels is not None and not isinstance(current_labels, list):
                    raise JiraBridgeError(
                        "BRIDGE_INVALID_RESPONSE",
                        "Jira update pre-read returned invalid labels",
                    )
                fields["labels"] = list(
                    dict.fromkeys(
                        [
                            *(
                                str(value)
                                for value in (current_labels or [])
                                if str(value).strip()
                            ),
                            *required_labels,
                        ]
                    )
                )
                issue = self.client.request(
                    "updateIssue",
                    {
                        "key": provider_id,
                        "input": {
                            "summary": str(
                                spec.get("title") or spec.get("id") or provider_id
                            ),
                            "description": _spec_adf(spec, marker),
                            "fields": fields,
                        },
                    },
                )
            if not isinstance(issue, Mapping):
                raise JiraBridgeError(
                    "BRIDGE_INVALID_RESPONSE", "Jira write returned invalid issue"
                )
            if payload.get("operation") == "transition":
                provider_id = str(issue.get("key") or "").strip()
                if not provider_id:
                    raise JiraBridgeError(
                        "BRIDGE_INVALID_RESPONSE", "Jira write returned no issue key"
                    )
                issue = self.client.request("getIssue", {"key": provider_id})
                if not isinstance(issue, Mapping):
                    raise JiraBridgeError(
                        "BRIDGE_INVALID_RESPONSE",
                        "Jira transition pre-read was invalid",
                    )
                current_status = issue.get("status")
                if not (
                    isinstance(current_status, Mapping)
                    and current_status.get("name") == destination
                ):
                    issue = self._transition_issue(provider_id, destination)
            return self._provider_record(issue)
        if action == "get_spec":
            issue = self.client.request(
                "getIssue", {"key": str(payload["provider_id"])}
            )
            if issue is None:
                raise JiraBridgeError(
                    "NOT_FOUND",
                    f"Jira issue {payload['provider_id']} was not found",
                )
            if not isinstance(issue, Mapping):
                raise JiraBridgeError(
                    "BRIDGE_INVALID_RESPONSE", "Jira readback returned invalid issue"
                )
            return self._provider_record(issue)
        if action == "get_by_spec_id":
            return {}
        if action == "list_specs":
            page = self.client.request(
                "searchIssues",
                {"jql": f'project = {project} AND labels = "agentic-os-spec"'},
            )
            values = page.get("values") if isinstance(page, Mapping) else None
            if not isinstance(values, list) or page.get("complete") is not True:
                raise JiraBridgeError(
                    "BRIDGE_INVALID_RESPONSE", "Jira list returned incomplete results"
                )
            return {"items": values}
        raise JiraBridgeError(
            "UNSUPPORTED_OPERATION", "Unsupported Jira Spec transport action"
        )


def transport_from_environment(
    environ: Mapping[str, str] | None = None,
) -> SpecTransport | None:
    values = os.environ if environ is None else environ
    configured = any(
        values.get(name)
        for name in (
            "GENOMES_JIRA_BRIDGE_COMMAND",
            "JIRA_BASE_URL",
            "JIRA_OAUTH_TOKEN",
            "JIRA_EMAIL",
            "JIRA_API_TOKEN",
        )
    )
    if not configured:
        return None
    try:
        command = command_from_environment(values)
    except JiraBridgeError as exc:
        return _JiraBridgeConfigurationTransport(str(exc))
    if not command:
        return _JiraBridgeConfigurationTransport(
            "Jira bridge command must be configured"
        )
    try:
        auth = auth_from_environment(values)
        base_url = base_url_from_environment(values)
    except JiraBridgeError as exc:
        return _JiraBridgeConfigurationTransport(str(exc))
    return JiraBridgeSpecTransport(JiraBridgeClient(command, base_url, auth))


class _JiraBridgeConfigurationTransport:
    """Fail-closed transport retained so doctor/apply return durable receipts."""

    def __init__(self, error: str):
        self.error = error

    def request(self, action: str, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        del action, payload
        raise JiraBridgeError("CONFIGURATION_ERROR", self.error)


class JiraSpecAdapter(GuardedProviderAdapter):
    name = "jira"

    def __init__(
        self,
        policy: Mapping[str, Any] | None = None,
        transport: SpecTransport | None = None,
    ):
        super().__init__(policy, transport)

    def get(self, spec_id: str) -> Spec | None:
        try:
            return super().get(spec_id)
        except JiraBridgeError:
            return None

    def list(self, **filters: Any) -> list[Spec]:
        try:
            return super().list(**filters)
        except JiraBridgeError:
            return []

    def _plan(
        self, spec: Spec, operation: str, *, extra: Mapping[str, Any] | None = None
    ) -> dict[str, Any]:
        plan = super()._plan(spec, operation, extra=extra)
        types = (
            self.policy.get("issue_type_map")
            if isinstance(self.policy.get("issue_type_map"), Mapping)
            else {}
        )
        statuses = (
            self.policy.get("status_map")
            if isinstance(self.policy.get("status_map"), Mapping)
            else {}
        )
        placement_cfg = (
            self.policy.get("placement")
            if isinstance(self.policy.get("placement"), Mapping)
            else {}
        )
        requested = str(
            (extra or {}).get("placement") or placement_cfg.get("default") or "backlog"
        )
        if requested == "active_sprint" and not placement_cfg.get(
            "allow_active_sprint_override", False
        ):
            raise ValueError(
                "active sprint placement is disabled by Jira project policy"
            )
        plan.update(
            {
                "mode": str(self.policy.get("mode") or "sprint"),
                "issue_type": str(
                    types.get(spec.type)
                    or {"bug": "Bug", "feature": "Story", "config": "Task"}[spec.type]
                ),
                "native_status": statuses.get(spec.status),
                "placement": requested,
                "resolve_active_sprint": requested == "active_sprint",
            }
        )
        return plan

    def create(
        self, spec: Spec, *, apply: bool = False, placement: str | None = None
    ) -> AdapterReceipt:
        try:
            return self._operate(
                spec,
                "create",
                apply=apply,
                extra={"placement": placement} if placement else None,
            )
        except ValueError as exc:
            return AdapterReceipt(
                self.name,
                "create",
                False,
                status="blocked",
                spec_id=spec.id,
                detail="Jira placement rejected by project policy",
                error=str(exc),
            )

    def _apply(
        self, spec: Spec, operation: str, plan: dict[str, Any]
    ) -> AdapterReceipt:
        if plan.get("resolve_active_sprint"):
            try:
                target = self._target()
                resolved = self._request("resolve_active_sprint", {"target": target})
                sprint_id = resolved.get("sprint_id") or resolved.get("id")
                if not resolved.get("ok", bool(sprint_id)) or not sprint_id:
                    return AdapterReceipt(
                        self.name,
                        operation,
                        False,
                        status="blocked",
                        spec_id=spec.id,
                        idempotency_key=str(plan["idempotency_key"]),
                        error=str(resolved.get("error") or "active sprint not found"),
                        detail="active sprint resolution failed",
                        plan=plan,
                    )
                plan = dict(plan)
                plan["resolved_sprint_id"] = str(sprint_id)
            except Exception as exc:
                return AdapterReceipt(
                    self.name,
                    operation,
                    False,
                    status="blocked",
                    spec_id=spec.id,
                    idempotency_key=str(plan["idempotency_key"]),
                    error=str(exc),
                    detail="active sprint resolution failed",
                    plan=plan,
                )
        return super()._apply(spec, operation, plan)

    def doctor(self) -> AdapterReceipt:
        receipt = super().doctor()
        target = self._target()
        if (
            receipt.ok
            and self.policy.get("enabled")
            and not (target.get("project_key") or target.get("project"))
        ):
            receipt.ok = False
            receipt.status = "blocked"
            receipt.error = "Jira target requires project or project_key"
        return receipt
