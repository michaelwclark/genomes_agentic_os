"""Read-only Claude Desktop / Claude Code conversation adapter."""

from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any

from .conversation_index import (
    age_label,
    build_project_routes,
    build_work_item_routes,
    extract_references,
    human_title,
    iso_from_timestamp,
    model_metadata,
    route_conversation,
    visible_text,
)


MAX_TRANSCRIPT_BYTES = 4_000_000
MAX_REFERENCE_TEXT = 2_000_000


def default_desktop_sessions_root() -> Path:
    return Path.home() / "Library" / "Application Support" / "Claude" / "claude-code-sessions"


def _safe_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}


def _metadata_records(desktop_root: Path) -> dict[str, tuple[dict[str, Any], Path]]:
    """Return newest non-archived Desktop metadata by Claude CLI session ID."""
    records: dict[str, tuple[dict[str, Any], Path]] = {}
    if not desktop_root.is_dir():
        return records
    try:
        candidates = desktop_root.rglob("local_*.json")
    except OSError:
        return records
    for path in candidates:
        data = _safe_json(path)
        cli_id = str(data.get("cliSessionId") or "")
        if not cli_id or data.get("isArchived") is not False:
            continue
        current = records.get(cli_id)
        activity = data.get("lastActivityAt") or data.get("lastFocusedAt") or data.get("createdAt") or 0
        current_activity = (
            current[0].get("lastActivityAt")
            or current[0].get("lastFocusedAt")
            or current[0].get("createdAt")
            or 0
            if current
            else -1
        )
        try:
            is_newer = float(activity) >= float(current_activity)
        except (TypeError, ValueError):
            is_newer = current is None
        if current is None or is_newer:
            records[cli_id] = (data, path)
    return records


def _transcript_index(claude_home: Path) -> dict[str, Path]:
    projects = claude_home / "projects"
    if not projects.is_dir():
        return {}
    paths: dict[str, Path] = {}
    try:
        candidates = projects.rglob("*.jsonl")
    except OSError:
        return paths
    for path in candidates:
        session_id = path.stem
        existing = paths.get(session_id)
        try:
            newer = existing is None or path.stat().st_mtime >= existing.stat().st_mtime
        except OSError:
            newer = existing is None
        if newer:
            paths[session_id] = path
    return paths


def _read_jsonl(path: Path, *, max_bytes: int = MAX_TRANSCRIPT_BYTES) -> tuple[list[dict[str, Any]], bool]:
    rows: list[dict[str, Any]] = []
    try:
        size = path.stat().st_size
    except OSError:
        return rows, False
    truncated = size > max_bytes
    try:
        with path.open("rb") as handle:
            if not truncated:
                raw_lines = handle.readlines()
            else:
                head_bytes = max_bytes // 4
                tail_bytes = max_bytes - head_bytes
                head = handle.read(head_bytes)
                if not head.endswith(b"\n"):
                    head = head.rsplit(b"\n", 1)[0] + b"\n" if b"\n" in head else b""
                handle.seek(max(0, size - tail_bytes))
                tail = handle.read()
                if size > tail_bytes and b"\n" in tail:
                    tail = tail.split(b"\n", 1)[1]
                raw_lines = (head + tail).splitlines()
    except OSError:
        return rows, False
    for raw in raw_lines:
        try:
            row = json.loads(raw.decode("utf-8", errors="replace"))
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows, truncated


def visible_claude_transcript_with_status(path: str | Path) -> tuple[list[dict[str, str]], bool]:
    """Return only visible human and assistant text from Claude Code JSONL."""
    messages: list[dict[str, str]] = []
    rows, truncated = _read_jsonl(Path(path))
    for row in rows:
        if row.get("isMeta") is True:
            continue
        row_type = str(row.get("type") or "")
        message = row.get("message")
        message = message if isinstance(message, dict) else {}
        role = str(message.get("role") or row_type)
        if role not in {"user", "assistant"} or row_type not in {"user", "assistant"}:
            continue
        text = visible_text(message.get("content"))
        if not text:
            continue
        messages.append({"role": role, "text": text, "timestamp": str(row.get("timestamp") or "")})
    return messages, truncated


