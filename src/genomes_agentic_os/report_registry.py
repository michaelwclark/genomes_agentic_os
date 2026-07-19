"""Read-only discovery of local Agentic OS reports for operator surfaces.

The filesystem remains authoritative.  This module intentionally builds no
central registry; it presents a small, deterministic projection over report
artifacts that already exist in an installed OS root.
"""

from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any, Iterable

import yaml

from .lifecycle import redact_text


MAX_REPORT_BYTES = 64 * 1024
REPORT_EXTENSIONS = {".json", ".md", ".txt", ".yaml", ".yml"}
REPORT_STEMS = {
    "daily-report",
    "details",
    "diagnostic",
    "diagnostics",
    "findings",
    "health",
    "holdout_qa_results",
    "receipt",
    "report",
    "results",
    "run-log",
    "status",
    "summary",
}
PRUNED_DIRS = {
    ".cache",
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    ".venv",
    "__pycache__",
    "cache",
    "caches",
    "dist",
    "build",
    "node_modules",
    "site-packages",
    "src",
    "source",
    "sources",
    "venv",
    "worktrees",
}
RAW_SUFFIXES = {".log", ".jsonl", ".out", ".sqlite", ".sqlite3", ".db"}
NON_REPORT_STEMS = {
    "agents",
    "automation",
    "config",
    "context",
    "documentation",
    "items",
    "memory",
    "plan",
    "prompt",
    "readme",
    "router",
    "rules",
    "runbook",
    "spec",
    "tools",
    "worklog",
}
SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")
STATUS_RE = re.compile(r"^\s*(?:status|state|result|outcome)\s*:\s*(.+?)\s*$", re.IGNORECASE | re.MULTILINE)


def _utc_iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _now(value: datetime | None) -> datetime:
    return value or datetime.now(timezone.utc)


