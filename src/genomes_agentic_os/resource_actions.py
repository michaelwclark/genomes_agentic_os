"""Governed, file-backed actions for operator-facing Agentic OS resources.

This module deliberately stops at filesystem mutation and run-queue creation.
It never dispatches a queued command or performs an external effect.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import re
import shlex
import shutil
from typing import Any, Callable

import yaml

from .automation_ops import check_automation
from .runtime_ops import RUNTIME_REGISTRY, RUN_QUEUE, append_run_queue_item
from .scaffold import (
    PROGRAM_FILES,
    create_automation,
    create_instance_program,
    create_program,
    create_workflow,
    domain_path,
    expand_path,
    normalize_domain,
    shared_factory_path,
    validate_name,
)
from .workflow_ops import check_workflow


API_VERSION = "resource-actions/v1"
RESOURCE_ACTION_LOG_DIR = "harness/shared_factory/06-runs-and-logs/resource-actions"
MUTABLE_SCHEDULE_FIELDS = {
    "display_name",
    "enabled",
    "cadence",
    "timezone",
    "local_time",
    "execution_target",
    "command",
}
ACTIVE_QUEUE_STATES = {"queued", "running", "approval-needed"}
SUPPORTED_RESOURCE_KINDS = ("automation", "workflow", "program", "instance-program")
SUPPORTED_CADENCES = {"manual", "hourly", "daily", "weekly"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None = None) -> str:
    return (value or _now()).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _stamp(value: datetime | None = None) -> str:
    return (value or _now()).strftime("%Y%m%dT%H%M%S%fZ")


def _digest(value: str, length: int = 12) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:length]


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ValueError(f"required file is missing: {path}")
    loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(loaded, dict):
        raise ValueError(f"expected mapping in {path}")
    return loaded


def _atomic_write_yaml(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{_stamp()}.tmp")
    temporary.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    temporary.replace(path)


def _registry_path(root: Path) -> Path:
    path = root / RUNTIME_REGISTRY
    if not path.is_file():
        raise ValueError(f"runtime registry is missing: {path}; run `agentic-os runtime init --root {root}`")
    return path


def _schedule_by_id(registry: dict[str, Any], schedule_id: str) -> dict[str, Any]:
    found = next(
        (item for item in registry.get("schedules") or [] if isinstance(item, dict) and item.get("id") == schedule_id),
        None,
    )
    if found is None:
        raise ValueError(f"unknown schedule: {schedule_id}")
    return found


def _validate_cadence(value: str) -> str:
    if value in SUPPORTED_CADENCES:
        return value
    match = re.fullmatch(r"every_(\d+)_(minute|minutes|hour|hours)", value)
    if not match or int(match.group(1)) <= 0:
        raise ValueError(f"unsupported cadence: {value}")
    return value


def _validate_timezone(value: str) -> str:
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

    try:
        ZoneInfo(value)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"invalid timezone: {value}") from exc
    return value


def _validate_local_time(value: str | None, cadence: str) -> str | None:
    if value in (None, ""):
        return None
    if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", value):
        raise ValueError(f"invalid local_time: {value}")
    if cadence != "daily":
        raise ValueError("local_time requires daily cadence")
    return value


def _validate_command(value: str) -> str:
    if not value or len(value) > 4096 or "\x00" in value or "\n" in value or "\r" in value:
        raise ValueError("command must be a non-empty single line of at most 4096 characters")
    try:
        parsed = shlex.split(value)
    except ValueError as exc:
        raise ValueError(f"invalid command quoting: {exc}") from exc
    if not parsed:
        raise ValueError("command must not be empty")
    return value


def _validate_schedule(schedule: dict[str, Any], registry: dict[str, Any]) -> dict[str, Any]:
    validated = deepcopy(schedule)
    validated["id"] = validate_name(str(validated.get("id") or ""), "schedule_id")
    cadence = _validate_cadence(str(validated.get("cadence") or "manual"))
    timezone_name = _validate_timezone(str(validated.get("timezone") or "America/Chicago"))
    local_time = _validate_local_time(validated.get("local_time"), cadence)
    target_id = validate_name(str(validated.get("execution_target") or "script"), "execution_target")
    target_ids = {
        str(item.get("id"))
        for item in registry.get("execution_targets") or []
        if isinstance(item, dict) and item.get("id")
    }
    if target_id not in target_ids:
        raise ValueError(f"unknown execution target: {target_id}")
    validated.update(
        {
            "enabled": bool(validated.get("enabled", False)),
            "cadence": cadence,
            "timezone": timezone_name,
            "local_time": local_time,
            "execution_target": target_id,
            "command": _validate_command(str(validated.get("command") or "")),
        }
    )
    return validated


def _base_result(action: str, root: Path, *, dry_run: bool, status: str) -> dict[str, Any]:
    return {
        "api_version": API_VERSION,
        "action": action,
        "status": status,
        "dry_run": dry_run,
        "root": str(root),
        "backup": None,
        "receipt": None,
    }


def _backup_registry(
    root: Path,
    registry_path: Path,
    occurred_at: datetime,
) -> Path:
    evidence_root = root / RESOURCE_ACTION_LOG_DIR
    backup_dir = evidence_root / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = backup_dir / f"runtime-registry-{_stamp(occurred_at)}.yml"
    shutil.copy2(registry_path, backup_path)
    return backup_path


def _write_mutation_receipt(
    root: Path,
    registry_path: Path,
    *,
    occurred_at: datetime,
    backup_path: Path,
    action: str,
    resource_kind: str,
    resource_id: str,
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
    readback_ok: bool,
) -> Path:
    evidence_root = root / RESOURCE_ACTION_LOG_DIR
    receipt_path = evidence_root / f"{_stamp(occurred_at)}-{resource_kind}-{resource_id}-{action.rsplit('.', 1)[-1]}.yml"
    receipt = {
        "api_version": API_VERSION,
        "action": action,
        "resource": {"kind": resource_kind, "id": resource_id},
        "occurred_at": _iso(occurred_at),
        "registry": str(registry_path.relative_to(root)),
        "backup": str(backup_path.relative_to(root)),
        "before_sha256": _digest(yaml.safe_dump(before, sort_keys=True), 64) if before is not None else None,
        "after_sha256": _digest(yaml.safe_dump(after, sort_keys=True), 64) if after is not None else None,
        "readback_ok": readback_ok,
        "external_effects": "none",
    }
    _atomic_write_yaml(receipt_path, receipt)
    return receipt_path


def schedule_list(root: str | Path) -> dict[str, Any]:
    os_root = expand_path(root)
    registry = _load_yaml(_registry_path(os_root))
    schedules = sorted(
        (deepcopy(item) for item in registry.get("schedules") or [] if isinstance(item, dict)),
        key=lambda item: str(item.get("id") or ""),
    )
    return {
        "api_version": API_VERSION,
        "action": "schedule.list",
        "status": "ok",
        "root": str(os_root),
        "count": len(schedules),
        "schedules": schedules,
    }


def schedule_get(root: str | Path, schedule_id: str) -> dict[str, Any]:
    schedule_id = validate_name(schedule_id, "schedule_id")
    os_root = expand_path(root)
    registry = _load_yaml(_registry_path(os_root))
    schedule = deepcopy(_schedule_by_id(registry, schedule_id))
    validation = _validate_schedule(schedule, registry)
    return {
        "api_version": API_VERSION,
        "action": "schedule.get",
        "status": "ok",
        "root": str(os_root),
        "resource": {"kind": "schedule", "id": schedule_id, "value": schedule},
        "validation": {"ok": True, "normalized_changed": validation != schedule, "normalized": validation},
    }


def schedule_create_governed(
    root: str | Path,
    schedule_id: str,
    *,
    cadence: str = "manual",
    timezone_name: str = "America/Chicago",
    command: str | None = None,
    enabled: bool = True,
    dry_run: bool = True,
) -> dict[str, Any]:
    schedule_id = validate_name(schedule_id, "schedule_id")
    os_root = expand_path(root)
    registry_path = _registry_path(os_root)
    registry = _load_yaml(registry_path)
    existing = next(
        (item for item in registry.get("schedules") or [] if isinstance(item, dict) and item.get("id") == schedule_id),
        None,
    )
    if existing is not None:
        result = _base_result("schedule.create", os_root, dry_run=dry_run, status="exists")
        result["resource"] = {"kind": "schedule", "id": schedule_id, "before": existing, "after": existing}
        result["readback"] = {"ok": True, "schedule": existing}
        return result
    schedule = _validate_schedule(
        {
            "id": schedule_id,
            "display_name": schedule_id.replace("_", " ").title(),
            "enabled": enabled,
            "cadence": cadence,
            "timezone": timezone_name,
            "execution_target": "script",
            "command": command or "agentic-os validate --root <root>",
            "outputs": ["harness/shared_factory/06-runs-and-logs/runs/"],
            "next_due_at": None,
            "last_queued_at": None,
        },
        registry,
    )
    result = _base_result("schedule.create", os_root, dry_run=dry_run, status="planned" if dry_run else "created")
    result["resource"] = {"kind": "schedule", "id": schedule_id, "before": None, "after": schedule}
    if dry_run:
        result["readback"] = {"ok": True, "schedule": None}
        return result
    occurred_at = _now()
    backup = _backup_registry(os_root, registry_path, occurred_at)
    registry.setdefault("schedules", []).append(schedule)
    _atomic_write_yaml(registry_path, registry)
    readback = deepcopy(_schedule_by_id(_load_yaml(registry_path), schedule_id))
    readback_ok = readback == schedule
    receipt = _write_mutation_receipt(
        os_root,
        registry_path,
        occurred_at=occurred_at,
        backup_path=backup,
        action="schedule.create",
        resource_kind="schedule",
        resource_id=schedule_id,
        before=None,
        after=schedule,
        readback_ok=readback_ok,
    )
    result.update(
        {
            "backup": str(backup),
            "receipt": str(receipt),
            "readback": {"ok": readback_ok, "schedule": readback},
        }
    )
    return result


def schedule_update(
    root: str | Path,
    schedule_id: str,
    *,
    changes: dict[str, Any],
    dry_run: bool = True,
    action: str = "schedule.update",
) -> dict[str, Any]:
    schedule_id = validate_name(schedule_id, "schedule_id")
    unknown_fields = sorted(set(changes) - MUTABLE_SCHEDULE_FIELDS)
    if unknown_fields:
        raise ValueError(f"unsupported schedule fields: {', '.join(unknown_fields)}")
    if not changes:
        raise ValueError("at least one schedule field is required")
    os_root = expand_path(root)
    registry_path = _registry_path(os_root)
    registry = _load_yaml(registry_path)
    before = deepcopy(_schedule_by_id(registry, schedule_id))
    after = deepcopy(before)
    after.update(changes)
    after = _validate_schedule(after, registry)
    changed = before != after
    status = "unchanged" if not changed else ("planned" if dry_run else "updated")
    result = _base_result(action, os_root, dry_run=dry_run, status=status)
    result["resource"] = {"kind": "schedule", "id": schedule_id, "before": before, "after": after}
    if dry_run or not changed:
        result["readback"] = {"ok": True, "schedule": before}
        return result
    occurred_at = _now()
    backup = _backup_registry(os_root, registry_path, occurred_at)
    target = _schedule_by_id(registry, schedule_id)
    target.clear()
    target.update(after)
    _atomic_write_yaml(registry_path, registry)
    readback = deepcopy(_schedule_by_id(_load_yaml(registry_path), schedule_id))
    readback_ok = readback == after
    receipt = _write_mutation_receipt(
        os_root,
        registry_path,
        occurred_at=occurred_at,
        backup_path=backup,
        action=action,
        resource_kind="schedule",
        resource_id=schedule_id,
        before=before,
        after=after,
        readback_ok=readback_ok,
    )
    result.update(
        {
            "backup": str(backup),
            "receipt": str(receipt),
            "readback": {"ok": readback_ok, "schedule": readback},
        }
    )
    return result


def schedule_set_enabled(root: str | Path, schedule_id: str, *, enabled: bool, dry_run: bool = True) -> dict[str, Any]:
    return schedule_update(
        root,
        schedule_id,
        changes={"enabled": enabled},
        dry_run=dry_run,
        action="schedule.enable" if enabled else "schedule.disable",
    )


def _active_queue_refs(root: Path, schedule_id: str) -> list[dict[str, Any]]:
    queue_path = root / RUN_QUEUE
    if not queue_path.is_file():
        return []
    queue = _load_yaml(queue_path)
    items = queue.get("items") if isinstance(queue.get("items"), list) else queue.get("run_queue") or []
    return [
        deepcopy(item)
        for item in items
        if isinstance(item, dict)
        and item.get("kind") == "schedule"
        and item.get("ref") == schedule_id
        and item.get("status") in ACTIVE_QUEUE_STATES
    ]


def schedule_delete(root: str | Path, schedule_id: str, *, dry_run: bool = True) -> dict[str, Any]:
    schedule_id = validate_name(schedule_id, "schedule_id")
    os_root = expand_path(root)
    registry_path = _registry_path(os_root)
    registry = _load_yaml(registry_path)
    before = deepcopy(_schedule_by_id(registry, schedule_id))
    if before.get("enabled"):
        raise ValueError(f"schedule must be disabled before deletion: {schedule_id}")
    active_refs = _active_queue_refs(os_root, schedule_id)
    if active_refs:
        raise ValueError(f"schedule has {len(active_refs)} active run-queue item(s): {schedule_id}")
    result = _base_result(
        "schedule.delete",
        os_root,
        dry_run=dry_run,
        status="planned" if dry_run else "deleted",
    )
    result["resource"] = {"kind": "schedule", "id": schedule_id, "before": before, "after": None}
    if dry_run:
        result["readback"] = {"ok": True, "schedule": before}
        return result
    occurred_at = _now()
    backup = _backup_registry(os_root, registry_path, occurred_at)
    registry["schedules"] = [item for item in registry.get("schedules") or [] if item.get("id") != schedule_id]
    _atomic_write_yaml(registry_path, registry)
    remaining = next((item for item in _load_yaml(registry_path).get("schedules") or [] if item.get("id") == schedule_id), None)
    readback_ok = remaining is None
    receipt = _write_mutation_receipt(
        os_root,
        registry_path,
        occurred_at=occurred_at,
        backup_path=backup,
        action="schedule.delete",
        resource_kind="schedule",
        resource_id=schedule_id,
        before=before,
        after=None,
        readback_ok=readback_ok,
    )
    result.update(
        {
            "backup": str(backup),
            "receipt": str(receipt),
            "readback": {"ok": readback_ok, "schedule": remaining},
        }
    )
    return result


def schedule_queue_now(root: str | Path, schedule_id: str, *, dry_run: bool = True) -> dict[str, Any]:
    schedule_id = validate_name(schedule_id, "schedule_id")
    os_root = expand_path(root)
    registry = _load_yaml(_registry_path(os_root))
    schedule = _validate_schedule(deepcopy(_schedule_by_id(registry, schedule_id)), registry)
    if not schedule.get("enabled"):
        raise ValueError(f"schedule must be enabled before queueing: {schedule_id}")
    target = next(
        (item for item in registry.get("execution_targets") or [] if item.get("id") == schedule.get("execution_target")),
        {},
    )
    approval_required = bool(schedule.get("approval_required")) or any(
        bool(value) for value in (schedule.get("approval_policy") or {}).values()
    )
    if target.get("status") != "active":
        queue_status, approval_state, blocked_reason = "blocked", "blocked", "execution target is not active"
    elif schedule.get("execution_target") != "script":
        queue_status, approval_state, blocked_reason = "blocked", "blocked", "provider execution is disabled by default"
    elif approval_required:
        queue_status, approval_state, blocked_reason = "approval-needed", "required", None
    else:
        queue_status, approval_state, blocked_reason = "queued", "not_required", None
    occurred_at = _now()
    nonce = _stamp(occurred_at)
    idempotency_key = f"schedule:{schedule_id}:manual:{nonce}"
    queue_item = {
        "id": f"queue_{_digest(idempotency_key)}",
        "kind": "schedule",
        "ref": schedule_id,
        "status": "dry-run" if dry_run else queue_status,
        "approval_state": "not_required" if dry_run else approval_state,
        "created_at": _iso(occurred_at),
        "dry_run": dry_run,
        "due_at": _iso(occurred_at),
        "idempotency_key": idempotency_key,
        "execution_target": schedule.get("execution_target"),
        "command": schedule.get("command"),
        "dispatch_performed": False,
        "blocked_reason": blocked_reason,
    }
    result = _base_result(
        "schedule.queue-now",
        os_root,
        dry_run=dry_run,
        status="planned" if dry_run else queue_status,
    )
    result["resource"] = {"kind": "schedule", "id": schedule_id, "value": schedule}
    result["queue_item"] = queue_item
    result["external_effects"] = "none; item was not dispatched"
    if dry_run:
        result["readback"] = {"ok": True, "queue_item": None}
        return result
    queued = append_run_queue_item(os_root, queue_item)
    result["readback"] = {"ok": True, "queue_item": queued["queue_item"]}
    result["queue_created"] = queued["created"]
    result["receipt"] = queued["run_queue"]
    return result


def _program_root(root: Path, kind: str, name: str, domain: str | None) -> Path:
    if kind == "program":
        return shared_factory_path(root, "00-programs", name)
    if not domain:
        raise ValueError("--domain is required for instance-program")
    return domain_path(root, normalize_domain(domain)) / "00-programs" / name


def validate_resource(
    root: str | Path,
    kind: str,
    name: str,
    *,
    domain: str | None = None,
    lane: str | None = None,
) -> dict[str, Any]:
    if kind not in SUPPORTED_RESOURCE_KINDS:
        raise ValueError(f"unsupported resource kind: {kind}")
    name = validate_name(name, kind)
    os_root = expand_path(root)
    findings: list[dict[str, str]]
    resource_path: Path
    if kind == "automation":
        if not domain or not lane:
            raise ValueError("--domain and --lane are required for automation")
        checked = check_automation(os_root, domain, lane, name)
        findings = checked["findings"]
        resource_path = Path(checked["automation"])
    elif kind == "workflow":
        if not domain or not lane:
            raise ValueError("--domain and --lane are required for workflow")
        workflow_findings = check_workflow(os_root, domain, lane, name)
        findings = [finding.as_dict() for finding in workflow_findings]
        resource_path = domain_path(os_root, domain) / "03-workflows" / validate_name(lane, "lane") / name
    else:
        resource_path = _program_root(os_root, kind, name, domain)
        required = ["AGENTS.md", "ROUTER.md", "CONTEXT.md", "RULES.md", "TOOLS.md", "config.toml", *PROGRAM_FILES]
        findings = [
            {"severity": "blocker", "path": str(resource_path / filename), "message": "required program file is missing"}
            for filename in required
            if not (resource_path / filename).is_file()
        ]
        if not resource_path.is_dir():
            findings.insert(0, {"severity": "blocker", "path": str(resource_path), "message": "program folder is missing"})
        if not findings:
            findings.append({"severity": "observation", "path": str(resource_path), "message": "program contract is structurally complete"})
    ok = not any(finding.get("severity") == "blocker" for finding in findings)
    return {
        "api_version": API_VERSION,
        "action": "resource.validate",
        "status": "valid" if ok else "invalid",
        "ok": ok,
        "root": str(os_root),
        "resource": {"kind": kind, "id": name, "path": str(resource_path), "domain": domain, "lane": lane},
        "findings": findings,
    }


def create_resource(
    root: str | Path,
    kind: str,
    name: str,
    *,
    domain: str | None = None,
    lane: str | None = None,
    dry_run: bool = True,
) -> dict[str, Any]:
    if kind not in SUPPORTED_RESOURCE_KINDS:
        raise ValueError(f"unsupported resource kind: {kind}")
    name = validate_name(name, kind)
    os_root = expand_path(root)
    if kind in {"automation", "workflow"} and (not domain or not lane):
        raise ValueError(f"--domain and --lane are required for {kind}")
    if kind == "instance-program" and not domain:
        raise ValueError("--domain is required for instance-program")
    if domain and not domain_path(os_root, normalize_domain(domain)).is_dir():
        raise ValueError(f"domain must already exist before resource creation: {domain}")
    if kind == "program" and not shared_factory_path(os_root).is_dir():
        raise ValueError("shared_factory must already exist before program creation")
    if kind == "automation":
        target = domain_path(os_root, str(domain)) / "04-automations" / validate_name(str(lane), "lane") / name
        creator: Callable[..., Any] = create_automation
        creator_args = (os_root, domain, lane, name)
    elif kind == "workflow":
        target = domain_path(os_root, str(domain)) / "03-workflows" / validate_name(str(lane), "lane") / name
        creator = create_workflow
        creator_args = (os_root, domain, lane, name)
    elif kind == "program":
        target = _program_root(os_root, kind, name, None)
        creator = create_program
        creator_args = (os_root, name)
    else:
        target = _program_root(os_root, kind, name, domain)
        creator = create_instance_program
        creator_args = (os_root, domain, name)
    exists = target.exists()
    result = _base_result(
        "resource.create",
        os_root,
        dry_run=dry_run,
        status="exists" if exists else ("planned" if dry_run else "created"),
    )
    result["resource"] = {"kind": kind, "id": name, "path": str(target), "domain": domain, "lane": lane}
    if dry_run or exists:
        result["readback"] = {"ok": exists if exists else True, "exists": exists}
        if exists:
            result["validation"] = validate_resource(os_root, kind, name, domain=domain, lane=lane)
        return result
    scaffold_result = creator(*creator_args)
    result["changes"] = {
        "created": [str(path) for path in scaffold_result.created],
        "updated": [str(path) for path in scaffold_result.updated],
        "skipped": [str(path) for path in scaffold_result.skipped],
    }
    result["validation"] = validate_resource(os_root, kind, name, domain=domain, lane=lane)
    result["readback"] = {"ok": target.is_dir(), "exists": target.is_dir()}
    return result
