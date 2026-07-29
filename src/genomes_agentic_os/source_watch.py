"""Connected source registry and dry-run watcher operations."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from pathlib import Path
from typing import Any, Callable

import yaml

from .event_graph import append_event, ensure_event_state
from .runtime_ops import append_run_queue_item
from .scaffold import expand_path, validate_name
from .source_providers import poll_live_source


CONTROL_PLANE = Path("harness/shared_factory/00-control-plane")
SOURCE_EVENTS = Path("harness/shared_factory/06-runs-and-logs/source-events")

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
    def system(
        system_id: str,
        display_name: str,
        system_name: str,
        provider_priority: list[str],
        *,
        credential_envs: list[str] | None = None,
        expected_workspace: str | None = None,
        read_permissions: list[str] | None = None,
        write_permissions: list[str] | None = None,
        status: str = "planned",
    ) -> dict[str, Any]:
        return {
            "id": system_id,
            "display_name": display_name,
            "system": system_name,
            "status": status,
            "owner": "OS Owner",
            "provider_priority": provider_priority,
            "credential_refs": {"env_vars": credential_envs or [], "account_aliases": []},
            "workspace_verification": {
                "required": expected_workspace is not None,
                "expected_workspace": expected_workspace,
            },
            "permissions": {"read": read_permissions or [], "write": write_permissions or []},
            "approval_required_for": ["external_write", "customer_visible_output"],
            "health_check": {"command": f"agentic-os connected-system doctor {system_id}"},
        }

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
            system(
                "slack_genome",
                "Genome Slack",
                "slack",
                ["composio", "slack_mcp", "slack_connector", "direct_api"],
                credential_envs=["COMPOSIO_API_KEY"],
                expected_workspace="Genome",
                read_permissions=["channels:history", "groups:history"],
                write_permissions=["chat:write"],
            ),
            system(
                "jira_genome",
                "Genome Jira",
                "jira",
                ["composio", "jira_mcp", "jira_connector", "direct_api"],
                credential_envs=["COMPOSIO_API_KEY"],
                expected_workspace="Genome",
                read_permissions=["issue.read", "project.read"],
                write_permissions=["issue.write"],
            ),
            system(
                "linear_genome",
                "Genome Linear",
                "linear",
                ["composio", "linear_mcp", "linear_connector", "direct_api"],
                credential_envs=["COMPOSIO_API_KEY"],
                expected_workspace="Genome",
                read_permissions=["issues:read", "teams:read"],
                write_permissions=["issues:write"],
            ),
            system(
                "email_genome",
                "Genome Email",
                "email",
                ["composio", "gmail_mcp", "email_connector", "direct_api"],
                credential_envs=["COMPOSIO_API_KEY"],
                expected_workspace="Genome",
                read_permissions=["mail.read"],
                write_permissions=["mail.send"],
            ),
            system(
                "github_genome",
                "Genome GitHub",
                "github",
                ["composio", "github_mcp", "github_cli", "direct_api"],
                credential_envs=["COMPOSIO_API_KEY", "GITHUB_TOKEN"],
                expected_workspace="Genome",
                read_permissions=["repo:read", "pull_request:read"],
                write_permissions=["issues:write", "pull_request:write"],
            ),
            system(
                "granola_local",
                "Granola Notes",
                "granola",
                ["composio", "granola_local", "direct_api"],
                credential_envs=["COMPOSIO_API_KEY"],
                read_permissions=["notes:read"],
                write_permissions=[],
            ),
            system(
                "agentmail_genome",
                "Genome AgentMail",
                "agentmail",
                ["composio", "agentmail_api", "direct_api"],
                credential_envs=["COMPOSIO_API_KEY", "AGENTMAIL_API_KEY"],
                expected_workspace="Genome",
                read_permissions=["inbox.read"],
                write_permissions=["message.send"],
            ),
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
            {"id": "slack_mcp", "type": "mcp", "status": "planned", "supports": ["slack", "poll"]},
            {"id": "slack_connector", "type": "connector", "status": "planned", "supports": ["slack", "trigger"]},
            {"id": "jira_mcp", "type": "mcp", "status": "planned", "supports": ["jira", "poll"]},
            {"id": "jira_connector", "type": "connector", "status": "planned", "supports": ["jira", "trigger"]},
            {"id": "linear_mcp", "type": "mcp", "status": "planned", "supports": ["linear", "poll"]},
            {"id": "linear_connector", "type": "connector", "status": "planned", "supports": ["linear", "trigger"]},
            {"id": "gmail_mcp", "type": "mcp", "status": "planned", "supports": ["email", "poll"]},
            {"id": "email_connector", "type": "connector", "status": "planned", "supports": ["email", "trigger"]},
            {"id": "github_mcp", "type": "mcp", "status": "planned", "supports": ["github", "poll"]},
            {"id": "github_cli", "type": "cli", "status": "planned", "supports": ["github", "poll"]},
            {"id": "granola_local", "type": "script", "status": "planned", "supports": ["granola", "poll"]},
            {"id": "agentmail_api", "type": "direct_api", "status": "planned", "supports": ["agentmail", "poll"]},
            {"id": "webhook", "type": "webhook", "status": "planned", "supports": ["trigger"]},
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


class SafeFormatDict(dict[str, Any]):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def format_template(template: str, values: dict[str, Any]) -> str:
    return template.format_map(SafeFormatDict({key: "" if value is None else value for key, value in values.items()}))


def default_trigger_rule(source_id: str, source_type: str, route_to: str) -> dict[str, Any]:
    return {
        "id": f"{source_id}_observed",
        "display_name": f"{source_id.replace('_', ' ').title()} observed",
        "enabled": False,
        "when": {"event_type": f"{source_type}.polled", "fields": {}},
        "then": {"emit_event": {"type": "os.observation"}},
        "approval": {"required": False},
        "idempotency": {"key": "{event_id}:{rule_id}"},
        "route": {"fallback_domain": route_to},
    }


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
        "trigger_rules": [default_trigger_rule(source_id, source_type, route_to)],
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
    trigger_rules = source.get("trigger_rules") or []
    if source.get("enabled") and not trigger_rules:
        findings.append({"severity": "blocker", "message": "enabled source missing trigger_rules"})
    for rule in [rule for rule in trigger_rules if isinstance(rule, dict)]:
        rule_id = rule.get("id")
        if rule.get("enabled") and not rule_id:
            findings.append({"severity": "blocker", "message": "enabled trigger rule missing id"})
        if rule.get("enabled") and not (rule.get("when") or {}).get("event_type"):
            findings.append({"severity": "blocker", "message": f"enabled trigger rule {rule_id} missing event_type"})
        then = rule.get("then") or {}
        if rule.get("enabled") and not (then.get("emit_event") or then.get("enqueue")):
            findings.append({"severity": "blocker", "message": f"enabled trigger rule {rule_id} missing action"})
        if rule.get("enabled") and not (rule.get("idempotency") or {}).get("key"):
            findings.append({"severity": "blocker", "message": f"enabled trigger rule {rule_id} missing idempotency key"})
    return {
        "source_id": source_id,
        "ok": not any(finding["severity"] == "blocker" for finding in findings),
        "findings": findings,
    }


def source_event_key(source: dict[str, Any], provider_id: str | None) -> str:
    return yaml.safe_dump(
        {
            "watch_source_id": source.get("id"),
            "source_type": source.get("source_type"),
            "external_ref": source.get("external_ref") or {},
            "cursor_type": (source.get("cursor") or {}).get("type"),
            "provider": provider_id,
            "synthetic_event": "poll",
        },
        sort_keys=True,
    )


def source_event_id(source_id: str, event_key: str) -> str:
    digest = hashlib.sha256(f"{source_id}:{event_key}".encode()).hexdigest()[:10]
    return f"src_evt_{digest}"


def selected_provider_record(root: str | Path, provider_id: str | None) -> dict[str, Any] | None:
    if provider_id is None:
        return None
    return find_by_id(source_providers(root), provider_id)


def normalized_source_event(
    root: str | Path,
    source: dict[str, Any],
    *,
    dry_run: bool,
    live_items: list[dict[str, Any]] | None = None,
    live_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the normalised source event envelope.

    When *live_items* is provided (from a live adapter poll), the idempotency
    key is derived from provider-issued event IDs rather than a registry digest,
    and the payload summary reflects the real items found.  The envelope shape
    is identical in both cases so downstream trigger rules are unaffected.
    """
    system = find_by_id(connected_systems(root), str(source.get("connected_system", ""))) or {}
    observed_at = utc_now()
    selected_provider = select_provider(root, system) if system else None
    event_key = source_event_key(source, selected_provider)
    event_id = source_event_id(str(source["id"]), event_key)
    provider = selected_provider_record(root, selected_provider)

    # When live items exist, derive a stable idempotency key from provider IDs
    if live_items:
        # Sort by the provider-issued idempotency key so the digest is stable
        sorted_keys = sorted(
            item.get("_idempotency_key", "") for item in live_items
        )
        live_digest = hashlib.sha256(
            ("\n".join(sorted_keys)).encode()
        ).hexdigest()[:12]
        live_event_key = f"{event_key}\nlive_digest:{live_digest}"
        live_event_seed = f"{source['id']}:{live_event_key}"
        live_event_id = f"src_evt_{hashlib.sha256(live_event_seed.encode()).hexdigest()[:10]}"
        effective_event_id = live_event_id
        # Idempotency key for deduplication: live items hash, not a timestamp
        effective_idempotency_key = f"{source.get('source_type')}:{source.get('id')}:{live_digest}"
        item_count = len(live_items)
        summary = f"Live poll: {item_count} item(s) from {source.get('display_name') or source['id']}"
        payload_ref: dict[str, Any] = {
            "type": "live",
            "item_count": item_count,
            "provider": (live_result or {}).get("provider", "direct_api"),
            "credential_env": (live_result or {}).get("credential_env"),
        }
        adapter_mode = "live_apply" if not dry_run else "live_dry_run"
    else:
        effective_event_id = event_id
        format_values: dict[str, Any] = {
            **(source.get("external_ref") or {}),
            "event_id": event_id,
            "event_key": event_key,
            "source_id": source.get("id"),
            "source_type": source.get("source_type"),
            "observed_at": observed_at,
            "provider": selected_provider,
        }
        effective_idempotency_key = format_template(
            str((source.get("dedupe") or {}).get("idempotency_key", "")), format_values
        )
        summary = (
            f"Dry-run poll for {source.get('display_name') or source['id']}"
            if dry_run
            else f"Polled {source['id']}"
        )
        payload_ref = {"type": "registry", "path": str(WATCH_SOURCES_FILE)}
        adapter_mode = "registry_dry_run" if dry_run else "registry_apply"

    event: dict[str, Any] = {
        "id": effective_event_id,
        "schema_version": 1,
        "event_type": f"{source.get('source_type', 'source')}.polled",
        "observed_at": observed_at,
        "source": {
            "watch_source_id": source["id"],
            "connected_system": source.get("connected_system"),
            "provider": selected_provider,
            "source_type": source.get("source_type"),
            "external_ref": source.get("external_ref") or {},
        },
        "dedupe": {"idempotency_key": effective_idempotency_key},
        "route": source.get("route") or {},
        "summary": summary,
        "payload_ref": payload_ref,
        "event_key": event_key,
        "provider_adapter": {
            "id": selected_provider,
            "type": (provider or {}).get("type"),
            "mode": adapter_mode,
        },
        "dry_run": dry_run,
    }
    if live_items is not None:
        event["live_items"] = live_items
    return event


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
        "last_idempotency_key": (event.get("dedupe") or {}).get("idempotency_key"),
        "updated_at": event["observed_at"],
    }
    if existing:
        existing.update(cursor)
    else:
        cursors.append(cursor)
    write_yaml(path, data)


