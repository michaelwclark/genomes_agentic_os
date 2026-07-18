#!/usr/bin/env python3
"""Best-effort conversation and tool-call logger for Agentic OS hooks."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sys
from typing import Any


TOKEN_RE = re.compile(
    r"(?i)("
    r"sk-[a-z0-9_-]{20,}|"
    r"gh[pousr]_[a-z0-9_]{20,}|"
    r"xox[baprs]-[a-z0-9-]{20,}|"
    r"bearer\s+[a-z0-9._~+/=-]{20,}|"
    r"(api[_-]?key|token|secret)\s*[:=]\s*[a-z0-9._~+/=-]{16,}"
    r")"
)

TOOL_KEYS = {
    "tool_use",
    "tool_result",
    "tool_call",
    "function_call",
    "mcp",
    "command",
    "spawn_agent",
    "followup_task",
}

WORK_ITEM_LANES = {"01-intake", "02-active", "03-complete"}


def emit() -> None:
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "Stop", "additionalContext": ""}}))


def log_line(message: str) -> None:
    log_dir = Path.home() / ".local" / "state" / "harness"
    log_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with (log_dir / "conversation-auto-log.log").open("a", encoding="utf-8") as handle:
        handle.write(f"{timestamp} {message}\n")


def redacted(text: str) -> str:
    return TOKEN_RE.sub("[REDACTED]", text)


def read_payload() -> dict[str, Any]:
    raw = sys.stdin.read()
    if not raw.strip():
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {"_raw": raw}
    return data if isinstance(data, dict) else {}


def payload_value(payload: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = payload.get(key)
        if value:
            return str(value)
    return ""


def agentic_root(cwd: Path) -> Path:
    configured = os.environ.get("AGENTIC_OS_ROOT") or os.environ.get("AOS_ROOT")
    if configured:
        return Path(configured).expanduser().resolve()
    for candidate in (cwd, *cwd.parents):
        if (candidate / ".agentic_root").is_file():
            return candidate.resolve()
    return (Path.home() / "agentic_os").resolve()


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    return slug or "conversation"


def yaml_scalar(path: Path, key: str) -> str:
    if not path.is_file():
        return ""
    pattern = re.compile(rf"^\s*{re.escape(key)}:\s*(.*?)\s*$")
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        match = pattern.match(line)
        if match:
            return match.group(1).strip().strip("'\"")
    return ""


def cwd_within(cwd: Path, candidate: Path) -> bool:
    try:
        cwd.resolve().relative_to(candidate.expanduser().resolve())
        return True
    except (OSError, ValueError):
        return False


def active_work_item(project_dir: Path) -> Path | None:
    active_states = {"captured", "triaged", "specified", "ready", "building", "validating", "blocked"}
    matches: list[Path] = []
    work_items = project_dir / "work-items"
    candidates = []
    if work_items.is_dir():
        candidates.extend(sorted(work_items.glob("*/work.yml")))
        candidates.extend(sorted(work_items.glob("*.md")))
        for lane in WORK_ITEM_LANES:
            candidates.extend(sorted((work_items / lane).glob("*/work.yml")))
            candidates.extend(sorted((work_items / lane).glob("*.md")))
    for metadata in candidates:
        status = yaml_scalar(metadata, "status") or yaml_scalar(metadata, "state")
        if status in active_states:
            matches.append(metadata if metadata.suffix == ".md" else metadata.parent)
    return matches[0] if len(matches) == 1 else None


def work_item_log_destination(work_item: Path) -> tuple[Path, str]:
    if work_item.is_file():
        return work_item.parent / f"{work_item.stem}.logs" / "conversations", work_item.stem
    return work_item / "logs" / "conversations", work_item.name


def linked_project_for_cwd(root: Path, cwd: Path) -> Path | None:
    project_globs = [
        (root / "domains").glob("*/02-projects/*"),
        root.glob("*/02-projects/*"),
        (root / "harness" / "shared_factory" / "02-projects").glob("*"),
    ]
    for projects in project_globs:
        for project_dir in projects:
            if not project_dir.is_dir():
                continue
            linked_paths = []
            src = project_dir / "src"
            if src.exists():
                linked_paths.append(src)
            repo = yaml_scalar(project_dir / "project.yml", "repo")
            if repo and "://" not in repo and not repo.startswith("git@"):
                linked_paths.append(Path(repo).expanduser())
            index = project_dir / "worktrees" / "index.yml"
            if index.is_file():
                for line in index.read_text(encoding="utf-8", errors="replace").splitlines():
                    if line.strip().startswith("path:"):
                        linked_paths.append(Path(line.split(":", 1)[1].strip().strip("'\"")).expanduser())
            if any(cwd_within(cwd, linked) for linked in linked_paths):
                return project_dir
    return None


def route_log_dir(root: Path, cwd: Path, payload: dict[str, Any]) -> tuple[Path, str]:
    try:
        relative = cwd.resolve().relative_to(root.resolve())
    except ValueError:
        relative = Path()

    parts = relative.parts
    if len(parts) >= 2 and parts[0] == "harness" and parts[1] == "shared_factory":
        shared = root / "harness" / "shared_factory"
        if len(parts) >= 5 and parts[2] == "02-projects":
            project = shared / "02-projects" / parts[3]
            if len(parts) >= 7 and parts[4] == "work-items" and parts[5] in WORK_ITEM_LANES:
                lane_item = project / "work-items" / parts[5] / parts[6]
                return work_item_log_destination(lane_item)
            if len(parts) >= 6 and parts[4] == "work-items":
                work_item = project / "work-items" / parts[5]
                return work_item_log_destination(work_item)
            return project / "logs" / "conversations", parts[3]
        return shared / "06-runs-and-logs" / "conversations", "shared_factory"
    if parts and parts[0] == "harness":
        return root / "harness" / "logs" / "conversations", "harness"
    domain_base = root
    if len(parts) >= 2 and parts[0] == "domains":
        domain_base = root / "domains"
        parts = parts[1:]
    if len(parts) >= 6 and parts[1] == "02-projects" and parts[3] == "work-items" and parts[4] in WORK_ITEM_LANES:
        lane_item = domain_base / parts[0] / "02-projects" / parts[2] / "work-items" / parts[4] / parts[5]
        return work_item_log_destination(lane_item)
    if len(parts) >= 5 and parts[1] == "02-projects" and parts[3] == "work-items":
        work_item = domain_base / parts[0] / "02-projects" / parts[2] / "work-items" / parts[4]
        return work_item_log_destination(work_item)
    if len(parts) >= 3 and parts[1] == "02-projects":
        project = domain_base / parts[0] / "02-projects" / parts[2]
        return project / "logs" / "conversations", parts[2]
    if parts:
        return domain_base / parts[0] / "06-runs-and-logs" / "conversations", parts[0]

    linked_project = linked_project_for_cwd(root, cwd)
    if linked_project:
        work_item = active_work_item(linked_project)
        if work_item:
            return work_item_log_destination(work_item)
        return linked_project / "logs" / "conversations", linked_project.name

    session = payload_value(payload, "session_id", "sessionId") or "conversation"
    return root / "harness" / "logs" / "conversations", slugify(session)


def iter_jsonl(path: Path) -> list[Any]:
    items: list[Any] = []
    if not path.is_file():
        return items
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            items.append(json.loads(line))
        except json.JSONDecodeError:
            items.append({"raw": line})
    return items


def contains_tool_marker(value: Any) -> bool:
    if isinstance(value, dict):
        keys = {str(key) for key in value}
        if keys & TOOL_KEYS:
            return True
        return any(contains_tool_marker(item) for item in value.values())
    if isinstance(value, list):
        return any(contains_tool_marker(item) for item in value)
    if isinstance(value, str):
        text = value.lower()
        return any(marker in text for marker in ("tool_use", "tool_call", "function_call", "exec_command", "spawn_agent"))
    return False


def extract_tool_items(transcript: Path) -> list[Any]:
    return [item for item in iter_jsonl(transcript) if contains_tool_marker(item)]


def write_jsonl(path: Path, items: list[Any]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for item in items:
            handle.write(redacted(json.dumps(item, sort_keys=True)) + "\n")


def write_tool_markdown(path: Path, items: list[Any], transcript: Path | None) -> None:
    lines = [
        "# Tool Calls",
        "",
        f"- Transcript: `{transcript}`" if transcript else "- Transcript: none",
        f"- Extracted items: {len(items)}",
        "- Redaction: token-shaped values replaced with `[REDACTED]`",
        "",
        "| # | Summary |",
        "| --- | --- |",
    ]
    for index, item in enumerate(items, start=1):
        summary = redacted(json.dumps(item, sort_keys=True))
        if len(summary) > 180:
            summary = summary[:177] + "..."
        lines.append(f"| {index} | `{summary}` |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    try:
        payload = read_payload()
        cwd_value = payload_value(payload, "cwd") or os.getcwd()
        cwd = Path(cwd_value).expanduser().resolve()
        root = agentic_root(cwd)
        log_dir, slug = route_log_dir(root, cwd, payload)
        log_dir.mkdir(parents=True, exist_ok=True)

        date_slug = datetime.now(timezone.utc).strftime("%Y_%m_%d") + f"_{slugify(slug)}"
        transcript_value = payload_value(payload, "transcript_path", "transcriptPath")
        transcript = Path(transcript_value).expanduser() if transcript_value else None
        raw_target = log_dir / f"{date_slug}.jsonl"
        tool_jsonl = log_dir / f"{date_slug}_tool_calls.jsonl"
        tool_md = log_dir / f"{date_slug}_tool_calls.md"

        tool_items: list[Any] = []
        if transcript and transcript.is_file():
            redacted_content = redacted(transcript.read_text(encoding="utf-8", errors="replace"))
            raw_target.write_text(redacted_content, encoding="utf-8")
            tool_items = extract_tool_items(transcript)
        else:
            raw_target.write_text(redacted(json.dumps({"payload": payload}, sort_keys=True)) + "\n", encoding="utf-8")

        write_jsonl(tool_jsonl, tool_items)
        write_tool_markdown(tool_md, tool_items, transcript)
        log_line(f"status=ok cwd={cwd} target={log_dir} transcript={transcript or ''}")
    except Exception as exc:  # noqa: BLE001 - hook must never block completion.
        log_line(f"status=error error={type(exc).__name__}: {exc}")
    emit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
