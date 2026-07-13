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
