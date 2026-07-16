"""File-backed runtime operations for installed Agentic OS roots."""

from __future__ import annotations

from collections import Counter
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import os
from pathlib import Path
import re
import shlex
import subprocess
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml

from .lifecycle import cleanup_terminal_worktrees
from .notion_sync import target_workspace, verify_workspace
from .scaffold import expand_path, install_docs, validate_name
from .self_improvement import (
    process_self_improvement_actions,
    run_self_improvement,
    run_self_improvement_morning_report,
    self_improvement_queue_health,
)
from .thread_closeout import stale_finalize_threads
from .validate import validate_root

RUNTIME_REGISTRY = "harness/shared_factory/00-control-plane/runtime-registry.yml"
INTEGRATION_REGISTRY = "harness/shared_factory/00-control-plane/integration-registry.yml"
RUN_QUEUE = "harness/shared_factory/00-control-plane/run-queue.yml"
HEARTBEAT_LOG_DIR = "harness/shared_factory/06-runs-and-logs/heartbeats"
RUNTIME_SETUP_RUN_DIR = "harness/shared_factory/06-runs-and-logs/runs"
RUN_QUEUE_PRUNE_LOG_DIR = "harness/shared_factory/06-runs-and-logs/run-queue-prune"
ADAPTIVE_ROUTING_OBSERVATION_REPORT_DIR = (
    "harness/shared_factory/06-runs-and-logs/adaptive-routing/observation-reports/"
)
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
ACTIVE_RUN_QUEUE_STATES = {"queued", "running", "approval-needed"}
RUN_QUEUE_STALE_GRACE = timedelta(hours=24)
SAFE_DISPATCH_TARGETS = {"script"}
SCRIPT_DISPATCH_TIMEOUT_SECONDS = 900
SCRIPT_DISPATCH_OUTPUT_LIMIT = 20000
DEFAULT_RUN_QUEUE_ACTIVE_MAX_AGE_HOURS = 24
DEFAULT_RUN_QUEUE_TERMINAL_MAX_AGE_DAYS = 2
DEFAULT_RUN_QUEUE_FAILED_MAX_AGE_DAYS = 7
DEFAULT_RUN_QUEUE_SKIPPED_MAX_AGE_DAYS = 1
DEFAULT_RUN_QUEUE_BACKUP_MAX_AGE_DAYS = 7
RUNTIME_TRACKING_RUN_QUEUE_LIMIT = 50


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


def _next_due_after_catchup(base: datetime, cadence: str, timezone_name: str, now: datetime) -> str | None:
    delta = _cadence_delta(cadence)
    if delta is None:
        return None
    next_due_text = _next_due_after(base, cadence, timezone_name)
    next_due = _parse_time(next_due_text, field="next_due_at.catchup")
    if next_due is None:
        return None
    if next_due <= now:
        missed_intervals = int((now - next_due) // delta) + 1
        next_due = next_due + (delta * missed_intervals)
    return _iso(next_due)


def _local_time_parts(value: Any, *, field: str) -> tuple[int, int] | None:
    if value in (None, ""):
        return None
    match = re.fullmatch(r"([01]\d|2[0-3]):([0-5]\d)", str(value))
    if not match:
        raise ValueError(f"invalid {field}: {value}")
    return int(match.group(1)), int(match.group(2))


def _local_time_due_at(schedule: dict[str, Any], now: datetime) -> datetime | None:
    local_time = _local_time_parts(schedule.get("local_time"), field=f"{schedule.get('id', '<unknown>')}.local_time")
    if local_time is None:
        return None
    cadence = str(schedule.get("cadence") or "")
    if cadence != "daily":
        raise ValueError(f"{schedule.get('id', '<unknown>')}.local_time requires daily cadence")
    zone = _timezone(str(schedule.get("timezone") or "UTC"))
    local_now = now.astimezone(zone)
    hour, minute = local_time
    return local_now.replace(hour=hour, minute=minute, second=0, microsecond=0)


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
    if next_due is not None:
        return next_due <= now
    local_due = _local_time_due_at(schedule, now)
    if local_due is not None:
        return local_due <= now
    return True


def _due_at_for_schedule(schedule: dict[str, Any], now: datetime) -> str:
    next_due = schedule.get("next_due_at")
    if next_due:
        return str(next_due)
    local_due = _local_time_due_at(schedule, now)
    if local_due is not None:
        return _iso(local_due)
    return _due_window_start(
        now,
        str(schedule.get("cadence")),
        str(schedule.get("timezone") or "UTC"),
    )


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
            "id": "run_queue_prune_daily",
            "display_name": "Run queue prune daily",
            "enabled": True,
            "cadence": "daily",
            "timezone": "America/Chicago",
            "local_time": "00:20",
            "execution_target": "script",
            "supervisor_priority": True,
            "command": "agentic-os run-queue prune --root <root> --apply",
            "outputs": [RUN_QUEUE_PRUNE_LOG_DIR],
            "notion_update": {"object": "Runtime Queue", "status_field": "Last Pruned"},
            "next_due_at": None,
            "last_queued_at": None,
        },
        {
            "id": "queue_worker_health_report",
            "display_name": "Queue and worker health report",
            "enabled": False,
            "cadence": "hourly",
            "timezone": "America/Chicago",
            "execution_target": "script",
            "supervisor_priority": True,
            "command": "agentic-os runtime health-report --root <root> --apply-notion",
            "outputs": ["harness/shared_factory/06-runs-and-logs/runtime-health/"],
            "external_effect": "replace one verified Genome's Notion automation summary page",
            "notion_update": {
                "workspace": "Genome's Notion",
                "mode": "replace_latest",
                "requires_verified_workspace": True,
            },
            "next_due_at": None,
            "last_queued_at": None,
        },
        {
            "id": "notion_runtime_tracking",
            "display_name": "Notion runtime tracking sync",
            "enabled": True,
            "cadence": "daily",
            "timezone": "America/Chicago",
            "local_time": "00:40",
            "execution_target": "script",
            "command": 'agentic-os notion track-runtime --root <root> --apply --verified-workspace "Genome\'s Notion"',
            "outputs": [NOTION_RUNTIME_MANIFEST],
            "notion_update": {"object": "Runtime Control Plane", "status_field": "Last Runtime Sync"},
            "next_due_at": None,
            "last_queued_at": None,
        },
        {
            "id": "stale_thread_finalizer",
            "display_name": "Stale thread finalizer",
            "enabled": True,
            "cadence": "daily",
            "timezone": "America/Chicago",
            "execution_target": "script",
            "command": "agentic-os thread stale-finalize --root <root> --older-than-days 3 --apply",
            "outputs": ["harness/shared_factory/06-runs-and-logs/runs/"],
            "notion_update": {"object": "Thread Closeouts", "status_field": "Last Status"},
            "next_due_at": None,
            "last_queued_at": None,
        },
        {
            "id": "adaptive_routing_observation_report",
            "display_name": "Adaptive routing observation report",
            "enabled": False,
            "cadence": "every_12_hours",
            "timezone": "America/Chicago",
            "execution_target": "script",
            "supervisor_priority": True,
            "command": "agentic-os adaptive-routing report --root <root> --hours 12 --apply-notion",
            "outputs": [ADAPTIVE_ROUTING_OBSERVATION_REPORT_DIR],
            "external_effect": "append-only projection to verified Genome's Notion",
            "notion_update": {
                "workspace": "Genome's Notion",
                "mode": "append_only",
                "requires_verified_workspace": True,
            },
            "next_due_at": None,
            "last_queued_at": None,
        },
        {
            "id": "closed_worktree_cleanup_0500",
            "display_name": "Closed worktree cleanup 05:00",
            "enabled": True,
            "cadence": "daily",
            "timezone": "America/Chicago",
            "local_time": "05:00",
            "execution_target": "script",
            "command": "agentic-os project worktree cleanup-closed --root <root> --apply",
            "outputs": ["00-control-plane/active/", "*/02-projects/*/worktrees/closed.yml"],
            "notion_update": {"object": "OS Cleanup", "status_field": "Last Status"},
            "next_due_at": None,
            "last_queued_at": None,
        },
        {
            "id": "closed_worktree_cleanup_2200",
            "display_name": "Closed worktree cleanup 22:00",
            "enabled": True,
            "cadence": "daily",
            "timezone": "America/Chicago",
            "local_time": "22:00",
            "execution_target": "script",
            "command": "agentic-os project worktree cleanup-closed --root <root> --apply",
            "outputs": ["00-control-plane/active/", "*/02-projects/*/worktrees/closed.yml"],
            "notion_update": {"object": "OS Cleanup", "status_field": "Last Status"},
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
            "command": "agentic-os self-improvement run --root <root> --apply",
            "outputs": ["harness/shared_factory/06-runs-and-logs/self-improvement/runs/"],
            "notion_update": {"object": "Self Improvement", "status_field": "Last Status"},
            "next_due_at": None,
            "last_queued_at": None,
        },
        {
            "id": "self_improvement_action_watch",
            "display_name": "Self-improvement Notion action watch",
            "enabled": False,
            "cadence": "every_5_minutes",
            "timezone": "America/Chicago",
            "execution_target": "script",
            "command": "agentic-os self-improvement actions --root <root> --apply",
            "outputs": ["harness/shared_factory/06-runs-and-logs/self-improvement/actions/"],
            "notion_update": {"object": "Self Improvement", "status_field": "Action Status"},
            "next_due_at": None,
            "last_queued_at": None,
        },
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


