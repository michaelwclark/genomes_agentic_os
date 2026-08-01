"""Source-aware automation controller for expensive Agentic OS automations."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from pathlib import Path
from typing import Any, Callable
import urllib.request

import yaml

from . import notion_api as _legacy_notion_api
from .notion_bridge_adapter import query_data_source_pages, query_database_pages
from .runtime_ops import append_run_queue_item
from .preconditions import evaluate_preconditions
from .scaffold import expand_path, validate_name
from .source_watch import find_by_id, load_yaml, watch_sources


CONTROL_CONFIG = "harness/shared_factory/00-control-plane/automation-control.yml"
CONTROL_LOG_DIR = "harness/shared_factory/06-runs-and-logs/automation-control"


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _digest(value: str, length: int = 12) -> str:
    return hashlib.sha256(value.encode()).hexdigest()[:length]


def _load_control(root: str | Path) -> tuple[Path, dict[str, Any]]:
    os_root = expand_path(root)
    path = os_root / CONTROL_CONFIG
    data = load_yaml(path)
    if not data:
        return path, {"schema_version": 1, "managed_automations": []}
    return path, data


def _write_receipt(root: Path, result: dict[str, Any]) -> Path:
    log_dir = root / CONTROL_LOG_DIR
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / f"{_stamp()}-{_digest(yaml.safe_dump(result, sort_keys=True), 8)}.yml"
    path.write_text(yaml.safe_dump(result, sort_keys=False), encoding="utf-8")
    return path


def _id_from_url(value: str | None) -> str | None:
    if not value:
        return None
    if value.startswith("collection://"):
        return value.removeprefix("collection://")
    tail = value.rstrip("/").split("/")[-1]
    if "?" in tail:
        tail = tail.split("?", 1)[0]
    if len(tail.replace("-", "")) >= 32:
        return tail
    return None


def _row_values(row: dict[str, Any]) -> dict[str, Any]:
    properties = row.get("properties")
    if isinstance(properties, dict):
        values = {str(key): value for key, value in properties.items()}
    else:
        values = {str(key): value for key, value in row.items()}
    values.setdefault("_id", row.get("id") or row.get("page_id"))
    values.setdefault("_last_edited_time", row.get("last_edited_time") or row.get("updated_at"))
    return values


def _query_notion_rows(
    source: dict[str, Any],
    probe: dict[str, Any],
    *,
    fetcher: Callable[[urllib.request.Request], Any] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if isinstance(probe.get("fixture_items"), list):
        return list(probe["fixture_items"]), {"provider": "fixture", "live": False}

    external_ref = source.get("external_ref") or {}
    data_source_id = (
        probe.get("data_source_id")
        or external_ref.get("data_source_id")
        or _id_from_url(str(external_ref.get("data_source_url") or ""))
    )
    database_id = probe.get("database_id") or external_ref.get("database_id") or _id_from_url(
        str(external_ref.get("database_url") or "")
    )
    token_env = str(probe.get("token_env") or source.get("token_env") or "GENOMES_NOTION_PAT")
    kwargs: dict[str, Any] = {"token_env": token_env}
    query_data_source = query_data_source_pages
    query_database = query_database_pages
    provider = "notion_bridge"
    if fetcher is not None:
        kwargs["fetcher"] = fetcher
        query_data_source = _legacy_notion_api.query_data_source_pages
        query_database = _legacy_notion_api.query_database_pages
        provider = "notion_fixture_transport"

    errors: list[str] = []
    if data_source_id:
        try:
            return query_data_source(str(data_source_id), **kwargs), {
                "provider": provider,
                "live": True,
                "ref": "data_source_id",
                "credential_env": token_env,
            }
        except RuntimeError as exc:
            errors.append(str(exc))
    if database_id:
        try:
            return query_database(str(database_id), **kwargs), {
                "provider": provider,
                "live": True,
                "ref": "database_id",
                "credential_env": token_env,
            }
        except RuntimeError as exc:
            errors.append(str(exc))
    reason = "; ".join(errors) if errors else "no notion database_id or data_source_id configured"
    raise RuntimeError(reason)


def _probe_notion_status(
    root: Path,
    automation: dict[str, Any],
    *,
    fetcher: Callable[[urllib.request.Request], Any] | None = None,
) -> dict[str, Any]:
    probe = automation.get("source_probe") or {}
    source_id = str(probe.get("watch_source_id") or probe.get("source_id") or "")
    source = find_by_id(watch_sources(root), source_id)
    if not source:
        return {
            "decision": "unknown",
            "ready": False,
            "reason": f"watch source not found: {source_id}",
            "source_id": source_id,
        }

    try:
        rows, adapter = _query_notion_rows(source, probe, fetcher=fetcher)
    except RuntimeError as exc:
        return {
            "decision": "unknown",
            "ready": False,
            "reason": str(exc),
            "source_id": source_id,
        }

    filters = source.get("filters") or {}
    status_field = str(probe.get("status_field") or filters.get("status_field") or "Status")
    actionable = set(probe.get("actionable_statuses") or [filters.get("status_value") or "Queue Start"])
    in_flight = set(probe.get("in_flight_statuses") or ["Running", "Watching PR", "Ready for Merge"])
    max_in_flight = probe.get("max_in_flight")
    try:
        max_in_flight_int = int(max_in_flight) if max_in_flight not in (None, "") else None
    except (TypeError, ValueError):
        max_in_flight_int = None

    normalized = [_row_values(row) for row in rows]
    actionable_rows = [row for row in normalized if row.get(status_field) in actionable]
    in_flight_rows = [row for row in normalized if row.get(status_field) in in_flight]
    available_capacity = None
    if max_in_flight_int is not None:
        available_capacity = max(0, max_in_flight_int - len(in_flight_rows))
        claimable_count = min(len(actionable_rows), available_capacity)
    else:
        claimable_count = len(actionable_rows)

    source_keys = [
        f"{row.get('_id') or row.get('Ticket') or row.get('Name')}:{row.get('_last_edited_time') or ''}"
        for row in actionable_rows
    ]
    if claimable_count > 0:
        decision = "ready"
        reason = "actionable source rows and capacity available"
    elif actionable_rows and available_capacity == 0:
        decision = "running"
        reason = "actionable rows exist but capacity is saturated"
    else:
        decision = "idle"
        reason = "no actionable source rows"

    return {
        "decision": decision,
        "ready": decision == "ready",
        "reason": reason,
        "source_id": source_id,
        "adapter": adapter,
        "source_count": len(rows),
        "actionable_count": len(actionable_rows),
        "in_flight_count": len(in_flight_rows),
        "claimable_count": claimable_count,
        "available_capacity": available_capacity,
        "source_keys": source_keys,
    }


def _probe_automation(
    root: Path,
    automation: dict[str, Any],
    *,
    fetcher: Callable[[urllib.request.Request], Any] | None = None,
) -> dict[str, Any]:
    probe = automation.get("source_probe") or {}
    probe_type = str(probe.get("type") or "")
    if probe_type in {"notion_status", "notion_queue", "notion_database_status"}:
        return _probe_notion_status(root, automation, fetcher=fetcher)
    return {
        "decision": "unknown",
        "ready": False,
        "reason": f"unsupported source_probe.type: {probe_type}",
    }


def _queue_item(root: Path, automation: dict[str, Any], probe: dict[str, Any]) -> dict[str, Any]:
    automation_id = str(automation["id"])
    target = automation.get("target") or {}
    command = str(target.get("command") or "").replace("<root>", str(root))
    key_template = str(
        automation.get("idempotency_key")
        or "automation_control:{automation_id}:{source_id}:{source_digest}"
    )
    values = {
        "automation_id": automation_id,
        "source_id": probe.get("source_id") or "",
        "source_digest": _digest("|".join(probe.get("source_keys") or [probe.get("decision", "")])),
    }
    idempotency_key = key_template.format_map(values)
    return {
        "id": f"queue_{_digest(idempotency_key)}",
        "kind": "automation_control",
        "ref": automation_id,
        "status": "queued",
        "approval_state": "not_required",
        "created_at": _now(),
        "dry_run": False,
        "idempotency_key": idempotency_key,
        "execution_target": target.get("execution_target") or "script",
        "dispatch_performed": False,
        "command": command,
        "source_probe": {
            "source_id": probe.get("source_id"),
            "decision": probe.get("decision"),
            "claimable_count": probe.get("claimable_count"),
        },
        "evidence": [{"type": "automation_control", "path": CONTROL_CONFIG}],
    }


def list_automation_control(root: str | Path) -> dict[str, Any]:
    os_root = expand_path(root)
    path, config = _load_control(os_root)
    return {
        "root": str(os_root),
        "path": str(path),
        "managed_automations": config.get("managed_automations") or [],
    }


def automation_control_doctor(root: str | Path) -> dict[str, Any]:
    os_root = expand_path(root)
    path, config = _load_control(os_root)
    findings: list[dict[str, str]] = []
    if not path.is_file():
        findings.append({"severity": "blocker", "path": str(path), "message": "automation-control.yml is missing"})
    sources = watch_sources(os_root)
    for automation in config.get("managed_automations") or []:
        automation_id = str(automation.get("id") or "")
        try:
            validate_name(automation_id, "automation_id")
        except ValueError as exc:
            findings.append({"severity": "blocker", "path": str(path), "message": str(exc)})
            continue
        if not automation.get("enabled", False):
            continue
        probe = automation.get("source_probe") or {}
        source_id = str(probe.get("watch_source_id") or probe.get("source_id") or "")
        if not source_id or not find_by_id(sources, source_id):
            findings.append({"severity": "blocker", "path": str(path), "message": f"{automation_id}: watch source not found: {source_id}"})
        target = automation.get("target") or {}
        if not target.get("command"):
            findings.append({"severity": "blocker", "path": str(path), "message": f"{automation_id}: target command missing"})
        if (target.get("execution_target") or "script") != "script":
            findings.append({"severity": "blocker", "path": str(path), "message": f"{automation_id}: only script targets are supported"})
    return {
        "root": str(os_root),
        "path": str(path),
        "ok": not any(finding["severity"] == "blocker" for finding in findings),
        "findings": findings,
    }


def run_automation_control(
    root: str | Path,
    *,
    dry_run: bool = True,
    automation_id: str | None = None,
    fetcher: Callable[[urllib.request.Request], Any] | None = None,
) -> dict[str, Any]:
    os_root = expand_path(root)
    _, config = _load_control(os_root)
    actions: list[dict[str, Any]] = []
    for automation in config.get("managed_automations") or []:
        item_id = str(automation.get("id") or "")
        if automation_id and item_id != automation_id:
            continue
        if not automation.get("enabled", False):
            actions.append({"id": item_id, "decision": "disabled", "action": "none", "reason": "automation control disabled"})
            continue
        probe = _probe_automation(os_root, automation, fetcher=fetcher)
        action: dict[str, Any] = {"id": item_id, **probe}
        if probe.get("decision") == "ready":
            preconditions = evaluate_preconditions(
                os_root,
                automation.get("preconditions"),
                context={"automation": {"id": item_id}, "probe": probe},
            )
            action["preconditions"] = preconditions
            if not preconditions["ok"]:
                action.update(
                    {
                        "decision": "precondition_failed",
                        "action": "none",
                        "dispatch_performed": False,
                        "reason": "declarative preconditions did not pass; no queue request was created",
                    }
                )
                actions.append(action)
                continue
            item = _queue_item(os_root, automation, probe)
            action["dispatch_performed"] = False
            if dry_run:
                action["action"] = "would_enqueue"
                action["queue_item"] = item
            else:
                queued = append_run_queue_item(os_root, item)
                action["action"] = "enqueued" if queued["created"] else "already_queued"
                action["queue_item"] = queued["queue_item"]
                action["run_queue"] = queued["run_queue"]
        else:
            action["action"] = "none"
            action["dispatch_performed"] = False
        actions.append(action)
    status = "dry-run" if dry_run else "applied"
    result = {"root": str(os_root), "status": status, "dry_run": dry_run, "actions": actions, "created_at": _now()}
    receipt = _write_receipt(os_root, result)
    result["receipt"] = str(receipt)
    return result


def format_automation_control_result(result: dict[str, Any]) -> str:
    return yaml.safe_dump(result, sort_keys=False).strip()
