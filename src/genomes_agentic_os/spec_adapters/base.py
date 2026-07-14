"""Adapter contracts and shared guarded-provider behavior."""

from __future__ import annotations

from typing import Any, Mapping, Protocol, runtime_checkable

from ..spec_engine import AdapterReceipt, Spec


@runtime_checkable
class SpecTransport(Protocol):
    """Injected provider boundary; implementations own auth and HTTP/CLI details."""

    def request(self, action: str, payload: Mapping[str, Any]) -> Mapping[str, Any]: ...


@runtime_checkable
class SpecAdapter(Protocol):
    name: str

    def create(self, spec: Spec, *, apply: bool = False) -> AdapterReceipt: ...
    def get(self, spec_id: str) -> Spec | None: ...
    def list(self, **filters: Any) -> list[Spec]: ...
    def transition(self, spec: Spec, *, previous_status: str, apply: bool = False) -> AdapterReceipt: ...
    def sync(self, spec: Spec, *, apply: bool = False) -> AdapterReceipt: ...
    def doctor(self) -> AdapterReceipt: ...


class GuardedProviderAdapter:
    """Common verify -> idempotency -> write -> readback provider workflow."""

    name = "provider"

    def __init__(self, policy: Mapping[str, Any] | None = None, transport: SpecTransport | None = None):
        self.policy = dict(policy or {})
        self.transport = transport

    def _target(self) -> dict[str, Any]:
        target = self.policy.get("target")
        return dict(target) if isinstance(target, Mapping) else {}

    def _plan(self, spec: Spec, operation: str, *, extra: Mapping[str, Any] | None = None) -> dict[str, Any]:
        plan = {
            "adapter": self.name,
            "operation": operation,
            "target": self._target(),
            "spec": spec.external_payload(),
            "idempotency_key": f"spec:{spec.domain}:{spec.project}:{spec.id}",
        }
        if extra:
            plan.update(dict(extra))
        return plan

    def _request(self, action: str, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        if self.transport is None:
            raise RuntimeError(f"{self.name} transport is not configured")
        result = self.transport.request(action, payload)
        if not isinstance(result, Mapping):
            raise RuntimeError(f"{self.name} transport returned a non-mapping response")
        return result

    def _apply(self, spec: Spec, operation: str, plan: dict[str, Any]) -> AdapterReceipt:
        key = str(plan["idempotency_key"])
        try:
            verified = self._request("verify_target", {"target": plan["target"]})
            if not verified.get("ok"):
                return AdapterReceipt(self.name, operation, False, status="blocked", spec_id=spec.id, idempotency_key=key, detail="provider target verification failed", error=str(verified.get("error") or "target unavailable"), plan=plan)
            existing = self._request("find_by_idempotency", {"target": plan["target"], "idempotency_key": key})
            provider_id = str(existing.get("provider_id") or existing.get("id") or "") or None
            action = "update_spec" if provider_id else "create_spec"
            write_payload = dict(plan)
            if provider_id:
                write_payload["provider_id"] = provider_id
            written = self._request(action, write_payload)
            provider_id = str(written.get("provider_id") or written.get("id") or provider_id or "") or None
            if not provider_id:
                return AdapterReceipt(self.name, operation, False, applied=True, status="failed", spec_id=spec.id, idempotency_key=key, verified_target=True, detail="provider write returned no stable id", error="missing provider id", plan=plan)
            readback = self._request("get_spec", {"target": plan["target"], "provider_id": provider_id})
            readback_ok = bool(readback.get("ok", True)) and str(readback.get("provider_id") or readback.get("id") or provider_id) == provider_id
            return AdapterReceipt(
                self.name,
                operation,
                readback_ok,
                applied=True,
                status="applied" if readback_ok else "failed",
                spec_id=spec.id,
                provider_id=provider_id,
                url=str(written.get("url") or readback.get("url") or "") or None,
                idempotency_key=key,
                verified_target=True,
                readback_verified=readback_ok,
                detail="provider write verified" if readback_ok else "provider readback verification failed",
                error=None if readback_ok else "readback mismatch",
                plan=plan,
            )
        except Exception as exc:  # transport failures become durable receipts
            return AdapterReceipt(self.name, operation, False, status="blocked", spec_id=spec.id, idempotency_key=key, detail="provider operation blocked", error=str(exc), plan=plan)

    def _operate(self, spec: Spec, operation: str, *, apply: bool, extra: Mapping[str, Any] | None = None) -> AdapterReceipt:
        plan = self._plan(spec, operation, extra=extra)
        if not apply:
            return AdapterReceipt(self.name, operation, True, status="planned", spec_id=spec.id, idempotency_key=str(plan["idempotency_key"]), detail="dry-run provider plan", plan=plan)
        return self._apply(spec, operation, plan)

    def create(self, spec: Spec, *, apply: bool = False) -> AdapterReceipt:
        return self._operate(spec, "create", apply=apply)

    def get(self, spec_id: str) -> Spec | None:
        if self.transport is None:
            return None
        response = self._request("get_by_spec_id", {"target": self._target(), "spec_id": spec_id})
        record = response.get("spec")
        return Spec.from_mapping(record) if isinstance(record, Mapping) else None

    def list(self, **filters: Any) -> list[Spec]:
        if self.transport is None:
            return []
        response = self._request("list_specs", {"target": self._target(), "filters": filters})
        return [Spec.from_mapping(item) for item in response.get("items") or [] if isinstance(item, Mapping)]

    def transition(self, spec: Spec, *, previous_status: str, apply: bool = False) -> AdapterReceipt:
        return self._operate(spec, "transition", apply=apply, extra={"previous_status": previous_status})

    def sync(self, spec: Spec, *, apply: bool = False) -> AdapterReceipt:
        return self._operate(spec, "sync", apply=apply)

    def doctor(self) -> AdapterReceipt:
        if not self.policy.get("enabled", False):
            return AdapterReceipt(self.name, "doctor", True, status="disabled", detail="adapter disabled by policy")
        target = self._target()
        if not target:
            return AdapterReceipt(self.name, "doctor", False, status="blocked", detail="provider target is not configured", error="missing target")
        if self.transport is None:
            return AdapterReceipt(self.name, "doctor", True, status="planned", detail="target configured; runtime transport not injected", plan={"target": target})
        try:
            result = self._request("verify_target", {"target": target})
            ok = bool(result.get("ok"))
            return AdapterReceipt(self.name, "doctor", ok, status="verified" if ok else "blocked", verified_target=ok, detail="provider target verified" if ok else "provider target verification failed", error=None if ok else str(result.get("error") or "target unavailable"), plan={"target": target})
        except Exception as exc:
            return AdapterReceipt(self.name, "doctor", False, status="blocked", detail="provider doctor failed", error=str(exc), plan={"target": target})
