"""File-backed runtime operations for installed Agentic OS roots."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import os
from pathlib import Path
import re
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml

from .notion_sync import target_workspace, verify_workspace
from .scaffold import expand_path, install_docs, validate_name
from .self_improvement import run_self_improvement
from .validate import validate_root

RUNTIME_REGISTRY = "harness/shared_factory/00-control-plane/runtime-registry.yml"
INTEGRATION_REGISTRY = "harness/shared_factory/00-control-plane/integration-registry.yml"
RUN_QUEUE = "harness/shared_factory/00-control-plane/run-queue.yml"
HEARTBEAT_LOG_DIR = "harness/shared_factory/06-runs-and-logs/heartbeats"
RUNTIME_SETUP_RUN_DIR = "harness/shared_factory/06-runs-and-logs/runs"
NOTION_RUNTIME_MANIFEST = ".notion-runtime-tracking/manifest.yml"

RUNTIME_REQUIRED_TARGETS = {
    "codex_harness",
    "claude_harness",
    "script",
    "orgo_desktop",
    "composio_cli",
    "agentmail_api",
    "granola_local",
    "notion_api",
}
REQUIRED_INTEGRATIONS = {"orgo", "composio", "agentmail", "granola", "notion"}
RUN_QUEUE_STATES = ("dry-run", "queued", "approval-needed", "running", "blocked", "done", "failed", "skipped")
APPROVAL_STATES = ("not_required", "required", "approved", "denied", "expired", "blocked")
TERMINAL_RUN_QUEUE_STATES = {"dry-run", "blocked", "done", "failed", "skipped"}
SAFE_DISPATCH_TARGETS = {"script"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _title(value: str) -> str:
    known = {
        "orgo": "Orgo.io",
        "composio": "Composio",
        "agentmail": "AgentMail",
        "granola": "Granola",
        "notion": "Notion",
    }
    return known.get(value, value.replace("_", " ").title())


def _local_id(record_key: str) -> str:
    digest = hashlib.sha256(record_key.encode()).hexdigest()[:16]
    return f"local-runtime-{digest}"


def _digest(value: str, length: int = 12) -> str:
    return hashlib.sha256(value.encode()).hexdigest()[:length]


def _parse_time(value: str | None, *, field: str) -> datetime | None:
    if not value:
        return None
    try:
        normalized = value.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError(f"invalid {field}: {value}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _timezone(timezone_name: str) -> ZoneInfo:
    try:
        return ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"invalid timezone: {timezone_name}") from exc


def _cadence_delta(cadence: str) -> timedelta | None:
    if cadence == "manual":
        return None
    if cadence == "hourly":
        return timedelta(hours=1)
    if cadence == "daily":
        return timedelta(days=1)
    if cadence == "weekly":
        return timedelta(days=7)
    match = re.fullmatch(r"every_(\d+)_(minute|minutes|hour|hours)", cadence)
    if match:
        amount = int(match.group(1))
        if amount <= 0:
            raise ValueError(f"invalid cadence: {cadence}")
        unit = match.group(2)
        if unit.startswith("minute"):
            return timedelta(minutes=amount)
        return timedelta(hours=amount)
    raise ValueError(f"unsupported cadence: {cadence}")


def _next_due_after(base: datetime, cadence: str, timezone_name: str) -> str | None:
    delta = _cadence_delta(cadence)
    if delta is None:
        return None
    zone = _timezone(timezone_name)
    local_base = base.astimezone(zone)
    return _iso(local_base + delta)


def _due_window_start(now: datetime, cadence: str, timezone_name: str) -> str:
    zone = _timezone(timezone_name)
    local_now = now.astimezone(zone)
    if cadence == "hourly":
        local_window = local_now.replace(minute=0, second=0, microsecond=0)
    elif cadence == "daily":
        local_window = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    elif cadence == "weekly":
        start = local_now - timedelta(days=local_now.weekday())
        local_window = start.replace(hour=0, minute=0, second=0, microsecond=0)
    else:
        match = re.fullmatch(r"every_(\d+)_(minute|minutes|hour|hours)", cadence)
        if not match:
            raise ValueError(f"unsupported cadence: {cadence}")
        amount = int(match.group(1))
        if amount <= 0:
            raise ValueError(f"invalid cadence: {cadence}")
        unit = match.group(2)
        if unit.startswith("minute"):
            minute = (local_now.minute // amount) * amount
            local_window = local_now.replace(minute=minute, second=0, microsecond=0)
        else:
            hour = (local_now.hour // amount) * amount
            local_window = local_now.replace(hour=hour, minute=0, second=0, microsecond=0)
    return _iso(local_window)


def _is_due(schedule: dict[str, Any], now: datetime) -> bool:
    if not schedule.get("enabled", False):
        return False
    cadence = str(schedule.get("cadence") or "")
    if _cadence_delta(cadence) is None:
        return False
    _timezone(str(schedule.get("timezone") or "UTC"))
    next_due = _parse_time(schedule.get("next_due_at"), field=f"{schedule.get('id', '<unknown>')}.next_due_at")
    return next_due is None or next_due <= now


def _requires_approval(record: dict[str, Any]) -> bool:
    if record.get("approval_required") is True:
        return True
    approval_policy = record.get("approval_policy") or {}
    if isinstance(approval_policy, dict) and any(bool(value) for value in approval_policy.values()):
        return True
    runtime_policy = record.get("runtime_policy") or {}
    if isinstance(runtime_policy, dict) and runtime_policy.get("approval_required") is True:
        return True
    return False


def _approval_state(record: dict[str, Any], *, dry_run: bool) -> str:
    if dry_run or not _requires_approval(record):
        return "not_required"
    return "required"


def _queue_status(record: dict[str, Any], *, dry_run: bool, enabled: bool = True) -> str:
    if not enabled:
        return "blocked"
    if dry_run:
        return "dry-run"
    if _requires_approval(record):
        return "approval-needed"
    return "queued"


def _normalized_queue(data: dict[str, Any]) -> dict[str, Any]:
    queue = deepcopy(data) if data else deepcopy(DEFAULT_RUN_QUEUE)
    items = queue.get("items")
    run_queue = queue.get("run_queue")
    if not isinstance(items, list):
        items = run_queue if isinstance(run_queue, list) else []
    if not isinstance(run_queue, list):
        run_queue = items
    merged = []
    seen = set()
    for item in [*items, *run_queue]:
        if not isinstance(item, dict):
            continue
        key = item.get("idempotency_key") or item.get("id")
        if key in seen:
            continue
        seen.add(key)
        merged.append(item)
    queue["items"] = merged
    queue["run_queue"] = merged
    queue["states"] = list(RUN_QUEUE_STATES)
    queue["approval_states"] = list(APPROVAL_STATES)
    return queue


def _write_queue(path: Path, data: dict[str, Any]) -> None:
    _write_yaml(path, _normalized_queue(data))


def _execution_targets_by_id(registry: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return _items_by_id(registry.get("execution_targets") or [])


def _runtime_gate(record: dict[str, Any], registry: dict[str, Any], *, dry_run: bool, enabled: bool = True) -> dict[str, str | None]:
    status = _queue_status(record, dry_run=dry_run, enabled=enabled)
    approval_state = _approval_state(record, dry_run=dry_run)
    blocked_reason = None
    target_id = str(record.get("execution_target") or "script")
    target = _execution_targets_by_id(registry).get(target_id)
    if not target:
        return {"status": "blocked", "approval_state": "blocked", "blocked_reason": f"unknown execution target: {target_id}"}
    if not dry_run and target.get("status") != "active":
        return {
            "status": "blocked",
            "approval_state": "blocked",
            "blocked_reason": f"execution target is not active: {target_id}",
        }
    if not dry_run and target_id not in SAFE_DISPATCH_TARGETS:
        return {
            "status": "blocked",
            "approval_state": "blocked",
            "blocked_reason": f"provider execution is disabled by default: {target_id}",
        }
    if status == "blocked":
        approval_state = "blocked"
        blocked_reason = "runtime item is disabled"
    return {"status": status, "approval_state": approval_state, "blocked_reason": blocked_reason}


DEFAULT_RUNTIME_REGISTRY: dict[str, Any] = {
    "version": "0.1.0",
    "managed_by": "agentic-os runtime",
    "updated_at": None,
    "execution_targets": [
        {
            "id": "codex_harness",
            "display_name": "Codex harness",
            "type": "agent_harness",
            "owner": "Genome",
            "status": "active",
            "use_for": ["code changes", "repo validation", "local OS operations"],
            "approval_required_for": ["production_changes", "credential_changes", "customer_visible_output"],
            "credentials": {"env_vars": []},
            "health_check": {"command": "agentic-os validate --root <root>"},
            "notion_tracking": {"database": "Integrations"},
        },
        {
            "id": "claude_harness",
            "display_name": "Claude harness",
            "type": "agent_harness",
            "owner": "Genome",
            "status": "active",
            "use_for": ["long-form reasoning", "repo validation", "operator docs"],
            "approval_required_for": ["production_changes", "credential_changes", "customer_visible_output"],
            "credentials": {"env_vars": []},
            "health_check": {"command": "agentic-os validate --root <root>"},
            "notion_tracking": {"database": "Integrations"},
        },
        {
            "id": "script",
            "display_name": "Local script runner",
            "type": "local_process",
            "owner": "Genome",
            "status": "active",
            "use_for": ["deterministic validation", "file-backed dry runs"],
            "approval_required_for": ["external_write", "production_changes"],
            "credentials": {"env_vars": []},
            "health_check": {"command": "agentic-os runtime doctor --root <root>"},
            "notion_tracking": {"database": "Integrations"},
        },
        {
            "id": "orgo_desktop",
            "display_name": "Orgo desktop",
            "type": "computer_use_desktop",
            "owner": "Genome",
            "status": "planned",
            "use_for": ["browser workflows", "desktop tasks requiring an isolated environment"],
            "approval_required_for": ["customer_visible_output", "production_changes", "credential_changes"],
            "credentials": {"env_vars": ["ORGO_API_KEY"]},
            "health_check": {"command": "agentic-os integration doctor orgo --root <root>"},
            "notion_tracking": {"database": "Integrations"},
        },
        {
            "id": "composio_cli",
            "display_name": "Composio CLI",
            "type": "tool_gateway",
            "owner": "Genome",
            "status": "planned",
            "use_for": ["authenticated app actions", "tool schema discovery"],
            "approval_required_for": ["external_write", "credential_changes"],
            "credentials": {"env_vars": ["COMPOSIO_API_KEY"]},
            "health_check": {"command": "agentic-os integration doctor composio --root <root>"},
            "notion_tracking": {"database": "Integrations"},
        },
        {
            "id": "agentmail_api",
            "display_name": "AgentMail API",
            "type": "mail_gateway",
            "owner": "Genome",
            "status": "planned",
            "use_for": ["inbound agent mail checks", "outbound approved mail"],
            "approval_required_for": ["external_write", "customer_visible_output"],
            "credentials": {"env_vars": ["AGENTMAIL_API_KEY"]},
            "health_check": {"command": "agentic-os integration doctor agentmail --root <root>"},
            "notion_tracking": {"database": "Integrations"},
        },
        {
            "id": "granola_local",
            "display_name": "Granola local notes",
            "type": "local_app_data",
            "owner": "Genome",
            "status": "planned",
            "use_for": ["recent meeting note inventory", "operator memory capture"],
            "approval_required_for": ["sensitive_transcript_handling", "external_write"],
            "credentials": {"env_vars": []},
            "health_check": {"command": "agentic-os integration doctor granola --root <root>"},
            "notion_tracking": {"database": "Integrations"},
        },
        {
            "id": "notion_api",
            "display_name": "Genome's Notion API",
            "type": "control_plane_api",
            "owner": "Genome",
            "status": "planned",
            "use_for": ["runtime tracking", "control-plane writeback"],
            "approval_required_for": ["external_write", "workspace_verification", "credential_changes"],
            "credentials": {"env_vars": ["GENOMES_NOTION_PAT", "GENOMES_NOTION_CONNECTOR"]},
            "health_check": {"command": "agentic-os notion track-runtime --root <root> --dry-run"},
            "notion_tracking": {"database": "Integrations"},
        },
    ],
    "heartbeats": [
        {
            "id": "granola_recent_notes_sync",
            "display_name": "Granola recent notes sync",
            "domain": "shared_factory",
            "enabled": False,
            "cadence": "every_2_hours",
            "execution_target": "script",
            "integration": "granola",
            "context": {
                "read_first": [
                    "harness/shared_factory/00-control-plane/integration-registry.yml",
                    "harness/shared_factory/05-knowledge/source-map.md",
                ]
            },
            "approval_policy": {
                "external_write": False,
                "customer_visible_output": False,
                "sensitive_transcript_handling": True,
            },
            "success_means": [
                "recent notes checked",
                "run log written",
                "Notion tracking updated or blocked with reason",
            ],
            "failure_escalation": {"after_consecutive_failures": 2, "notify": "Genome"},
        },
        {
            "id": "agentmail_inbound_check",
            "display_name": "AgentMail inbound check",
            "domain": "shared_factory",
            "enabled": False,
            "cadence": "hourly",
            "execution_target": "agentmail_api",
            "integration": "agentmail",
            "context": {"read_first": ["harness/shared_factory/00-control-plane/integration-registry.yml"]},
            "approval_policy": {"external_write": False, "customer_visible_output": False},
            "success_means": ["inbound queue checked", "run log written"],
            "failure_escalation": {"after_consecutive_failures": 2, "notify": "Genome"},
        },
    ],
    "schedules": [
        {
            "id": "daily_agentic_os_doctor",
            "display_name": "Daily Agentic OS doctor",
            "enabled": True,
            "cadence": "daily",
            "timezone": "America/Chicago",
            "execution_target": "script",
            "command": "agentic-os validate --root <root>",
            "outputs": ["harness/shared_factory/06-runs-and-logs/runs/"],
            "notion_update": {"object": "Heartbeats", "status_field": "Last Status"},
            "next_due_at": None,
            "last_queued_at": None,
        },
        {
            "id": "self_improvement_review",
            "display_name": "Self-improvement review",
            "enabled": False,
            "cadence": "weekly",
            "timezone": "America/Chicago",
            "execution_target": "script",
            "command": "agentic-os self-improvement run --root <root> --dry-run",
            "outputs": ["harness/shared_factory/06-runs-and-logs/self-improvement/runs/"],
            "notion_update": {"object": "Self Improvement", "status_field": "Last Status"},
            "next_due_at": None,
            "last_queued_at": None,
        }
    ],
}


DEFAULT_INTEGRATION_REGISTRY: dict[str, Any] = {
    "version": "0.1.0",
    "managed_by": "agentic-os runtime",
    "updated_at": None,
    "integrations": [
        {
            "id": "orgo",
            "display_name": "Orgo.io",
            "provider": "orgo.io",
            "status": "planned",
            "setup_tasks": [
                "Confirm approved use cases for remote desktop execution.",
                "Set ORGO_API_KEY in the host environment.",
                "Run a dry-run desktop health check before external writes.",
            ],
            "health_checks": [
                {"id": "credential_present", "type": "env", "env_var": "ORGO_API_KEY"},
                {"id": "operator_approval", "type": "approval", "approval": "desktop execution"},
            ],
            "approval_gates": ["credential_changes", "production_changes", "customer_visible_output"],
            "credentials": {"env_vars": ["ORGO_API_KEY"]},
            "notion_tracking": {
                "database": "Integrations",
                "fields": ["Status", "Last Health Check", "Approval Gate", "Credential State"],
            },
        },
        {
            "id": "composio",
            "display_name": "Composio",
            "provider": "composio",
            "status": "planned",
            "setup_tasks": [
                "Confirm target connected account and tool slug.",
                "Set COMPOSIO_API_KEY or complete composio link.",
                "Run tool schema discovery before any write action.",
            ],
            "health_checks": [
                {"id": "credential_present", "type": "env", "env_var": "COMPOSIO_API_KEY"},
                {"id": "tool_schema", "type": "manual", "command": "composio search <tool>"},
            ],
            "approval_gates": ["external_write", "credential_changes", "provider_account_selection"],
            "credentials": {"env_vars": ["COMPOSIO_API_KEY"]},
            "notion_tracking": {
                "database": "Integrations",
                "fields": ["Status", "Connected Account", "Tool Slug", "Last Health Check"],
            },
        },
        {
            "id": "agentmail",
            "display_name": "AgentMail",
            "provider": "agentmail",
            "status": "planned",
            "setup_tasks": [
                "Confirm inbound mailbox and retention policy.",
                "Set AGENTMAIL_API_KEY in the host environment.",
                "Run an inbound dry-run heartbeat before outbound mail is enabled.",
            ],
            "health_checks": [
                {"id": "credential_present", "type": "env", "env_var": "AGENTMAIL_API_KEY"},
                {"id": "inbound_read", "type": "dry_run", "command": "agentic-os heartbeat run agentmail_inbound_check --dry-run"},
            ],
            "approval_gates": ["external_write", "customer_visible_output", "mail_send"],
            "credentials": {"env_vars": ["AGENTMAIL_API_KEY"]},
            "notion_tracking": {
                "database": "Integrations",
                "fields": ["Status", "Mailbox", "Last Inbound Check", "Send Approval"],
            },
        },
        {
            "id": "granola",
            "display_name": "Granola",
            "provider": "granola",
            "status": "planned",
            "setup_tasks": [
                "Confirm transcript sensitivity handling.",
                "Run a local recent-notes dry run.",
                "Track any Notion write as blocked until workspace verification passes.",
            ],
            "health_checks": [
                {"id": "local_access", "type": "manual", "command": "check Granola export or local app access"},
                {"id": "pilot_heartbeat", "type": "dry_run", "command": "agentic-os heartbeat run granola_recent_notes_sync --dry-run"},
            ],
            "approval_gates": ["sensitive_transcript_handling", "external_write", "notion_workspace_verification"],
            "credentials": {"env_vars": []},
            "notion_tracking": {
                "database": "Integrations",
                "fields": ["Status", "Transcript Handling", "Last Sync", "Workspace Verified"],
            },
        },
        {
            "id": "notion",
            "display_name": "Genome's Notion",
            "provider": "notion",
            "status": "planned",
            "setup_tasks": [
                "Verify the active workspace is Genome's Notion.",
                "Set GENOMES_NOTION_PAT or GENOMES_NOTION_CONNECTOR if direct API fallback is needed.",
                "Run track-runtime dry-run before apply.",
            ],
            "health_checks": [
                {"id": "workspace_guard", "type": "workspace", "expected": "Genome's Notion"},
                {"id": "credential_present", "type": "env_any", "env_vars": ["GENOMES_NOTION_PAT", "GENOMES_NOTION_CONNECTOR"]},
            ],
            "approval_gates": ["workspace_verification", "external_write", "credential_changes"],
            "credentials": {"env_vars": ["GENOMES_NOTION_PAT", "GENOMES_NOTION_CONNECTOR"]},
            "notion_tracking": {
                "database": "Integrations",
                "fields": ["Status", "Workspace", "Parent Page", "Last Runtime Sync"],
            },
        },
    ],
}


DEFAULT_RUN_QUEUE: dict[str, Any] = {
    "version": "0.1.0",
    "managed_by": "agentic-os runtime",
    "updated_at": None,
    "states": list(RUN_QUEUE_STATES),
    "approval_states": list(APPROVAL_STATES),
    "items": [],
    "run_queue": [],
}


def _load_yaml(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    if not path.is_file():
        return deepcopy(default)
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else deepcopy(default)


def _write_yaml(path: Path, data: dict[str, Any]) -> None:
    payload = deepcopy(data)
    payload["updated_at"] = _now()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def _seed_yaml(path: Path, data: dict[str, Any], result: dict[str, Any]) -> None:
    if path.exists():
        result["skipped"].append(str(path))
        return
    _write_yaml(path, data)
    result["created"].append(str(path))


def _ensure_dir(path: Path, result: dict[str, Any]) -> None:
    if path.is_dir():
        result["skipped"].append(str(path))
        return
    path.mkdir(parents=True, exist_ok=True)
    result["created"].append(str(path))


def _runtime_path(root: Path, relative: str) -> Path:
    return root / relative


def _registry(root: Path) -> dict[str, Any]:
    path = _runtime_path(root, RUNTIME_REGISTRY)
    if not path.is_file():
        raise ValueError(f"runtime registry is missing: {path}; run `agentic-os runtime init --root {root}`")
    return _load_yaml(path, DEFAULT_RUNTIME_REGISTRY)


def _integration_registry(root: Path) -> dict[str, Any]:
    path = _runtime_path(root, INTEGRATION_REGISTRY)
    if not path.is_file():
        raise ValueError(f"integration registry is missing: {path}; run `agentic-os runtime init --root {root}`")
    return _load_yaml(path, DEFAULT_INTEGRATION_REGISTRY)


def _queue(root: Path) -> dict[str, Any]:
    return _normalized_queue(_load_yaml(_runtime_path(root, RUN_QUEUE), DEFAULT_RUN_QUEUE))


def _items_by_id(items: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(item.get("id")): item for item in items if isinstance(item, dict) and item.get("id")}


def _find_item(items: list[dict[str, Any]], item_id: str, kind: str) -> dict[str, Any]:
    item = _items_by_id(items).get(item_id)
    if item is None:
        raise ValueError(f"unknown {kind}: {item_id}")
    return item


def _append_queue_item(root: Path, item: dict[str, Any]) -> tuple[Path, dict[str, Any], bool]:
    path = _runtime_path(root, RUN_QUEUE)
    queue = _queue(root)
    items = queue.setdefault("items", [])
    idempotency_key = item.get("idempotency_key")
    existing = None
    if idempotency_key:
        existing = next((candidate for candidate in items if candidate.get("idempotency_key") == idempotency_key), None)
    if existing:
        existing.update({key: value for key, value in item.items() if key != "created_at"})
        existing["updated_at"] = _now()
        written = existing
        created = False
    else:
        item.setdefault("created_at", _now())
        item.setdefault("updated_at", item["created_at"])
        items.append(item)
        written = item
        created = True
    queue["run_queue"] = items
    _write_queue(path, queue)
    return path, written, created


def append_run_queue_item(root: str | Path, item: dict[str, Any]) -> dict[str, Any]:
    os_root = expand_path(root)
    path, written, created = _append_queue_item(os_root, item)
    return {"run_queue": str(path), "queue_item": written, "created": created}


def runtime_init(root: str | Path) -> dict[str, Any]:
    os_root = expand_path(root)
    install_result = install_docs(os_root)
    result: dict[str, Any] = {
        "root": str(os_root),
        "status": "initialized",
        "created": [],
        "skipped": [],
        "docs_created": len(install_result.created),
        "docs_skipped": len(install_result.skipped),
    }
    _ensure_dir(_runtime_path(os_root, "harness/shared_factory/00-control-plane"), result)
    _ensure_dir(_runtime_path(os_root, HEARTBEAT_LOG_DIR), result)
    _ensure_dir(_runtime_path(os_root, RUNTIME_SETUP_RUN_DIR), result)
    _seed_yaml(_runtime_path(os_root, RUNTIME_REGISTRY), DEFAULT_RUNTIME_REGISTRY, result)
    _seed_yaml(_runtime_path(os_root, INTEGRATION_REGISTRY), DEFAULT_INTEGRATION_REGISTRY, result)
    _seed_yaml(_runtime_path(os_root, RUN_QUEUE), DEFAULT_RUN_QUEUE, result)
    return result


def heartbeat_list(root: str | Path) -> dict[str, Any]:
    os_root = expand_path(root)
    registry = _registry(os_root)
    heartbeats = registry.get("heartbeats") or []
    return {"root": str(os_root), "heartbeats": heartbeats}


def heartbeat_run(root: str | Path, heartbeat_id: str, *, dry_run: bool = True) -> dict[str, Any]:
    heartbeat_id = validate_name(heartbeat_id, "heartbeat_id")
    os_root = expand_path(root)
    registry = _registry(os_root)
    heartbeat = _find_item(registry.get("heartbeats") or [], heartbeat_id, "heartbeat")
    enabled = bool(heartbeat.get("enabled", False))
    created_at = _now()
    run_id = f"{_stamp()}-{_digest(f'{heartbeat_id}:{created_at}', 8)}-{heartbeat_id}"
    gate = _runtime_gate(heartbeat, registry, dry_run=dry_run, enabled=enabled or dry_run)
    status = str(gate["status"])
    approval_state = str(gate["approval_state"])
    idempotency_key = f"heartbeat:{heartbeat_id}:{run_id}"
    external_effect = "none"
    if status == "queued":
        external_effect = "queued for approved execution"
    elif status == "approval-needed":
        external_effect = "none; approval required before execution"
    log = {
        "run_id": run_id,
        "kind": "heartbeat",
        "heartbeat_id": heartbeat_id,
        "status": status,
        "approval_state": approval_state,
        "dry_run": dry_run,
        "created_at": created_at,
        "idempotency_key": idempotency_key,
        "execution_target": heartbeat.get("execution_target"),
        "integration": heartbeat.get("integration"),
        "success_means": heartbeat.get("success_means") or [],
        "external_effect": external_effect,
    }
    if gate.get("blocked_reason"):
        log["blocked_reason"] = gate["blocked_reason"]
    log_path = _runtime_path(os_root, HEARTBEAT_LOG_DIR) / f"{run_id}.yml"
    _write_yaml(log_path, log)
    queue_path, queue_item, queue_created = _append_queue_item(
        os_root,
        {
            "id": run_id,
            "kind": "heartbeat",
            "ref": heartbeat_id,
            "status": status,
            "approval_state": approval_state,
            "created_at": created_at,
            "dry_run": dry_run,
            "idempotency_key": idempotency_key,
            "execution_target": heartbeat.get("execution_target"),
            "integration": heartbeat.get("integration"),
            "log": str(log_path.relative_to(os_root)),
            "evidence": [{"type": "run_log", "path": str(log_path.relative_to(os_root))}],
            "blocked_reason": gate.get("blocked_reason"),
        },
    )
    return {
        "root": str(os_root),
        "status": status,
        "approval_state": approval_state,
        "heartbeat": heartbeat,
        "log": str(log_path),
        "run_queue": str(queue_path),
        "queue_item": queue_item,
        "queue_created": queue_created,
    }


def schedule_create(
    root: str | Path,
    schedule_id: str,
    *,
    cadence: str = "manual",
    timezone_name: str = "America/Chicago",
    command: str | None = None,
) -> dict[str, Any]:
    schedule_id = validate_name(schedule_id, "schedule_id")
    _cadence_delta(cadence)
    _timezone(timezone_name)
    os_root = expand_path(root)
    registry = _registry(os_root)
    schedules = registry.setdefault("schedules", [])
    existing = _items_by_id(schedules).get(schedule_id)
    if existing:
        return {"root": str(os_root), "status": "exists", "schedule": existing, "registry": str(_runtime_path(os_root, RUNTIME_REGISTRY))}
    schedule = {
        "id": schedule_id,
        "display_name": _title(schedule_id),
        "enabled": True,
        "cadence": cadence,
        "timezone": timezone_name,
        "execution_target": "script",
        "command": command or "agentic-os validate --root <root>",
            "outputs": ["harness/shared_factory/06-runs-and-logs/runs/"],
        "notion_update": {"object": "Heartbeats", "status_field": "Last Status"},
        "next_due_at": None,
        "last_queued_at": None,
    }
    schedules.append(schedule)
    _write_yaml(_runtime_path(os_root, RUNTIME_REGISTRY), registry)
    return {"root": str(os_root), "status": "created", "schedule": schedule, "registry": str(_runtime_path(os_root, RUNTIME_REGISTRY))}


def schedule_run_due(root: str | Path, *, dry_run: bool = True) -> dict[str, Any]:
    os_root = expand_path(root)
    registry = _registry(os_root)
    queued = []
    skipped = []
    now = datetime.now(timezone.utc)
    registry_changed = False
    for schedule in registry.get("schedules") or []:
        schedule_id = schedule.get("id")
        if not schedule.get("enabled", False):
            skipped.append({"schedule": schedule_id, "reason": "disabled"})
            continue
        try:
            due = _is_due(schedule, now)
        except ValueError as exc:
            skipped.append({"schedule": schedule_id, "reason": str(exc), "status": "blocked"})
            continue
        if not due:
            skipped.append({"schedule": schedule_id, "reason": "not due", "next_due_at": schedule.get("next_due_at")})
            continue
        due_at = schedule.get("next_due_at") or _due_window_start(
            now,
            str(schedule.get("cadence")),
            str(schedule.get("timezone") or "UTC"),
        )
        idempotency_key = f"schedule:{schedule_id}:{due_at}"
        item_id = f"queue_{_digest(idempotency_key)}"
        gate = _runtime_gate(schedule, registry, dry_run=dry_run)
        status = str(gate["status"])
        approval_state = str(gate["approval_state"])
        run_id = f"{_stamp()}-{_digest(idempotency_key, 8)}-{schedule_id}"
        log_path = _runtime_path(os_root, RUNTIME_SETUP_RUN_DIR) / run_id / "run-log.yml"
        log = {
            "run_id": run_id,
            "kind": "schedule",
            "schedule_id": schedule_id,
            "status": status,
            "approval_state": approval_state,
            "dry_run": dry_run,
            "created_at": _now(),
            "due_at": due_at,
            "idempotency_key": idempotency_key,
            "command": schedule.get("command"),
            "external_effect": "none" if dry_run or status in {"approval-needed", "blocked"} else "queued for approved execution",
        }
        if gate.get("blocked_reason"):
            log["blocked_reason"] = gate["blocked_reason"]
        _write_yaml(log_path, log)
        item = {
            "id": item_id,
            "kind": "schedule",
            "ref": schedule_id,
            "status": status,
            "approval_state": approval_state,
            "created_at": log["created_at"],
            "dry_run": dry_run,
            "due_at": due_at,
            "idempotency_key": idempotency_key,
            "execution_target": schedule.get("execution_target"),
            "command": schedule.get("command"),
            "log": str(log_path.relative_to(os_root)),
            "evidence": [{"type": "run_log", "path": str(log_path.relative_to(os_root))}],
            "blocked_reason": gate.get("blocked_reason"),
        }
        _, written_item, created = _append_queue_item(os_root, item)
        queued.append({**written_item, "created": created})
        if not dry_run:
            schedule["last_queued_at"] = _iso(now)
            schedule["next_due_at"] = _next_due_after(
                _parse_time(due_at, field=f"{schedule_id}.due_at") or now,
                str(schedule.get("cadence")),
                str(schedule.get("timezone") or "UTC"),
            )
            registry_changed = True
    if registry_changed:
        _write_yaml(_runtime_path(os_root, RUNTIME_REGISTRY), registry)
    return {
        "root": str(os_root),
        "status": "dry-run" if dry_run else "queued",
        "queued": queued,
        "skipped": skipped,
    }


def _dispatchable_item(items: list[dict[str, Any]], item_id: str | None) -> dict[str, Any] | None:
    if item_id:
        return next((item for item in items if item.get("id") == item_id), None)
    return next((item for item in items if item.get("status") == "queued"), None)


def _dispatch_blocker(item: dict[str, Any], registry: dict[str, Any]) -> str | None:
    if item.get("status") != "queued":
        return f"queue item is not queued: {item.get('status')}"
    if item.get("approval_state") == "required":
        return "approval is required before dispatch"
    target_id = str(item.get("execution_target") or "script")
    target = _execution_targets_by_id(registry).get(target_id)
    if not target:
        return f"unknown execution target: {target_id}"
    if target.get("status") != "active":
        return f"execution target is not active: {target_id}"
    if target_id not in SAFE_DISPATCH_TARGETS:
        return f"provider execution is disabled by default: {target_id}"
    if not item.get("command"):
        return "queue item has no local script command"
    return None


def _run_local_script(root: Path, command: str) -> dict[str, Any]:
    normalized = command.replace("<root>", str(root)).strip()
    if normalized in {f"agentic-os validate --root {root}", f"agentic-os validate --root {str(root)}"}:
        validation = validate_root(root)
        return {
            "supported": True,
            "ok": validation.ok,
            "command": normalized,
            "errors": validation.errors,
            "warnings": validation.warnings,
        }
    if normalized in {
        f"agentic-os self-improvement run --root {root} --dry-run",
        f"agentic-os self-improvement run --root {str(root)} --dry-run",
    }:
        try:
            result = run_self_improvement(root, dry_run=True)
        except ValueError as exc:
            return {
                "supported": True,
                "ok": False,
                "command": normalized,
                "errors": [str(exc)],
                "warnings": [],
            }
        return {
            "supported": True,
            "ok": bool(result.get("ok")),
            "command": normalized,
            "errors": [],
            "warnings": [],
            "evidence_files": result.get("evidence_files"),
            "findings": len(result.get("findings") or []),
        }
    return {
        "supported": False,
        "ok": False,
        "command": normalized,
        "errors": ["unsupported local script command"],
        "warnings": [],
    }


def runtime_run_next(root: str | Path, *, dry_run: bool = True, item_id: str | None = None) -> dict[str, Any]:
    os_root = expand_path(root)
    registry = _registry(os_root)
    queue_path = _runtime_path(os_root, RUN_QUEUE)
    queue = _queue(os_root)
    items = queue.setdefault("items", [])
    item = _dispatchable_item(items, item_id)
    if item is None:
        return {"root": str(os_root), "status": "idle", "dry_run": dry_run, "message": "no queued runtime work"}

    if item.get("status") == "approval-needed":
        return {
            "root": str(os_root),
            "status": "approval-needed",
            "dry_run": dry_run,
            "queue_item": item,
            "blocked_reason": "approval is required before dispatch",
            "external_effect": "none",
        }

    blocker = _dispatch_blocker(item, registry)
    if blocker:
        result = {
            "root": str(os_root),
            "status": "blocked",
            "dry_run": dry_run,
            "queue_item": item,
            "blocked_reason": blocker,
            "external_effect": "none",
        }
        if not dry_run:
            item["status"] = "blocked"
            item["blocked_reason"] = blocker
            item["updated_at"] = _now()
            queue["run_queue"] = items
            _write_queue(queue_path, queue)
        return result

    run_id = f"{_stamp()}-{_digest(str(item.get('id')), 8)}-dispatch"
    log_path = _runtime_path(os_root, RUNTIME_SETUP_RUN_DIR) / run_id / "run-log.yml"
    if dry_run:
        return {
            "root": str(os_root),
            "status": "would-run",
            "dry_run": True,
            "queue_item": item,
            "log": str(log_path),
            "external_effect": "none",
        }

    started_at = _now()
    execution = _run_local_script(os_root, str(item.get("command")))
    finished_at = _now()
    status = "done" if execution["supported"] and execution["ok"] else "failed"
    log = {
        "run_id": run_id,
        "kind": "runtime_dispatch",
        "queue_item_id": item.get("id"),
        "status": status,
        "approval_state": item.get("approval_state", "not_required"),
        "dry_run": False,
        "started_at": started_at,
        "finished_at": finished_at,
        "execution_target": item.get("execution_target"),
        "command": execution["command"],
        "evidence": execution,
        "external_effect": "local script validation only",
    }
    _write_yaml(log_path, log)
    item["status"] = status
    item["started_at"] = started_at
    item["finished_at"] = finished_at
    item["dispatch_log"] = str(log_path.relative_to(os_root))
    item["updated_at"] = finished_at
    item.setdefault("evidence", []).append({"type": "dispatch_log", "path": str(log_path.relative_to(os_root))})
    if status == "failed":
        item["error"] = "; ".join(execution["errors"]) or "runtime dispatch failed"
    queue["run_queue"] = items
    _write_queue(queue_path, queue)
    return {
        "root": str(os_root),
        "status": status,
        "dry_run": False,
        "queue_item": item,
        "log": str(log_path),
        "external_effect": "local script validation only",
    }


def integration_list(root: str | Path) -> dict[str, Any]:
    os_root = expand_path(root)
    registry = _integration_registry(os_root)
    return {"root": str(os_root), "integrations": registry.get("integrations") or []}


def integration_setup(root: str | Path, integration_id: str, *, dry_run: bool = True) -> dict[str, Any]:
    integration_id = validate_name(integration_id, "integration_id")
    os_root = expand_path(root)
    registry = _integration_registry(os_root)
    integration = _find_item(registry.get("integrations") or [], integration_id, "integration")
    approval_state = _approval_state({"approval_policy": {gate: True for gate in integration.get("approval_gates") or []}}, dry_run=dry_run)
    result = {
        "root": str(os_root),
        "status": "dry-run" if dry_run else "setup-recorded",
        "approval_state": approval_state,
        "integration": integration,
        "external_effect": "none" if dry_run else "local setup run log written",
    }
    if dry_run:
        return result
    run_id = f"{_stamp()}-{integration_id}-setup"
    log_path = _runtime_path(os_root, RUNTIME_SETUP_RUN_DIR) / run_id / "run-log.yml"
    _write_yaml(
        log_path,
            {
                "run_id": run_id,
                "kind": "integration_setup",
                "integration_id": integration_id,
                "status": "setup-recorded",
                "approval_state": approval_state,
                "created_at": _now(),
                "setup_tasks": integration.get("setup_tasks") or [],
                "approval_gates": integration.get("approval_gates") or [],
        },
    )
    result["log"] = str(log_path)
    return result


def _credential_findings(path: Path, item: dict[str, Any]) -> list[dict[str, str]]:
    findings = []
    credentials = item.get("credentials") or {}
    for env_var in credentials.get("env_vars") or []:
        if not os.environ.get(str(env_var)):
            findings.append(
                {
                    "severity": "fix-soon",
                    "path": str(path),
                    "message": f"credential environment variable is not set: {env_var}",
                }
            )
    return findings


def runtime_doctor(root: str | Path) -> dict[str, Any]:
    os_root = expand_path(root)
    findings: list[dict[str, str]] = []
    registry_path = _runtime_path(os_root, RUNTIME_REGISTRY)
    integration_path = _runtime_path(os_root, INTEGRATION_REGISTRY)
    queue_path = _runtime_path(os_root, RUN_QUEUE)
    for path in (registry_path, integration_path, queue_path):
        if not path.is_file():
            findings.append({"severity": "blocker", "path": str(path), "message": "required runtime state file is missing"})
    if not _runtime_path(os_root, HEARTBEAT_LOG_DIR).is_dir():
        findings.append({"severity": "blocker", "path": str(_runtime_path(os_root, HEARTBEAT_LOG_DIR)), "message": "heartbeat log folder is missing"})
    if findings:
        return {"root": str(os_root), "ok": False, "findings": findings}

    registry = _load_yaml(registry_path, DEFAULT_RUNTIME_REGISTRY)
    integration_registry = _load_yaml(integration_path, DEFAULT_INTEGRATION_REGISTRY)
    target_ids = set(_items_by_id(registry.get("execution_targets") or []))
    missing_targets = sorted(RUNTIME_REQUIRED_TARGETS - target_ids)
    for target in missing_targets:
        findings.append({"severity": "blocker", "path": str(registry_path), "message": f"missing execution target: {target}"})
    for target in registry.get("execution_targets") or []:
        for key in ("id", "display_name", "type", "status", "health_check", "notion_tracking"):
            if key not in target:
                findings.append({"severity": "blocker", "path": str(registry_path), "message": f"execution target missing {key}: {target.get('id', '<unknown>')}"})
        findings.extend(_credential_findings(registry_path, target))
    for heartbeat in registry.get("heartbeats") or []:
        for key in ("id", "display_name", "domain", "cadence", "execution_target", "integration", "approval_policy", "success_means"):
            if key not in heartbeat:
                findings.append({"severity": "blocker", "path": str(registry_path), "message": f"heartbeat missing {key}: {heartbeat.get('id', '<unknown>')}"})
        try:
            _cadence_delta(str(heartbeat.get("cadence") or ""))
        except ValueError as exc:
            findings.append({"severity": "blocker", "path": str(registry_path), "message": f"{heartbeat.get('id', '<unknown>')} {exc}"})
    for schedule in registry.get("schedules") or []:
        for key in ("id", "display_name", "enabled", "cadence", "timezone", "execution_target", "command"):
            if key not in schedule:
                findings.append({"severity": "blocker", "path": str(registry_path), "message": f"schedule missing {key}: {schedule.get('id', '<unknown>')}"})
        try:
            _cadence_delta(str(schedule.get("cadence") or ""))
            _timezone(str(schedule.get("timezone") or ""))
            _parse_time(schedule.get("next_due_at"), field=f"{schedule.get('id', '<unknown>')}.next_due_at")
        except ValueError as exc:
            findings.append({"severity": "blocker", "path": str(registry_path), "message": f"{schedule.get('id', '<unknown>')} {exc}"})
        else:
            next_due = _parse_time(schedule.get("next_due_at"), field=f"{schedule.get('id', '<unknown>')}.next_due_at")
            if schedule.get("enabled") and next_due and next_due < datetime.now(timezone.utc):
                findings.append({"severity": "fix-soon", "path": str(registry_path), "message": f"schedule is past due: {schedule.get('id')}"})

    integration_ids = set(_items_by_id(integration_registry.get("integrations") or []))
    missing_integrations = sorted(REQUIRED_INTEGRATIONS - integration_ids)
    for integration in missing_integrations:
        findings.append({"severity": "blocker", "path": str(integration_path), "message": f"missing integration: {integration}"})
    for integration in integration_registry.get("integrations") or []:
        for key in ("id", "display_name", "provider", "status", "setup_tasks", "health_checks", "approval_gates", "notion_tracking"):
            if not integration.get(key):
                findings.append({"severity": "blocker", "path": str(integration_path), "message": f"integration missing {key}: {integration.get('id', '<unknown>')}"})
        findings.extend(_credential_findings(integration_path, integration))
    queue = _normalized_queue(_load_yaml(queue_path, DEFAULT_RUN_QUEUE))
    queue_states = set(queue.get("states") or [])
    missing_states = sorted(set(RUN_QUEUE_STATES) - queue_states)
    for state in missing_states:
        findings.append({"severity": "blocker", "path": str(queue_path), "message": f"missing run queue state: {state}"})
    approval_states = set(queue.get("approval_states") or [])
    missing_approval_states = sorted(set(APPROVAL_STATES) - approval_states)
    for state in missing_approval_states:
        findings.append({"severity": "blocker", "path": str(queue_path), "message": f"missing approval state: {state}"})
    for item in queue.get("items") or []:
        item_id = item.get("id", "<unknown>")
        status = item.get("status")
        approval_state = item.get("approval_state")
        if status not in RUN_QUEUE_STATES:
            findings.append({"severity": "blocker", "path": str(queue_path), "message": f"run queue item has invalid status: {item_id}"})
        if approval_state not in APPROVAL_STATES:
            findings.append({"severity": "blocker", "path": str(queue_path), "message": f"run queue item has invalid approval_state: {item_id}"})
        if status == "approval-needed" and approval_state != "required":
            findings.append({"severity": "blocker", "path": str(queue_path), "message": f"approval-needed item must have approval_state required: {item_id}"})
        if status not in TERMINAL_RUN_QUEUE_STATES and not item.get("idempotency_key"):
            findings.append({"severity": "fix-soon", "path": str(queue_path), "message": f"non-terminal queue item lacks idempotency_key: {item_id}"})
    if not findings:
        findings.append({"severity": "observation", "path": str(os_root), "message": "runtime registries and heartbeat log folders are present"})
    return {"root": str(os_root), "ok": not any(finding["severity"] == "blocker" for finding in findings), "findings": findings}


def integration_doctor(root: str | Path, integration_id: str | None = None) -> dict[str, Any]:
    os_root = expand_path(root)
    integration_registry = _integration_registry(os_root)
    integrations = integration_registry.get("integrations") or []
    if integration_id:
        integration_id = validate_name(integration_id, "integration_id")
        integrations = [_find_item(integrations, integration_id, "integration")]
    findings = []
    for integration in integrations:
        for key in ("setup_tasks", "health_checks", "approval_gates", "notion_tracking"):
            if not integration.get(key):
                findings.append({"severity": "blocker", "path": str(_runtime_path(os_root, INTEGRATION_REGISTRY)), "message": f"{integration['id']} missing {key}"})
        findings.extend(_credential_findings(_runtime_path(os_root, INTEGRATION_REGISTRY), integration))
    if not findings:
        findings.append({"severity": "observation", "path": str(_runtime_path(os_root, INTEGRATION_REGISTRY)), "message": "integration setup contract is complete"})
    return {"root": str(os_root), "ok": not any(finding["severity"] == "blocker" for finding in findings), "findings": findings}


def build_runtime_tracking_plan(root: str | Path) -> dict[str, Any]:
    os_root = expand_path(root)
    runtime_registry = _load_yaml(_runtime_path(os_root, RUNTIME_REGISTRY), DEFAULT_RUNTIME_REGISTRY)
    integration_registry = _load_yaml(_runtime_path(os_root, INTEGRATION_REGISTRY), DEFAULT_INTEGRATION_REGISTRY)
    queue = _queue(os_root)
    records = []
    for target in runtime_registry.get("execution_targets") or []:
        records.append({"kind": "execution_target", "key": target["id"], "title": target["display_name"], "action": "create-or-update"})
    for heartbeat in runtime_registry.get("heartbeats") or []:
        records.append({"kind": "heartbeat", "key": heartbeat["id"], "title": heartbeat["display_name"], "action": "create-or-update"})
    for schedule in runtime_registry.get("schedules") or []:
        records.append({"kind": "schedule", "key": schedule["id"], "title": schedule["display_name"], "action": "create-or-update"})
    for integration in integration_registry.get("integrations") or []:
        records.append({"kind": "integration", "key": integration["id"], "title": integration["display_name"], "action": "create-or-update"})
    for item in queue.get("items") or []:
        records.append(
            {
                "kind": "run_queue_item",
                "key": item["id"],
                "title": item.get("ref") or item.get("work_type") or item["id"],
                "action": "create-or-update",
            }
        )
    for log_path in sorted(_runtime_path(os_root, HEARTBEAT_LOG_DIR).glob("*.yml"))[-20:]:
        records.append({"kind": "heartbeat_run", "key": log_path.stem, "title": log_path.stem, "path": str(log_path), "action": "create-or-update"})
    return {
        "root": str(os_root),
        "workspace": target_workspace(os_root),
        "manifest_path": str(_runtime_path(os_root, NOTION_RUNTIME_MANIFEST)),
        "databases": ["Integrations", "Execution Targets", "Heartbeats", "Schedules", "Run Queue", "Approvals", "Runs"],
        "records": records,
    }


def _load_notion_tracking_config(os_root: Path) -> dict[str, Any]:
    """Load notion-tracking.yml from the installed root's 00-control-plane."""
    from .scaffold import shared_factory_path
    config_path = shared_factory_path(os_root, "00-control-plane", "notion-tracking.yml")
    return _load_yaml(config_path, {})