def trigger_rule_matches(rule: dict[str, Any], event: dict[str, Any]) -> bool:
    when = rule.get("when") or {}
    if when.get("event_type") and when.get("event_type") != event.get("event_type"):
        return False
    source = event.get("source") or {}
    fields = when.get("fields") or {}
    for key, value in fields.items():
        if event.get(key) == value or source.get(key) == value:
            continue
        return False
    return True


def trigger_format_values(rule: dict[str, Any], event: dict[str, Any]) -> dict[str, Any]:
    source = event.get("source") or {}
    return {
        "event_id": event.get("id"),
        "rule_id": rule.get("id"),
        "source_id": source.get("watch_source_id"),
        "source_type": source.get("source_type"),
        "provider": source.get("provider"),
        **(source.get("external_ref") or {}),
    }


def trigger_idempotency_key(rule: dict[str, Any], event: dict[str, Any]) -> str:
    template = ((rule.get("idempotency") or {}).get("key")) or "{event_id}:{rule_id}"
    return format_template(str(template).replace("{event.id}", "{event_id}").replace("{rule.id}", "{rule_id}"), trigger_format_values(rule, event))


def queue_item_for_trigger(rule: dict[str, Any], event: dict[str, Any]) -> dict[str, Any]:
    enqueue = ((rule.get("then") or {}).get("enqueue")) or {}
    approval_required = bool((rule.get("approval") or {}).get("required"))
    key = trigger_idempotency_key(rule, event)
    item = {
        "id": f"queue_{hashlib.sha256(key.encode()).hexdigest()[:12]}",
        "kind": "source_trigger",
        "ref": rule["id"],
        "source_event_id": event["id"],
        "watch_source_id": (event.get("source") or {}).get("watch_source_id"),
        "trigger_rule_id": rule["id"],
        "status": "approval-needed" if approval_required else "queued",
        "approval_state": "required" if approval_required else "not_required",
        "work_type": enqueue.get("work_type", "review"),
        "route_to": enqueue.get("route_to", ((rule.get("route") or {}).get("fallback_domain")) or "shared_factory"),
        "workflow": enqueue.get("workflow"),
        "context_profile": enqueue.get("context_profile", "default"),
        "maturity": enqueue.get("maturity", "observe"),
        "idempotency_key": key,
        "created_at": utc_now(),
        "evidence": [{"type": "source_event", "path": event.get("path")}],
    }
    command = enqueue.get("command") or enqueue.get("worker_command")
    if command:
        item["command"] = format_template(str(command), trigger_format_values(rule, event))
    execution_target = enqueue.get("execution_target")
    if execution_target:
        item["execution_target"] = execution_target
    return item


