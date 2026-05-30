"""Best-effort conversation transcript sidecar logging."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
from typing import Any

from .lifecycle import (
    TOKEN_SHAPED_VALUE_RE,
    contains_token_shaped_value,
    project_work_item_records,
    redact_text,
    select_project_work_item,
    slugify_work_id,
)
from .routing import detect_from_cwd, project_records, read_yaml
from .scaffold import domain_path, expand_path


def utc_date_slug() -> str:
    return datetime.now(timezone.utc).strftime("%Y_%m_%d")


def find_os_root(cwd: Path) -> Path | None:
    env_root = os.environ.get("AGENTIC_OS_ROOT")
    if env_root:
        root = expand_path(env_root)
        if (root / ".agentic_root").is_file():
            return root
    for candidate in [cwd, *cwd.parents]:
        if (candidate / ".agentic_root").is_file():
            return candidate.resolve()
    default = Path("~/agentic_os").expanduser()
    if (default / ".agentic_root").is_file():
        return default.resolve()
    return None


def redact_json(value: Any) -> Any:
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, list):
        return [redact_json(item) for item in value]
    if isinstance(value, dict):
        return {str(key): redact_json(item) for key, item in value.items()}
    return value


def parse_jsonl(path: Path) -> list[Any]:
    rows: list[Any] = []
    if not path.is_file():
        return rows
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            rows.append({"type": "raw_line", "text": line})
    return rows


def looks_like_tool_call(value: dict[str, Any]) -> bool:
    type_value = str(value.get("type") or value.get("event") or "").lower()
    if "tool" in type_value or type_value in {"function_call", "mcp_call"}:
        return True
    if any(key in value for key in ("tool_call", "tool_calls", "toolName", "recipient_name")):
        return True
    if "cmd" in value and any(key in value for key in ("status", "output", "yield_time_ms")):
        return True
    if "name" in value and any(key in value for key in ("arguments", "input", "parameters")):
        name = str(value.get("name") or "")
        return bool(name and name not in {"user", "assistant", "system"})
    return False


def collect_tool_calls(value: Any, *, found: list[dict[str, Any]]) -> None:
    if isinstance(value, dict):
        if looks_like_tool_call(value):
            found.append(redact_json(value))
        for item in value.values():
            collect_tool_calls(item, found=found)
    elif isinstance(value, list):
        for item in value:
            collect_tool_calls(item, found=found)


def write_jsonl(path: Path, rows: list[Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8")


def write_tool_call_markdown(path: Path, *, source: Path | None, tool_calls: list[dict[str, Any]], redacted: bool) -> None:
    lines = [
        f"# Tool Calls: {utc_date_slug()}",
        "",
        "| Field | Value |",
        "| --- | --- |",
        f"| Source Transcript | `{source or 'none'}` |",
        f"| Tool Calls | {len(tool_calls)} |",
        f"| Redaction Applied | `{str(redacted).lower()}` |",
        "",
        "## Calls",
        "",
    ]
    if not tool_calls:
        lines.append("- No tool calls found in the available transcript payload.")
    for index, call in enumerate(tool_calls, start=1):
        name = call.get("name") or call.get("toolName") or call.get("recipient_name") or call.get("type") or "tool_call"
        lines.append(f"{index}. `{name}`")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def project_root_for_context(root: Path, context: dict[str, str]) -> Path | None:
    domain = context.get("domain")
    project = context.get("project")
    if not domain or not project:
        return None
    candidate = domain_path(root, domain) / "02-projects" / project
    return candidate if candidate.is_dir() else None


def destination_for_payload(root: Path, cwd: Path, transcript_path: Path | None, payload: dict[str, Any]) -> tuple[Path, str]:
    context = detect_from_cwd(root, cwd)
    project_root = project_root_for_context(root, context)
    if project_root:
        try:
            work_item = select_project_work_item(project_root, cwd=cwd)
        except ValueError:
            work_item = None
        if work_item:
            return work_item.conversation_logs_path, work_item.path.name
        active_items = [record for record in project_work_item_records(project_root) if record.status != "archived"]
        if len(active_items) == 1:
            return active_items[0].conversation_logs_path, active_items[0].path.name
        return project_root / "logs" / "conversations", project_root.name

    domain = context.get("domain")
    if domain:
        domain_root = domain_path(root, domain)
        return domain_root / "06-runs-and-logs" / "conversations", domain

    records = project_records(root)
    for record in records:
        project_root = Path(record["path"])
        for candidate in [Path(str(record.get("repo") or "")).expanduser(), *[Path(str(item.get("path") or "")).expanduser() for item in record.get("worktrees", [])]]:
            if not str(candidate):
                continue
            try:
                cwd.relative_to(candidate.resolve())
            except (ValueError, OSError):
                continue
            return project_root / "logs" / "conversations", project_root.name

    fallback_slug = slugify_work_id(str(payload.get("session_id") or payload.get("sessionId") or "conversation"))
    return root / "harness" / "logs" / "conversations", fallback_slug


def conversation_log_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    cwd = Path(str(payload.get("cwd") or os.getcwd())).expanduser().resolve()
    root = find_os_root(cwd)
    if root is None:
        return {"ok": False, "error": "could not resolve Agentic OS root"}

    transcript_value = str(payload.get("transcript_path") or payload.get("transcriptPath") or "")
    transcript_path = Path(transcript_value).expanduser() if transcript_value else None
    if transcript_path and not transcript_path.is_absolute():
        transcript_path = (cwd / transcript_path).resolve()

    destination, slug_source = destination_for_payload(root, cwd, transcript_path, payload)
    slug = slugify_work_id(slug_source)
    base = f"{utc_date_slug()}_{slug}"
    raw_path = destination / f"{base}.jsonl"
    tool_jsonl_path = destination / f"{base}_tool_calls.jsonl"
    tool_md_path = destination / f"{base}_tool_calls.md"

    rows = parse_jsonl(transcript_path) if transcript_path else []
    redacted_rows = [redact_json(row) for row in rows]
    raw_text = "\n".join(json.dumps(row, sort_keys=True) for row in rows)
    redacted = raw_text != "\n".join(json.dumps(row, sort_keys=True) for row in redacted_rows)
    if transcript_path and rows:
        write_jsonl(raw_path, redacted_rows)

    tool_calls: list[dict[str, Any]] = []
    for row in rows:
        collect_tool_calls(row, found=tool_calls)
    write_jsonl(tool_jsonl_path, tool_calls)
    write_tool_call_markdown(tool_md_path, source=transcript_path, tool_calls=tool_calls, redacted=redacted)

    return {
        "ok": True,
        "root": str(root),
        "destination": str(destination),
        "raw_transcript": str(raw_path) if transcript_path and rows else "",
        "tool_calls_jsonl": str(tool_jsonl_path),
        "tool_calls_markdown": str(tool_md_path),
        "tool_call_count": len(tool_calls),
        "redacted": redacted,
    }


def main(argv: list[str] | None = None) -> int:
    _ = argv or sys.argv[1:]
    try:
        payload = json.loads(sys.stdin.read() or "{}")
        if not isinstance(payload, dict):
            payload = {}
        result = conversation_log_from_payload(payload)
    except Exception as exc:  # pragma: no cover - hook must never block callers
        result = {"ok": False, "error": str(exc)}
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
