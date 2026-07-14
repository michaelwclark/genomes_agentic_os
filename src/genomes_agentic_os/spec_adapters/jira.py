"""Jira Spec adapter with backlog-first and explicit active-sprint placement."""

from __future__ import annotations

from typing import Any, Mapping

from .base import GuardedProviderAdapter, SpecTransport
from ..spec_engine import AdapterReceipt, Spec


class JiraSpecAdapter(GuardedProviderAdapter):
    name = "jira"

    def __init__(self, policy: Mapping[str, Any] | None = None, transport: SpecTransport | None = None):
        super().__init__(policy, transport)

    def _plan(self, spec: Spec, operation: str, *, extra: Mapping[str, Any] | None = None) -> dict[str, Any]:
        plan = super()._plan(spec, operation, extra=extra)
        types = self.policy.get("issue_type_map") if isinstance(self.policy.get("issue_type_map"), Mapping) else {}
        statuses = self.policy.get("status_map") if isinstance(self.policy.get("status_map"), Mapping) else {}
        placement_cfg = self.policy.get("placement") if isinstance(self.policy.get("placement"), Mapping) else {}
        requested = str((extra or {}).get("placement") or placement_cfg.get("default") or "backlog")
        if requested == "active_sprint" and not placement_cfg.get("allow_active_sprint_override", False):
            raise ValueError("active sprint placement is disabled by Jira project policy")
        plan.update({
            "mode": str(self.policy.get("mode") or "sprint"),
            "issue_type": str(types.get(spec.type) or {"bug": "Bug", "feature": "Story", "config": "Task"}[spec.type]),
            "native_status": statuses.get(spec.status),
            "placement": requested,
            "resolve_active_sprint": requested == "active_sprint",
        })
        return plan

    def create(self, spec: Spec, *, apply: bool = False, placement: str | None = None) -> AdapterReceipt:
        try:
            return self._operate(spec, "create", apply=apply, extra={"placement": placement} if placement else None)
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

    def _apply(self, spec: Spec, operation: str, plan: dict[str, Any]) -> AdapterReceipt:
        if plan.get("resolve_active_sprint"):
            try:
                target = self._target()
                resolved = self._request("resolve_active_sprint", {"target": target})
                sprint_id = resolved.get("sprint_id") or resolved.get("id")
                if not resolved.get("ok", bool(sprint_id)) or not sprint_id:
                    return AdapterReceipt(self.name, operation, False, status="blocked", spec_id=spec.id, idempotency_key=str(plan["idempotency_key"]), error=str(resolved.get("error") or "active sprint not found"), detail="active sprint resolution failed", plan=plan)
                plan = dict(plan)
                plan["resolved_sprint_id"] = str(sprint_id)
            except Exception as exc:
                return AdapterReceipt(self.name, operation, False, status="blocked", spec_id=spec.id, idempotency_key=str(plan["idempotency_key"]), error=str(exc), detail="active sprint resolution failed", plan=plan)
        return super()._apply(spec, operation, plan)

    def doctor(self) -> AdapterReceipt:
        receipt = super().doctor()
        target = self._target()
        if receipt.ok and self.policy.get("enabled") and not (target.get("project_key") or target.get("project")):
            receipt.ok = False
            receipt.status = "blocked"
            receipt.error = "Jira target requires project or project_key"
        return receipt
