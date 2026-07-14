"""Linear Spec adapter. Live behavior is supplied through an injected transport."""

from __future__ import annotations

from typing import Any, Mapping

from .base import GuardedProviderAdapter, SpecTransport
from ..spec_engine import AdapterReceipt, Spec


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