def _safe_relative(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _is_report_candidate(path: Path) -> bool:
    if path.suffix.lower() not in REPORT_EXTENSIONS or path.suffix.lower() in RAW_SUFFIXES:
        return False
    lower_parts = tuple(part.lower() for part in path.parts)
    if any(part in PRUNED_DIRS for part in lower_parts):
        return False
    stem = path.stem.lower()
    if stem in NON_REPORT_STEMS:
        return False
    in_report_dir = any(part in {"report", "reports", "morning-reports", "observation-reports"} for part in lower_parts)
    named_report = stem in REPORT_STEMS or "report" in stem or stem.endswith("-summary") or stem.endswith("_summary")
    work_item_result = "work-items" in lower_parts and stem in {"summary", "holdout_qa_results"}
    run_receipt = "runs" in lower_parts and stem in {"run-log", "summary", "receipt", "status"}
    return in_report_dir or named_report or work_item_result or run_receipt


def _walk_files(start: Path, *, max_dirs: int, max_candidates: int) -> Iterable[Path]:
    if not start.is_dir() or start.is_symlink():
        return
    visited_dirs = 0
    candidates = 0
    for dirpath, dirnames, filenames in os.walk(start, followlinks=False):
        visited_dirs += 1
        if visited_dirs > max_dirs or candidates >= max_candidates:
            return
        dirnames[:] = sorted(
            (name for name in dirnames if name.lower() not in PRUNED_DIRS and not (Path(dirpath) / name).is_symlink()),
            reverse=True,
        )
        for filename in sorted(filenames, reverse=True):
            path = Path(dirpath) / filename
            if not path.is_symlink() and _is_report_candidate(path):
                yield path
                candidates += 1
                if candidates >= max_candidates:
                    return


def _discovery_roots(root: Path) -> list[Path]:
    """Return bounded, known report-bearing surfaces without following sources."""
    starts: set[Path] = set()
    try:
        root_children = sorted(root.iterdir(), key=lambda item: item.name)
    except OSError:
        return []

    for child in root_children:
        if not child.is_dir() or child.is_symlink() or child.name.lower() in PRUNED_DIRS:
            continue
        projects = child / "02-projects"
        if projects.is_dir() and not projects.is_symlink():
            starts.add(projects)

    domains_root = root / "domains"
    if domains_root.is_dir() and not domains_root.is_symlink():
        for domain_root in sorted(domains_root.iterdir(), key=lambda item: item.name):
            projects = domain_root / "02-projects"
            if domain_root.is_dir() and not domain_root.is_symlink() and projects.is_dir() and not projects.is_symlink():
                starts.add(projects)

    shared = root / "harness" / "shared_factory"
    for relative in (
        "02-projects",
        "03-workflows",
        "04-automations",
        "06-runs-and-logs/runs",
        "06-runs-and-logs/reports",
        "06-runs-and-logs/self-improvement/reports",
        "06-runs-and-logs/self-improvement/morning-reports",
        "06-runs-and-logs/adaptive-routing/observation-reports",
    ):
        starts.add(shared / relative)
    starts.add(root / "watchers")
    return sorted((path for path in starts if path.is_dir() and not path.is_symlink()), key=lambda item: item.as_posix())


def _read_bounded(path: Path) -> str:
    try:
        with path.open("rb") as handle:
            return handle.read(MAX_REPORT_BYTES).decode("utf-8", errors="replace")
    except OSError:
        return ""


def _frontmatter(text: str) -> tuple[dict[str, Any], str]:
    if not text.startswith("---"):
        return {}, text
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text
    try:
        end = lines[1:].index("---") + 1
    except ValueError:
        return {}, text
    try:
        parsed = yaml.safe_load("\n".join(lines[1:end])) or {}
    except yaml.YAMLError:
        parsed = {}
    return (parsed if isinstance(parsed, dict) else {}), "\n".join(lines[end + 1 :])


def _structured_payload(path: Path, text: str) -> dict[str, Any]:
    try:
        if path.suffix.lower() == ".json":
            value = json.loads(text)
        elif path.suffix.lower() in {".yml", ".yaml"}:
            value = yaml.safe_load(text)
        else:
            return {}
    except (json.JSONDecodeError, yaml.YAMLError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _compact(value: Any, limit: int = 480) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        value = json.dumps(value, sort_keys=True, default=str)
    return " ".join(redact_text(str(value)).split())[:limit].rstrip()


def _paragraphs(text: str) -> list[str]:
    paragraphs: list[str] = []
    in_fence = False
    current: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence or line.startswith("#") or line.startswith("|") or re.match(r"^[-*+]\s+", line):
            if current:
                paragraphs.append(_compact(" ".join(current)))
                current = []
            continue
        if not line:
            if current:
                paragraphs.append(_compact(" ".join(current)))
                current = []
            continue
        if STATUS_RE.match(line):
            continue
        current.append(line)
    if current:
        paragraphs.append(_compact(" ".join(current)))
    return [item for item in paragraphs if item]


def _first_sentence(value: str, limit: int = 240) -> str:
    compact = _compact(value, limit=limit * 2)
    if not compact:
        return ""
    sentence = SENTENCE_RE.split(compact, maxsplit=1)[0]
    if len(sentence) > limit:
        sentence = sentence[: limit - 1].rstrip() + "…"
    elif sentence[-1:] not in ".!?":
        sentence += "."
    return sentence


def _heading(text: str) -> str:
    for line in text.splitlines():
        match = re.match(r"^#\s+(.+?)\s*$", line)
        if match:
            return _compact(match.group(1), 180)
    return ""


def _metadata_value(metadata: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = metadata.get(key)
        if value not in (None, "", [], {}):
            return value
    return None


def _normalized_status(value: Any, text: str) -> str:
    raw = _compact(value, 80)
    if not raw:
        match = STATUS_RE.search(text[:8192])
        raw = _compact(match.group(1), 80) if match else "unknown"
    normalized = re.sub(r"[^a-z0-9]+", "_", raw.lower()).strip("_")
    aliases = {
        "complete": "completed",
        "done": "completed",
        "finished": "completed",
        "ok": "success",
        "pass": "success",
        "passed": "success",
    }
    return aliases.get(normalized, normalized or "unknown")


def _normalized_severity(value: Any, status: str) -> str:
    raw = re.sub(r"[^a-z0-9]+", "_", _compact(value, 40).lower()).strip("_")
    aliases = {"warn": "warning", "medium": "warning", "high": "error", "critical": "critical", "low": "info"}
    if raw:
        return aliases.get(raw, raw)
    if status in {"blocked", "error", "failed", "failure"}:
        return "error"
    if status in {"degraded", "partial", "pending", "warning"}:
        return "warning"
    return "info"


def _timestamp(value: Any, path: Path, fallback: datetime) -> str:
    if isinstance(value, datetime):
        return _utc_iso(value)
    if isinstance(value, date):
        return _utc_iso(datetime(value.year, value.month, value.day, tzinfo=timezone.utc))
    if value:
        raw = str(value).strip()
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            return _utc_iso(parsed)
        except ValueError:
            try:
                parsed_date = date.fromisoformat(raw[:10])
                return _utc_iso(datetime(parsed_date.year, parsed_date.month, parsed_date.day, tzinfo=timezone.utc))
            except ValueError:
                pass
    try:
        return _utc_iso(datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc))
    except OSError:
        return _utc_iso(fallback)


def _scope(path: Path, root: Path) -> tuple[str, str, str, str]:
    relative = Path(_safe_relative(path, root))
    parts = relative.parts
    lower = tuple(part.lower() for part in parts)
    domain = "system"
    project = ""
    if "02-projects" in lower:
        index = lower.index("02-projects")
        domain = parts[index - 1] if index else "system"
        if index + 1 < len(parts):
            project = parts[index + 1]
    elif "watchers" in lower:
        index = lower.index("watchers")
        project = parts[index + 1] if index + 1 < len(parts) else "watchers"
        domain = "watchers"

    if "work-items" in lower:
        return "work_item", "work-item-report", domain, project
    if "watchers" in lower:
        return "watcher", "watcher-report", domain, project
    if "self-improvement" in lower:
        return "system", "self-improvement-report", domain, project
    if "observation-reports" in lower or ("adaptive-routing" in lower and "reports" in lower):
        return "system", "adaptive-routing-report", domain, project
    if "runs" in lower:
        return "run", "run-report", domain, project
    if "03-workflows" in lower:
        return "workflow", "workflow-report", domain, project
    if project:
        return "project", "project-report", domain, project
    return "system", "system-report", domain, project


def _report_row(path: Path, root: Path, fallback_now: datetime) -> dict[str, Any] | None:
    text = _read_bounded(path)
    if not text:
        return None
    frontmatter, body = _frontmatter(text)
    structured = _structured_payload(path, text)
    metadata = {**structured, **frontmatter}
    paragraphs = _paragraphs(body if path.suffix.lower() in {".md", ".txt"} else "")

    title = _compact(_metadata_value(metadata, "title", "name", "report_title", "display_name"), 180) or _heading(body)
    identifier = _compact(_metadata_value(metadata, "report_id", "run_id", "id"), 100)
    kind = _compact(_metadata_value(metadata, "kind", "report_type"), 80)
    if not title:
        if identifier and kind:
            title = f"{kind.replace('_', ' ').title()} — {identifier}"
        elif identifier:
            title = identifier
        else:
            title = path.stem.replace("_", " ").replace("-", " ").title()
    status = _normalized_status(_metadata_value(metadata, "status", "state", "result", "outcome"), text)
    detail = _compact(_metadata_value(metadata, "detail", "description", "message"))
    if not detail and paragraphs:
        detail = paragraphs[0]
    if not detail and kind:
        detail = f"{kind.replace('_', ' ').title()} finished with status {status}."
    summary_value = _metadata_value(metadata, "summary", "one_line_summary", "overview")
    if isinstance(summary_value, dict):
        summary_value = _metadata_value(summary_value, "text", "summary", "result", "status")
    summary = _first_sentence(_compact(summary_value) or detail or title)
    if not detail:
        detail = summary

    severity = _normalized_severity(_metadata_value(metadata, "severity", "level", "priority"), status)
    generated_at = _timestamp(
        _metadata_value(metadata, "generated_at", "generated", "updated_at", "updated", "completed_at", "date"),
        path,
        fallback_now,
    )
    scope, report_type, domain, project = _scope(path, root)
    source = _safe_relative(path, root)
    stable_id = "report-" + hashlib.sha256(source.encode("utf-8")).hexdigest()[:16]
    return {
        "id": stable_id,
        "title": title,
        "summary": summary,
        "detail": detail[:480],
        "status": status,
        "severity": severity,
        "type": report_type,
        "scope": scope,
        "domain": domain,
        "project": project,
        "generated_at": generated_at,
        "updated_at": generated_at,
        "source": source,
    }


def collect_reports(root: str | Path, *, now: datetime | None = None, max_files: int = 500) -> list[dict[str, Any]]:
    """Collect a bounded, deterministic read-only projection of local reports."""
    os_root = Path(root).expanduser().resolve()
    if max_files <= 0 or not os_root.is_dir():
        return []
    candidates: set[Path] = set()
    traversal_limit = max(250, max_files * 4)
    for start in _discovery_roots(os_root):
        candidates.update(_walk_files(start, max_dirs=traversal_limit, max_candidates=traversal_limit))

    def freshness(path: Path) -> tuple[float, str]:
        try:
            modified = path.stat().st_mtime
        except OSError:
            modified = 0.0
        return (-modified, _safe_relative(path, os_root))

    rows: list[dict[str, Any]] = []
    fallback_now = _now(now)
    for path in sorted(candidates, key=freshness)[:max_files]:
        row = _report_row(path, os_root, fallback_now)
        if row is not None:
            rows.append(row)
    rows.sort(key=lambda row: (row["generated_at"], row["source"]), reverse=True)
    return rows


def report_summary(reports: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Return deterministic cockpit counts for a report collection."""
    rows = list(reports)

    def counts(key: str, *, skip_empty: bool = False) -> dict[str, int]:
        values = []
        for row in rows:
            value = str(row.get(key) or "")
            if value or not skip_empty:
                values.append(value or "unknown")
        return dict(sorted(Counter(values).items()))

    return {
        "total": len(rows),
        "by_status": counts("status"),
        "by_severity": counts("severity"),
        "by_type": counts("type"),
        "by_scope": counts("scope"),
        "by_domain": counts("domain"),
        "by_project": counts("project", skip_empty=True),
    }
