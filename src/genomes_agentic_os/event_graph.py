"""File-backed event ledger and chain processing."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from pathlib import Path
from typing import Any

import yaml

from .scaffold import expand_path, validate_name


CONTROL_PLANE = Path("shared_factory/00-control-plane")
EVENTS = Path("shared_factory/06-runs-and-logs/events")
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
                    }
                },
                "approval": {"required": False},
                "limits": {"max_chain_depth": 3, "cooldown": "10_minutes"},
                "idempotency": {"key": "{event_id}:feature_merged_to_docs_update"},
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
                "idempotency": {"key": "{event_id}:approval_item"},
            },
        ]
    }


def default_event_cursors() -> dict[str, Any]:
    return {"processed_idempotency_keys": []}


def default_run_queue() -> dict[str, Any]:
    return {"run_queue": []}


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
    event["path"] = str(path)
    return event


def list_events(root: str | Path, *, limit: int = 20) -> dict[str, Any]:
    os_root = ensure_event_state(root)
    events = []
    for path in sorted((os_root / EVENTS).glob("evt_*.yml"))[-limit:]:
        event = load_yaml(path)
        event["path"] = str(path)
        events.append(event)
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


def rule_idempotency_key(rule: dict[str, Any], event: dict[str, Any]) -> str:
    template = ((rule.get("idempotency") or {}).get("key")) or "{event_id}:{rule_id}"
    return template.format(event_id=event["id"], rule_id=rule["id"])


def queue_item_for(rule: dict[str, Any], event: dict[str, Any]) -> dict[str, Any]:
    enqueue = ((rule.get("then") or {}).get("enqueue")) or {}
    return {
        "id": f"queue_{hashlib.sha256(rule_idempotency_key(rule, event).encode()).hexdigest()[:12]}",
        "source_event_id": event["id"],
        "chain_rule_id": rule["id"],
        "status": "pending",
        "work_type": enqueue.get("work_type", "review"),
        "route_to": enqueue.get("route_to", "shared_factory"),
        "workflow": enqueue.get("workflow"),
        "context_profile": enqueue.get("context_profile", "default"),
        "maturity": enqueue.get("maturity", "observe"),
        "idempotency_key": rule_idempotency_key(rule, event),
        "created_at": utc_now(),
    }


def append_queue_item(root: Path, item: dict[str, Any]) -> bool:
    data = load_yaml(root / RUN_QUEUE) or default_run_queue()
    queue = data.setdefault("run_queue", [])
    if any(existing.get("idempotency_key") == item["idempotency_key"] for existing in queue):
        return False
    queue.append(item)
    write_yaml(root / RUN_QUEUE, data)
    return True


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
        "chain_rule_id": rule["id"],
        "status": status,
        "reason": reason,
        "queue_item": item,
        "processed_at": utc_now(),
    }


def write_processing_result(root: Path, result: dict[str, Any]) -> Path:
    path = root / PROCESSING_RESULTS / f"{result['event_id']}-{result['chain_rule_id']}.yml"
    write_yaml(path, result)
    return path


def write_dead_letter(root: Path, event: dict[str, Any], rule: dict[str, Any], reason: str) -> Path:
    payload = {
        "event_id": event.get("id"),
        "chain_rule_id": rule.get("id"),
        "failure_reason": reason,
        "next_action": "Review the event and chain rule before replay.",
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
            dead_letter = write_dead_letter(root, event, rule, "enabled rule is missing id or enqueue action")
            results.append({"status": "dead-letter", "dead_letter": str(dead_letter), "rule": rule.get("id")})
            continue
        key = rule_idempotency_key(rule, event)
        if key in processed:
            results.append(processing_result(rule, event, None, "skipped", "idempotency key already processed"))
            continue
        item = queue_item_for(rule, event)
        result = processing_result(rule, event, item, "dry-run" if dry_run else "queued", "matched chain rule")
        if not dry_run:
            append_queue_item(root, item)
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
