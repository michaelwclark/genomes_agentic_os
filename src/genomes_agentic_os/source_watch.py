"""Connected source registry and dry-run watcher operations."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from pathlib import Path
from typing import Any

import yaml

from .scaffold import expand_path, validate_name


CONTROL_PLANE = Path("shared_factory/00-control-plane")
SOURCE_EVENTS = Path("shared_factory/06-runs-and-logs/source-events")

CONNECTED_SYSTEMS_FILE = CONTROL_PLANE / "connected-systems.yml"
SOURCE_PROVIDERS_FILE = CONTROL_PLANE / "source-providers.yml"
WATCH_SOURCES_FILE = CONTROL_PLANE / "watch-sources.yml"
WATCH_CURSORS_FILE = CONTROL_PLANE / "watch-cursors.yml"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def write_yaml_once(path: Path, data: dict[str, Any]) -> None:
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def write_yaml(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def default_connected_systems() -> dict[str, Any]:
    return {
        "connected_systems": [
            {
                "id": "notion_genome",
                "display_name": "Genome Notion",
                "system": "notion",
                "status": "planned",
                "owner": "Genome",
                "provider_priority": ["notion_mcp", "notion_connector", "direct_api"],
                "credential_refs": {"env_vars": ["GENOMES_NOTION_PAT"]},
                "workspace_verification": {"required": True, "expected_workspace": "Genome's Notion"},
                "permissions": {"read": ["database.query"], "write": []},
                "approval_required_for": ["external_write", "customer_visible_output"],
                "health_check": {"command": "agentic-os connected-system doctor notion_genome"},
            },
            {
                "id": "filesystem_local",
                "display_name": "Local Filesystem",
                "system": "filesystem",
                "status": "available",
                "owner": "OS Owner",
                "provider_priority": ["filesystem"],
                "credential_refs": {"env_vars": []},
                "workspace_verification": {"required": False},
                "permissions": {"read": ["local files"], "write": ["source-events"]},
                "approval_required_for": ["destructive_actions"],
                "health_check": {"command": "agentic-os connected-system doctor filesystem_local"},
            },
        ]
    }


def default_source_providers() -> dict[str, Any]:
    return {
        "source_providers": [
            {"id": "composio", "type": "composio", "status": "planned", "supports": ["oauth", "triggers", "tools"]},
            {"id": "notion_mcp", "type": "mcp", "status": "planned", "supports": ["notion"]},
            {"id": "notion_connector", "type": "connector", "status": "planned", "supports": ["notion"]},
            {"id": "direct_api", "type": "direct_api", "status": "planned", "supports": ["http_api"]},
            {"id": "filesystem", "type": "script", "status": "available", "supports": ["file_watch", "poll"]},
        ]
    }


def default_watch_sources() -> dict[str, Any]:
    return {"watch_sources": []}


def default_watch_cursors() -> dict[str, Any]:
    return {"watch_cursors": []}


def ensure_registries(root: str | Path) -> Path:
    os_root = expand_path(root)
    write_yaml_once(os_root / CONNECTED_SYSTEMS_FILE, default_connected_systems())
    write_yaml_once(os_root / SOURCE_PROVIDERS_FILE, default_source_providers())
    write_yaml_once(os_root / WATCH_SOURCES_FILE, default_watch_sources())
    write_yaml_once(os_root / WATCH_CURSORS_FILE, default_watch_cursors())
    (os_root / SOURCE_EVENTS).mkdir(parents=True, exist_ok=True)
    return os_root


def list_items(root: str | Path, file_path: Path, key: str) -> list[dict[str, Any]]:
    os_root = ensure_registries(root)
    data = load_yaml(os_root / file_path)
    items = data.get(key) or []
    return [item for item in items if isinstance(item, dict)]


def connected_systems(root: str | Path) -> list[dict[str, Any]]:
    return list_items(root, CONNECTED_SYSTEMS_FILE, "connected_systems")


def source_providers(root: str | Path) -> list[dict[str, Any]]:
    return list_items(root, SOURCE_PROVIDERS_FILE, "source_providers")


def watch_sources(root: str | Path) -> list[dict[str, Any]]:
    return list_items(root, WATCH_SOURCES_FILE, "watch_sources")


def find_by_id(items: list[dict[str, Any]], item_id: str) -> dict[str, Any] | None:
    return next((item for item in items if item.get("id") == item_id), None)


def provider_ids(root: str | Path) -> set[str]:
    return {str(provider.get("id")) for provider in source_providers(root) if provider.get("id")}


def select_provider(root: str | Path, system: dict[str, Any]) -> str | None:
    available = {
        str(provider["id"])
        for provider in source_providers(root)
        if provider.get("id") and provider.get("status") != "unavailable"
    }
    for provider_id in system.get("provider_priority") or []:
        if str(provider_id) in available:
            return str(provider_id)
    return None


def list_connected_systems(root: str | Path) -> dict[str, Any]:
    systems = []
    for system in connected_systems(root):
        systems.append({**system, "selected_provider": select_provider(root, system)})
    return {"connected_systems": systems}


def list_watch_sources(root: str | Path) -> dict[str, Any]:
    return {"watch_sources": watch_sources(root)}


def parse_external_refs(values: list[str] | None) -> dict[str, str]:
    refs: dict[str, str] = {}
    for value in values or []:
        if "=" not in value:
            raise ValueError(f"external ref must be key=value: {value!r}")
        key, raw = value.split("=", 1)
        refs[validate_name(key, "external_ref_key")] = raw
    return refs


def create_watch_source(
    root: str | Path,
    source_id: str,
    *,
    connected_system: str = "notion_genome",
    source_type: str = "notion_database",
    display_name: str | None = None,
    cadence: str = "manual",
    external_ref: dict[str, str] | None = None,
    route_to: str = "shared_factory",
    enabled: bool = False,
) -> dict[str, Any]:
    os_root = ensure_registries(root)
    source_id = validate_name(source_id, "source_id")
    systems = connected_systems(os_root)
    if not find_by_id(systems, connected_system):
        raise ValueError(f"connected system not found: {connected_system}")
    data = load_yaml(os_root / WATCH_SOURCES_FILE)
    sources = data.setdefault("watch_sources", [])
    if find_by_id(sources, source_id):
        return {"action": "exists", "watch_source": find_by_id(sources, source_id), "path": str(os_root / WATCH_SOURCES_FILE)}
    source = {
        "id": source_id,
        "display_name": display_name or source_id.replace("_", " ").title(),
        "connected_system": connected_system,
        "source_type": source_type,
        "external_ref": external_ref or {"local_ref": source_id},
        "watch_method": "poll",
        "cadence": cadence,
        "enabled": enabled,
        "cursor": {"type": "last_seen_event_id", "state_ref": str(WATCH_CURSORS_FILE)},
        "dedupe": {"idempotency_key": "{source_type}:{source_id}:{event_id}"},
        "filters": {},
        "trigger_rules": [],
        "route": {
            "command": "agentic-os route",
            "context_command": "agentic-os context build",
            "fallback_domain": route_to,
        },
        "outputs": {
            "source_events_dir": str(SOURCE_EVENTS),
            "run_queue_ref": str(CONTROL_PLANE / "run-queue.yml"),
        },
    }
    sources.append(source)
    write_yaml(os_root / WATCH_SOURCES_FILE, data)
    return {"action": "created", "watch_source": source, "path": str(os_root / WATCH_SOURCES_FILE)}


def doctor_connected_system(root: str | Path, system_id: str) -> dict[str, Any]:
    system = find_by_id(connected_systems(root), system_id)
    findings: list[dict[str, str]] = []
    if not system:
        return {"system_id": system_id, "ok": False, "findings": [{"severity": "blocker", "message": "connected system not found"}]}
    priority = system.get("provider_priority") or []
    if not priority:
        findings.append({"severity": "blocker", "message": "missing provider_priority"})
    missing = [provider for provider in priority if provider not in provider_ids(root)]
    if missing:
        findings.append({"severity": "blocker", "message": f"missing providers: {', '.join(missing)}"})
    if not select_provider(root, system):
        findings.append({"severity": "blocker", "message": "no healthy provider available"})
    if "workspace_verification" not in system:
        findings.append({"severity": "fix-soon", "message": "missing workspace_verification"})
    if "health_check" not in system:
        findings.append({"severity": "fix-soon", "message": "missing health_check"})
    return {
        "system_id": system_id,
        "selected_provider": select_provider(root, system),
        "ok": not any(finding["severity"] == "blocker" for finding in findings),
        "findings": findings,
    }


def doctor_watch_source(root: str | Path, source_id: str) -> dict[str, Any]:
    source = find_by_id(watch_sources(root), source_id)
    findings: list[dict[str, str]] = []
    if not source:
        return {"source_id": source_id, "ok": False, "findings": [{"severity": "blocker", "message": "watch source not found"}]}
    system = find_by_id(connected_systems(root), str(source.get("connected_system", "")))
    if not system:
        findings.append({"severity": "blocker", "message": "connected_system not found"})
    elif not select_provider(root, system):
        findings.append({"severity": "blocker", "message": "connected_system has no healthy provider"})
    if not source.get("source_type"):
        findings.append({"severity": "blocker", "message": "missing source_type"})
    if not source.get("external_ref"):
        findings.append({"severity": "blocker", "message": "missing external_ref"})
    cursor = source.get("cursor") or {}
    if not cursor.get("type") or not cursor.get("state_ref"):
        findings.append({"severity": "blocker", "message": "missing cursor type or state_ref"})
    if not (source.get("dedupe") or {}).get("idempotency_key"):
        findings.append({"severity": "blocker", "message": "missing dedupe idempotency_key"})
    route = source.get("route") or {}
    if not route.get("command") or not route.get("context_command") or not route.get("fallback_domain"):
        findings.append({"severity": "blocker", "message": "missing route command, context_command, or fallback_domain"})
    if source.get("enabled") and source.get("watch_method") not in {"poll", "manual_replay", "file_watch"}:
        findings.append({"severity": "fix-soon", "message": "enabled source uses unproven watch_method"})
    return {
        "source_id": source_id,
        "ok": not any(finding["severity"] == "blocker" for finding in findings),
        "findings": findings,
    }


def source_event_id(source_id: str, observed_at: str) -> str:
    digest = hashlib.sha256(f"{source_id}:{observed_at}".encode()).hexdigest()[:10]
    return f"src_evt_{digest}"


def normalized_source_event(root: str | Path, source: dict[str, Any], *, dry_run: bool) -> dict[str, Any]:
    system = find_by_id(connected_systems(root), str(source.get("connected_system", ""))) or {}
    observed_at = utc_now()
    event_id = source_event_id(str(source["id"]), observed_at)
    selected_provider = select_provider(root, system) if system else None
    return {
        "id": event_id,
        "schema_version": 1,
        "event_type": f"{source.get('source_type', 'source')}.polled",
        "observed_at": observed_at,
        "source": {
            "watch_source_id": source["id"],
            "connected_system": source.get("connected_system"),
            "provider": selected_provider,
            "source_type": source.get("source_type"),
        },
        "dedupe": {
            "idempotency_key": str((source.get("dedupe") or {}).get("idempotency_key", "")).format(
                source_type=source.get("source_type"),
                source_id=source.get("id"),
                event_id=event_id,
            )
        },
        "route": source.get("route") or {},
        "summary": f"Dry-run poll for {source.get('display_name') or source['id']}" if dry_run else f"Polled {source['id']}",
        "payload_ref": {"type": "registry", "path": str(WATCH_SOURCES_FILE)},
        "dry_run": dry_run,
    }


def write_source_event(root: str | Path, event: dict[str, Any]) -> Path:
    os_root = ensure_registries(root)
    event_path = os_root / SOURCE_EVENTS / f"{event['id']}.yml"
    write_yaml_once(event_path, event)
    return event_path


def record_cursor(root: str | Path, source_id: str, event: dict[str, Any]) -> None:
    os_root = ensure_registries(root)
    path = os_root / WATCH_CURSORS_FILE
    data = load_yaml(path)
    cursors = data.setdefault("watch_cursors", [])
    existing = find_by_id(cursors, source_id)
    cursor = {
        "id": source_id,
        "watch_source_id": source_id,
        "cursor_type": "event_id",
        "last_value": event["id"],
        "updated_at": event["observed_at"],
    }
    if existing:
        existing.update(cursor)
    else:
        cursors.append(cursor)
    write_yaml(path, data)


def poll_watch_source(root: str | Path, source_id: str, *, dry_run: bool = True) -> dict[str, Any]:
    source = find_by_id(watch_sources(root), source_id)
    if not source:
        raise ValueError(f"watch source not found: {source_id}")
    doctor = doctor_watch_source(root, source_id)
    if not doctor["ok"]:
        return {"source_id": source_id, "ok": False, "dry_run": dry_run, "findings": doctor["findings"], "events": []}
    event = normalized_source_event(root, source, dry_run=dry_run)
    result = {"source_id": source_id, "ok": True, "dry_run": dry_run, "events": [event]}
    if not dry_run:
        result["written"] = [str(write_source_event(root, event))]
        record_cursor(root, source_id, event)
    return result


def run_due_watch_sources(root: str | Path, *, dry_run: bool = True) -> dict[str, Any]:
    actions = []
    for source in watch_sources(root):
        if not source.get("enabled"):
            actions.append({"source_id": source.get("id"), "action": "skip", "reason": "disabled"})
            continue
        poll = poll_watch_source(root, str(source["id"]), dry_run=dry_run)
        actions.append({"source_id": source["id"], "action": "poll", **poll})
    return {"dry_run": dry_run, "actions": actions}


def format_source_watch_result(result: dict[str, Any]) -> str:
    return yaml.safe_dump(result, sort_keys=False).strip()
