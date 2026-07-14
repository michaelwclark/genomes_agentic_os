"""Canonical Spec model and orchestration service.

A Spec is the single work-intake object. Providers may own lifecycle state, but
the local record preserves identity, provenance, policy, and projection receipts.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import re
from typing import Any, Iterable, Mapping


SPEC_TYPES = ("bug", "feature", "config")
SPEC_STATUSES = ("idea", "grooming", "blocked", "ready", "in_progress", "built")
SPEC_DISPOSITIONS = ("active", "cancelled", "duplicate", "wont_do", "archived")

LEGACY_STATUS_MAP = {
    "captured": "idea",
    "inbox": "idea",
    "triaged": "grooming",
    "specified": "grooming",
    "spec-ready": "grooming",
    "spec_ready": "grooming",
    "ready": "ready",
    "queued": "ready",
    "building": "in_progress",
    "validating": "in_progress",
    "in-progress": "in_progress",
    "in progress": "in_progress",
    "finished": "built",
    "documented": "built",
    "done": "built",
    "blocked": "blocked",
}
LEGACY_DISPOSITION_MAP = {
    "archived": "archived",
    "dropped": "cancelled",
    "canceled": "cancelled",
    "cancelled": "cancelled",
    "duplicate": "duplicate",
    "wont_do": "wont_do",
    "won't do": "wont_do",
}
LEGACY_TYPE_MAP = {
    "bug": "bug",
    "config": "config",
    "configuration": "config",
    "idea": "feature",
    "spec": "feature",
    "feature": "feature",
    "plan": "feature",
    "improvement": "feature",
    "gap": "feature",
    "investigation": "feature",
}

_LOCAL_PATH_RE = re.compile(r"(?:/Users/|/home/|~/(?:agentic_os|projects)/)[^\s)\]}>]+")
_PRIVATE_NOTION_RE = re.compile(r"https?://(?:www\.)?notion\.(?:so|site)/\S+", re.IGNORECASE)
_TOKEN_RE = re.compile(
    r"(?i)(?:sk-[a-z0-9_-]{20,}|gh[pousr]_[a-z0-9_]{20,}|xox[baprs]-[a-z0-9-]{20,}|"
    r"(?:api[_-]?key|token|secret)\s*[:=]\s*[a-z0-9._~+/=-]{16,})"
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_status(value: str | None, *, fallback: str = "idea") -> tuple[str, str | None, str | None]:
    """Return canonical status, retained legacy value, and inferred disposition."""
    raw = str(value or fallback).strip().lower()
    normalized = raw.replace(" ", "_")
    if normalized in SPEC_STATUSES:
        return normalized, None, None
    if raw in LEGACY_DISPOSITION_MAP or normalized in LEGACY_DISPOSITION_MAP:
        return fallback, raw, LEGACY_DISPOSITION_MAP.get(raw, LEGACY_DISPOSITION_MAP.get(normalized))
    canonical = LEGACY_STATUS_MAP.get(raw, LEGACY_STATUS_MAP.get(normalized))
    if canonical:
        return canonical, raw, None
    raise ValueError(f"status must be one of {', '.join(SPEC_STATUSES)}: {value!r}")


def normalize_type(value: str | None) -> tuple[str, str | None]:
    raw = str(value or "feature").strip().lower()
    normalized = raw.replace(" ", "_")
    if normalized in SPEC_TYPES:
        return normalized, None
    canonical = LEGACY_TYPE_MAP.get(raw, LEGACY_TYPE_MAP.get(normalized))
    if canonical:
        return canonical, raw
    raise ValueError(f"type must be one of {', '.join(SPEC_TYPES)}: {value!r}")


def sanitize_external_text(value: str) -> str:
    """Strip private machine/workspace details before provider projection."""
    text = _LOCAL_PATH_RE.sub("[local path removed]", value)
    text = _PRIVATE_NOTION_RE.sub("[private Notion link removed]", text)
    return _TOKEN_RE.sub("[secret removed]", text)


@dataclass
class Spec:
    id: str
    title: str
    type: str = "feature"
    status: str = "idea"
    disposition: str = "active"
    domain: str = ""
    project: str = ""
    summary: str = ""
    blocked_from: str | None = None
    acceptance_criteria: list[str] = field(default_factory=list)
    external_refs: list[dict[str, Any]] = field(default_factory=list)
    authority: dict[str, str] = field(default_factory=dict)
    legacy: dict[str, Any] = field(default_factory=dict)
    provenance: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)
    schema_version: int = 1

    def __post_init__(self) -> None:
        canonical_type, legacy_type = normalize_type(self.type)
        canonical_status, legacy_status, inferred_disposition = normalize_status(self.status)
        self.type = canonical_type
        self.status = canonical_status
        if self.disposition not in SPEC_DISPOSITIONS:
            raise ValueError(f"disposition must be one of {', '.join(SPEC_DISPOSITIONS)}")
        if inferred_disposition and self.disposition == "active":
            self.disposition = inferred_disposition
        if legacy_type:
            self.legacy.setdefault("type", legacy_type)
        if legacy_status:
            self.legacy.setdefault("status", legacy_status)
        if self.blocked_from is not None:
            blocked_from, _, _ = normalize_status(self.blocked_from)
            if blocked_from == "blocked":
                raise ValueError("blocked_from cannot itself be blocked")
            self.blocked_from = blocked_from

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "Spec":
        lifecycle = data.get("lifecycle") if isinstance(data.get("lifecycle"), Mapping) else {}
        raw_status = lifecycle.get("state") or data.get("state") or data.get("status") or "idea"
        raw_type = data.get("type") or data.get("kind") or "feature"
        canonical_status, legacy_status, inferred_disposition = normalize_status(str(raw_status))
        canonical_type, legacy_type = normalize_type(str(raw_type))
        legacy = dict(data.get("legacy") or {})
        if legacy_status:
            legacy.setdefault("status", legacy_status)
        if legacy_type:
            legacy.setdefault("type", legacy_type)
        disposition = str(data.get("disposition") or inferred_disposition or "active")
        return cls(
            id=str(data.get("id") or data.get("slug") or ""),
            title=str(data.get("title") or data.get("summary") or "Untitled Spec"),
            type=canonical_type,
            status=canonical_status,
            disposition=disposition,
            domain=str(data.get("domain") or ""),
            project=str(data.get("project") or ""),
            summary=str(data.get("summary") or ""),
            blocked_from=data.get("blocked_from"),
            acceptance_criteria=list(data.get("acceptance_criteria") or []),
            external_refs=list(data.get("external_refs") or []),
            authority=dict(data.get("authority") or {}),
            legacy=legacy,
            provenance=dict(data.get("provenance") or {}),
            created_at=str(data.get("created_at") or data.get("created") or utc_now()),
            updated_at=str(data.get("updated_at") or utc_now()),
            schema_version=int(data.get("schema_version") or 1),
        )

    def transition(self, status: str) -> None:
        if status == "resume":
            if self.status != "blocked" or not self.blocked_from:
                raise ValueError("only a blocked spec with blocked_from can resume")
            target = self.blocked_from
            self.blocked_from = None
        else:
            target, _, inferred_disposition = normalize_status(status)
            if inferred_disposition:
                self.disposition = inferred_disposition
                return
        if target == "blocked" and self.status != "blocked":
            self.blocked_from = self.status
        elif self.status == "blocked" and target != "blocked":
            self.blocked_from = None
        self.status = target
        self.updated_at = utc_now()

    def to_mapping(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["state"] = self.status
        payload["lane"] = lane_for_status(self.status)
        payload["format"] = "folder"
        payload["lifecycle"] = {
            "state": self.status,
            "state_vocabulary": list(SPEC_STATUSES),
            "disposition_vocabulary": list(SPEC_DISPOSITIONS),
            "conversation_logs": "logs/conversations",
        }
        return payload

    def external_payload(self) -> dict[str, Any]:
        payload = self.to_mapping()
        payload["title"] = sanitize_external_text(self.title)
        payload["summary"] = sanitize_external_text(self.summary)
        payload["acceptance_criteria"] = [sanitize_external_text(item) for item in self.acceptance_criteria]
        payload.pop("provenance", None)
        return payload


def lane_for_status(status: str) -> str:
    normalized, _, _ = normalize_status(status)
    if normalized in {"idea", "grooming"}:
        return "01-intake"
    if normalized == "built":
        return "03-complete"
    return "02-active"


@dataclass
class AdapterReceipt:
    adapter: str
    operation: str
    ok: bool
    applied: bool = False
    status: str = "planned"
    spec_id: str | None = None
    provider_id: str | None = None
    url: str | None = None
    idempotency_key: str | None = None
    verified_target: bool = False
    readback_verified: bool = False
    detail: str = ""
    plan: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    def to_mapping(self) -> dict[str, Any]:
        return asdict(self)


class SpecEngine:
    """Small composition service over policy-selected adapters."""

    def __init__(self, policy: Mapping[str, Any], adapters: Mapping[str, Any]):
        self.policy = dict(policy)
        self.adapters = dict(adapters)

    def selected_adapters(self, explicit: str | None = None) -> list[str]:
        if explicit:
            names = [explicit]
        else:
            cfg = self.policy.get("adapters") if isinstance(self.policy.get("adapters"), Mapping) else {}
            names = [str(cfg.get("primary") or "filesystem"), *[str(x) for x in cfg.get("mirrors") or []]]
        result: list[str] = []
        for name in names:
            if name not in self.adapters:
                raise ValueError(f"unknown or unavailable spec adapter: {name}")
            if name not in result:
                result.append(name)
        return result

    def operation_adapters(self, explicit: str | None = None) -> list[str]:
        """Select write adapters while preserving the configured local identity."""
        names = self.selected_adapters(explicit)
        sync = self.policy.get("sync") if isinstance(self.policy.get("sync"), Mapping) else {}
        if sync.get("local_identity_required", True) and "filesystem" not in names:
            if "filesystem" not in self.adapters:
                raise ValueError("local Spec identity is required but the filesystem adapter is unavailable")
            names.insert(0, "filesystem")
        return names

    def add(self, spec: Spec, *, adapter: str | None = None, apply_external: bool = False, dry_run: bool = False) -> dict[str, Any]:
        receipt_objects = []
        for name in self.operation_adapters(adapter):
            apply = False if dry_run else (name == "filesystem" or apply_external)
            receipt_objects.append(self.adapters[name].create(spec, apply=apply))
        if not dry_run and "filesystem" in self.adapters:
            self.adapters["filesystem"].record_receipts(spec.id, "add", receipt_objects)
        receipts = [receipt.to_mapping() for receipt in receipt_objects]
        return {"ok": all(r["ok"] for r in receipts), "spec": spec.to_mapping(), "receipts": receipts}

    def transition(self, spec: Spec, status: str, *, adapter: str | None = None, apply_external: bool = False, dry_run: bool = False) -> dict[str, Any]:
        previous = spec.status
        spec.transition(status)
        receipt_objects = []
        for name in self.operation_adapters(adapter):
            apply = False if dry_run else (name == "filesystem" or apply_external)
            receipt_objects.append(self.adapters[name].transition(spec, previous_status=previous, apply=apply))
        if not dry_run and "filesystem" in self.adapters:
            self.adapters["filesystem"].record_receipts(spec.id, f"transition-{spec.status}", receipt_objects)
        receipts = [receipt.to_mapping() for receipt in receipt_objects]
        return {"ok": all(r["ok"] for r in receipts), "spec": spec.to_mapping(), "receipts": receipts}

    def sync(self, spec: Spec, *, adapter: str, apply: bool = False) -> dict[str, Any]:
        if adapter == "filesystem":
            raise ValueError("sync requires an external adapter")
        receipt = self.adapters[adapter].sync(spec, apply=apply)
        if apply and "filesystem" in self.adapters:
            self.adapters["filesystem"].record_receipts(spec.id, f"sync-{adapter}", [receipt])
        return {"ok": receipt.ok, "spec": spec.to_mapping(), "receipts": [receipt.to_mapping()]}

    def doctor(self, adapter: str | None = None) -> dict[str, Any]:
        names = self.selected_adapters(adapter)
        checks = [self.adapters[name].doctor().to_mapping() for name in names]
        return {"ok": all(item["ok"] for item in checks), "checks": checks}


def migrate_legacy_records(records: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [Spec.from_mapping(record).to_mapping() for record in records]