def visible_claude_transcript(path: str | Path) -> list[dict[str, str]]:
    return visible_claude_transcript_with_status(path)[0]


def _claude_reference_texts(path: Path) -> list[str]:
    values: list[str] = []
    retained = 0
    try:
        handle = path.open("r", encoding="utf-8", errors="replace")
    except OSError:
        return values
    with handle:
        for line in handle:
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("isMeta") is True or row.get("type") not in {"user", "assistant"}:
                continue
            message = row.get("message")
            if not isinstance(message, dict):
                continue
            text = visible_text(message.get("content"))
            if not text or not re.search(r"https?://|\b[A-Z][A-Z0-9]{1,15}-\d+\b|/(?:Users|Volumes|tmp|private)/", text):
                continue
            remaining = MAX_REFERENCE_TEXT - retained
            if remaining <= 0:
                break
            values.append(text[:remaining])
            retained += min(len(text), remaining)
    return values


def _transcript_title(path: Path) -> tuple[str, str]:
    custom_title = ""
    summary = ""
    first_user = ""
    rows, _ = _read_jsonl(path)
    for row in rows:
        row_type = str(row.get("type") or "")
        if row_type == "custom-title" and isinstance(row.get("customTitle"), str):
            custom_title = str(row["customTitle"])
        elif row_type == "summary" and isinstance(row.get("summary"), str):
            summary = str(row["summary"])
        elif not first_user and row_type == "user" and row.get("isMeta") is not True:
            message = row.get("message")
            if isinstance(message, dict):
                first_user = visible_text(message.get("content"))
    return human_title(custom_title, summary, first_user, fallback="Untitled Claude task"), first_user


def _native_pull_requests(metadata: dict[str, Any]) -> list[dict[str, Any]]:
    """Sanitize Desktop-native PR linkage without projecting provider blobs."""
    merged: dict[str, dict[str, Any]] = {}

    def add(value: dict[str, Any]) -> None:
        url = value.get("url") or value.get("prUrl")
        number = value.get("number") or value.get("prNumber")
        repo = value.get("repo") or value.get("prRepository")
        status = value.get("status") or value.get("state") or value.get("prState")
        if not isinstance(url, str) or not url.startswith("https://github.com/"):
            return
        item: dict[str, Any] = {"url": url}
        if isinstance(number, (str, int)):
            item["number"] = number
        if isinstance(repo, str) and repo:
            item["repo"] = repo
        if isinstance(status, str) and status:
            item["status"] = status
        merged[url.lower()] = item

    raw_prs = metadata.get("prs")
    if isinstance(raw_prs, list):
        for raw in raw_prs:
            if isinstance(raw, dict):
                add(raw)
    add(metadata)
    return [merged[key] for key in sorted(merged)]