def apply_trigger_rules(
    root: str | Path,
    source: dict[str, Any],
    event: dict[str, Any],
    *,
    dry_run: bool,
    event_path: Path | None = None,
) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    os_root = expand_path(root)
    if not dry_run:
        ensure_event_state(os_root)
    for rule in [rule for rule in source.get("trigger_rules") or [] if isinstance(rule, dict)]:
        if not rule.get("enabled") or not trigger_rule_matches(rule, event):
            continue
        then = rule.get("then") or {}
        emit = then.get("emit_event") or {}
        if emit:
            event_type = emit.get("type", "os.observation")
            action = {
                "trigger_rule_id": rule.get("id"),
                "action": "emit_event",
                "event_type": event_type,
                "status": "dry-run" if dry_run else "emitted",
            }
            if not dry_run:
                emitted = append_event(
                    os_root,
                    event_type=event_type,
                    source_ref=f"source-watch:{(event.get('source') or {}).get('watch_source_id')}:{event['id']}",
                    summary=event.get("summary", ""),
                    payload_ref={"type": "file", "href": str(event_path)} if event_path else event.get("payload_ref"),
                    correlation_id=event["id"],
                )
                action["event_id"] = emitted["id"]
                action["path"] = emitted["path"]
            actions.append(action)
        if then.get("enqueue"):
            item = queue_item_for_trigger(rule, event)
            action = {
                "trigger_rule_id": rule.get("id"),
                "action": "enqueue",
                "status": "dry-run" if dry_run else "queued",
                "queue_item": item,
            }
            if not dry_run:
                queued = append_run_queue_item(os_root, item)
                action["queue_item"] = queued["queue_item"]
                action["run_queue"] = queued["run_queue"]
                action["created"] = queued["created"]
                if not queued["created"]:
                    action["status"] = "skipped"
                    action["reason"] = "idempotency key already queued"
            actions.append(action)
    return actions


