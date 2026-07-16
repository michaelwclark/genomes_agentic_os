"""Privacy-safe, provider-agnostic activity ingestion for operator analytics."""

from __future__ import annotations
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import re
from typing import Any
import yaml
from .scaffold import expand_path, validate_name

CONTROL_PLANE = Path("harness/shared_factory/00-control-plane")
REGISTRY = CONTROL_PLANE / "activity-sources.yml"
CURSORS = CONTROL_PLANE / "activity-cursors.yml"
HEALTH = CONTROL_PLANE / "activity-source-health.yml"
EVENTS = Path("harness/shared_factory/06-runs-and-logs/source-events/activity")
METRICS = Path("harness/registries/analytics-metrics.yml")
LOCAL_EVENT_LEDGER = Path("harness/shared_factory/06-runs-and-logs/events")
LOCAL_RUN_LOGS = Path("harness/shared_factory/06-runs-and-logs/runs")
PROVIDERS = {"slack", "github", "jira", "linear", "agentic_os"}
EVENT_ALIASES = {
    "slack": {
        "message": "message.sent",
        "message_created": "message.sent",
        "reply": "thread.reply",
    },
    "github": {
        "pr_opened": "pull_request.opened",
        "pr_closed": "pull_request.closed",
        "pr_merged": "pull_request.merged",
        "review_submitted": "pull_request.reviewed",
        "action_completed": "workflow_run.completed",
        "action_failed": "workflow_run.failed",
    },
    "jira": {
        "created": "issue.created",
        "transitioned": "issue.transitioned",
        "completed": "issue.completed",
    },
    "linear": {
        "created": "issue.created",
        "transitioned": "issue.transitioned",
        "completed": "issue.completed",
    },
    "agentic_os": {
        "tool_ran": "tool.ran",
        "message": "conversation.message",
        "automation_ran": "automation.ran",
        "error": "error.recorded",
    },
}
FORBIDDEN_KEYS = {
    "body",
    "content",
    "text",
    "message",
    "prompt",
    "response",
    "description",
    "token",
    "secret",
    "credential",
    "password",
    "authorization",
    "cookie",
    "customer",
    "customer_name",
    "email",
    "url",
    "html_url",
    "web_url",
}
SAFE_ATTRIBUTES = {
    "action",
    "conclusion",
    "harness",
    "kind",
    "provider",
    "result",
    "state",
    "status",
}
SAFE_SLUG = re.compile(r"^[a-z0-9][a-z0-9_.:/-]{0,99}$")
ISO_TIMESTAMP = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$"
)
LOCAL_STATUS_VALUES = {
    "approval-needed",
    "blocked",
    "completed",
    "done",
    "dry-run",
    "error",
    "failed",
    "finalized",
    "healthy",
    "passed",
    "queued",
    "running",
    "skipped",
    "success",
    "unavailable",
}
LOCAL_KIND_VALUES = {
    "automation",
    "command",
    "event_chain",
    "heartbeat",
    "integration",
    "run",
    "runtime_dispatch",
    "schedule",
    "source_trigger",
    "tool",
    "tool_call",
}


def utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _load(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    value = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return value if isinstance(value, dict) else {}


def _write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")


def ensure_state(root: str | Path) -> Path:
    os_root = expand_path(root)
    for relative, value in (
        (REGISTRY, {"schema_version": 1, "activity_sources": []}),
        (CURSORS, {"schema_version": 1, "sources": {}}),
        (HEALTH, {"schema_version": 1, "sources": {}}),
    ):
        if not (os_root / relative).exists():
            _write(os_root / relative, value)
    (os_root / EVENTS).mkdir(parents=True, exist_ok=True)
    return os_root


def list_sources(root: str | Path) -> list[dict[str, Any]]:
    items = _load(expand_path(root) / REGISTRY).get("activity_sources") or []
    return [item for item in items if isinstance(item, dict)]


def _metric_ids(root: Path) -> set[str]:
    return {
        str(item.get("id"))
        for item in (_load(root / METRICS).get("metrics") or [])
        if isinstance(item, dict)
    }


def _safe_value(key: str, value: Any) -> bool:
    if key.lower() in FORBIDDEN_KEYS or not isinstance(value, (str, int, float, bool)):
        return False
    if isinstance(value, str):
        lowered = value.lower()
        return (
            bool(SAFE_SLUG.fullmatch(lowered))
            and not lowered.startswith(("http:", "https:", "xox", "sk-"))
            and "@" not in lowered
        )
    return True


def _safe_dimensions(source: dict[str, Any]) -> dict[str, Any]:
    dimensions = source.get("dimensions") or {}
    if not isinstance(dimensions, dict) or any(
        not _safe_value(str(key), value) for key, value in dimensions.items()
    ):
        raise ValueError("dimensions must contain privacy-safe registered scalar slugs")
    return dict(dimensions)


def validate_sources(root: str | Path) -> dict[str, Any]:
    os_root = expand_path(root)
    findings = []
    metric_ids = _metric_ids(os_root)
    seen = set()
    for source in list_sources(os_root):
        source_id = str(source.get("id") or "")
        prefix = source_id or "<missing-id>"
        if not source_id:
            findings.append(
                {"severity": "blocker", "source": prefix, "message": "missing id"}
            )
        elif source_id in seen:
            findings.append(
                {"severity": "blocker", "source": prefix, "message": "duplicate id"}
            )
        else:
            validate_name(source_id, "activity source id")
            seen.add(source_id)
        if source.get("provider") not in PROVIDERS:
            findings.append(
                {
                    "severity": "blocker",
                    "source": prefix,
                    "message": "unsupported provider",
                }
            )
        scope = source.get("scope") or {}
        if not scope.get("domain") or not scope.get("project"):
            findings.append(
                {
                    "severity": "blocker",
                    "source": prefix,
                    "message": "registered domain and project are required",
                }
            )
        if source.get("enabled") and source.get("opt_in") is not True:
            findings.append(
                {
                    "severity": "blocker",
                    "source": prefix,
                    "message": "enabled source requires explicit opt_in: true",
                }
            )
        try:
            _safe_dimensions(source)
        except ValueError as exc:
            findings.append(
                {"severity": "blocker", "source": prefix, "message": str(exc)}
            )
        for event_type, metric_id in (source.get("metric_bindings") or {}).items():
            if metric_id not in metric_ids:
                findings.append(
                    {
                        "severity": "blocker",
                        "source": prefix,
                        "message": f"{event_type} binds unknown metric {metric_id}",
                    }
                )
    return {
        "ok": not any(f["severity"] == "blocker" for f in findings),
        "findings": findings,
        "sources": len(seen),
    }


def _event_type(provider: str, item: dict[str, Any]) -> str:
    raw = str(
        item.get("event_type") or item.get("type") or item.get("action") or "observed"
    )
    normalized = raw.lower().replace(" ", "_").replace("-", "_")
    normalized = EVENT_ALIASES.get(provider, {}).get(normalized, normalized)
    event_type = (
        normalized
        if normalized.startswith(f"{provider}.") or normalized.startswith("os.")
        else f"{'os' if provider == 'agentic_os' else provider}.{normalized}"
    )
    if not SAFE_SLUG.fullmatch(event_type):
        raise ValueError("provider event type is not a safe slug")
    return event_type


def _safe_attributes(item: dict[str, Any]) -> dict[str, Any]:
    result = {}
    for key in SAFE_ATTRIBUTES:
        value = item.get(key)
        if value is not None and _safe_value(key, value):
            result[key] = value
    return result


def event_envelope(source: dict[str, Any], item: dict[str, Any]) -> dict[str, Any]:
    provider = str(source["provider"])
    external_id = item.get("id") or item.get("event_id") or item.get("node_id")
    if not external_id:
        raise ValueError("provider item missing stable id")
    event_type = _event_type(provider, item)
    digest = hashlib.sha256(
        f"{source['id']}:{external_id}:{event_type}".encode()
    ).hexdigest()
    scope = source.get("scope") or {}
    candidate_time = str(
        item.get("occurred_at")
        or item.get("created_at")
        or item.get("updated_at")
        or ""
    )
    occurred_at = (
        candidate_time if ISO_TIMESTAMP.fullmatch(candidate_time) else utc_now()
    )
    metric_id = (source.get("metric_bindings") or {}).get(event_type)
    if not metric_id:
        raise ValueError(f"event type has no analytics metric binding: {event_type}")
    return {
        "id": f"activity_{digest[:16]}",
        "schema_version": 1,
        "type": event_type,
        "occurred_at": occurred_at,
        "observed_at": utc_now(),
        "source": {"id": source["id"], "provider": provider},
        "scope": {"domain": scope["domain"], "project": scope["project"]},
        "dimensions": _safe_dimensions(source),
        "metric": {"id": metric_id, "value": 1},
        "attributes": _safe_attributes(item),
        "idempotency_key": digest,
        "privacy": {
            "classification": "metadata_only",
            "contains_body": False,
            "contains_secret": False,
            "contains_customer_data": False,
            "contains_private_link": False,
        },
    }


def _update_health(root: Path, source_id: str, **values: Any) -> None:
    data = _load(root / HEALTH) or {"schema_version": 1, "sources": {}}
    data.setdefault("sources", {}).setdefault(source_id, {}).update(values)
    data["sources"][source_id]["checked_at"] = utc_now()
    _write(root / HEALTH, data)


def _local_event_type(evidence_kind: str, record: dict[str, Any]) -> str | None:
    """Classify local evidence without copying its provider payload."""
    raw_type = str(record.get("type") or record.get("event_type") or "").lower()
    status = str(record.get("status") or "").lower()
    kind = str(record.get("kind") or "").lower()
    combined = f"{raw_type} {status} {kind}"
    if any(
        marker in combined
        for marker in ("error", "failed", "failure", "regression", "unavailable")
    ):
        return "error"
    if evidence_kind == "event" and (
        "conversation.message" in raw_type or raw_type.endswith(".message")
    ):
        return "message"
    if evidence_kind == "event" and ("tool." in raw_type or ".tool" in raw_type):
        return "tool_ran"
    if evidence_kind == "run" and kind in {"tool", "tool_call", "command"}:
        return "tool_ran"
    if (
        evidence_kind == "run"
        or raw_type.startswith("os.run.")
        or raw_type.startswith("os.schedule.")
    ):
        return "automation_ran"
    return None


def _local_occurred_at(record: dict[str, Any]) -> str:
    for key in (
        "finished_at",
        "updated_at",
        "observed_at",
        "occurred_at",
        "started_at",
        "created_at",
    ):
        candidate = str(record.get(key) or "")
        if ISO_TIMESTAMP.fullmatch(candidate):
            return candidate
    return utc_now()


def _local_item(evidence_kind: str, record: dict[str, Any]) -> dict[str, Any] | None:
    event_type = _local_event_type(evidence_kind, record)
    stable_id = (
        record.get("id") or record.get("run_id") or record.get("idempotency_key")
    )
    if not event_type or not stable_id:
        return None
    item: dict[str, Any] = {
        "id": hashlib.sha256(f"{evidence_kind}:{stable_id}".encode()).hexdigest(),
        "type": event_type,
        "occurred_at": _local_occurred_at(record),
    }
    status = str(record.get("status") or "").lower()
    kind = str(record.get("kind") or "").lower()
    if status in LOCAL_STATUS_VALUES:
        item["status"] = status
    if kind in LOCAL_KIND_VALUES:
        item["kind"] = kind
    return item


def discover_local_activity(
    root: str | Path,
    *,
    after_cursor: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    """Read bounded canonical local receipts and return metadata-only records."""
    if limit < 1:
        raise ValueError("local activity limit must be at least 1")
    os_root = expand_path(root)
    candidates: list[tuple[str, str, Path]] = []
    roots_present = 0
    for evidence_kind, directory, pattern in (
        ("event", os_root / LOCAL_EVENT_LEDGER, "evt_*.yml"),
        ("run", os_root / LOCAL_RUN_LOGS, "*/run-log.yml"),
    ):
        if not directory.is_dir():
            continue
        roots_present += 1
        for path in directory.glob(pattern):
            if not path.is_file():
                continue
            path_digest = hashlib.sha256(
                str(path.relative_to(os_root)).encode()
            ).hexdigest()[:16]
            cursor = f"{path.stat().st_mtime_ns:020d}:{path_digest}"
            if after_cursor and cursor <= after_cursor:
                continue
            candidates.append((cursor, evidence_kind, path))
    candidates.sort(key=lambda item: item[0])
    records: list[dict[str, Any]] = []
    malformed = 0
    unsupported = 0
    last_cursor = after_cursor
    for cursor, evidence_kind, path in candidates:
        if malformed + unsupported + len(records) >= max(1, limit):
            break
        try:
            record = _load(path)
        except (OSError, yaml.YAMLError):
            malformed += 1
            last_cursor = cursor
            continue
        if not record:
            malformed += 1
            last_cursor = cursor
            continue
        item = _local_item(evidence_kind, record)
        last_cursor = cursor
        if not item:
            unsupported += 1
            continue
        records.append(item)
    return {
        "available": roots_present > 0,
        "items": records,
        "next_cursor": last_cursor,
        "malformed": malformed,
        "unsupported": unsupported,
        "scanned": malformed + unsupported + len(records),
    }


def collect_local_activity(
    root: str | Path,
    source_id: str,
    *,
    limit: int = 100,
    apply: bool = False,
) -> dict[str, Any]:
    """Collect local receipts through the same CC-307 envelope and cursor path."""
    if limit < 1:
        raise ValueError("local activity limit must be at least 1")
    os_root = ensure_state(root) if apply else expand_path(root)
    source = next(
        (item for item in list_sources(os_root) if item.get("id") == source_id), None
    )
    if not source:
        raise ValueError(f"activity source not found: {source_id}")
    if source.get("provider") != "agentic_os":
        raise ValueError("collect-local requires an agentic_os activity source")
    cursor_state = _load(os_root / CURSORS).get("sources") or {}
    current_cursor = (cursor_state.get(source_id) or {}).get("cursor")
    discovered = discover_local_activity(
        os_root, after_cursor=current_cursor, limit=limit
    )
    if not discovered["available"]:
        error = "canonical local evidence directories are unavailable"
        if apply:
            _update_health(
                os_root,
                source_id,
                status="unavailable",
                freshness="stale",
                completeness="none",
                last_error=error,
                cursor=current_cursor,
                events=0,
            )
        return {
            "ok": False,
            "source_id": source_id,
            "status": "unavailable",
            "error": error,
            "dry_run": not apply,
            **discovered,
        }
    page = {"items": discovered["items"], "next_cursor": discovered["next_cursor"]}
    result = ingest_pages(os_root, source_id, [page], apply=apply)
    result["collector"] = {
        key: discovered[key] for key in ("scanned", "malformed", "unsupported")
    }
    if discovered["malformed"]:
        result["status"] = "degraded"
        result["ok"] = True
        result["error"] = f"{discovered['malformed']} malformed local evidence file(s)"
        if apply:
            _update_health(
                os_root,
                source_id,
                status="degraded",
                freshness="fresh",
                completeness="partial",
                last_error=result["error"],
                cursor=result.get("cursor"),
                events=result.get("emitted", 0),
            )
    return result


def ingest_pages(
    root: str | Path,
    source_id: str,
    pages: list[dict[str, Any]],
    *,
    apply: bool = False,
) -> dict[str, Any]:
    os_root = ensure_state(root) if apply else expand_path(root)
    source_id = validate_name(source_id, "activity source id")
    source = next(
        (item for item in list_sources(os_root) if item.get("id") == source_id), None
    )
    if not source:
        raise ValueError(f"activity source not found: {source_id}")
    if not source.get("enabled") or source.get("opt_in") is not True:
        raise ValueError(f"activity source is not enabled and opted in: {source_id}")
    blockers = [
        f
        for f in validate_sources(os_root)["findings"]
        if f.get("source") == source_id and f["severity"] == "blocker"
    ]
    if blockers:
        raise ValueError(blockers[0]["message"])
    cursor_data = _load(os_root / CURSORS) or {"schema_version": 1, "sources": {}}
    cursor = cursor_data.setdefault("sources", {}).setdefault(
        source_id, {"cursor": None, "seen": []}
    )
    seen = set(cursor.get("seen") or [])
    emitted = []
    duplicates = 0
    next_cursor = cursor.get("cursor")
    status = "healthy"
    error = None
    try:
        for page in pages[
            : int((source.get("limits") or {}).get("max_pages_per_run", 100))
        ]:
            if page.get("error"):
                raise RuntimeError(str(page["error"]))
            for item in page.get("items") or []:
                envelope = event_envelope(source, item)
                if envelope["idempotency_key"] in seen:
                    duplicates += 1
                    continue
                emitted.append(envelope)
                seen.add(envelope["idempotency_key"])
                if apply:
                    _write(os_root / EVENTS / f"{envelope['id']}.yml", envelope)
            next_cursor = page.get("next_cursor", next_cursor)
            if (
                page.get("rate_limit_remaining") is not None
                and int(page["rate_limit_remaining"]) <= 0
                and next_cursor
            ):
                status = "rate_limited"
                break
    except Exception as exc:
        status = "unavailable"
        error = f"{type(exc).__name__}: {exc}"
    if apply:
        cursor.update(
            {"cursor": next_cursor, "seen": sorted(seen), "updated_at": utc_now()}
        )
        _write(os_root / CURSORS, cursor_data)
    if apply:
        _update_health(
            os_root,
            source_id,
            status=status,
            freshness="fresh" if status == "healthy" else "stale",
            completeness="complete" if status == "healthy" else "partial",
            last_error=error,
            cursor=next_cursor,
            events=len(emitted),
        )
    return {
        "ok": status in {"healthy", "rate_limited"},
        "source_id": source_id,
        "status": status,
        "events": emitted,
        "emitted": len(emitted),
        "duplicates": duplicates,
        "cursor": next_cursor,
        "error": error,
        "dry_run": not apply,
    }


def ingest_fixture(
    root: str | Path, fixture: str | Path, *, apply: bool = False
) -> dict[str, Any]:
    results = []
    for run in _load(Path(fixture)).get("sources") or []:
        try:
            results.append(
                ingest_pages(
                    root, str(run["id"]), list(run.get("pages") or []), apply=apply
                )
            )
        except Exception as exc:
            source_id = str(run.get("id") or "unknown")
            if apply:
                _update_health(
                    ensure_state(root),
                    source_id,
                    status="unavailable",
                    freshness="stale",
                    completeness="none",
                    last_error=f"{type(exc).__name__}: {exc}",
                )
            results.append(
                {
                    "ok": False,
                    "source_id": source_id,
                    "status": "unavailable",
                    "error": f"{type(exc).__name__}: {exc}",
                    "emitted": 0,
                }
            )
    return {
        "ok": all(item["ok"] for item in results),
        "partial": any(item["ok"] for item in results)
        and not all(item["ok"] for item in results),
        "results": results,
        "dry_run": not apply,
    }


def health(root: str | Path) -> dict[str, Any]:
    return _load(expand_path(root) / HEALTH) or {"schema_version": 1, "sources": {}}
