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
MAX_ROUTING_TEXT_BYTES = 400_000


def emit() -> None:
    # An empty JSON object is accepted by both Claude and Codex Stop-hook
    # transports; harness-specific output envelopes are not cross-compatible.
    print(json.dumps({}))


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


def conversation_artifact_stem(root: Path, value: str) -> str:
    enabled = True
    date_format = "%m%d%y"
    separator = "-"
    try:
        import yaml

        config_path = root / "harness" / "config" / "artifact-naming.yml"
        data = yaml.safe_load(config_path.read_text(encoding="utf-8")) if config_path.is_file() else {}
        date_prefix = (data or {}).get("artifact_naming", {}).get("date_prefix", {})
        enabled = bool(date_prefix.get("enabled", True))
        date_format = str(date_prefix.get("format", date_format))
        separator = str(date_prefix.get("separator", separator))
        enabled = enabled and bool((date_prefix.get("scopes") or {}).get("conversation_logs", True))
    except Exception:
        # Stop hooks are best-effort; malformed config is reported by
        # `agentic-os validate` and must not block transcript capture.
        pass
    unprefixed = value
    sample_length = len(datetime(2026, 7, 18, tzinfo=timezone.utc).strftime(date_format))
    if len(unprefixed) > sample_length and unprefixed[sample_length : sample_length + len(separator)] == separator:
        try:
            datetime.strptime(unprefixed[:sample_length], date_format)
            unprefixed = unprefixed[sample_length + len(separator) :]
        except ValueError:
            pass
    slug = slugify(unprefixed)
    if not enabled:
        return slug
    return f"{datetime.now(timezone.utc).strftime(date_format)}{separator}{slug}"


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


def tail_text(path: Path, max_bytes: int = MAX_ROUTING_TEXT_BYTES) -> str:
    if not path.is_file():
        return ""
    try:
        size = path.stat().st_size
        with path.open("rb") as handle:
            if size > max_bytes:
                handle.seek(size - max_bytes)
            return handle.read(max_bytes).decode("utf-8", errors="replace")
    except OSError:
        return ""


def work_item_metadata_path(work_item: Path) -> Path | None:
    if work_item.is_file():
        return work_item
    metadata = work_item / "work.yml"
    return metadata if metadata.is_file() else None


def iter_work_items(root: Path) -> list[Path]:
    projects = [
        (root / "domains").glob("*/projects/*"),
        (root / "domains").glob("*/02-projects/*"),
        root.glob("*/projects/*"),
        root.glob("*/02-projects/*"),
        (root / "harness" / "shared_factory" / "02-projects").glob("*"),
    ]
    seen: set[Path] = set()
    items: list[Path] = []
    for project_glob in projects:
        for project_dir in project_glob:
            work_items = project_dir / "work-items"
            if not work_items.is_dir():
                continue
            candidates = []
            candidates.extend(work_items.glob("*/work.yml"))
            candidates.extend(work_items.glob("*.md"))
            for lane in WORK_ITEM_LANES:
                candidates.extend((work_items / lane).glob("*/work.yml"))
                candidates.extend((work_items / lane).glob("*.md"))
            for metadata in candidates:
                item = metadata if metadata.suffix == ".md" else metadata.parent
                try:
                    resolved = item.resolve()
                except OSError:
                    continue
                if resolved in seen:
                    continue
                seen.add(resolved)
                items.append(item)
    return items


def work_item_aliases(root: Path, work_item: Path) -> set[str]:
    aliases = {work_item.name}
    try:
        resolved = work_item.resolve()
        aliases.add(str(resolved))
        aliases.add(str(resolved.relative_to(root.resolve())))
    except (OSError, ValueError):
        pass
    if work_item.is_file():
        aliases.add(work_item.stem)

    metadata = work_item_metadata_path(work_item)
    if metadata:
        for key in ("id", "title"):
            value = yaml_scalar(metadata, key)
            if value:
                aliases.add(value)
                aliases.add(slugify(value))
                aliases.add(slugify(value).replace("_", "-"))
    return {alias for alias in aliases if len(alias) >= 8}