def poll_watch_source(
    root: str | Path,
    source_id: str,
    *,
    dry_run: bool = True,
    fetcher: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Poll a single watch source.

    When a live adapter exists for the source's connected system and a credential
    env var is available, real API data is fetched and embedded in the event.
    When no credential is present or no live adapter exists, the existing
    registry dry-run path is used unchanged.

    Parameters
    ----------
    fetcher:
        Injectable HTTP transport (``urllib.request.Request -> response``).
        Defaults to ``urllib.request.urlopen``.  Pass a fake in tests so no
        network calls are made.
    """
    source = find_by_id(watch_sources(root), source_id)
    if not source:
        raise ValueError(f"watch source not found: {source_id}")
    doctor = doctor_watch_source(root, source_id)
    if not doctor["ok"]:
        return {"source_id": source_id, "ok": False, "dry_run": dry_run, "findings": doctor["findings"], "events": []}

    # --- attempt live adapter ---
    system = find_by_id(connected_systems(root), str(source.get("connected_system", ""))) or {}
    live_kwargs: dict[str, Any] = {}
    if fetcher is not None:
        live_kwargs["fetcher"] = fetcher
    live_result = poll_live_source(source, system, **live_kwargs)

    # Every live-adapter failure is terminal for this poll. Falling back to a
    # registry event would turn provider/configuration failures into false
    # success and can advance cursors or trigger downstream work incorrectly.
    if live_result is not None and live_result.get("ok") is False:
        return {
            "source_id": source_id,
            "ok": False,
            "dry_run": dry_run,
            "findings": live_result.get("findings") or [],
            "events": [],
            "adapter": {
                "live": live_result.get("live", False),
                "item_count": live_result.get("item_count", 0),
                "provider": live_result.get("provider"),
                "partial": live_result.get("partial", False),
            },
        }

    # Build normalised event envelope
    live_items: list[dict[str, Any]] | None = None
    if live_result is not None and live_result.get("live"):
        live_items = live_result.get("items") or []

    event = normalized_source_event(
        root, source, dry_run=dry_run, live_items=live_items, live_result=live_result
    )

    result: dict[str, Any] = {
        "source_id": source_id,
        "ok": True,
        "dry_run": dry_run,
        "events": [event],
    }
    if live_result is not None:
        result["adapter"] = {
            "live": live_result.get("live", False),
            "item_count": live_result.get("item_count", 0),
            "dry_run_reason": live_result.get("dry_run_reason"),
        }

    event_path = None
    if not dry_run:
        event_path = write_source_event(root, event)
        event["path"] = str(event_path)
        result["written"] = [str(event_path)]
        record_cursor(root, source_id, event)
    trigger_actions = apply_trigger_rules(root, source, event, dry_run=dry_run, event_path=event_path)
    if trigger_actions:
        result["trigger_actions"] = trigger_actions
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
