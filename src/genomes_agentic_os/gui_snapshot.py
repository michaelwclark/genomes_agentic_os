"""Versioned local snapshot consumed by the AgenticOSGui desktop shell."""

from __future__ import annotations

from datetime import datetime
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
from .runtime_snapshot import build_runtime_snapshot
from .long_run import ACTIVE_STATUSES, list_runs


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
        long_running_rows = list_runs(root, limit=100)["runs"]
    except Exception:
        long_running_rows = []
    long_running_active = [row for row in long_running_rows if row.get("status") in ACTIVE_STATUSES]
    long_running_attention = [
        row
        for row in long_running_rows
        if row.get("status") in {"paused", "no-progress-timeout", "resource-budget-exceeded", "stale"}
    ]
    try:
        snapshot = build_runtime_snapshot(root, task_limit=200)
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
            "max_interactive_running": 1,
            "queues": [],
            "worker_pools": [],
            "workers": [],
            "tasks": [],
            "task_count": 0,
            "task_sample_count": 0,
            "task_sample_limit": 200,
            "long_running_runs": long_running_rows,
            "long_running_active": len(long_running_active),
            "long_running_attention": len(long_running_attention),
            "captured_at": _generated_at(),
            "reason": f"{type(exc).__name__}: {exc}",
        }
    summary = snapshot["summary"]
    return {
        "status": snapshot["health"],
        "queue_mode": snapshot["queue_mode"],
        "queue_depth": int(summary["queued"]) + int(summary["approval_needed"]),
        "running": int(summary["running"]),
        "failed": int(summary["failed"]),
        "dead_letter": int(summary["dead_letter"]),
        "active_workers": int(summary["active_workers"]),
        "unhealthy_workers": int(summary["unhealthy_workers"]),
        "stale_queued": int(summary["stale_queued"]),
        "expired_running_leases": int(summary["expired_running_leases"]),
        "reserved_interactive_slots": max(1, int(summary["reserved_interactive_slots"])),
        "max_interactive_running": max(1, int(summary["max_interactive_running"])),
        "queues": snapshot["queues"],
        "worker_pools": snapshot["worker_pools"],
        "workers": snapshot["workers"],
        "tasks": snapshot["tasks"],
        "task_count": int(summary["total_records"]),
        "task_sample_count": len(snapshot["tasks"]),
        "task_sample_limit": 200,
        "long_running_runs": long_running_rows,
        "long_running_active": len(long_running_active),
        "long_running_attention": len(long_running_attention),
        "captured_at": snapshot["captured_at"],
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
