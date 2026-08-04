"""File-backed event ledger and chain processing."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from pathlib import Path
from typing import Any

import yaml

from .runtime_backend import runtime_queue_items
from .runtime_ops import append_run_queue_item
from .scaffold import expand_path, validate_name
from .state import db as state_db
from .state import events as state_events


CONTROL_PLANE = Path("harness/shared_factory/00-control-plane")
EVENTS = Path("harness/shared_factory/06-runs-and-logs/events")
DEAD_LETTER = EVENTS / "dead-letter"
PROCESSING_RESULTS = EVENTS / "processing-results"
RUN_QUEUE = CONTROL_PLANE / "run-queue.yml"

EVENT_GRAPH_FILE = CONTROL_PLANE / "event-graph.yml"
CHAIN_RULES_FILE = CONTROL_PLANE / "chain-rules.yml"
EVENT_CURSORS_FILE = CONTROL_PLANE / "event-cursors.yml"
LEDGER_INDEX = EVENTS / "event-ledger-index.md"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def write_yaml(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def write_yaml_once(path: Path, data: dict[str, Any]) -> None:
    if path.exists():
        return
    write_yaml(path, data)


def default_event_graph() -> dict[str, Any]:
    return {
        "event_graph": {
            "schema_version": 1,
            "description": "File-backed event graph. Watchers detect, routers decide, agents execute, closeout emits events.",
            "event_log": str(EVENTS),
            "chain_rules": str(CHAIN_RULES_FILE),
            "run_queue": str(RUN_QUEUE),
            # The YAML ledger remains authoritative until a separate read-path
            # cutover.  Enabling this creates a SQLite shadow ledger only.
            "state_ledger": {"dual_write": False},
        }
    }


def default_chain_rules() -> dict[str, Any]:
    return {
        "chain_rules": [
            {
                "id": "feature_merged_to_docs_update",
                "display_name": "Feature merged creates docs follow-up",
                "enabled": False,
                "when": {"event_type": "github.pull_request.merged", "filters": {"repo": "genomes_agentic_os"}},
                "then": {
                    "enqueue": {
                        "work_type": "documentation_update",
                        "route_to": "shared_factory",
                        "workflow": "docs_update_after_merge",
                        "context_profile": "merged_feature_docs",
                        "maturity": "prepare",
                        "documentation_site_delivery": {
                            "required": True,
                            "published_source_roots": ["docs/", "operating-manual/"],
                            "validation": "npm --prefix website run build",
                            "on_unavailable": {
                                "provider": "linear",
                                "action": "find_or_create_issue",
                                "team": "Agentic OS",
                                "project": "Rubicon: Documentation",
                            },
                        },
                    }
                },
                "approval": {"required": False},
                "limits": {"max_chain_depth": 3, "cooldown": "10_minutes"},
                "idempotency": {"key": "{event_idempotency_key}:feature_merged_to_docs_update"},
            },
            {
                "id": "email_sent_to_crm_update",
                "display_name": "Email sent updates CRM follow-up",
                "enabled": False,
                "when": {"event_type": "email.message.sent", "filters": {}},
                "then": {
                    "enqueue": {
                        "work_type": "crm_update",
                        "route_to": "shared_factory",
                        "workflow": "email_to_crm_update",
                        "context_profile": "customer_communication",
                        "maturity": "prepare",
                    }
                },
                "approval": {"required": True},
                "limits": {"max_chain_depth": 2},
                "idempotency": {"key": "{event_idempotency_key}:email_sent_to_crm_update"},
            },
            {
                "id": "transcript_to_followup_tasks",
                "display_name": "Meeting transcript creates follow-up task review",
                "enabled": False,
                "when": {"event_type": "granola.note.created", "filters": {}},
                "then": {
                    "enqueue": {
                        "work_type": "task_extraction",
                        "route_to": "shared_factory",
                        "workflow": "transcript_followup_tasks",
                        "context_profile": "meeting_transcript",
                        "maturity": "prepare",
                    }
                },
                "approval": {"required": False},
                "limits": {"max_chain_depth": 2},
                "idempotency": {"key": "{event_idempotency_key}:transcript_to_followup_tasks"},
            },
            {
                "id": "notion_card_to_worktree",
                "display_name": "Notion work item starts worktree preparation",
                "enabled": False,
                "when": {"event_type": "notion.card.ready", "filters": {}},
                "then": {
                    "enqueue": {
                        "work_type": "worktree_prepare",
                        "route_to": "shared_factory",
                        "workflow": "work_item_worktree_prepare",
                        "context_profile": "notion_work_item",
                        "maturity": "prepare",
                    }
                },
                "approval": {"required": False},
                "limits": {"max_chain_depth": 2},
                "idempotency": {"key": "{event_idempotency_key}:notion_card_to_worktree"},
            },
            {
                "id": "run_needs_approval_to_approval_item",
                "display_name": "Run needs approval creates approval work item",
                "enabled": False,
                "when": {"event_type": "os.run.closed.needs_approval"},
                "then": {
                    "enqueue": {
                        "work_type": "approval_review",
                        "route_to": "shared_factory",
                        "workflow": "approval_review",
                        "context_profile": "run_closeout",
                        "maturity": "prepare",
                    }
                },
                "approval": {"required": True},
                "limits": {"max_chain_depth": 2},
                "idempotency": {"key": "{event_idempotency_key}:approval_item"},
            },
            {
                "id": "approval_granted_dispatch",
                "display_name": "Approval granted dispatches guarded action",
                "enabled": False,
                "when": {"event_type": "os.approval.granted", "filters": {}},
                "then": {
                    "enqueue": {
                        "work_type": "approved_dispatch",
                        "route_to": "shared_factory",
                        "workflow": "dispatch_approved_action",
                        "context_profile": "approval_evidence",
                        "maturity": "execute_guarded",
                    }
                },
                "approval": {"required": False},
                "limits": {"max_chain_depth": 2},
                "idempotency": {"key": "{event_idempotency_key}:approval_granted_dispatch"},
            },
            {
                "id": "ci_failure_investigation",
                "display_name": "CI failure queues investigation workflow",
                "enabled": False,
                "when": {"event_type": "github.check_suite.failed", "filters": {}},
                "then": {
                    "enqueue": {
                        "work_type": "ci_failure_investigation",
                        "route_to": "shared_factory",
                        "workflow": "investigate_ci_failure",
                        "context_profile": "github_ci_failure",
                        "maturity": "prepare",
                    }
                },
                "approval": {"required": False},
                "limits": {"max_chain_depth": 2},
                "idempotency": {"key": "{event_idempotency_key}:ci_failure_investigation"},
            },
        ]
    }


def default_event_cursors() -> dict[str, Any]:
    return {"processed_idempotency_keys": []}


def default_run_queue() -> dict[str, Any]:
    return {
        "version": "0.1.0",
        "managed_by": "agentic-os runtime",
        "states": ["dry-run", "queued", "approval-needed", "running", "blocked", "done", "failed", "skipped"],
        "approval_states": ["not_required", "required", "approved", "denied", "expired", "blocked"],
        "items": [],
        "run_queue": [],
    }


def ensure_event_state(root: str | Path) -> Path:
    os_root = expand_path(root)
    write_yaml_once(os_root / EVENT_GRAPH_FILE, default_event_graph())
    write_yaml_once(os_root / CHAIN_RULES_FILE, default_chain_rules())
    write_yaml_once(os_root / EVENT_CURSORS_FILE, default_event_cursors())
    write_yaml_once(os_root / RUN_QUEUE, default_run_queue())
    (os_root / EVENTS).mkdir(parents=True, exist_ok=True)
    (os_root / DEAD_LETTER).mkdir(parents=True, exist_ok=True)
    (os_root / PROCESSING_RESULTS).mkdir(parents=True, exist_ok=True)
    if not (os_root / LEDGER_INDEX).is_file():
        (os_root / LEDGER_INDEX).write_text("# Event Ledger\n\n| Event | Type | Observed At | Summary |\n| --- | --- | --- | --- |\n", encoding="utf-8")
    return os_root


def event_id(event_type: str, source_ref: str, observed_at: str) -> str:
    digest = hashlib.sha256(f"{event_type}:{source_ref}:{observed_at}".encode()).hexdigest()[:12]
    return f"evt_{digest}"


def append_ledger_index(root: Path, event: dict[str, Any]) -> None:
    ensure_event_state(root)
    row = f"| `{event['id']}` | `{event['type']}` | {event['observed_at']} | {event.get('summary', '')} |\n"
    path = root / LEDGER_INDEX
    content = path.read_text(encoding="utf-8")
    if row not in content:
        path.write_text(f"{content}{row}", encoding="utf-8")


def state_ledger_dual_write_enabled(root: Path) -> bool:
    """Whether event appends should also target the SQLite shadow ledger.

    The setting is deliberately opt-in and lives beside the event-graph
    configuration so an existing installed root keeps its file-only behavior
    until an operator has established a parity baseline.
    """
    config = load_yaml(root / EVENT_GRAPH_FILE).get("event_graph") or {}
    state_ledger = config.get("state_ledger") if isinstance(config, dict) else {}
    return isinstance(state_ledger, dict) and state_ledger.get("dual_write") is True


def append_state_ledger_event(root: Path, event: dict[str, Any]) -> dict[str, Any]:
    """Append the normalized SQLite projection for an existing YAML event.

    Callers write the file-backed event first.  This preserves the established
    ledger as the ground truth while a configured shadow write is active.
    """
    source = event.get("source") or {}
    correlation = event.get("correlation") or {}
    privacy = event.get("privacy") or {}
    links = event.get("links") or {}
    connection = state_db.connect(state_db.default_db_path(root))
    try:
        return state_events.append(
            connection,
            event_type=str(event["type"]),
            id=str(event["id"]),
            schema_version_value=int(event.get("schema_version") or 1),
            occurred_at=str(event["occurred_at"]),
            observed_at=str(event["observed_at"]),
            source_ref=source.get("ref"),
            correlation_id=correlation.get("correlation_id"),
            idempotency_key=event.get("idempotency_key"),
            summary=event.get("summary"),
            payload=event.get("payload_ref") or {},
            contains_secret=bool(privacy.get("contains_secret", False)),
            contains_customer_data=bool(privacy.get("contains_customer_data", False)),
            run_log_link=links.get("run_log"),
            source_url=links.get("source_url"),
            domain="shared_factory",
        )
    finally:
        connection.close()


def append_event(
    root: str | Path,
    *,
    event_type: str,
    source_ref: str,
    summary: str = "",
    correlation_id: str | None = None,
    payload_ref: dict[str, Any] | None = None,
    run_log: str | None = None,
) -> dict[str, Any]:
    os_root = ensure_event_state(root)
    observed_at = utc_now()
    event = {
        "id": event_id(event_type, source_ref, observed_at),
        "type": event_type,
        "schema_version": 1,
        "occurred_at": observed_at,
        "observed_at": observed_at,
        "source": {"ref": source_ref},
        "correlation": {"correlation_id": correlation_id or hashlib.sha256(source_ref.encode()).hexdigest()[:16]},
        "idempotency_key": f"{event_type}:{hashlib.sha256(source_ref.encode()).hexdigest()[:16]}",
        "summary": summary or f"Observed {event_type} from {source_ref}.",
        "payload_ref": payload_ref or {"type": "ref", "href": source_ref},
        "privacy": {"contains_secret": False, "contains_customer_data": False},
        "links": {"run_log": run_log, "source_url": source_ref},
    }
    path = os_root / EVENTS / f"{event['id']}.yml"
    write_yaml_once(path, event)
    append_ledger_index(os_root, event)
    if state_ledger_dual_write_enabled(os_root):
        append_state_ledger_event(os_root, event)
    event["path"] = str(path)
    return event


def list_events(root: str | Path, *, limit: int = 20) -> dict[str, Any]:
    os_root = ensure_event_state(root)
    events = []
    for path in sorted((os_root / EVENTS).glob("evt_*.yml")):
        event = load_yaml(path)
        event["path"] = str(path)
        events.append(event)
    events.sort(key=lambda item: str(item.get("observed_at") or item.get("occurred_at") or ""))
    events = events[-limit:]
    return {"events": events, "ledger": str(os_root / LEDGER_INDEX)}


def load_chain_rules(root: str | Path) -> list[dict[str, Any]]:
    os_root = ensure_event_state(root)
    data = load_yaml(os_root / CHAIN_RULES_FILE)
    rules = data.get("chain_rules") or []
    return [rule for rule in rules if isinstance(rule, dict)]


def chain_list(root: str | Path) -> dict[str, Any]:
    return {"chain_rules": load_chain_rules(root)}


def match_rule(rule: dict[str, Any], event: dict[str, Any]) -> bool:
    when = rule.get("when") or {}
    if when.get("event_type") != event.get("type"):
        return False
    filters = when.get("filters") or {}
    payload = event.get("payload") or {}
    source = event.get("source") or {}
    for key, value in filters.items():
        if event.get(key) == value or payload.get(key) == value or source.get(key) == value:
            continue
        return False
    return True


class SafeFormatDict(dict[str, Any]):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def format_template(template: str, values: dict[str, Any]) -> str:
    normalized = template.replace("{event.id}", "{event_id}").replace("{rule.id}", "{rule_id}")
    return normalized.format_map(SafeFormatDict({key: "" if value is None else value for key, value in values.items()}))


def chain_format_values(rule: dict[str, Any], event: dict[str, Any]) -> dict[str, Any]:
    correlation = event.get("correlation") or {}
    source = event.get("source") or {}
    payload_ref = event.get("payload_ref") or {}
    return {
        "event_id": event.get("id"),
        "event_type": event.get("type"),
        "event_idempotency_key": event.get("idempotency_key") or event.get("id"),
        "rule_id": rule.get("id"),
        "correlation_id": correlation.get("correlation_id"),
        "parent_event_id": correlation.get("parent_event_id"),
        "run_id": correlation.get("run_id"),
        "source_ref": source.get("ref"),
        "payload_href": payload_ref.get("href") or payload_ref.get("path"),
    }


def rule_idempotency_key(rule: dict[str, Any], event: dict[str, Any]) -> str:
    enqueue = ((rule.get("then") or {}).get("enqueue")) or {}
    template = enqueue.get("idempotency_key") or ((rule.get("idempotency") or {}).get("key")) or "{event_idempotency_key}:{rule_id}"
    return format_template(str(template), chain_format_values(rule, event))


def event_chain_depth(event: dict[str, Any]) -> int:
    correlation = event.get("correlation") or {}
    raw_depth = correlation.get("chain_depth", event.get("chain_depth", 0))
    try:
        return int(raw_depth or 0)
    except (TypeError, ValueError):
        return 0


def max_chain_depth(rule: dict[str, Any]) -> int | None:
    raw_depth = (rule.get("limits") or {}).get("max_chain_depth")
    try:
        return int(raw_depth)
    except (TypeError, ValueError):
        return None


def queue_item_for(rule: dict[str, Any], event: dict[str, Any]) -> dict[str, Any]:
    enqueue = ((rule.get("then") or {}).get("enqueue")) or {}
    approval_required = bool((rule.get("approval") or {}).get("required"))
    correlation = event.get("correlation") or {}
    key = rule_idempotency_key(rule, event)
    return {
        "id": f"queue_{hashlib.sha256(key.encode()).hexdigest()[:12]}",
        "kind": "event_chain",
        "ref": rule["id"],
        "source_event_id": event["id"],
        "chain_rule_id": rule["id"],
        "status": "approval-needed" if approval_required else "queued",
        "approval_state": "required" if approval_required else "not_required",
        "work_type": enqueue.get("work_type", "review"),
        "route_to": enqueue.get("route_to", "shared_factory"),
        "workflow": enqueue.get("workflow"),
        "context_profile": enqueue.get("context_profile", "default"),
        "execution_target": enqueue.get("execution_target"),
        "maturity": enqueue.get("maturity", "observe"),
        "documentation_site_delivery": enqueue.get("documentation_site_delivery"),
        "idempotency_key": key,
        "correlation_id": correlation.get("correlation_id"),
        "chain_depth": event_chain_depth(event) + 1,
        "evidence": [{"type": "event", "path": event.get("path"), "event_id": event.get("id")}],
        "created_at": utc_now(),
    }


def append_queue_item(root: Path, item: dict[str, Any]) -> dict[str, Any]:
    return append_run_queue_item(root, item)


def processed_keys(root: Path) -> set[str]:
    data = load_yaml(root / EVENT_CURSORS_FILE) or default_event_cursors()
    return set(data.get("processed_idempotency_keys") or [])


def record_processed_key(root: Path, key: str) -> None:
    data = load_yaml(root / EVENT_CURSORS_FILE) or default_event_cursors()
    keys = data.setdefault("processed_idempotency_keys", [])
    if key not in keys:
        keys.append(key)
    write_yaml(root / EVENT_CURSORS_FILE, data)


def processing_result(rule: dict[str, Any], event: dict[str, Any], item: dict[str, Any] | None, status: str, reason: str) -> dict[str, Any]:
    return {
        "event_id": event["id"],
        "chain_rule_id": rule.get("id"),
        "status": status,
        "reason": reason,
        "idempotency_key": rule_idempotency_key(rule, event) if rule.get("id") and (rule.get("then") or {}).get("enqueue") else None,
        "queue_item_id": item.get("id") if item else None,
        "queue_item": item,
        "processed_at": utc_now(),
    }


def write_processing_result(root: Path, result: dict[str, Any]) -> Path:
    path = root / PROCESSING_RESULTS / f"{result['event_id']}-{result.get('chain_rule_id') or 'unknown-rule'}.yml"
    write_yaml(path, result)
    return path


def write_dead_letter(root: Path, event: dict[str, Any], rule: dict[str, Any], reason: str) -> Path:
    payload = {
        "event_id": event.get("id"),
        "chain_rule_id": rule.get("id"),
        "failure_reason": reason,
        "next_action": "Review the event and chain rule before replay.",
        "processing_result": None,
        "recorded_at": utc_now(),
    }
    path = root / DEAD_LETTER / f"{event.get('id', 'event')}-{rule.get('id', 'rule')}.yml"
    write_yaml(path, payload)
    return path


def process_event(root: Path, event: dict[str, Any], *, dry_run: bool) -> list[dict[str, Any]]:
    results = []
    processed = processed_keys(root)
    for rule in load_chain_rules(root):
        if not rule.get("enabled"):
            continue
        if not match_rule(rule, event):
            continue
        if not rule.get("id") or not (rule.get("then") or {}).get("enqueue"):
            reason = "enabled rule is missing id or enqueue action"
            result = processing_result(rule, event, None, "dead-letter", reason)
            if not dry_run:
                dead_letter = write_dead_letter(root, event, rule, reason)
                result["dead_letter"] = str(dead_letter)
                result["path"] = str(write_processing_result(root, result))
            results.append(result)
            continue
        key = rule_idempotency_key(rule, event)
        max_depth = max_chain_depth(rule)
        current_depth = event_chain_depth(event)
        if max_depth is not None and current_depth >= max_depth:
            reason = f"max chain depth reached: {current_depth} >= {max_depth}"
            result = processing_result(rule, event, None, "skipped", reason)
            if not dry_run:
                result["path"] = str(write_processing_result(root, result))
            results.append(result)
            continue
        if key in processed:
            results.append(processing_result(rule, event, None, "skipped", "idempotency key already processed"))
            continue
        item = queue_item_for(rule, event)
        result = processing_result(rule, event, item, "dry-run" if dry_run else item["status"], "matched chain rule")
        if not dry_run:
            queued = append_queue_item(root, item)
            result["queue_item"] = queued["queue_item"]
            result["queue_item_id"] = queued["queue_item"].get("id")
            result["run_queue"] = queued["run_queue"]
            result["created"] = queued["created"]
            if not queued["created"]:
                result["status"] = "skipped"
                result["reason"] = "idempotency key already queued"
            record_processed_key(root, key)
            path = write_processing_result(root, result)
            result["path"] = str(path)
        results.append(result)
    return results


def process_due(root: str | Path, *, dry_run: bool = True) -> dict[str, Any]:
    os_root = ensure_event_state(root)
    actions = []
    for event in list_events(os_root, limit=1000)["events"]:
        event_results = process_event(os_root, event, dry_run=dry_run)
        if event_results:
            actions.append({"event_id": event["id"], "results": event_results})
    return {"dry_run": dry_run, "actions": actions}


def replay_event(root: str | Path, event_id_value: str, *, dry_run: bool = True) -> dict[str, Any]:
    os_root = ensure_event_state(root)
    event_path = os_root / EVENTS / f"{validate_name(event_id_value, 'event_id')}.yml"
    if not event_path.is_file():
        raise ValueError(f"event not found: {event_id_value}")
    event = load_yaml(event_path)
    return {"dry_run": dry_run, "event_id": event_id_value, "results": process_event(os_root, event, dry_run=dry_run)}


def summarize_events(root: str | Path, *, limit: int = 20) -> dict[str, Any]:
    os_root = ensure_event_state(root)
    items = runtime_queue_items(os_root)
    pending = [
        item
        for item in items
        if isinstance(item, dict) and item.get("status") in {"queued", "approval-needed", "running", "blocked"}
    ]
    dead_letters = []
    for path in sorted((os_root / DEAD_LETTER).glob("*.yml"))[-limit:]:
        record = load_yaml(path)
        record["path"] = str(path)
        dead_letters.append(record)
    processing_results = []
    for path in sorted((os_root / PROCESSING_RESULTS).glob("*.yml"))[-limit:]:
        record = load_yaml(path)
        record["path"] = str(path)
        processing_results.append(record)
    return {
        "last_events": list_events(os_root, limit=limit)["events"],
        "pending_follow_up": pending[-limit:],
        "dead_letters": dead_letters,
        "processing_results": processing_results,
        "ledger": str(os_root / LEDGER_INDEX),
        "run_queue": str(os_root / RUN_QUEUE),
    }


def test_chain_rule(root: str | Path, rule_id: str, event_file: str | Path) -> dict[str, Any]:
    rule_id = validate_name(rule_id, "chain_rule_id")
    rule = next((candidate for candidate in load_chain_rules(root) if candidate.get("id") == rule_id), None)
    if not rule:
        raise ValueError(f"chain rule not found: {rule_id}")
    event = load_yaml(Path(event_file))
    matched = match_rule(rule, event)
    return {
        "rule_id": rule_id,
        "event_id": event.get("id"),
        "matched": matched,
        "queue_item": queue_item_for(rule, event) if matched and (rule.get("then") or {}).get("enqueue") else None,
    }


def chain_doctor(root: str | Path) -> dict[str, Any]:
    findings = []
    for rule in load_chain_rules(root):
        path = str(expand_path(root) / CHAIN_RULES_FILE)
        if not rule.get("id"):
            findings.append({"severity": "blocker", "path": path, "message": "chain rule missing id"})
        if not (rule.get("when") or {}).get("event_type"):
            findings.append({"severity": "blocker", "path": path, "message": f"chain rule {rule.get('id')} missing event_type"})
        if rule.get("enabled") and not (rule.get("then") or {}).get("enqueue"):
            findings.append({"severity": "blocker", "path": path, "message": f"enabled chain rule {rule.get('id')} missing enqueue action"})
        if not (rule.get("idempotency") or {}).get("key"):
            findings.append({"severity": "fix-soon", "path": path, "message": f"chain rule {rule.get('id')} missing idempotency key"})
        if rule.get("enabled") and not (rule.get("limits") or {}).get("max_chain_depth"):
            findings.append({"severity": "blocker", "path": path, "message": f"enabled chain rule {rule.get('id')} missing max_chain_depth"})
    return {"ok": not any(finding["severity"] == "blocker" for finding in findings), "findings": findings}


def emit_run_close_event(root: str | Path, close_result: dict[str, Any]) -> dict[str, Any]:
    run_log = close_result["run_log"]
    status = close_result["status"]
    event = append_event(
        root,
        event_type=f"os.run.closed.{status}",
        source_ref=run_log,
        summary=f"Run closed as {status}.",
        run_log=run_log,
    )
    emitted_dir = Path(run_log).parent / "emitted-events"
    emitted_dir.mkdir(parents=True, exist_ok=True)
    emitted_path = emitted_dir / f"{event['id']}.yml"
    write_yaml_once(emitted_path, event)
    event["emitted_path"] = str(emitted_path)
    return event


def format_event_graph_result(result: dict[str, Any]) -> str:
    return yaml.safe_dump(result, sort_keys=False).strip()
