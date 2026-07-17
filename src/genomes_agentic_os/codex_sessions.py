"""Read-only Codex Desktop conversation adapter."""

from __future__ import annotations

import json
from pathlib import Path
import re
import sqlite3
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


UUID_RE = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.IGNORECASE)
MAX_TRANSCRIPT_BYTES = 4_000_000
MAX_REFERENCE_TEXT = 2_000_000


def _safe_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}


def _desktop_state(codex_home: Path) -> tuple[set[str], set[str], dict[str, str], dict[str, list[str]]]:
    """Return thread UUID references, pin state, and Desktop display titles."""
    state = _safe_json(codex_home / ".codex-global-state.json")
    if not state:
        return set(), set(), {}, {}
    pinned = {
        str(value)
        for value in state.get("pinned-thread-ids", [])
        if isinstance(value, str) and UUID_RE.fullmatch(value)
    }
    projectless = {
        str(value)
        for value in state.get("projectless-thread-ids", [])
        if isinstance(value, str) and UUID_RE.fullmatch(value)
    }
    assignments = state.get("thread-project-assignments")
    assignment_ids = {
        str(key)
        for key in assignments
        if isinstance(key, str) and UUID_RE.fullmatch(key)
    } if isinstance(assignments, dict) else set()
    # These are the compact, current Desktop navigation references. Historical
    # descriptions/client IDs are title caches, not evidence that a task is open.
    ui_refs = pinned | projectless | assignment_ids
    atom_state = state.get("electron-persisted-atom-state")
    atom_state = atom_state if isinstance(atom_state, dict) else {}
    raw_descriptions = atom_state.get("thread-descriptions-v1")
    raw_descriptions = raw_descriptions if isinstance(raw_descriptions, dict) else {}
    descriptions = {
        str(key): value
        for key, value in raw_descriptions.items()
        if isinstance(value, str) and UUID_RE.fullmatch(str(key))
    }
    hints: dict[str, list[str]] = {}
    workspace_hints = state.get("thread-workspace-root-hints")
    if isinstance(workspace_hints, dict):
        for thread_id, value in workspace_hints.items():
            if isinstance(value, str):
                hints.setdefault(str(thread_id), []).append(value)
    if isinstance(assignments, dict):
        for thread_id, value in assignments.items():
            if not isinstance(value, dict):
                continue
            for key in ("cwd", "path", "projectId"):
                candidate = value.get(key)
                if isinstance(candidate, str) and candidate.startswith("/"):
                    hints.setdefault(str(thread_id), []).append(candidate)
    return ui_refs, pinned, descriptions, hints


def _session_names(codex_home: Path) -> dict[str, str]:
    """Read the newest human thread name per UUID from the append-only index."""
    path = codex_home / "session_index.jsonl"
    names: dict[str, tuple[str, str]] = {}
    try:
        handle = path.open("r", encoding="utf-8")
    except OSError:
        return {}
    with handle:
        for line in handle:
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(row, dict):
                continue
            session_id = str(row.get("id") or "")
            title = row.get("thread_name")
            updated = str(row.get("updated_at") or "")
            if not session_id or not isinstance(title, str):
                continue
            current = names.get(session_id)
            if current is None or updated >= current[0]:
                names[session_id] = (updated, title)
    return {key: value[1] for key, value in names.items()}


def _thread_rows(codex_home: Path) -> list[dict[str, Any]]:
    database = codex_home / "state_5.sqlite"
    if not database.is_file():
        return []
    uri = f"file:{database}?mode=ro"
    try:
        connection = sqlite3.connect(uri, uri=True, timeout=2)
    except sqlite3.Error:
        return []
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA query_only=ON")
        connection.execute("PRAGMA busy_timeout=2000")
        rows = connection.execute(
            """
            SELECT id, rollout_path, created_at, updated_at, created_at_ms,
                   updated_at_ms, recency_at_ms, source, thread_source,
                   model_provider, model, reasoning_effort, cwd, title,
                   first_user_message, preview, archived
            FROM threads
            WHERE archived = 0 AND thread_source = 'user'
            """
        ).fetchall()
    except sqlite3.Error:
        return []
    finally:
        connection.close()
    return [dict(row) for row in rows]


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


def visible_codex_transcript_with_status(path: str | Path) -> tuple[list[dict[str, str]], bool]:
    """Return only canonical user/assistant text from one Codex rollout."""
    messages: list[dict[str, str]] = []
    rows, truncated = _read_jsonl(Path(path))
    for row in rows:
        if row.get("type") != "response_item":
            continue
        payload = row.get("payload")
        if not isinstance(payload, dict) or payload.get("type") != "message":
            continue
        role = str(payload.get("role") or "")
        if role not in {"user", "assistant"}:
            continue
        text = visible_text(payload.get("content"))
        if not text:
            continue
        messages.append({"role": role, "text": text, "timestamp": str(row.get("timestamp") or "")})
    if messages:
        return messages, truncated

    # Older rollouts may have only event messages. This fallback is used only
    # when canonical response items are absent, preventing duplicate rendering.
    for row in rows:
        if row.get("type") != "event_msg":
            continue
        payload = row.get("payload")
        if not isinstance(payload, dict):
            continue
        event_type = payload.get("type")
        role = "user" if event_type == "user_message" else "assistant" if event_type == "agent_message" else ""
        if not role:
            continue
        text = visible_text(payload.get("message") or payload.get("text"))
        if text:
            messages.append({"role": role, "text": text, "timestamp": str(row.get("timestamp") or "")})
    return messages, truncated