def _live_notion_config(config: dict[str, Any]) -> tuple[str | None, str, str, str]:
    """Extract live-path settings from a tracking config dict.

    Returns (parent_page_id_or_None, token_env, cockpit_title, workspace).
    """
    parent_page_id = (config.get("parent_page_id") or "").strip() or None
    token_env = (config.get("token_env") or "GENOMES_NOTION_PAT").strip()
    cockpit_title = (config.get("cockpit_page_title") or "Runtime Control Plane").strip()
    workspace = (config.get("workspace") or "Genome's Notion").strip()
    return parent_page_id, token_env, cockpit_title, workspace


def _apply_runtime_tracking_live(
    os_root: Path,
    workspace: str,
    plan: dict[str, Any],
    manifest_path: Path,
    existing_manifest: dict[str, Any],
    parent_page_id: str,
    token_env: str,
    cockpit_title: str,
    fetcher: Any,
) -> dict[str, Any]:
    """Execute the live Notion path for apply_runtime_tracking.

    Verifies workspace via live API, ensures cockpit page + 7 databases exist,
    upserts all records, writes manifest with real IDs and live: true.
    """
    from .notion_api import (
        DATABASE_PROPERTY_SCHEMAS,
        _base_db_properties,
        build_record_properties,
        create_database,
        create_database_page,
        create_page,
        get_bot_workspace,
        query_database_by_key,
        search_child_databases,
        search_child_pages,
        update_database_page,
    )

    # --- live workspace verification ---
    bot_workspace = get_bot_workspace(token_env, fetcher=fetcher)
    if bot_workspace != workspace:
        raise ValueError(
            f"live API workspace mismatch: bot reports {bot_workspace!r} "
            f"but verified_workspace expects {workspace!r}; refusing Notion write"
        )

    now = _now()

    # --- cockpit page ---
    existing_cockpit_id: str | None = existing_manifest.get("cockpit_page_id")
    cockpit_id: str | None = None
    cockpit_created = False

    if existing_cockpit_id:
        cockpit_id = existing_cockpit_id
    else:
        child_pages = search_child_pages(parent_page_id, token_env, fetcher=fetcher)
        for page in child_pages:
            if page["title"] == cockpit_title:
                cockpit_id = page["id"]
                break

    if cockpit_id is None:
        cockpit_id = create_page(parent_page_id, cockpit_title, token_env, fetcher=fetcher)
        cockpit_created = True

    # --- 7 databases ---
    database_ids: dict[str, str] = {}
    databases_created = 0
    databases_reused = 0

    existing_db_ids: dict[str, str] = existing_manifest.get("database_ids") or {}

    child_dbs = search_child_databases(cockpit_id, token_env, fetcher=fetcher)
    live_db_by_title: dict[str, str] = {db["title"]: db["id"] for db in child_dbs}

    for db_name in plan["databases"]:
        db_id: str | None = existing_db_ids.get(db_name)
        if db_id:
            database_ids[db_name] = db_id
            databases_reused += 1
        elif db_name in live_db_by_title:
            database_ids[db_name] = live_db_by_title[db_name]
            databases_reused += 1
        else:
            schema = DATABASE_PROPERTY_SCHEMAS.get(db_name) or _base_db_properties()
            new_id = create_database(cockpit_id, db_name, schema, token_env, fetcher=fetcher)
            database_ids[db_name] = new_id
            databases_created += 1

    # --- kind → database name mapping ---
    KIND_TO_DATABASE: dict[str, str] = {
        "integration": "Integrations",
        "execution_target": "Execution Targets",
        "heartbeat": "Heartbeats",
        "schedule": "Schedules",
        "run_queue_item": "Run Queue",
        "approval": "Approvals",
        "heartbeat_run": "Runs",
        "run": "Runs",
    }

    # --- upsert records ---
    records_created = 0
    records_updated = 0
    records: list[dict[str, Any]] = []

    for record in plan["records"]:
        record_key = f"{record['kind']}:{record['key']}"
        record_with_key = {**record, "record_key": record_key}
        db_name = KIND_TO_DATABASE.get(record["kind"])
        if db_name is None or db_name not in database_ids:
            records.append({**record_with_key, "notion_id": _local_id(record_key)})
            continue

        db_id = database_ids[db_name]
        props = build_record_properties(record_with_key, now)
        existing_page_id = query_database_by_key(db_id, record_key, token_env, fetcher=fetcher)
        if existing_page_id:
            update_database_page(existing_page_id, props, token_env, fetcher=fetcher)
            notion_id = existing_page_id
            records_updated += 1
        else:
            notion_id = create_database_page(db_id, props, token_env, fetcher=fetcher)
            records_created += 1
        records.append({**record_with_key, "notion_id": notion_id})

    manifest = {
        "live": True,
        "workspace": workspace,
        "cockpit_page_id": cockpit_id,
        "updated_at": now,
        "databases": plan["databases"],
        "database_ids": database_ids,
        "records": records,
    }
    _write_yaml(manifest_path, manifest)

    return {
        **plan,
        "applied": True,
        "live": True,
        "cockpit_page_id": cockpit_id,
        "cockpit_created": cockpit_created,
        "databases_created": databases_created,
        "databases_reused": databases_reused,
        "records_created": records_created,
        "records_updated": records_updated,
        "database_ids": database_ids,
        "records": records,
    }