def _append_queue_item_to_queue(queue: dict[str, Any], item: dict[str, Any]) -> tuple[dict[str, Any], bool]:
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
    return written, created


def _append_queue_item(root: Path, item: dict[str, Any]) -> tuple[Path, dict[str, Any], bool]:
    path = _runtime_path(root, RUN_QUEUE)
    queue = _queue(root)
    written, created = _append_queue_item_to_queue(queue, item)
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
    queue_path = _runtime_path(os_root, RUN_QUEUE)
    queue = _queue(os_root)
    queued = []
    skipped = []
    now = datetime.now(timezone.utc)
    registry_changed = False
    queue_changed = False
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
        due_at = _due_at_for_schedule(schedule, now)
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
        written_item, created = _append_queue_item_to_queue(queue, item)
        queue_changed = True
        queued.append({**written_item, "created": created})
        if not dry_run:
            schedule["last_queued_at"] = _iso(now)
            schedule["next_due_at"] = _next_due_after_catchup(
                _parse_time(due_at, field=f"{schedule_id}.due_at") or now,
                str(schedule.get("cadence")),
                str(schedule.get("timezone") or "UTC"),
                now,
            )
            registry_changed = True
    if queue_changed:
        _write_queue(queue_path, queue)
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


def _queue_item_ref(item: dict[str, Any]) -> str:
    return str(item.get("ref") or item.get("schedule_id") or item.get("work_type") or "")


def _queue_item_time(item: dict[str, Any]) -> datetime:
    for field in ("due_at", "created_at", "updated_at"):
        try:
            parsed = _parse_time(item.get(field), field=f"{item.get('id', '<unknown>')}.{field}")
        except ValueError:
            parsed = None
        if parsed:
            return parsed
    return datetime.min.replace(tzinfo=timezone.utc)


def runtime_priority_dispatch_refs(root: str | Path) -> list[str]:
    """Return schedule refs that should bypass stale generic queue backlog."""
    os_root = expand_path(root)
    registry = _registry(os_root)
    refs: list[str] = []
    for schedule in registry.get("schedules") or []:
        supervisor_config = schedule.get("supervisor") or {}
        if not isinstance(supervisor_config, dict):
            supervisor_config = {}
        if schedule.get("supervisor_priority") or supervisor_config.get("priority_dispatch"):
            schedule_id = str(schedule.get("id") or "")
            if schedule_id:
                refs.append(schedule_id)
    return refs


def runtime_run_latest_by_ref(root: str | Path, ref: str, *, dry_run: bool = True) -> dict[str, Any]:
    """Dispatch the newest queued item for a ref and supersede older duplicates.

    The normal runtime dispatcher intentionally processes a single generic queue
    item per tick. Always-on monitors can fall behind when unrelated stale items
    are ahead of them, so priority schedules use this helper to keep the newest
    queued item moving while marking older queued duplicates as skipped.
    """
    ref = validate_name(ref, "ref")
    os_root = expand_path(root)
    queue_path = _runtime_path(os_root, RUN_QUEUE)
    queue = _queue(os_root)
    items = queue.setdefault("items", [])
    candidates = [
        item
        for item in items
        if isinstance(item, dict) and item.get("status") == "queued" and _queue_item_ref(item) == ref
    ]
    if not candidates:
        return {"root": str(os_root), "status": "idle", "dry_run": dry_run, "ref": ref, "message": "no queued runtime work for ref"}

    candidates.sort(key=_queue_item_time)
    latest = candidates[-1]
    superseded = candidates[:-1]
    if dry_run:
        return {
            "root": str(os_root),
            "status": "would-run",
            "dry_run": True,
            "ref": ref,
            "queue_item": latest,
            "superseded_count": len(superseded),
            "external_effect": "none",
        }

    now = _now()
    latest_id = str(latest.get("id"))
    for item in superseded:
        item["status"] = "skipped"
        item["skipped_reason"] = f"superseded by latest queued {ref} item {latest_id}"
        item["updated_at"] = now
    if superseded:
        queue["run_queue"] = items
        _write_queue(queue_path, queue)

    result = runtime_run_next(os_root, dry_run=False, item_id=latest_id)
    result["ref"] = ref
    result["superseded_count"] = len(superseded)
    return result


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


def _dispatch_timeout_seconds(item: dict[str, Any]) -> int:
    runtime_policy = item.get("runtime_policy") or {}
    values = [
        item.get("timeout_seconds"),
        runtime_policy.get("timeout_seconds") if isinstance(runtime_policy, dict) else None,
    ]
    for value in values:
        if value is None or isinstance(value, bool):
            continue
        try:
            timeout = int(value)
        except (TypeError, ValueError):
            continue
        if timeout > 0:
            return timeout
    return SCRIPT_DISPATCH_TIMEOUT_SECONDS


