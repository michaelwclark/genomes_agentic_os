"""File-backed runtime operations for installed Agentic OS roots."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
from typing import Any

import yaml

from .notion_sync import target_workspace, verify_workspace
from .scaffold import expand_path, install_docs, validate_name

RUNTIME_REGISTRY = "shared_factory/00-control-plane/runtime-registry.yml"
INTEGRATION_REGISTRY = "shared_factory/00-control-plane/integration-registry.yml"
RUN_QUEUE = "shared_factory/00-control-plane/run-queue.yml"
HEARTBEAT_LOG_DIR = "shared_factory/06-runs-and-logs/heartbeats"
RUNTIME_SETUP_RUN_DIR = "shared_factory/06-runs-and-logs/runs"
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
            "enabled": True,
            "cadence": "every_2_hours",
            "execution_target": "script",
            "integration": "granola",
            "context": {
                "read_first": [
                    "shared_factory/00-control-plane/integration-registry.yml",
                    "shared_factory/05-knowledge/source-map.md",
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
            "context": {"read_first": ["shared_factory/00-control-plane/integration-registry.yml"]},
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
            "outputs": ["shared_factory/06-runs-and-logs/runs/"],
            "notion_update": {"object": "Heartbeats", "status_field": "Last Status"},
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
    "states": ["queued", "running", "blocked", "done", "failed", "dry-run"],
    "items": [],
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
    return _load_yaml(_runtime_path(root, RUN_QUEUE), DEFAULT_RUN_QUEUE)


def _items_by_id(items: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(item.get("id")): item for item in items if isinstance(item, dict) and item.get("id")}


def _find_item(items: list[dict[str, Any]], item_id: str, kind: str) -> dict[str, Any]:
    item = _items_by_id(items).get(item_id)
    if item is None:
        raise ValueError(f"unknown {kind}: {item_id}")
    return item


def _append_queue_item(root: Path, item: dict[str, Any]) -> Path:
    path = _runtime_path(root, RUN_QUEUE)
    queue = _queue(root)
    queue.setdefault("items", []).append(item)
    _write_yaml(path, queue)
    return path


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
    _ensure_dir(_runtime_path(os_root, "shared_factory/00-control-plane"), result)
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
    if not dry_run and not heartbeat.get("enabled", False):
        raise ValueError(f"heartbeat is disabled: {heartbeat_id}")
    run_id = f"{_stamp()}-{heartbeat_id}"
    status = "dry-run" if dry_run else "queued"
    log = {
        "run_id": run_id,
        "kind": "heartbeat",
        "heartbeat_id": heartbeat_id,
        "status": status,
        "dry_run": dry_run,
        "created_at": _now(),
        "execution_target": heartbeat.get("execution_target"),
        "integration": heartbeat.get("integration"),
        "success_means": heartbeat.get("success_means") or [],
        "external_effect": "none" if dry_run else "queued for approved execution",
    }
    log_path = _runtime_path(os_root, HEARTBEAT_LOG_DIR) / f"{run_id}.yml"
    _write_yaml(log_path, log)
    queue_path = _append_queue_item(
        os_root,
        {
            "id": run_id,
            "kind": "heartbeat",
            "ref": heartbeat_id,
            "status": status,
            "created_at": _now(),
            "dry_run": dry_run,
            "log": str(log_path.relative_to(os_root)),
        },
    )
    return {"root": str(os_root), "status": status, "heartbeat": heartbeat, "log": str(log_path), "run_queue": str(queue_path)}


def schedule_create(
    root: str | Path,
    schedule_id: str,
    *,
    cadence: str = "manual",
    timezone_name: str = "America/Chicago",
    command: str | None = None,
) -> dict[str, Any]:
    schedule_id = validate_name(schedule_id, "schedule_id")
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
        "outputs": ["shared_factory/06-runs-and-logs/runs/"],
        "notion_update": {"object": "Heartbeats", "status_field": "Last Status"},
    }
    schedules.append(schedule)
    _write_yaml(_runtime_path(os_root, RUNTIME_REGISTRY), registry)
    return {"root": str(os_root), "status": "created", "schedule": schedule, "registry": str(_runtime_path(os_root, RUNTIME_REGISTRY))}


def schedule_run_due(root: str | Path, *, dry_run: bool = True) -> dict[str, Any]:
    os_root = expand_path(root)
    registry = _registry(os_root)
    queued = []
    for schedule in registry.get("schedules") or []:
        if not schedule.get("enabled", False):
            continue
        item_id = f"{_stamp()}-{schedule['id']}"
        item = {
            "id": item_id,
            "kind": "schedule",
            "ref": schedule["id"],
            "status": "dry-run" if dry_run else "queued",
            "created_at": _now(),
            "dry_run": dry_run,
            "command": schedule.get("command"),
        }
        _append_queue_item(os_root, item)
        queued.append(item)
    return {"root": str(os_root), "status": "dry-run" if dry_run else "queued", "queued": queued}


def integration_list(root: str | Path) -> dict[str, Any]:
    os_root = expand_path(root)
    registry = _integration_registry(os_root)
    return {"root": str(os_root), "integrations": registry.get("integrations") or []}


def integration_setup(root: str | Path, integration_id: str, *, dry_run: bool = True) -> dict[str, Any]:
    integration_id = validate_name(integration_id, "integration_id")
    os_root = expand_path(root)
    registry = _integration_registry(os_root)
    integration = _find_item(registry.get("integrations") or [], integration_id, "integration")
    result = {
        "root": str(os_root),
        "status": "dry-run" if dry_run else "setup-recorded",
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
    for schedule in registry.get("schedules") or []:
        for key in ("id", "display_name", "enabled", "cadence", "timezone", "execution_target", "command"):
            if key not in schedule:
                findings.append({"severity": "blocker", "path": str(registry_path), "message": f"schedule missing {key}: {schedule.get('id', '<unknown>')}"})

    integration_ids = set(_items_by_id(integration_registry.get("integrations") or []))
    missing_integrations = sorted(REQUIRED_INTEGRATIONS - integration_ids)
    for integration in missing_integrations:
        findings.append({"severity": "blocker", "path": str(integration_path), "message": f"missing integration: {integration}"})
    for integration in integration_registry.get("integrations") or []:
        for key in ("id", "display_name", "provider", "status", "setup_tasks", "health_checks", "approval_gates", "notion_tracking"):
            if not integration.get(key):
                findings.append({"severity": "blocker", "path": str(integration_path), "message": f"integration missing {key}: {integration.get('id', '<unknown>')}"})
        findings.extend(_credential_findings(integration_path, integration))
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
    queue = _load_yaml(_runtime_path(os_root, RUN_QUEUE), DEFAULT_RUN_QUEUE)
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
        records.append({"kind": "run_queue_item", "key": item["id"], "title": item["ref"], "action": "create-or-update"})
    for log_path in sorted(_runtime_path(os_root, HEARTBEAT_LOG_DIR).glob("*.yml"))[-20:]:
        records.append({"kind": "heartbeat_run", "key": log_path.stem, "title": log_path.stem, "path": str(log_path), "action": "create-or-update"})
    return {
        "root": str(os_root),
        "workspace": target_workspace(os_root),
        "manifest_path": str(_runtime_path(os_root, NOTION_RUNTIME_MANIFEST)),
        "databases": ["Integrations", "Heartbeats", "Schedules", "Runs"],
        "records": records,
    }


def apply_runtime_tracking(root: str | Path, *, verified_workspace: str | None) -> dict[str, Any]:
    os_root = expand_path(root)
    workspace = verify_workspace(os_root, verified_workspace)
    plan = build_runtime_tracking_plan(os_root)
    manifest_path = _runtime_path(os_root, NOTION_RUNTIME_MANIFEST)
    records = []
    for record in plan["records"]:
        record_key = f"{record['kind']}:{record['key']}"
        records.append({**record, "notion_id": _local_id(record_key), "record_key": record_key})
    manifest = {
        "workspace": workspace,
        "updated_at": _now(),
        "databases": plan["databases"],
        "records": records,
    }
    _write_yaml(manifest_path, manifest)
    return {**plan, "applied": True, "records": records}


def format_runtime_result(result: dict[str, Any]) -> str:
    return yaml.safe_dump(result, sort_keys=False).strip()
