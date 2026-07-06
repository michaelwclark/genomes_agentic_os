"""Read-only mining for Agentic OS conversation-report JSONL sidecars."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Any

from .lifecycle import redact_text
from .scaffold import expand_path


REPORT_FILENAMES = {
    "conversation-report-scan.json",
    "conversation-report-scan.md",
    "conversation-report-backlog.md",
}
SKIP_ROW_TYPES = {"session_meta", "turn_context"}
SKIP_PAYLOAD_TYPES = {
    "agent_reasoning",
    "context_compacted",
    "function_call",
    "reasoning",
    "token_count",
    "tool_search_call",
    "tool_search_output",
    "web_search_call",
    "web_search_end",
}
SKIP_TEXT_KEYS = {
    "base_instructions",
    "developer_instructions",
    "encrypted_content",
    "image",
    "image_url",
    "last_token_usage",
    "metadata",
    "rate_limits",
    "system_instructions",
    "total_token_usage",
    "workspace_roots",
}
TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9_-]{2,}", re.IGNORECASE)
ENCODED_RE = re.compile(r"^[A-Za-z0-9+/=_-]{400,}$")
CONTEXT_BLOB_PREFIXES = (
    "# AGENTS.md instructions",
    "# Prompt:",
    "## Memory",
    "<app-context>",
    "<apps_instructions>",
    "<collaboration_mode>",
    "<environment_context>",
    "<permissions instructions>",
    "<plugins_instructions>",
    "<skills_instructions>",
    "========= MEMORY_SUMMARY",
    "You are `/root`",
)
CONTEXT_BLOB_MARKERS = (
    "# Agent Router",
    "## External Tool Routing",
    "## Hard Requirements",
    "## Preference Routes",
    "## Tool Contract",
    "<INSTRUCTIONS>",
    "</INSTRUCTIONS>",
    '"substrate": "cocoindex"',
    '"substrate":"cocoindex"',
    '\\"substrate\\": \\"cocoindex\\"',
    '\\"substrate\\":\\"cocoindex\\"',
    "Filesystem sandboxing defines which files can be read or written",
    "Read `CONTEXT.md`, `RULES.md`, and `TOOLS.md`",
    "Registry-confirmed",
    "The logged-in user's email is",
)
FINDING_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("timeout", ("timed out", "timeout expired", "timeout waiting", "deadline exceeded", "command timed out")),
    ("missing_config", ("missing config", "config missing", "config.toml is missing", "missing required")),
    ("missing_registry", ("missing registry", "registry gap", "missing matching command", "missing matching skill")),
    (
        "notion_workspace",
        (
            "michael clark",
            "genome's notion",
            "verified workspace",
            "wrong workspace",
            "notion workspace",
            "refusing notion write",
        ),
    ),
    (
        "tracker_drift",
        (
            "tracker drift",
            "usage_limit_exceeded",
            "workspace drift",
            "linear project",
            "linear workspace",
            "jira auth",
            "jira project",
            "project id",
        ),
    ),
    (
        "auth_or_permission",
        (
            "http 401",
            "401 unauthorized",
            "oauth_token_invalid_grant",
            "permission denied",
            "not authorized",
            "forbidden",
            "reauthentication required",
        ),
    ),
    ("validation_failure", ("validation failed", "pytest failed", "test failed", "exit code 1", "exits 1", "not ok")),
    ("runtime_failure", ("traceback", "exception", "error:", "failed", "blocked")),
    ("confusion_signal", ("confused", "unclear", "lost", "stuck", "over and over", "manual loop", "too many")),
)
SEVERITY_BY_CLASS = {
    "timeout": "medium",
    "missing_config": "high",
    "missing_registry": "high",
    "notion_workspace": "high",
    "tracker_drift": "high",
    "auth_or_permission": "high",
    "validation_failure": "high",
    "runtime_failure": "medium",
    "confusion_signal": "medium",
}


@dataclass(frozen=True)
class WorkItemRef:
    """Small index row used to link findings to existing work packets."""

    work_item_id: str
    title: str
    relative_path: str
    tokens: frozenset[str]


def utc_stamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _safe_relative(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _tokenize(text: str) -> set[str]:
    ignored = {
        "the",
        "and",
        "for",
        "with",
        "that",
        "this",
        "from",
        "into",
        "work",
        "item",
        "agentic",
        "genomes",
        "agentic_os",
    }
    return {token.lower() for token in TOKEN_RE.findall(text) if len(token) >= 3 and token.lower() not in ignored}


def _snippet(text: str, pattern: str | None = None, *, max_chars: int = 220) -> str:
    compact = " ".join(redact_text(text).split())
    if not compact:
        return ""
    if pattern:
        index = compact.lower().find(pattern.lower())
        if index > 0:
            start = max(0, index - 70)
            compact = compact[start:]
            if start:
                compact = "..." + compact
    return compact[:max_chars].rstrip()


def _iter_jsonl_rows(path: Path) -> list[Any]:
    rows: list[Any] = []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return rows
    for line in lines:
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            rows.append({"type": "raw_line", "text": line})
    return rows


def _looks_encoded(text: str) -> bool:
    compact = "".join(text.split())
    return bool(ENCODED_RE.match(compact))


def _looks_context_blob(text: str) -> bool:
    stripped = text.lstrip()
    if any(stripped.startswith(prefix) for prefix in CONTEXT_BLOB_PREFIXES):
        return True
    head = stripped[:1200]
    return any(marker in head for marker in CONTEXT_BLOB_MARKERS)


def _append_text_if_interesting(text: str, found: list[str]) -> None:
    if text and not _looks_encoded(text) and not _looks_context_blob(text):
        found.append(text)


def _collect_text(value: Any, *, found: list[str]) -> None:
    if isinstance(value, str):
        _append_text_if_interesting(value, found)
        return
    if isinstance(value, list):
        for item in value:
            _collect_text(item, found=found)
        return
    if isinstance(value, dict):
        content_type = str(value.get("type") or "").lower()
        if content_type in {"input_image", "image"}:
            return
        for key, item in value.items():
            if str(key) in SKIP_TEXT_KEYS:
                continue
            _collect_text(item, found=found)


def _interesting_row_text(row: Any) -> str:
    """Return user/assistant/tool-output text while skipping large metadata blobs."""

    if not isinstance(row, dict):
        return str(row)
    row_type = str(row.get("type") or "").lower()
    if row_type in SKIP_ROW_TYPES:
        return ""
    payload = row.get("payload") if isinstance(row.get("payload"), dict) else row
    if not isinstance(payload, dict):
        return ""
    payload_type = str(payload.get("type") or "").lower()
    if payload_type in SKIP_PAYLOAD_TYPES:
        return ""
    texts: list[str] = []
    if row_type == "event_msg":
        message = payload.get("message")
        if isinstance(message, str):
            _append_text_if_interesting(message, texts)
    elif payload_type == "function_call_output":
        output = payload.get("output")
        if isinstance(output, str):
            _append_text_if_interesting(output, texts)
    elif payload_type == "message":
        if str(payload.get("role") or "").lower() in {"developer", "system"}:
            return ""
        _collect_text(payload.get("content"), found=texts)
    else:
        _collect_text(payload, found=texts)
    return "\n".join(texts)


def _conversation_dirs(root: Path, *, project: str | None = None) -> list[Path]:
    dirs: list[Path] = []
    dirs.append(root / "harness" / "logs" / "conversations")
    for domain_root in sorted(path for path in root.iterdir() if path.is_dir() and not path.name.startswith(".")):
        runs_dir = domain_root / "06-runs-and-logs" / "conversations"
        dirs.append(runs_dir)
        projects_root = domain_root / "02-projects"
        if not projects_root.is_dir():
            continue
        for project_root in sorted(path for path in projects_root.iterdir() if path.is_dir()):
            if project and project_root.name != project:
                continue
            dirs.append(project_root / "logs" / "conversations")
            work_items = project_root / "work-items"
            if not work_items.is_dir():
                continue
            for lane in ("01-intake", "02-active", "03-complete"):
                lane_root = work_items / lane
                if not lane_root.is_dir():
                    continue
                for item_root in sorted(path for path in lane_root.iterdir() if path.is_dir()):
                    dirs.append(item_root / "logs" / "conversations")
    return [path for path in dirs if path.is_dir()]


def find_conversation_report_files(root: str | Path, *, project: str | None = None) -> list[Path]:
    """Return known conversation JSONL sidecars without walking source worktrees."""

    os_root = expand_path(root)
    files: list[Path] = []
    seen: set[Path] = set()
    for directory in _conversation_dirs(os_root, project=project):
        for path in sorted(directory.glob("*.jsonl")):
            if path.name.endswith("_tool_calls.jsonl"):
                continue
            if path.name in REPORT_FILENAMES:
                continue
            resolved = path.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            files.append(path)
    return files


def _read_title(path: Path) -> str:
    for candidate in ("work.yml", "SPEC.md", "SUMMARY.md"):
        file_path = path / candidate
        if not file_path.is_file():
            continue
        try:
            text = file_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for line in text.splitlines()[:30]:
            stripped = line.strip()
            if stripped.startswith("# "):
                return stripped[2:].strip()
            if stripped.lower().startswith("title:"):
                return stripped.split(":", 1)[1].strip().strip('"')
            if stripped.lower().startswith("name:"):
                return stripped.split(":", 1)[1].strip().strip('"')
    return path.name.replace("_", " ")


def build_work_item_index(root: str | Path, *, project: str | None = None) -> list[WorkItemRef]:
    os_root = expand_path(root)
    refs: list[WorkItemRef] = []
    for domain_root in sorted(path for path in os_root.iterdir() if path.is_dir() and not path.name.startswith(".")):
        projects_root = domain_root / "02-projects"
        if not projects_root.is_dir():
            continue
        for project_root in sorted(path for path in projects_root.iterdir() if path.is_dir()):
            if project and project_root.name != project:
                continue
            work_items = project_root / "work-items"
            if not work_items.is_dir():
                continue
            for lane in ("01-intake", "02-active", "03-complete"):
                lane_root = work_items / lane
                if not lane_root.is_dir():
                    continue
                for item in sorted(lane_root.iterdir()):
                    if item.is_dir():
                        title = _read_title(item)
                        text = f"{item.name} {title}"
                        refs.append(
                            WorkItemRef(
                                work_item_id=item.name,
                                title=title,
                                relative_path=_safe_relative(item, os_root),
                                tokens=frozenset(_tokenize(text)),
                            )
                        )
                    elif item.suffix == ".md":
                        title = _read_title(item.parent)
                        text = f"{item.stem} {title}"
                        refs.append(
                            WorkItemRef(
                                work_item_id=item.stem,
                                title=title,
                                relative_path=_safe_relative(item, os_root),
                                tokens=frozenset(_tokenize(text)),
                            )
                        )
    return refs


def _classify(text: str) -> tuple[str, str] | None:
    lowered = text.lower()
    for class_name, patterns in FINDING_PATTERNS:
        for pattern in patterns:
            if pattern in lowered:
                return class_name, pattern
    return None


def _match_work_items(text: str, work_items: list[WorkItemRef], *, limit: int = 3) -> list[dict[str, Any]]:
    tokens = _tokenize(text)
    if not tokens:
        return []
    scored: list[tuple[float, WorkItemRef, set[str]]] = []
    for ref in work_items:
        overlap = tokens & set(ref.tokens)
        if not overlap:
            continue
        score = len(overlap) / max(4, len(ref.tokens))
        if ref.work_item_id.lower() in text.lower():
            score += 0.5
        scored.append((score, ref, overlap))
    scored.sort(key=lambda row: (row[0], len(row[2])), reverse=True)
    matches: list[dict[str, Any]] = []
    for score, ref, overlap in scored[:limit]:
        matches.append(
            {
                "work_item": ref.work_item_id,
                "title": ref.title,
                "relative_path": ref.relative_path,
                "confidence": round(min(score, 1.0), 2),
                "matched_terms": sorted(overlap)[:8],
            }
        )
    return matches


def scan_conversation_reports(
    root: str | Path,
    *,
    project: str | None = None,
    output_dir: str | Path | None = None,
    max_findings: int = 200,
    max_files: int | None = None,
) -> dict[str, Any]:
    """Scan local conversation JSONL sidecars and optionally write reports."""

    os_root = expand_path(root)
    files = find_conversation_report_files(os_root, project=project)
    if max_files is not None:
        files = files[:max_files]
    work_items = build_work_item_index(os_root, project=project)
    class_counts: Counter[str] = Counter()
    files_with_findings: set[str] = set()
    findings: list[dict[str, Any]] = []
    rows_scanned = 0

    for path in files:
        rel_path = _safe_relative(path, os_root)
        rows = _iter_jsonl_rows(path)
        rows_scanned += len(rows)
        seen_classes_for_file: set[str] = set()
        for row_index, row in enumerate(rows, start=1):
            text = _interesting_row_text(row)
            if not text:
                continue
            classified = _classify(text)
            if not classified:
                continue
            class_name, pattern = classified
            if class_name in seen_classes_for_file:
                continue
            seen_classes_for_file.add(class_name)
            class_counts[class_name] += 1
            files_with_findings.add(rel_path)
            snippet = _snippet(text, pattern)
            finding_text = f"{rel_path} {snippet}"
            findings.append(
                {
                    "id": f"F{len(findings) + 1:04d}",
                    "class": class_name,
                    "severity": SEVERITY_BY_CLASS.get(class_name, "medium"),
                    "source": rel_path,
                    "row": row_index,
                    "snippet": snippet,
                    "matches": _match_work_items(finding_text, work_items),
                }
            )
            if len(findings) >= max_findings:
                break
        if len(findings) >= max_findings:
            break

    result: dict[str, Any] = {
        "created_at": utc_stamp(),
        "root": str(os_root),
        "project": project or "",
        "summary": {
            "files_scanned": len(files),
            "rows_scanned": rows_scanned,
            "findings": len(findings),
            "files_with_findings": len(files_with_findings),
            "work_items_indexed": len(work_items),
            "classes": dict(sorted(class_counts.items())),
            "truncated": len(findings) >= max_findings,
        },
        "findings": findings,
    }
    if output_dir:
        output_root = expand_path(output_dir)
        output_root.mkdir(parents=True, exist_ok=True)
        json_path = output_root / "conversation-report-scan.json"
        markdown_path = output_root / "conversation-report-scan.md"
        backlog_path = output_root / "conversation-report-backlog.md"
        json_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        markdown_path.write_text(format_conversation_report_scan(result), encoding="utf-8")
        backlog_path.write_text(format_conversation_report_backlog(result), encoding="utf-8")
        result["artifacts"] = {
            "json": str(json_path),
            "markdown": str(markdown_path),
            "backlog": str(backlog_path),
        }
    return result


def format_conversation_report_scan(result: dict[str, Any]) -> str:
    summary = result.get("summary") or {}
    classes = summary.get("classes") or {}
    lines = [
        "# Conversation Report Scan",
        "",
        f"- Created: {result.get('created_at', '')}",
        f"- Project filter: `{result.get('project') or 'all'}`",
        f"- Files scanned: {summary.get('files_scanned', 0)}",
        f"- Rows scanned: {summary.get('rows_scanned', 0)}",
        f"- Findings: {summary.get('findings', 0)}",
        f"- Work items indexed: {summary.get('work_items_indexed', 0)}",
        "",
        "## Failure Classes",
        "",
    ]
    if classes:
        for class_name, count in classes.items():
            lines.append(f"- `{class_name}`: {count}")
    else:
        lines.append("- No repeated failure or confusion classes found.")
    lines.extend(["", "## Findings", ""])
    findings = result.get("findings") or []
    if not findings:
        lines.append("- No findings.")
    for finding in findings:
        matches = finding.get("matches") or []
        match_text = ", ".join(f"{match['work_item']} ({match['confidence']})" for match in matches) if matches else "none"
        lines.append(
            f"- `{finding['id']}` `{finding['class']}` `{finding['severity']}` "
            f"from `{finding['source']}` row {finding['row']} -> matches: {match_text}"
        )
        if finding.get("snippet"):
            lines.append(f"  - Evidence: {finding['snippet']}")
    return "\n".join(lines).rstrip() + "\n"


def format_conversation_report_receipt(result: dict[str, Any]) -> str:
    summary = result.get("summary") or {}
    classes = summary.get("classes") or {}
    artifacts = result.get("artifacts") or {}
    lines = [
        "# Conversation Report Scan Receipt",
        "",
        f"- Created: {result.get('created_at', '')}",
        f"- Project filter: `{result.get('project') or 'all'}`",
        f"- Files scanned: {summary.get('files_scanned', 0)}",
        f"- Rows scanned: {summary.get('rows_scanned', 0)}",
        f"- Findings: {summary.get('findings', 0)}",
        f"- Files with findings: {summary.get('files_with_findings', 0)}",
        f"- Work items indexed: {summary.get('work_items_indexed', 0)}",
    ]
    if summary.get("truncated"):
        lines.append("- Truncated: true")
    if classes:
        class_text = ", ".join(f"{name}={count}" for name, count in classes.items())
        lines.append(f"- Classes: {class_text}")
    if artifacts:
        lines.extend(["", "## Artifacts", ""])
        for label in ("json", "markdown", "backlog"):
            if artifacts.get(label):
                lines.append(f"- {label}: `{artifacts[label]}`")
    else:
        lines.append("- Artifacts: none; pass `--output-dir` to write JSON, Markdown, and backlog files.")
    return "\n".join(lines).rstrip() + "\n"


def format_conversation_report_backlog(result: dict[str, Any]) -> str:
    lines = [
        "# Conversation Report Backlog Candidates",
        "",
        "Generated from redacted local conversation-report JSONL sidecars.",
        "",
        "| ID | Priority | Class | Candidate | Existing Match | Source |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for finding in result.get("findings") or []:
        priority = "P0" if finding.get("severity") == "high" else "P1"
        snippet = str(finding.get("snippet") or "").replace("|", "\\|")
        candidate = snippet[:120] or "Review repeated report signal."
        matches = finding.get("matches") or []
        match_text = ", ".join(str(match["work_item"]) for match in matches[:2]) if matches else "new or unmapped"
        lines.append(
            f"| {finding['id']} | {priority} | `{finding['class']}` | {candidate} | {match_text} | `{finding['source']}` |"
        )
    if not (result.get("findings") or []):
        lines.append("| - | - | - | No candidates found. | - | - |")
    return "\n".join(lines).rstrip() + "\n"