def _trim_dispatch_output(value: str | bytes | None) -> str:
    if value is None:
        return ""
    text = value.decode(errors="replace") if isinstance(value, bytes) else value
    if len(text) <= SCRIPT_DISPATCH_OUTPUT_LIMIT:
        return text
    omitted = len(text) - SCRIPT_DISPATCH_OUTPUT_LIMIT
    return f"{text[:SCRIPT_DISPATCH_OUTPUT_LIMIT]}\n... <truncated {omitted} chars>"


def _runtime_subprocess_env(root: Path) -> dict[str, str]:
    """Build the stable environment inherited by runtime-dispatched workers.

    Service managers commonly start the supervisor without the interactive
    shell's user-local binary directory.  Preserve the inherited PATH, but make
    the standard user-local launcher location available to deterministic child
    scripts and the detached workers they start.
    """
    env = os.environ.copy()
    env.setdefault("AGENTIC_OS_ROOT", str(root))
    user_local_bin = str(Path.home() / ".local" / "bin")
    path_entries = [entry for entry in env.get("PATH", "").split(os.pathsep) if entry]
    if user_local_bin not in path_entries:
        path_entries.insert(0, user_local_bin)
    env["PATH"] = os.pathsep.join(path_entries)
    return env


def _run_subprocess_script(root: Path, command: str, *, timeout_seconds: int) -> dict[str, Any]:
    try:
        args = shlex.split(command)
    except ValueError as exc:
        return {
            "supported": True,
            "ok": False,
            "command": command,
            "errors": [f"invalid local script command: {exc}"],
            "warnings": [],
            "external_effect": "local script failed before execution",
        }
    if not args:
        return {
            "supported": True,
            "ok": False,
            "command": command,
            "errors": ["local script command is empty"],
            "warnings": [],
            "external_effect": "local script failed before execution",
        }

    env = _runtime_subprocess_env(root)
    try:
        completed = subprocess.run(
            args,
            cwd=root,
            env=env,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except FileNotFoundError:
        return {
            "supported": True,
            "ok": False,
            "command": command,
            "args": args,
            "cwd": str(root),
            "errors": [f"local script executable not found: {args[0]}"],
            "warnings": [],
            "external_effect": "local script failed before execution",
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "supported": True,
            "ok": False,
            "command": command,
            "args": args,
            "cwd": str(root),
            "returncode": None,
            "timeout_seconds": timeout_seconds,
            "timed_out": True,
            "stdout": _trim_dispatch_output(exc.stdout),
            "stderr": _trim_dispatch_output(exc.stderr),
            "errors": [f"local script timed out after {timeout_seconds}s"],
            "warnings": [],
            "external_effect": "local script timed out",
        }
    except OSError as exc:
        return {
            "supported": True,
            "ok": False,
            "command": command,
            "args": args,
            "cwd": str(root),
            "errors": [f"local script failed to start: {exc}"],
            "warnings": [],
            "external_effect": "local script failed before execution",
        }

    ok = completed.returncode == 0
    return {
        "supported": True,
        "ok": ok,
        "command": command,
        "args": args,
        "cwd": str(root),
        "returncode": completed.returncode,
        "timeout_seconds": timeout_seconds,
        "stdout": _trim_dispatch_output(completed.stdout),
        "stderr": _trim_dispatch_output(completed.stderr),
        "errors": [] if ok else [f"local script exited {completed.returncode}"],
        "warnings": [],
        "external_effect": "local script executed" if ok else "local script failed",
    }


def _run_local_script(
    root: Path,
    command: str,
    *,
    timeout_seconds: int = SCRIPT_DISPATCH_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    normalized = command.replace("<root>", str(root)).strip()
    if normalized in {f"agentic-os validate --root {root}", f"agentic-os validate --root {str(root)}"}:
        validation = validate_root(root)
        return {
            "supported": True,
            "ok": validation.ok,
            "command": normalized,
            "errors": validation.errors,
            "warnings": validation.warnings,
            "external_effect": "local validation completed",
        }
    watch_source_result = _run_watch_source_script(root, normalized)
    if watch_source_result is not None:
        return watch_source_result
    watcher_script_result = _run_registered_watcher_script(root, normalized, timeout_seconds=timeout_seconds)
    if watcher_script_result is not None:
        return watcher_script_result
    quiet_run_result = _run_quiet_run_script(root, normalized)
    if quiet_run_result is not None:
        return quiet_run_result
    _si_morning_persist_forms = {
        f"agentic-os self-improvement morning-report --root {root} --apply",
        f"agentic-os self-improvement morning-report --root {str(root)} --apply",
    }
    _si_morning_dry_forms = {
        f"agentic-os self-improvement morning-report --root {root}",
        f"agentic-os self-improvement morning-report --root {str(root)}",
        f"agentic-os self-improvement morning-report --root {root} --dry-run",
        f"agentic-os self-improvement morning-report --root {str(root)} --dry-run",
    }
    if normalized in _si_morning_persist_forms | _si_morning_dry_forms:
        _dry = normalized not in _si_morning_persist_forms
        try:
            result = run_self_improvement_morning_report(root, dry_run=_dry)
        except ValueError as exc:
            return {
                "supported": True,
                "ok": False,
                "command": normalized,
                "errors": [str(exc)],
                "warnings": [],
            }
        morning_report = result.get("morning_report") or {}
        notion_projection = result.get("notion_page_projection") or {}
        validation_after = result.get("validation_after") or {}
        return {
            "supported": True,
            "ok": bool(result.get("ok")),
            "command": normalized,
            "errors": [],
            "warnings": validation_after.get("warnings") or [],
            "validation_errors": validation_after.get("error_count"),
            "repairs_applied": (result.get("repair") or {}).get("applied_count"),
            "report_path": morning_report.get("report"),
            "logs_path": morning_report.get("logs"),
            "notion_projected": bool(notion_projection.get("projected")),
        }
    _si_action_persist_forms = {
        f"agentic-os self-improvement actions --root {root} --apply",
        f"agentic-os self-improvement actions --root {str(root)} --apply",
    }
    _si_action_dry_forms = {
        f"agentic-os self-improvement actions --root {root}",
        f"agentic-os self-improvement actions --root {str(root)}",
        f"agentic-os self-improvement actions --root {root} --dry-run",
        f"agentic-os self-improvement actions --root {str(root)} --dry-run",
    }
    if normalized in _si_action_persist_forms | _si_action_dry_forms:
        _dry = normalized not in _si_action_persist_forms
        result = process_self_improvement_actions(root, dry_run=_dry)
        return {
            "supported": True,
            "ok": bool(result.get("ok")),
            "command": normalized,
            "errors": [] if result.get("ok") else [str(result.get("reason") or "self-improvement action watcher failed")],
            "warnings": [],
            "status": result.get("status"),
            "actions": len(result.get("actions") or []),
            "queued": len(result.get("queued") or []),
            "skipped": len(result.get("skipped") or []),
        }
    _si_persist_forms = {
        f"agentic-os self-improvement run --root {root} --apply",
        f"agentic-os self-improvement run --root {str(root)} --apply",
    }
    _si_dry_forms = {
        f"agentic-os self-improvement run --root {root}",
        f"agentic-os self-improvement run --root {str(root)}",
        f"agentic-os self-improvement run --root {root} --dry-run",
        f"agentic-os self-improvement run --root {str(root)} --dry-run",
    }
    if normalized in _si_persist_forms | _si_dry_forms:
        _dry = normalized not in _si_persist_forms
        try:
            result = run_self_improvement(root, dry_run=_dry)
        except ValueError as exc:
            return {
                "supported": True,
                "ok": False,
                "command": normalized,
                "errors": [str(exc)],
                "warnings": [],
            }
        report = result.get("report") or {}
        notion_projection = result.get("notion_projection") or {}
        return {
            "supported": True,
            "ok": bool(result.get("ok")),
            "command": normalized,
            "errors": [],
            "warnings": [],
            "evidence_files": result.get("evidence_files"),
            "findings": len(result.get("findings") or []),
            "report_path": report.get("latest"),
            "notion_projected": bool(notion_projection.get("projected")),
        }
    if normalized in {
        f"agentic-os thread stale-finalize --root {root} --older-than-days 3 --apply",
        f"agentic-os thread stale-finalize --root {str(root)} --older-than-days 3 --apply",
    }:
        result = stale_finalize_threads(root, older_than_days=3, apply=True)
        return {
            "supported": True,
            "ok": bool(result.get("ok")),
            "command": normalized,
            "errors": [],
            "warnings": [],
            "candidate_count": result.get("candidate_count"),
            "applied_count": len(result.get("applied") or []),
        }
    if normalized in {
        f"agentic-os project worktree cleanup-closed --root {root} --apply",
        f"agentic-os project worktree cleanup-closed --root {str(root)} --apply",
    }:
        result = cleanup_terminal_worktrees(root, apply=True, remove_files=False)
        return {
            "supported": True,
            "ok": True,
            "command": normalized,
            "errors": [],
            "warnings": [],
            "candidate_count": result.get("candidate_count"),
            "closed_count": len(result.get("closed") or []),
            "skipped_count": len(result.get("skipped") or []),
        }
    if normalized in {
        f"agentic-os automation-control run --root {root} --apply",
        f"agentic-os automation-control run --root {str(root)} --apply",
    }:
        from .automation_control import run_automation_control

        result = run_automation_control(root, dry_run=False)
        enqueued_count = len([action for action in result.get("actions") or [] if action.get("action") == "enqueued"])
        return {
            "supported": True,
            "ok": True,
            "command": normalized,
            "errors": [],
            "warnings": [],
            "receipt": result.get("receipt"),
            "enqueued_count": enqueued_count,
        }
    if normalized.startswith("agentic-os watch-source poll ") and normalized.endswith(f" --root {root} --apply"):
        from .source_watch import poll_watch_source

        parts = normalized.split()
        if len(parts) == 7:
            source_id = parts[3]
            result = poll_watch_source(root, source_id, dry_run=False)
            return {
                "supported": True,
                "ok": bool(result.get("ok")),
                "command": normalized,
                "errors": [] if result.get("ok") else [
                    finding.get("message", "watch-source poll failed")
                    for finding in result.get("findings") or []
                ],
                "warnings": [],
                "source_id": source_id,
                "events_count": len(result.get("events") or []),
                "trigger_actions_count": len(result.get("trigger_actions") or []),
            }
    return _run_subprocess_script(root, normalized, timeout_seconds=timeout_seconds)


def _local_script_dispatch_preflight(root: Path, command: str) -> str | None:
    """Return a dispatch blocker that can be detected without executing scripts."""
    normalized = command.replace("<root>", str(root)).strip()
    supported_exact = {
        f"agentic-os validate --root {root}",
        f"agentic-os validate --root {str(root)}",
        f"agentic-os self-improvement morning-report --root {root} --apply",
        f"agentic-os self-improvement morning-report --root {str(root)} --apply",
        f"agentic-os self-improvement morning-report --root {root}",
        f"agentic-os self-improvement morning-report --root {str(root)}",
        f"agentic-os self-improvement morning-report --root {root} --dry-run",
        f"agentic-os self-improvement morning-report --root {str(root)} --dry-run",
        f"agentic-os self-improvement run --root {root} --apply",
        f"agentic-os self-improvement run --root {str(root)} --apply",
        f"agentic-os self-improvement run --root {root}",
        f"agentic-os self-improvement run --root {str(root)}",
        f"agentic-os self-improvement run --root {root} --dry-run",
        f"agentic-os self-improvement run --root {str(root)} --dry-run",
        f"agentic-os self-improvement actions --root {root} --apply",
        f"agentic-os self-improvement actions --root {str(root)} --apply",
        f"agentic-os self-improvement actions --root {root}",
        f"agentic-os self-improvement actions --root {str(root)}",
        f"agentic-os self-improvement actions --root {root} --dry-run",
        f"agentic-os self-improvement actions --root {str(root)} --dry-run",
        f"agentic-os thread stale-finalize --root {root} --older-than-days 3 --apply",
        f"agentic-os thread stale-finalize --root {str(root)} --older-than-days 3 --apply",
        f"agentic-os project worktree cleanup-closed --root {root} --apply",
        f"agentic-os project worktree cleanup-closed --root {str(root)} --apply",
        f"agentic-os automation-control run --root {root} --apply",
        f"agentic-os automation-control run --root {str(root)} --apply",
        f"agentic-os runtime health-report --root {root} --apply-notion",
        f"agentic-os runtime health-report --root {str(root)} --apply-notion",
    }
    if normalized in supported_exact:
        return None
    try:
        parts = shlex.split(normalized)
    except ValueError as exc:
        return f"invalid local script command: {exc}"
    if len(parts) >= 3 and parts[:2] == ["agentic-os", "watch-source"] and parts[2] in {"poll", "run-due"}:
        return None
    watcher_script = _parse_registered_watcher_script(root, normalized)
    if watcher_script is not None:
        return watcher_script if isinstance(watcher_script, str) else None
    quiet_run = root / "harness" / "bin" / "agentic-os-quiet-run"
    if len(parts) >= 2 and parts[0] in {str(quiet_run), "harness/bin/agentic-os-quiet-run"} and parts[1] == "start":
        return None
    if not parts:
        return "local script command is empty"
    return None


def _run_watch_source_script(root: Path, command: str) -> dict[str, Any] | None:
    try:
        parts = shlex.split(command)
    except ValueError as exc:
        return {
            "supported": True,
            "ok": False,
            "command": command,
            "errors": [f"invalid watch-source command: {exc}"],
            "warnings": [],
        }
    if len(parts) < 3 or parts[:2] != ["agentic-os", "watch-source"]:
        return None

    mode = parts[2]
    if mode not in {"poll", "run-due"}:
        return None

    source_id: str | None = None
    command_root = root
    apply = False
    dry_run_flag = False
    index = 3
    if mode == "poll":
        if index >= len(parts) or parts[index].startswith("-"):
            return {
                "supported": True,
                "ok": False,
                "command": command,
                "errors": ["watch-source poll command is missing source_id"],
                "warnings": [],
            }
        source_id = parts[index]
        index += 1
    while index < len(parts):
        token = parts[index]
        if token == "--root":
            index += 1
            if index >= len(parts):
                return {
                    "supported": True,
                    "ok": False,
                    "command": command,
                    "errors": ["watch-source command is missing --root value"],
                    "warnings": [],
                }
            command_root = expand_path(parts[index])
        elif token == "--apply":
            apply = True
        elif token == "--dry-run":
            dry_run_flag = True
        else:
            return {
                "supported": True,
                "ok": False,
                "command": command,
                "errors": [f"unsupported watch-source argument: {token}"],
                "warnings": [],
            }
        index += 1
    if command_root != root:
        return {
            "supported": True,
            "ok": False,
            "command": command,
            "errors": [f"watch-source root mismatch: {command_root}"],
            "warnings": [],
        }

    from .source_watch import poll_watch_source, run_due_watch_sources

    try:
        result = (
            poll_watch_source(root, str(source_id), dry_run=not apply)
            if mode == "poll"
            else run_due_watch_sources(root, dry_run=not apply)
        )
    except ValueError as exc:
        return {
            "supported": True,
            "ok": False,
            "command": command,
            "errors": [str(exc)],
            "warnings": [],
        }
    ok = bool(result.get("ok", True))
    if mode == "run-due":
        ok = all(action.get("ok", True) for action in result.get("actions", []))
    warnings: list[str] = []
    if dry_run_flag and apply:
        warnings.append("both --dry-run and --apply were present; --apply took precedence")
    return {
        "supported": True,
        "ok": ok,
        "command": command,
        "errors": [] if ok else [str(result.get("findings") or result)],
        "warnings": warnings,
        "watch_source": result,
    }


def _parse_registered_watcher_script(root: Path, command: str) -> list[str] | str | None:
    try:
        parts = shlex.split(command)
    except ValueError as exc:
        return f"invalid watcher script command: {exc}"
    if not parts or parts[0] not in {"python", "python3"}:
        return None
    if len(parts) < 2:
        return None

    script = expand_path(parts[1])
    watchers_root = (root / "watchers").resolve()
    try:
        script.resolve().relative_to(watchers_root)
    except ValueError:
        return None

    if len(parts) != 3 or parts[2] != "--once":
        return "watcher script dispatch only supports: python3 <root>/watchers/<id>/scripts/<script>.py --once"
    if script.parent.name != "scripts" or script.suffix != ".py":
        return "watcher script must be a Python file under <root>/watchers/<id>/scripts/"
    watcher_dir = script.parent.parent
    if not (watcher_dir / "watcher.yml").is_file():
        return f"watcher config not found: {watcher_dir / 'watcher.yml'}"
    if not script.is_file():
        return f"watcher script not found: {script}"
    return [parts[0], str(script), "--once"]


def _run_registered_watcher_script(
    root: Path,
    command: str,
    *,
    timeout_seconds: int = SCRIPT_DISPATCH_TIMEOUT_SECONDS,
) -> dict[str, Any] | None:
    parsed = _parse_registered_watcher_script(root, command)
    if parsed is None:
        return None
    if isinstance(parsed, str):
        return {
            "supported": True,
            "ok": False,
            "command": command,
            "errors": [parsed],
            "warnings": [],
        }
    try:
        completed = subprocess.run(
            parsed,
            cwd=root,
            env=_runtime_subprocess_env(root),
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "supported": True,
            "ok": False,
            "command": command,
            "timeout_seconds": timeout_seconds,
            "timed_out": True,
            "stdout": _trim_dispatch_output(exc.stdout),
            "stderr": _trim_dispatch_output(exc.stderr),
            "errors": [f"watcher script timed out after {timeout_seconds}s"],
            "warnings": [],
        }
    except Exception as exc:  # pragma: no cover - defensive CLI boundary
        return {
            "supported": True,
            "ok": False,
            "command": command,
            "errors": [repr(exc)],
            "warnings": [],
        }
    return {
        "supported": True,
        "ok": completed.returncode == 0,
        "command": command,
        "errors": [] if completed.returncode == 0 else [completed.stderr.strip() or completed.stdout.strip()],
        "warnings": [],
        "timeout_seconds": timeout_seconds,
        "stdout": completed.stdout.strip(),
        "stderr": completed.stderr.strip(),
        "exit_code": completed.returncode,
    }


def _run_quiet_run_script(root: Path, command: str) -> dict[str, Any] | None:
    try:
        parts = shlex.split(command)
    except ValueError as exc:
        return {
            "supported": True,
            "ok": False,
            "command": command,
            "errors": [f"invalid quiet-run command: {exc}"],
            "warnings": [],
        }
    if not parts:
        return None
    quiet_run = root / "harness" / "bin" / "agentic-os-quiet-run"
    if parts[0] not in {str(quiet_run), "harness/bin/agentic-os-quiet-run"}:
        return None
    if len(parts) < 2 or parts[1] != "start":
        return {
            "supported": True,
            "ok": False,
            "command": command,
            "errors": ["only agentic-os-quiet-run start is supported by runtime dispatch"],
            "warnings": [],
        }
    resolved_parts = [str(quiet_run), *parts[1:]]
    try:
        completed = subprocess.run(
            resolved_parts,
            cwd=root,
            env=_runtime_subprocess_env(root),
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except Exception as exc:  # pragma: no cover - defensive CLI boundary
        return {
            "supported": True,
            "ok": False,
            "command": command,
            "errors": [repr(exc)],
            "warnings": [],
        }
    return {
        "supported": True,
        "ok": completed.returncode == 0,
        "command": command,
        "errors": [] if completed.returncode == 0 else [completed.stderr.strip() or completed.stdout.strip()],
        "warnings": [],
        "stdout": completed.stdout.strip(),
        "stderr": completed.stderr.strip(),
        "exit_code": completed.returncode,
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
    relative_log_path = str(log_path.relative_to(os_root))
    timeout_seconds = _dispatch_timeout_seconds(item)
    item["status"] = "running"
    item["started_at"] = started_at
    item["dispatch_log"] = relative_log_path
    item["updated_at"] = started_at
    queue["run_queue"] = items
    _write_queue(queue_path, queue)

    execution = _run_local_script(os_root, str(item.get("command")), timeout_seconds=timeout_seconds)
    finished_at = _now()
    status = "done" if execution["supported"] and execution["ok"] else "failed"
    external_effect = execution.get("external_effect") or ("local script executed" if execution.get("ok") else "local script failed")
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
        "external_effect": external_effect,
    }
    _write_yaml(log_path, log)
    item["status"] = status
    item["started_at"] = started_at
    item["finished_at"] = finished_at
    item["dispatch_log"] = relative_log_path
    item["updated_at"] = finished_at
    item["external_effect"] = external_effect
    item.setdefault("evidence", []).append({"type": "dispatch_log", "path": relative_log_path})
    if status == "failed":
        item["error"] = "; ".join(execution["errors"]) or "runtime dispatch failed"
    else:
        item.pop("error", None)
    queue["run_queue"] = items
    _write_queue(queue_path, queue)
    return {
        "root": str(os_root),
        "status": status,
        "dry_run": False,
        "queue_item": item,
        "log": str(log_path),
        "external_effect": external_effect,
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


def _queue_status_counts(items: list[dict[str, Any]]) -> dict[str, int]:
    return dict(Counter(str(item.get("status") or "<missing>") for item in items))


def _raw_queue_items(queue: dict[str, Any]) -> list[dict[str, Any]]:
    items = queue.get("items")
    if not isinstance(items, list):
        items = queue.get("run_queue") if isinstance(queue.get("run_queue"), list) else []
    return [item for item in items if isinstance(item, dict)]


def _queue_time(item: dict[str, Any], field: str) -> datetime | None:
    try:
        return _parse_time(item.get(field), field=f"{item.get('id', '<unknown>')}.{field}")
    except ValueError:
        return None


def _run_queue_stale_reason(item: dict[str, Any], now: datetime) -> str | None:
    due_at = _queue_time(item, "due_at")
    if due_at and now - due_at > RUN_QUEUE_STALE_GRACE:
        return "due_at_past_24h_grace"
    updated_at = _queue_time(item, "updated_at")
    if updated_at and now - updated_at > RUN_QUEUE_STALE_GRACE:
        return "updated_past_24h_grace"
    created_at = _queue_time(item, "created_at")
    if created_at and now - created_at > RUN_QUEUE_STALE_GRACE:
        return "created_past_24h_grace"
    return None


def _run_queue_prune_time(item: dict[str, Any], status: str) -> datetime | None:
    fields_by_status = {
        "queued": ("due_at", "updated_at", "created_at"),
        "approval-needed": ("due_at", "updated_at", "created_at"),
        "running": ("updated_at", "started_at", "created_at"),
        "done": ("finished_at", "updated_at", "created_at"),
        "failed": ("finished_at", "updated_at", "created_at"),
        "blocked": ("updated_at", "created_at"),
        "skipped": ("updated_at", "created_at"),
        "dry-run": ("updated_at", "created_at"),
    }
    for field in fields_by_status.get(status, ("updated_at", "created_at")):
        parsed = _queue_time(item, field)
        if parsed is not None:
            return parsed
    return None


def _run_queue_prune_reason(
    item: dict[str, Any],
    now: datetime,
    *,
    active_max_age_hours: int,
    terminal_max_age_days: int,
    failed_max_age_days: int,
    skipped_max_age_days: int,
) -> str | None:
    status = str(item.get("status") or "")
    reference_time = _run_queue_prune_time(item, status)
    if reference_time is None:
        return None
    age = now - reference_time
    if status in {"queued", "approval-needed", "running"} and age > timedelta(hours=active_max_age_hours):
        return f"{status}_older_than_{active_max_age_hours}h"
    if status in {"failed", "blocked"} and age > timedelta(days=failed_max_age_days):
        return f"{status}_older_than_{failed_max_age_days}d"
    if status in {"skipped", "dry-run"} and age > timedelta(days=skipped_max_age_days):
        return f"{status}_older_than_{skipped_max_age_days}d"
    if status == "done" and age > timedelta(days=terminal_max_age_days):
        return f"{status}_older_than_{terminal_max_age_days}d"
    return None


def _stale_run_queue_backups(queue_path: Path, now: datetime, max_age_days: int) -> list[dict[str, Any]]:
    stale: list[dict[str, Any]] = []
    for path in sorted(queue_path.parent.glob("run-queue.yml.backup*")):
        try:
            age_days = (now.timestamp() - path.stat().st_mtime) / 86400.0
        except OSError:
            continue
        if age_days > max_age_days:
            stale.append(
                {
                    "path": str(path),
                    "name": path.name,
                    "size_bytes": path.stat().st_size,
                    "age_days": round(age_days, 1),
                }
            )
    return stale


def run_queue_prune(
    root: str | Path,
    *,
    dry_run: bool = True,
    active_max_age_hours: int = DEFAULT_RUN_QUEUE_ACTIVE_MAX_AGE_HOURS,
    terminal_max_age_days: int = DEFAULT_RUN_QUEUE_TERMINAL_MAX_AGE_DAYS,
    failed_max_age_days: int = DEFAULT_RUN_QUEUE_FAILED_MAX_AGE_DAYS,
    skipped_max_age_days: int = DEFAULT_RUN_QUEUE_SKIPPED_MAX_AGE_DAYS,
    backup_max_age_days: int = DEFAULT_RUN_QUEUE_BACKUP_MAX_AGE_DAYS,
    archive: bool = True,
) -> dict[str, Any]:
    for name, value in {
        "active_max_age_hours": active_max_age_hours,
        "terminal_max_age_days": terminal_max_age_days,
        "failed_max_age_days": failed_max_age_days,
        "skipped_max_age_days": skipped_max_age_days,
        "backup_max_age_days": backup_max_age_days,
    }.items():
        if value < 0:
            raise ValueError(f"{name} must be non-negative")

    os_root = expand_path(root)
    queue_path = _runtime_path(os_root, RUN_QUEUE)
    raw_queue = _load_yaml(queue_path, DEFAULT_RUN_QUEUE)
    queue = _normalized_queue(raw_queue)
    items = queue.get("items") or []
    now = datetime.now(timezone.utc)
    kept: list[dict[str, Any]] = []
    pruned: list[dict[str, Any]] = []
    prune_reasons: Counter[str] = Counter()
    for item in items:
        if not isinstance(item, dict):
            continue
        reason = _run_queue_prune_reason(
            item,
            now,
            active_max_age_hours=active_max_age_hours,
            terminal_max_age_days=terminal_max_age_days,
            failed_max_age_days=failed_max_age_days,
            skipped_max_age_days=skipped_max_age_days,
        )
        if reason:
            pruned_item = deepcopy(item)
            pruned_item["prune_reason"] = reason
            pruned.append(pruned_item)
            prune_reasons[reason] += 1
        else:
            kept.append(item)

    stale_backups = _stale_run_queue_backups(queue_path, now, backup_max_age_days)
    run_id = f"{_stamp()}-{_digest(str(queue_path), 8)}-run-queue-prune"
    log_path = _runtime_path(os_root, RUN_QUEUE_PRUNE_LOG_DIR) / f"{run_id}.yml"
    result: dict[str, Any] = {
        "root": str(os_root),
        "status": "would-prune" if dry_run and (pruned or stale_backups) else ("pruned" if pruned or stale_backups else "idle"),
        "dry_run": dry_run,
        "run_queue": str(queue_path),
        "retention": {
            "active_max_age_hours": active_max_age_hours,
            "terminal_max_age_days": terminal_max_age_days,
            "failed_max_age_days": failed_max_age_days,
            "skipped_max_age_days": skipped_max_age_days,
            "backup_max_age_days": backup_max_age_days,
            "archive": archive,
        },
        "counts": {"before": len(items), "after": len(kept), "pruned": len(pruned)},
        "status_counts_before": _queue_status_counts(items),
        "status_counts_after": _queue_status_counts(kept),
        "pruned_counts_by_status": _queue_status_counts(pruned),
        "pruned_counts_by_reason": dict(prune_reasons),
        "sample_pruned_ids": [str(item.get("id") or "<unknown>") for item in pruned[:10]],
        "stale_backup_files": {
            "count": len(stale_backups),
            "sample": stale_backups[:10],
            "removed": [] if dry_run else [entry["path"] for entry in stale_backups],
        },
        "archive_log": str(log_path) if archive and (not dry_run or pruned) else None,
        "external_effect": "none" if dry_run else "local run queue rewritten; stale run-queue backups removed",
    }
    if dry_run:
        return result

    if archive and pruned:
        _write_yaml(
            log_path,
            {
                "run_id": run_id,
                "kind": "run_queue_prune",
                "status": "pruned",
                "created_at": _now(),
                "retention": result["retention"],
                "counts": result["counts"],
                "status_counts_before": result["status_counts_before"],
                "status_counts_after": result["status_counts_after"],
                "pruned_counts_by_status": result["pruned_counts_by_status"],
                "pruned_counts_by_reason": result["pruned_counts_by_reason"],
                "pruned_items": pruned,
            },
        )
    queue["items"] = kept
    queue["run_queue"] = kept
    _write_queue(queue_path, queue)
    removed_backups = []
    for entry in stale_backups:
        path = Path(str(entry["path"]))
        try:
            path.unlink()
        except FileNotFoundError:
            continue
        removed_backups.append(str(path))
    result["stale_backup_files"]["removed"] = removed_backups
    return result


def _queue_label(item: dict[str, Any]) -> str:
    return str(item.get("ref") or item.get("work_type") or item.get("kind") or "<unknown>")


def _sample_ids(ids: list[str], *, limit: int = 5) -> str:
    sample = ", ".join(ids[:limit])
    suffix = "" if len(ids) <= limit else f", +{len(ids) - limit} more"
    return f"count={len(ids)}; sample={sample}{suffix}"


def _short_text(value: str, *, limit: int = 100) -> str:
    one_line = " ".join(value.split())
    if len(one_line) <= limit:
        return one_line
    return f"{one_line[: limit - 3]}..."


def _short_command(command: str, *, limit: int = 100) -> str:
    return _short_text(command, limit=limit)


def _run_queue_health_findings(
    os_root: Path,
    *,
    registry: dict[str, Any],
    raw_queue: dict[str, Any],
    queue: dict[str, Any],
) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    queue_path = _runtime_path(os_root, RUN_QUEUE)
    now = datetime.now(timezone.utc)
    raw_items = _raw_queue_items(raw_queue)
    active_items = [
        item
        for item in queue.get("items") or []
        if isinstance(item, dict) and item.get("status") in ACTIVE_RUN_QUEUE_STATES
    ]

    duplicate_keys: dict[str, list[str]] = {}
    for item in raw_items:
        if item.get("status") not in ACTIVE_RUN_QUEUE_STATES:
            continue
        key = item.get("idempotency_key")
        if not key:
            continue
        duplicate_keys.setdefault(str(key), []).append(str(item.get("id") or "<unknown>"))
    for key, ids in sorted(duplicate_keys.items()):
        if len(ids) > 1:
            findings.append(
                {
                    "severity": "fix-soon",
                    "path": str(queue_path),
                    "message": f"duplicate active run queue idempotency_key: {key} ({_sample_ids(ids)})",
                }
            )

    schedule_ids = set(_items_by_id(registry.get("schedules") or []))
    active_schedule_refs: dict[str, list[str]] = {}
    unknown_schedule_refs: dict[str, list[str]] = {}
    for item in active_items:
        if item.get("kind") != "schedule":
            continue
        ref = str(item.get("ref") or item.get("schedule_id") or "<unknown>")
        active_schedule_refs.setdefault(ref, []).append(str(item.get("id") or "<unknown>"))
        if ref not in schedule_ids:
            unknown_schedule_refs.setdefault(ref, []).append(str(item.get("id") or "<unknown>"))
    for ref, ids in sorted(unknown_schedule_refs.items()):
        findings.append(
            {
                "severity": "fix-soon",
                "path": str(queue_path),
                "message": f"schedule queue items reference unknown schedule: {ref} ({_sample_ids(ids)})",
            }
        )
    for ref, ids in sorted(active_schedule_refs.items()):
        if len(ids) > 1:
            findings.append(
                {
                    "severity": "fix-soon",
                    "path": str(queue_path),
                    "message": f"multiple active schedule queue items: {ref} ({_sample_ids(ids)})",
                }
            )

    failed_items: dict[str, list[str]] = {}
    blocked_items: dict[str, list[str]] = {}
    stale_items: dict[tuple[str, str, str], list[str]] = {}
    missing_command_items: dict[str, list[str]] = {}
    unsupported_command_items: dict[tuple[str, str, str], list[str]] = {}
    for item in queue.get("items") or []:
        if not isinstance(item, dict):
            continue
        item_id = str(item.get("id") or "<unknown>")
        label = _queue_label(item)
        status = str(item.get("status") or "")
        if status == "failed":
            reason = str(item.get("error") or item.get("blocked_reason") or item.get("dispatch_log") or "no failure detail")
            failed_items.setdefault(_short_text(reason, limit=180), []).append(item_id)
        elif status == "blocked":
            reason = str(item.get("blocked_reason") or item.get("error") or "no blocker detail")
            blocked_items.setdefault(_short_text(reason, limit=180), []).append(item_id)

        if status in ACTIVE_RUN_QUEUE_STATES:
            stale_reason = _run_queue_stale_reason(item, now)
            if stale_reason:
                stale_items.setdefault((status, label, stale_reason), []).append(item_id)

            target_id = str(item.get("execution_target") or "script")
            if target_id == "script":
                command = item.get("command")
                if not command:
                    missing_command_items.setdefault(label, []).append(item_id)
                else:
                    blocker = _local_script_dispatch_preflight(os_root, str(command))
                    if blocker:
                        key = (label, blocker, _short_command(str(command)))
                        unsupported_command_items.setdefault(key, []).append(item_id)

    for reason, ids in sorted(failed_items.items()):
        findings.append(
            {
                "severity": "fix-soon",
                "path": str(queue_path),
                "message": f"run queue items failed: {reason} ({_sample_ids(ids)})",
            }
        )
    for reason, ids in sorted(blocked_items.items()):
        findings.append(
            {
                "severity": "fix-soon",
                "path": str(queue_path),
                "message": f"run queue items blocked: {reason} ({_sample_ids(ids)})",
            }
        )
    for (status, label, stale_reason), ids in sorted(stale_items.items()):
        findings.append(
            {
                "severity": "fix-soon",
                "path": str(queue_path),
                "message": f"{status} run queue items are stale: {label} {stale_reason} ({_sample_ids(ids)})",
            }
        )
    for label, ids in sorted(missing_command_items.items()):
        findings.append(
            {
                "severity": "fix-soon",
                "path": str(queue_path),
                "message": f"script queue items have no command: {label} ({_sample_ids(ids)})",
            }
        )
    for (label, blocker, command), ids in sorted(unsupported_command_items.items()):
        findings.append(
            {
                "severity": "fix-soon",
                "path": str(queue_path),
                "message": (
                    "script commands are unsupported by runtime dispatch: "
                    f"{label} ({blocker}; command={command!r}; {_sample_ids(ids)})"
                ),
            }
        )
    return findings


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


SELF_IMPROVEMENT_CONFIG = "harness/shared_factory/00-control-plane/self-improvement.yml"
SELF_IMPROVEMENT_OUTPUT = "harness/shared_factory/06-runs-and-logs/self-improvement"
SELF_IMPROVEMENT_REPORT = f"{SELF_IMPROVEMENT_OUTPUT}/latest-report.md"
SELF_IMPROVEMENT_RUNS = f"{SELF_IMPROVEMENT_OUTPUT}/runs"
REPORT_STALE_DAYS = 2


def _self_improvement_doctor_findings(os_root: Path) -> list[dict[str, str]]:
    """Heartbeat health checks for the self-improvement documentation loop.

    All findings are advisory (``fix-soon``/``observation``) so they surface in
    the doctor report without flipping ``ok`` to False. Each check is gated on the
    existence of its inputs so a fresh install missing these files is silent.
    """
    findings: list[dict[str, str]] = []
    config_path = _runtime_path(os_root, SELF_IMPROVEMENT_CONFIG)
    if not config_path.is_file():
        return findings
    config = _load_yaml(config_path, {})

    # 1. Enabled but never ran (no run records present).
    runs_dir = _runtime_path(os_root, SELF_IMPROVEMENT_RUNS)
    has_run = runs_dir.is_dir() and any(runs_dir.glob("*.yml"))
    if config.get("enabled") and not has_run:
        findings.append(
            {
                "severity": "fix-soon",
                "path": str(runs_dir),
                "message": "self-improvement is enabled but has never produced a run record",
            }
        )

    # 2. latest-report.md missing or stale (>REPORT_STALE_DAYS old) once enabled.
    report_path = _runtime_path(os_root, SELF_IMPROVEMENT_REPORT)
    if config.get("enabled"):
        if not report_path.is_file():
            if has_run:
                findings.append(
                    {
                        "severity": "fix-soon",
                        "path": str(report_path),
                        "message": "self-improvement has run records but no latest-report.md",
                    }
                )
        else:
            age_days = (datetime.now(timezone.utc).timestamp() - report_path.stat().st_mtime) / 86400.0
            if age_days > REPORT_STALE_DAYS:
                findings.append(
                    {
                        "severity": "fix-soon",
                        "path": str(report_path),
                        "message": f"self-improvement latest-report.md is stale ({age_days:.1f} days old)",
                    }
                )

    # 3. Missing "Self Improvement" Notion DB id in the runtime tracking manifest.
    manifest_path = _runtime_path(os_root, NOTION_RUNTIME_MANIFEST)
    if manifest_path.is_file():
        manifest = _load_yaml(manifest_path, {})
        if manifest.get("live") and not (manifest.get("database_ids") or {}).get("Self Improvement"):
            findings.append(
                {
                    "severity": "fix-soon",
                    "path": str(manifest_path),
                    "message": "Notion runtime tracking is live but has no 'Self Improvement' database id",
                }
            )

    # 4. Configured conversation evidence roots that resolve to a missing dir.
    for entry in config.get("evidence_roots") or []:
        if not isinstance(entry, dict):
            continue
        path_value = str(entry.get("path") or "")
        if "conversations" not in path_value:
            continue
        resolved = _runtime_path(os_root, path_value)
        if not resolved.exists():
            findings.append(
                {
                    "severity": "observation",
                    "path": str(resolved),
                    "message": f"configured conversation evidence root is missing: {path_value}",
                }
            )
    for item in self_improvement_queue_health(os_root).get("stale_items") or []:
        findings.append(
            {
                "severity": "fix-soon",
                "path": str(_runtime_path(os_root, RUN_QUEUE)),
                "message": (
                    "self-improvement review queue item is stale: "
                    f"{item.get('id')} ({item.get('stale_reason')})"
                ),
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
            _local_time_due_at(schedule, datetime.now(timezone.utc))
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
    raw_queue = _load_yaml(queue_path, DEFAULT_RUN_QUEUE)
    queue = _normalized_queue(raw_queue)
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
    findings.extend(_run_queue_health_findings(os_root, registry=registry, raw_queue=raw_queue, queue=queue))
    findings.extend(_self_improvement_doctor_findings(os_root))
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


def _runtime_tracking_queue_items(queue: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the bounded queue slice worth projecting to Notion.

    Runtime tracking is an operator cockpit, not a historical queue archive. Keep
    active work visible first, then fill the remaining space with the newest
    terminal records so live Notion syncs stay bounded.
    """
    items = [item for item in queue.get("items") or [] if isinstance(item, dict)]
    active = [item for item in items if item.get("status") in ACTIVE_RUN_QUEUE_STATES]
    terminal = [item for item in items if item.get("status") not in ACTIVE_RUN_QUEUE_STATES]

    active.sort(key=_queue_item_time, reverse=True)
    terminal.sort(key=_queue_item_time, reverse=True)

    selected = active[:RUNTIME_TRACKING_RUN_QUEUE_LIMIT]
    if len(selected) < RUNTIME_TRACKING_RUN_QUEUE_LIMIT:
        selected.extend(terminal[: RUNTIME_TRACKING_RUN_QUEUE_LIMIT - len(selected)])
    return selected


def build_runtime_tracking_plan(root: str | Path) -> dict[str, Any]:
    os_root = expand_path(root)
    runtime_registry = _load_yaml(_runtime_path(os_root, RUNTIME_REGISTRY), DEFAULT_RUNTIME_REGISTRY)
    integration_registry = _load_yaml(_runtime_path(os_root, INTEGRATION_REGISTRY), DEFAULT_INTEGRATION_REGISTRY)
    queue = _queue(os_root)
    queue_items = _runtime_tracking_queue_items(queue)
    records = []
    for target in runtime_registry.get("execution_targets") or []:
        records.append({"kind": "execution_target", "key": target["id"], "title": target["display_name"], "action": "create-or-update"})
    for heartbeat in runtime_registry.get("heartbeats") or []:
        records.append({"kind": "heartbeat", "key": heartbeat["id"], "title": heartbeat["display_name"], "action": "create-or-update"})
    for schedule in runtime_registry.get("schedules") or []:
        records.append({"kind": "schedule", "key": schedule["id"], "title": schedule["display_name"], "action": "create-or-update"})
    for integration in integration_registry.get("integrations") or []:
        records.append({"kind": "integration", "key": integration["id"], "title": integration["display_name"], "action": "create-or-update"})
    for item in queue_items:
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
        "record_scope": {
            "run_queue_item_limit": RUNTIME_TRACKING_RUN_QUEUE_LIMIT,
            "run_queue_total_items": len(queue.get("items") or []),
            "run_queue_projected_items": len(queue_items),
            "run_queue_omitted_items": max(0, len(queue.get("items") or []) - len(queue_items)),
        },
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
        "record_scope": plan.get("record_scope", {}),
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
        "record_scope": plan.get("record_scope", {}),
        "records": records,
    }
    _write_yaml(manifest_path, manifest)
    return {**plan, "applied": True, "live": False, "database_ids": database_ids, "records": records}


def format_runtime_result(result: dict[str, Any]) -> str:
    return yaml.safe_dump(result, sort_keys=False).strip()