def apply_runtime_tracking(
    root: str | Path,
    *,
    verified_workspace: str | None,
    fetcher: Any = None,
) -> dict[str, Any]:
    """Apply runtime tracking — writes a local manifest or goes live to Notion.

    Live path is activated when ``harness/shared_factory/00-control-plane/
    notion-tracking.yml`` has a non-empty ``parent_page_id`` AND the token
    env var it names is set. In all other cases the local-only path is used
    and the manifest gains ``live: false``.

    The ``fetcher`` kwarg is the injectable HTTP transport used by the live
    path — pass a fake in tests to avoid network access.
    """
    os_root = expand_path(root)
    workspace = verify_workspace(os_root, verified_workspace)
    plan = build_runtime_tracking_plan(os_root)
    manifest_path = _runtime_path(os_root, NOTION_RUNTIME_MANIFEST)

    config = _load_notion_tracking_config(os_root)
    parent_page_id, token_env, cockpit_title, _config_workspace = _live_notion_config(config)

    from .notion_api import resolve_token
    token_present = resolve_token(token_env) is not None

    go_live = bool(parent_page_id and token_present)

    if go_live:
        existing_manifest: dict[str, Any] = _load_yaml(manifest_path, {})
        from . import notion_api as _notion_api
        _fetcher = fetcher if fetcher is not None else _notion_api._default_fetcher
        return _apply_runtime_tracking_live(
            os_root=os_root,
            workspace=workspace,
            plan=plan,
            manifest_path=manifest_path,
            existing_manifest=existing_manifest,
            parent_page_id=parent_page_id,
            token_env=token_env,
            cockpit_title=cockpit_title,
            fetcher=_fetcher,
        )

    # --- local path (original behaviour + live: false) ---
    database_ids = {database: _local_id(f"database:{workspace}:{database}") for database in plan["databases"]}
    records = []
    for record in plan["records"]:
        record_key = f"{record['kind']}:{record['key']}"
        records.append({**record, "notion_id": _local_id(record_key), "record_key": record_key})
    manifest = {
        "live": False,
        "workspace": workspace,
        "updated_at": _now(),
        "databases": plan["databases"],
        "database_ids": database_ids,
        "records": records,
    }
    _write_yaml(manifest_path, manifest)
    return {**plan, "applied": True, "live": False, "database_ids": database_ids, "records": records}


def format_runtime_result(result: dict[str, Any]) -> str:
    return yaml.safe_dump(result, sort_keys=False).strip()