def collect_claude_conversations(
    root: str | Path,
    *,
    claude_home: str | Path | None = None,
    desktop_root: str | Path | None = None,
    now=None,
) -> list[dict[str, Any]]:
    """Join Claude Desktop's non-archived metadata to Claude Code transcripts."""
    home = Path(claude_home).expanduser() if claude_home else Path.home() / ".claude"
    desktop = Path(desktop_root).expanduser() if desktop_root else default_desktop_sessions_root()
    transcripts = _transcript_index(home)
    routes = build_project_routes(root)
    work_items = build_work_item_routes(root)
    conversations: list[dict[str, Any]] = []
    for cli_id, (metadata, metadata_path) in _metadata_records(desktop).items():
        transcript_path = transcripts.get(cli_id)
        # The Desktop metadata/CLI transcript join is the authority boundary.
        # Orphan metadata is diagnosed by absence rather than shown as a task.
        if transcript_path is None:
            continue
        transcript = visible_claude_transcript(transcript_path)
        fallback_title, first_user = _transcript_title(transcript_path)
        native_id = str(metadata.get("sessionId") or cli_id)
        title = human_title(metadata.get("title"), fallback_title, first_user, fallback="Untitled Claude task")
        cwd = str(metadata.get("cwd") or metadata.get("originCwd") or "")
        updated_at = iso_from_timestamp(
            metadata.get("lastActivityAt") or metadata.get("lastFocusedAt") or metadata.get("createdAt")
        )
        created_at = iso_from_timestamp(metadata.get("createdAt"))
        model = model_metadata("anthropic", metadata.get("model"), metadata.get("effort"))
        reference_text = _claude_reference_texts(transcript_path)
        references = extract_references(reference_text)
        pull_requests = {item["url"].lower(): item for item in references["pull_requests"]}
        for item in _native_pull_requests(metadata):
            pull_requests[item["url"].lower()] = item
        references["pull_requests"] = [pull_requests[key] for key in sorted(pull_requests)]
        route = route_conversation(
            cwd=cwd,
            routes=routes,
            work_items=work_items,
            title=title,
            visible_texts=[message["text"] for message in transcript],
            references=references,
        )
        conversations.append(
            {
                "key": f"claude:{native_id}",
                "id": native_id,
                "native_id": native_id,
                "cli_session_id": cli_id,
                "resume_id": cli_id,
                "harness": "claude",
                "provider": model["provider"],
                "model": model["model"],
                "reasoning_effort": model["reasoning_effort"],
                "model_tier": model["model_tier"],
                "title": title,
                "created_at": created_at,
                "updated_at": updated_at,
                "age": age_label(updated_at, now=now),
                "status": "active",
                "archived": False,
                "pinned": False,
                "cwd": cwd,
                **route,
                "source": str(transcript_path),
                "transcript_available": bool(transcript),
                "can_continue": True,
                "imported": True,
                "continuation_note": (
                    "Imported Claude sessions continue as a fork so the native Desktop task remains unchanged."
                ),
                "jira_keys": [item["key"] for item in references["jira"]],
                "jira_issues": [item for item in references["jira"] if item.get("url")],
                "linear_issues": references["linear"],
                "pull_requests": references["pull_requests"],
                "slack_threads": [item["url"] for item in references["slack"]],
                "assets": [
                    {"label": Path(item["path"]).name or item["path"], **item}
                    for item in references["assets"]
                ],
                "continuation": {
                    "adapter": "claude-cli-fork",
                    "session_id": cli_id,
                    "fallback_argv": ["claude", "--resume", cli_id, "--fork-session"],
                },
                # Metadata path is useful for refresh diagnostics but its raw
                # contents are never projected.
                "metadata_source": str(metadata_path),
            }
        )
    return sorted(conversations, key=lambda item: item["updated_at"], reverse=True)


def claude_transcript_for_id(
    claude_home: str | Path,
    desktop_root: str | Path,
    conversation_id: str,
) -> list[dict[str, str]]:
    """Resolve either Desktop sessionId or cliSessionId to visible transcript text."""
    home = Path(claude_home).expanduser()
    transcripts = _transcript_index(home)
    if conversation_id in transcripts:
        return visible_claude_transcript(transcripts[conversation_id])
    for cli_id, (metadata, _) in _metadata_records(Path(desktop_root).expanduser()).items():
        if conversation_id not in {cli_id, str(metadata.get("sessionId") or "")}:
            continue
        path = transcripts.get(cli_id)
        return visible_claude_transcript(path) if path else []
    return []


def claude_transcript_result_for_id(
    claude_home: str | Path,
    desktop_root: str | Path,
    conversation_id: str,
) -> tuple[list[dict[str, str]], bool]:
    home = Path(claude_home).expanduser()
    transcripts = _transcript_index(home)
    if conversation_id in transcripts:
        return visible_claude_transcript_with_status(transcripts[conversation_id])
    for cli_id, (metadata, _) in _metadata_records(Path(desktop_root).expanduser()).items():
        if conversation_id not in {cli_id, str(metadata.get("sessionId") or "")}:
            continue
        path = transcripts.get(cli_id)
        return visible_claude_transcript_with_status(path) if path else ([], False)
    return [], False