def visible_codex_transcript(path: str | Path) -> list[dict[str, str]]:
    return visible_codex_transcript_with_status(path)[0]


def _codex_reference_texts(path: Path) -> list[str]:
    """Stream every visible message for routing refs without retaining transcripts."""
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
            if row.get("type") != "response_item":
                continue
            payload = row.get("payload")
            if not isinstance(payload, dict) or payload.get("type") != "message":
                continue
            if payload.get("role") not in {"user", "assistant"}:
                continue
            text = visible_text(payload.get("content"))
            if not text or not re.search(r"https?://|\b[A-Z][A-Z0-9]{1,15}-\d+\b|/(?:Users|Volumes|tmp|private)/", text):
                continue
            remaining = MAX_REFERENCE_TEXT - retained
            if remaining <= 0:
                break
            values.append(text[:remaining])
            retained += min(len(text), remaining)
    return values


def collect_codex_conversations(
    root: str | Path,
    *,
    codex_home: str | Path | None = None,
    now=None,
) -> list[dict[str, Any]]:
    """Join Codex Desktop UI references to the read-only thread database."""
    home = Path(codex_home).expanduser() if codex_home else Path.home() / ".codex"
    ui_refs, pinned, descriptions, native_hints = _desktop_state(home)
    if not ui_refs:
        return []
    names = _session_names(home)
    routes = build_project_routes(root)
    work_items = build_work_item_routes(root)
    conversations: list[dict[str, Any]] = []
    for row in _thread_rows(home):
        native_id = str(row.get("id") or "")
        if native_id not in ui_refs:
            continue
        # `vscode` is the current Codex Desktop origin. `cli` is accepted only
        # when Desktop itself retains a UI reference for the task.
        if str(row.get("source") or "") not in {"vscode", "cli"}:
            continue
        rollout_path = Path(str(row.get("rollout_path") or ""))
        transcript = visible_codex_transcript(rollout_path) if rollout_path.is_file() else []
        transcript_text = [message["text"] for message in transcript]
        reference_text = _codex_reference_texts(rollout_path) if rollout_path.is_file() else transcript_text
        title = human_title(
            descriptions.get(native_id),
            names.get(native_id),
            row.get("preview"),
            row.get("first_user_message"),
            row.get("title"),
            fallback="Untitled Codex task",
        )
        cwd = str(row.get("cwd") or "")
        updated_at = iso_from_timestamp(
            row.get("recency_at_ms") or row.get("updated_at_ms") or row.get("updated_at")
        )
        created_at = iso_from_timestamp(row.get("created_at_ms") or row.get("created_at"))
        model = model_metadata(
            str(row.get("model_provider") or "openai"),
            row.get("model"),
            row.get("reasoning_effort"),
        )
        references = extract_references(reference_text)
        route = route_conversation(
            cwd=cwd,
            routes=routes,
            work_items=work_items,
            title=title,
            visible_texts=transcript_text,
            references=references,
            native_hints=native_hints.get(native_id, []),
        )
        conversations.append(
            {
                "key": f"codex:{native_id}",
                "id": native_id,
                "native_id": native_id,
                "resume_id": native_id,
                "harness": "codex",
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
                "pinned": native_id in pinned,
                "pin_source": "native" if native_id in pinned else "",
                "cwd": cwd,
                **route,
                "source": str(rollout_path) if rollout_path.is_file() else "",
                "transcript_available": bool(transcript),
                "can_continue": True,
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
                    "adapter": "codex-app-server",
                    "session_id": native_id,
                    "fallback_argv": ["codex", "resume", native_id, "-C", cwd, "--no-alt-screen"]
                    if cwd
                    else ["codex", "resume", native_id, "--no-alt-screen"],
                },
            }
        )
    return sorted(conversations, key=lambda item: (item["pinned"], item["updated_at"]), reverse=True)


def codex_transcript_for_id(codex_home: str | Path, conversation_id: str) -> list[dict[str, str]]:
    """Resolve one native ID through the read-only database and return visible text."""
    home = Path(codex_home).expanduser()
    for row in _thread_rows(home):
        if str(row.get("id") or "") != conversation_id:
            continue
        path = Path(str(row.get("rollout_path") or ""))
        return visible_codex_transcript(path) if path.is_file() else []
    return []


def codex_transcript_result_for_id(
    codex_home: str | Path,
    conversation_id: str,
) -> tuple[list[dict[str, str]], bool]:
    home = Path(codex_home).expanduser()
    for row in _thread_rows(home):
        if str(row.get("id") or "") != conversation_id:
            continue
        path = Path(str(row.get("rollout_path") or ""))
        return visible_codex_transcript_with_status(path) if path.is_file() else ([], False)
    return [], False
