"""Versioned local snapshot consumed by the AgenticOSGui desktop shell."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from typing import Any

from .claude_sessions import (
    claude_transcript_result_for_id,
    collect_claude_conversations,
    default_desktop_sessions_root,
)
from .codex_sessions import codex_transcript_result_for_id, collect_codex_conversations
from .conversation_index import build_navigation, utc_now
from .runtime_backend import queue_mode_status, runtime_queue_items


SCHEMA_VERSION = "agentic-os-gui/v1"
DEFAULT_OUTPUT = Path("harness/shared_factory/06-runs-and-logs/gui/latest/snapshot.json")


CONVERSATION_FIELDS = (
    "key",
    "id",
    "native_id",
    "cli_session_id",
    "resume_id",
    "title",
    "harness",
    "provider",
    "model",
    "model_tier",
    "reasoning_effort",
    "status",
    "created_at",
    "updated_at",
    "age",
    "domain",
    "project",
    "project_title",
    "project_root",
    "work_item",
    "route_confidence",
    "route_source",
    "route_conflict",
    "cwd",
    "pinned",
    "pin_source",
    "can_continue",
    "imported",
    "continuation_note",
    "continuation",
    "jira_keys",
    "jira_issues",
    "linear_issues",
    "pull_requests",
    "slack_threads",
    "assets",
    "source",
)


def _generated_at(now: datetime | None = None) -> str:
    return utc_now(now).astimezone().isoformat().replace("+00:00", "Z")


def _project_conversation(item: dict[str, Any]) -> dict[str, Any]:
    """Whitelist renderer fields; do not project raw harness/provider blobs."""
    return {field: item[field] for field in CONVERSATION_FIELDS if field in item and item[field] not in (None, "")}


def _runtime_snapshot(root: Path) -> dict[str, Any]:
    try:
        backend = queue_mode_status(root)
    except Exception as exc:
        return {
            "status": "unavailable",
            "queue_mode": "unknown",
            "queue_depth": 0,
            "running": 0,
            "failed": 0,
            "dead_letter": 0,
            "active_workers": 0,
            "unhealthy_workers": 0,
            "stale_queued": 0,
            "expired_running_leases": 0,
            "reserved_interactive_slots": 1,
            "queues": [],
            "worker_pools": [],
            "reason": f"{type(exc).__name__}: {exc}",
        }
    metrics = backend["metrics"]
    statuses: dict[str, int] = {}
    for queue in metrics.get("queues") or []:
        for name, count in (queue.get("statuses") or {}).items():
            statuses[str(name)] = statuses.get(str(name), 0) + int(count)
    dead_letter = int(statuses.get("dead-letter", 0))
    failed = int(statuses.get("failed", 0))
    unhealthy = int(metrics.get("unhealthy_worker_count") or 0)
    queue_depth = int(statuses.get("queued", 0)) + int(statuses.get("approval-needed", 0))
    now = datetime.now(timezone.utc)

    def parsed(value: object) -> datetime | None:
        if not value:
            return None
        try:
            result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
        return result.replace(tzinfo=timezone.utc) if result.tzinfo is None else result.astimezone(timezone.utc)

    items = runtime_queue_items(root)
    recent_failed = sum(
        1
        for item in items
        if item.get("status") == "failed"
        and (finished := parsed(item.get("finished_at") or item.get("updated_at"))) is not None
        and now - finished <= timedelta(hours=1)
    )
    stale_queued = sum(
        1
        for item in items
        if item.get("status") == "queued"
        and (created := parsed(item.get("due_at") or item.get("created_at"))) is not None
        and now - created > timedelta(hours=24)
    )
    expired_running = sum(
        1
        for item in items
        if item.get("status") == "running"
        and (lease := parsed(item.get("lease_until"))) is not None
        and lease < now
    )
    saturated = any(
        int(queue.get("max_queued") or 0)
        and (
            int((queue.get("statuses") or {}).get("queued", 0))
            + int((queue.get("statuses") or {}).get("approval-needed", 0))
        )
        >= int(queue["max_queued"]) * 0.8
        for queue in metrics.get("queues") or []
    )
    status = (
        "critical"
        if dead_letter or stale_queued or expired_running
        else "degraded"
        if recent_failed or unhealthy or saturated
        else "healthy"
    )
    return {
        "status": status,
        "queue_mode": backend["queue_mode"],
        "queue_depth": queue_depth,
        "running": int(statuses.get("running", 0)),
        "failed": failed,
        "dead_letter": dead_letter,
        "active_workers": int(metrics.get("live_worker_count") or 0),
        "unhealthy_workers": unhealthy,
        "stale_queued": stale_queued,
        "expired_running_leases": expired_running,
        "reserved_interactive_slots": int(metrics.get("reserved_interactive_slots") or 1),
        "queues": metrics.get("queues") or [],
        "worker_pools": metrics.get("worker_pools") or [],
    }


def build_gui_snapshot(
    root: str | Path,
    *,
    codex_home: str | Path | None = None,
    claude_home: str | Path | None = None,
    claude_desktop_root: str | Path | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    os_root = Path(root).expanduser().resolve(strict=False)
    codex = collect_codex_conversations(os_root, codex_home=codex_home, now=now)
    claude = collect_claude_conversations(
        os_root,
        claude_home=claude_home,
        desktop_root=claude_desktop_root,
        now=now,
    )
    conversations = [_project_conversation(item) for item in [*codex, *claude]]
    conversations.sort(key=lambda item: (bool(item.get("pinned")), str(item.get("updated_at") or "")), reverse=True)
    runtime = _runtime_snapshot(os_root)

    diagnostics: list[dict[str, str]] = []
    resolved_codex_home = Path(codex_home).expanduser() if codex_home else Path.home() / ".codex"
    resolved_claude_home = Path(claude_home).expanduser() if claude_home else Path.home() / ".claude"
    resolved_desktop = (
        Path(claude_desktop_root).expanduser() if claude_desktop_root else default_desktop_sessions_root()
    )
    if not (resolved_codex_home / ".codex-global-state.json").is_file():
        diagnostics.append(
            {"severity": "info", "message": "Codex Desktop state is unavailable.", "source": str(resolved_codex_home)}
        )
    if not (resolved_codex_home / "state_5.sqlite").is_file():
        diagnostics.append(
            {"severity": "info", "message": "Codex thread database is unavailable.", "source": str(resolved_codex_home)}
        )
    if not resolved_desktop.is_dir():
        diagnostics.append(
            {"severity": "info", "message": "Claude Desktop session metadata is unavailable.", "source": str(resolved_desktop)}
        )
    if not (resolved_claude_home / "projects").is_dir():
        diagnostics.append(
            {"severity": "info", "message": "Claude Code transcripts are unavailable.", "source": str(resolved_claude_home)}
        )
    if runtime["status"] == "unavailable":
        diagnostics.append({"severity": "warning", "message": "Runtime queue health is unavailable.", "source": runtime.get("reason", "runtime")})

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _generated_at(now),
        "root": str(os_root),
        "summary": {
            "conversations": len(conversations),
            "codex": len(codex),
            "claude": len(claude),
            "pinned": sum(bool(item.get("pinned")) for item in conversations),
            "unrouted": sum(not item.get("domain") or not item.get("project") for item in conversations),
        },
        "navigation": build_navigation(os_root, conversations),
        "runtime": runtime,
        "conversations": conversations,
        "diagnostics": diagnostics,
    }


def write_gui_snapshot(snapshot: dict[str, Any], output: str | Path) -> Path:
    path = Path(output).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(snapshot, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def build_transcript_snapshot(
    provider: str,
    conversation_id: str,
    *,
    codex_home: str | Path | None = None,
    claude_home: str | Path | None = None,
    claude_desktop_root: str | Path | None = None,
) -> dict[str, Any]:
    """Return a renderer-safe transcript containing user/assistant text only."""
    if provider == "codex":
        home = Path(codex_home).expanduser() if codex_home else Path.home() / ".codex"
        raw_messages, truncated = codex_transcript_result_for_id(home, conversation_id)
        mode = "resume"
    elif provider == "claude":
        home = Path(claude_home).expanduser() if claude_home else Path.home() / ".claude"
        desktop = (
            Path(claude_desktop_root).expanduser()
            if claude_desktop_root
            else default_desktop_sessions_root()
        )
        raw_messages, truncated = claude_transcript_result_for_id(home, desktop, conversation_id)
        mode = "fork-on-continue"
    else:
        raise ValueError("provider must be codex or claude")

    messages = [
        {
            "id": f"{provider}:{conversation_id}:{index}",
            "role": message["role"],
            "content": message["text"],
            **({"created_at": message["timestamp"]} if message.get("timestamp") else {}),
        }
        for index, message in enumerate(raw_messages, start=1)
        if message.get("role") in {"user", "assistant"} and message.get("text")
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "transcript",
        "conversation_id": conversation_id,
        "provider": provider,
        "messages": messages,
        "truncated": truncated,
        "continuation": {"supported": bool(messages), "mode": mode},
        "diagnostics": []
        if messages
        else [{"severity": "warning", "message": "Conversation transcript was not found."}],
    }