def explicit_work_item(root: Path, payload: dict[str, Any]) -> Path | None:
    explicit_values = [
        os.environ.get("AGENTIC_OS_ACTIVE_WORK_ITEM", ""),
        os.environ.get("AOS_ACTIVE_WORK_ITEM", ""),
    ]
    explicit_values.extend(
        payload_value(
            payload,
            "active_work_item",
            "activeWorkItem",
            "work_item",
            "workItem",
            "work_item_path",
            "workItemPath",
        ).splitlines()
    )
    for value in explicit_values:
        if not value:
            continue
        candidate = Path(value).expanduser()
        if not candidate.is_absolute():
            candidate = root / candidate
        if candidate.exists():
            return candidate.resolve()
    return None


def discussed_work_item(root: Path, payload: dict[str, Any], transcript: Path | None) -> Path | None:
    explicit = explicit_work_item(root, payload)
    if explicit:
        return explicit

    text_parts = [json.dumps(payload, sort_keys=True)]
    if transcript:
        text_parts.append(tail_text(transcript))
    routing_text = "\n".join(text_parts).lower()
    if not routing_text.strip():
        return None

    scored: list[tuple[int, str, Path]] = []
    for item in iter_work_items(root):
        score = 0
        for alias in work_item_aliases(root, item):
            normalized = alias.lower()
            if normalized in routing_text:
                score += 5 if "/" in normalized or "\\" in normalized else 2
        if score:
            scored.append((score, str(item), item))

    if not scored:
        return None
    scored.sort(reverse=True)
    if len(scored) == 1 or scored[0][0] > scored[1][0]:
        return scored[0][2]
    return None


def linked_project_for_cwd(root: Path, cwd: Path) -> Path | None:
    project_globs = [
        (root / "domains").glob("*/projects/*"),
        (root / "domains").glob("*/02-projects/*"),
        root.glob("*/projects/*"),
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


def route_log_dir(
    root: Path,
    cwd: Path,
    payload: dict[str, Any],
    transcript: Path | None = None,
) -> tuple[Path, str]:
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
            discussed = discussed_work_item(root, payload, transcript)
            if discussed:
                return work_item_log_destination(discussed)
            return project / "logs" / "conversations", parts[3]
        return shared / "06-runs-and-logs" / "conversations", "shared_factory"
    if parts and parts[0] == "harness":
        return root / "harness" / "logs" / "conversations", "harness"
    domain_base = root
    if len(parts) >= 2 and parts[0] == "domains":
        domain_base = root / "domains"
        parts = parts[1:]
    if (
        len(parts) >= 6
        and parts[1] in {"02-projects", "projects"}
        and parts[3] == "work-items"
        and parts[4] in WORK_ITEM_LANES
    ):
        lane_item = domain_base / parts[0] / parts[1] / parts[2] / "work-items" / parts[4] / parts[5]
        return work_item_log_destination(lane_item)
    if len(parts) >= 5 and parts[1] in {"02-projects", "projects"} and parts[3] == "work-items":
        work_item = domain_base / parts[0] / parts[1] / parts[2] / "work-items" / parts[4]
        return work_item_log_destination(work_item)
    discussed = discussed_work_item(root, payload, transcript)
    if discussed:
        return work_item_log_destination(discussed)
    if len(parts) >= 3 and parts[1] in {"02-projects", "projects"}:
        project = domain_base / parts[0] / parts[1] / parts[2]
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
        transcript_value = payload_value(payload, "transcript_path", "transcriptPath")
        transcript = Path(transcript_value).expanduser() if transcript_value else None
        log_dir, slug = route_log_dir(root, cwd, payload, transcript)
        log_dir.mkdir(parents=True, exist_ok=True)

        date_slug = conversation_artifact_stem(root, slug)
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
