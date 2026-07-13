"""Deterministic, local-only source intelligence for an installed Agentic OS.

The module deliberately observes existing OS metadata without mutating source
registries.  It never invokes a provider, shell command, network client, or
secret-bearing configuration surface.  Returned evidence is limited to
root-relative file and line references; source text is never retained.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
from typing import Any, Iterable, Mapping

import yaml


WATCH_SOURCES = Path("harness/shared_factory/00-control-plane/watch-sources.yml")
MAX_SCAN_FILES = 500
MAX_FILE_BYTES = 2_000_000
MAX_EVIDENCE_REFS = 25
MAX_REASON_GROUPS = 25
MAX_SUGGESTIONS = 100

SIGNAL_WEIGHTS = {
    "slack_ingest_activity": 8.0,
    "conversation_reference": 4.0,
    "report_reference": 3.0,
    "work_item_reference": 2.0,
}

RECENCY_BUCKETS = (
    (1, 1.0),
    (7, 0.75),
    (30, 0.5),
    (90, 0.25),
    (None, 0.1),
)

GITHUB_URL_RE = re.compile(
    r"https?://github\.com/(?P<owner>[A-Za-z0-9_.-]+)/(?P<repo>[A-Za-z0-9_.-]+?)"
    r"(?:\.git)?(?:/pull/(?P<pr>\d+))?(?=[/?#\s\"'<>)]|$)",
    re.IGNORECASE,
)
GITHUB_SHORTHAND_RE = re.compile(
    r"(?<![A-Za-z0-9_.-])(?P<owner>[A-Za-z0-9_.-]+)/"
    r"(?P<repo>[A-Za-z0-9_.-]+)#(?P<pr>\d+)(?!\d)"
)
JIRA_RE = re.compile(r"(?<![A-Z0-9])(?P<key>[A-Z][A-Z0-9]{1,11})-(?P<number>\d{1,9})(?![A-Z0-9])")
SLACK_ARCHIVE_RE = re.compile(r"https?://[^/\s]+\.slack\.com/archives/(?P<channel>[CGD][A-Z0-9]{7,15})", re.IGNORECASE)
SLACK_CHANNEL_ID_RE = re.compile(r"(?<![A-Z0-9])(?P<channel>[CGD][A-Z0-9]{7,15})(?![A-Z0-9])")
SLACK_CHANNEL_NAME_RE = re.compile(r"(?<![A-Za-z0-9])#(?P<channel>[a-z0-9][a-z0-9_-]{1,79})", re.IGNORECASE)
JIRA_PROJECT_RE = re.compile(r"\bproject\s*=\s*[\"']?(?P<project>[A-Z][A-Z0-9]{1,11})", re.IGNORECASE)

SAFE_EXTERNAL_REF_FIELDS = {
    "channel_id",
    "channel_name",
    "event_types",
    "jql",
    "owner",
    "project_key",
    "repo",
    "team_id",
}


def _as_utc(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc).replace(microsecond=0)
    if not isinstance(value, datetime):
        raise TypeError("now must be a datetime or None")
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).replace(microsecond=0)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_time(value: object, fallback: datetime) -> datetime:
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value), timezone.utc)
        except (OverflowError, OSError, ValueError):
            return fallback
    if isinstance(value, str):
        stripped = value.strip()
        try:
            if re.fullmatch(r"\d{9,12}(?:\.\d+)?", stripped):
                return datetime.fromtimestamp(float(stripped), timezone.utc)
            parsed = datetime.fromisoformat(stripped.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except (OverflowError, OSError, ValueError):
            pass
    return fallback


def _file_time(path: Path, fallback: datetime) -> datetime:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
    except OSError:
        return fallback


def _recency_multiplier(observed_at: datetime, now: datetime) -> float:
    age_days = max(0.0, (now - observed_at).total_seconds() / 86_400)
    for maximum_days, multiplier in RECENCY_BUCKETS:
        if maximum_days is None or age_days <= maximum_days:
            return multiplier
    return 0.1


def _slug(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    return normalized[:80] or "source"


def _safe_external_ref(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    safe: dict[str, Any] = {}
    for key in sorted(SAFE_EXTERNAL_REF_FIELDS):
        item = value.get(key)
        if isinstance(item, (str, int, float, bool)):
            safe[key] = item
        elif isinstance(item, list) and all(isinstance(entry, (str, int, float, bool)) for entry in item):
            safe[key] = list(item)
    return safe


def _jira_project(external_ref: Mapping[str, Any]) -> str | None:
    explicit = external_ref.get("project_key")
    if isinstance(explicit, str) and explicit.strip():
        return explicit.strip().upper()
    jql = external_ref.get("jql")
    if isinstance(jql, str):
        match = JIRA_PROJECT_RE.search(jql)
        if match:
            return match.group("project").upper()
    return None


def _source_keys(source_type: str, external_ref: Mapping[str, Any]) -> set[str]:
    if source_type == "github_repo":
        owner, repo = external_ref.get("owner"), external_ref.get("repo")
        if isinstance(owner, str) and isinstance(repo, str) and owner and repo:
            return {f"github:{owner.lower()}/{repo.lower()}"}
    if source_type in {"jira_jql", "jira_project"}:
        project = _jira_project(external_ref)
        if project:
            return {f"jira:{project}"}
    if source_type == "slack_channel":
        keys: set[str] = set()
        channel_id, channel_name = external_ref.get("channel_id"), external_ref.get("channel_name")
        if isinstance(channel_id, str) and channel_id:
            keys.add(f"slack:id:{channel_id.upper()}")
        if isinstance(channel_name, str) and channel_name:
            keys.add(f"slack:name:{channel_name.lower().lstrip('#')}")
        return keys
    return set()


def _configured_sources(root: Path, diagnostics: dict[str, Any]) -> tuple[list[dict[str, Any]], set[str]]:
    path = root / WATCH_SOURCES
    if not path.is_file():
        diagnostics["notices"].append({"path": str(WATCH_SOURCES), "reason": "watch source registry missing"})
        return [], set()
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        diagnostics["malformed_files"].append({"path": str(WATCH_SOURCES), "reason": type(exc).__name__})
        return [], set()
    rows = data.get("watch_sources") if isinstance(data, Mapping) else None
    if not isinstance(rows, list):
        diagnostics["malformed_files"].append({"path": str(WATCH_SOURCES), "reason": "watch_sources must be a list"})
        return [], set()

    configured: list[dict[str, Any]] = []
    known_keys: set[str] = set()
    seen_primary: set[str] = set()
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            diagnostics["ignored_records"] += 1
            continue
        source_type = str(row.get("source_type") or "")
        external_ref = _safe_external_ref(row.get("external_ref") or row.get("external_refs"))
        keys = _source_keys(source_type, external_ref)
        primary = sorted(keys)[0] if keys else f"configured:{row.get('id') or index}"
        if primary in seen_primary:
            diagnostics["configured_duplicates"] += 1
            known_keys.update(keys)
            continue
        seen_primary.add(primary)
        known_keys.update(keys)
        configured.append(
            {
                "id": str(row.get("id") or f"configured_{index}"),
                "display_name": str(row.get("display_name") or row.get("id") or "Configured source"),
                "connected_system": str(row.get("connected_system") or ""),
                "source_type": source_type,
                "external_ref": external_ref,
                "watch_method": str(row.get("watch_method") or "poll"),
                "cadence": str(row.get("cadence") or "manual"),
                "enabled": bool(row.get("enabled", False)),
            }
        )
    configured.sort(key=lambda item: (item["source_type"], item["id"]))
    return configured, known_keys


def _relative_ref(root: Path, path: Path, line_number: int | None = None) -> str:
    relative = path.relative_to(root).as_posix()
    return f"{relative}#L{line_number}" if line_number else relative


def _candidate_files(root: Path) -> list[tuple[int, str, Path]]:
    candidates: dict[Path, tuple[int, str, Path]] = {}

    def add(path: Path, priority: int, category: str) -> None:
        try:
            resolved = path.resolve()
            resolved.relative_to(root.resolve())
        except (OSError, ValueError):
            return
        if path.is_file() and not path.is_symlink():
            current = candidates.get(path)
            if current is None or priority < current[0]:
                candidates[path] = (priority, category, path)

    slack_data = root / "watchers/slack_ingest/data"
    if slack_data.is_dir():
        for path in slack_data.glob("*.jsonl"):
            add(path, 0, "slack_ingest")

    conversation_roots = (
        root / "harness/shared_factory/06-runs-and-logs/conversations",
        root / "watchers/06-runs-and-logs/conversations",
    )
    for directory in conversation_roots:
        if directory.is_dir():
            for path in directory.rglob("*.jsonl"):
                add(path, 1, "conversation")

    # JSONL reports are receipts; markdown reports are intentionally excluded
    # because they can contain copied message bodies.
    for directory in (root / "harness/shared_factory/06-runs-and-logs", root / "watchers"):
        if directory.is_dir():
            for path in directory.rglob("*.jsonl"):
                if "report" in {part.lower() for part in path.parts} or "reports" in {part.lower() for part in path.parts}:
                    add(path, 2, "report")

    # Avoid an unbounded root.rglob: installed roots can contain linked repos,
    # worktrees, archives, and large runtime log trees.  Work items have a
    # stable directory name, so walk only the shallow OS hierarchy and prune
    # non-authoritative/generated surfaces deterministically.
    skipped_trees = {
        ".git",
        ".venv",
        ".features",
        "08-archive",
        "archive",
        "artifacts",
        "build",
        "dist",
        "logs",
        "node_modules",
        "runs",
        "worktrees",
    }
    visited_directories = 0
    for directory, directory_names, file_names in os.walk(root, followlinks=False):
        visited_directories += 1
        current = Path(directory)
        try:
            relative_parts = current.relative_to(root).parts
        except ValueError:
            directory_names[:] = []
            continue
        directory_names[:] = sorted(
            name
            for name in directory_names
            if name not in skipped_trees and not (current / name).is_symlink()
        )
        if len(relative_parts) > 9 or visited_directories >= 5_000:
            directory_names[:] = []
        if "work-items" not in {part.lower() for part in relative_parts}:
            continue
        for file_name in sorted(file_names):
            if file_name.endswith(".md"):
                add(current / file_name, 3, "work_item")

    def sort_key(item: tuple[int, str, Path]) -> tuple[int, float, str]:
        priority, _, path = item
        try:
            mtime = path.stat().st_mtime
        except OSError:
            mtime = 0.0
        return priority, -mtime, path.relative_to(root).as_posix()

    return sorted(candidates.values(), key=sort_key)


def _text_signals(text: str, slack_names: Mapping[str, str]) -> list[tuple[str, str, dict[str, Any], str]]:
    signals: dict[str, tuple[str, str, dict[str, Any], str]] = {}
    for pattern in (GITHUB_URL_RE, GITHUB_SHORTHAND_RE):
        for match in pattern.finditer(text):
            owner = match.group("owner").lower()
            repo = match.group("repo").lower().removesuffix(".git")
            key = f"github:{owner}/{repo}"
            signals[key] = (key, "github_repo", {"owner": owner, "repo": repo}, "github")
    for match in JIRA_RE.finditer(text):
        project = match.group("key").upper()
        key = f"jira:{project}"
        signals[key] = (key, "jira_jql", {"project_key": project}, "jira")
    for pattern in (SLACK_ARCHIVE_RE, SLACK_CHANNEL_ID_RE):
        for match in pattern.finditer(text):
            channel_id = match.group("channel").upper()
            key = f"slack:id:{channel_id}"
            signals[key] = (key, "slack_channel", {"channel_id": channel_id}, "slack")
    for match in SLACK_CHANNEL_NAME_RE.finditer(text):
        name = match.group("channel").lower()
        channel_id = slack_names.get(name)
        external_ref = {"channel_name": name}
        if channel_id:
            external_ref["channel_id"] = channel_id
        key = f"slack:id:{channel_id}" if channel_id else f"slack:name:{name}"
        signals[key] = (key, "slack_channel", external_ref, "slack")
    return [signals[key] for key in sorted(signals)]


def _read_json_lines(
    root: Path, path: Path, diagnostics: dict[str, Any]
) -> Iterable[tuple[int, dict[str, Any], str]]:
    evidence_path = _relative_ref(root, path)
    try:
        if path.stat().st_size > MAX_FILE_BYTES:
            diagnostics["skipped_files"].append({"path": evidence_path, "reason": "file exceeds size limit"})
            return []
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        diagnostics["skipped_files"].append({"path": evidence_path, "reason": type(exc).__name__})
        return []
    rows: list[tuple[int, dict[str, Any], str]] = []
    for line_number, line in enumerate(lines, start=1):
        try:
            value = json.loads(line)
        except (json.JSONDecodeError, TypeError):
            diagnostics["malformed_records"] += 1
            continue
        if isinstance(value, dict):
            rows.append((line_number, value, line))
        else:
            diagnostics["ignored_records"] += 1
    return rows


def _suggestion(observation: Mapping[str, Any]) -> dict[str, Any]:
    source_type = str(observation["source_type"])
    external_ref = dict(observation["external_ref"])
    source_key = str(observation["source_key"])
    connected_system = {
        "github_repo": "github_genome",
        "jira_jql": "jira_genome",
        "slack_channel": "slack_genome",
    }[source_type]
    if source_type == "github_repo":
        name = f"GitHub {external_ref['owner']}/{external_ref['repo']}"
        external_ref["event_types"] = ["pull_request"]
        dedupe = "{source_type}:{owner}:{repo}:{event_type}:{event_id}"
    elif source_type == "jira_jql":
        project = str(external_ref["project_key"])
        name = f"Jira {project} activity"
        external_ref["jql"] = f'project = "{project}" ORDER BY updated DESC'
        dedupe = "{source_type}:{project_key}:{issue_key}:{updated}"
    else:
        label = external_ref.get("channel_name") or external_ref.get("channel_id") or "channel"
        name = f"Slack {label} activity"
        dedupe = "{source_type}:{channel_id}:{event_id}"
    return {
        "id": f"observed_{_slug(source_key)}",
        "display_name": name,
        "connected_system": connected_system,
        "source_type": source_type,
        "external_ref": external_ref,
        "watch_method": "poll",
        "cadence": "daily",
        "enabled": False,
        "cursor": {"type": "timestamp", "state_ref": "harness/shared_factory/00-control-plane/watch-cursors.yml"},
        "dedupe": {"idempotency_key": dedupe},
        "filters": {},
        "trigger_rules": [],
        "route": {
            "command": "agentic-os route",
            "context_command": "agentic-os context build",
            "fallback_domain": "shared_factory",
        },
        "outputs": {
            "source_events_dir": "harness/shared_factory/06-runs-and-logs/source-events/",
            "run_queue_ref": "harness/shared_factory/00-control-plane/run-queue.yml",
        },
        "observation": {
            "score": observation["score"],
            "signal_count": observation["signal_count"],
            "last_observed_at": observation["last_observed_at"],
            "reasons": observation["reasons"],
            "reason_group_count": observation.get("reason_group_count", len(observation["reasons"])),
            "reasons_truncated": observation.get("reasons_truncated", False),
            "evidence_refs": observation["evidence_refs"],
            "evidence_count": observation.get("evidence_count", len(observation["evidence_refs"])),
            "evidence_truncated": observation.get("evidence_truncated", False),
            "requires_resolution": source_type == "slack_channel" and "channel_id" not in external_ref,
        },
    }


def build_source_observation_snapshot(
    root: str | Path,
    *,
    now: datetime | None = None,
    max_files: int = MAX_SCAN_FILES,
) -> dict[str, Any]:
    """Build a privacy-safe source activity snapshot from local OS receipts.

    ``max_files`` is clamped to 500.  The function performs no writes and does
    not inspect environment variables, credential files, databases, or provider
    APIs.  Malformed and missing inputs are summarized under ``diagnostics``.
    """

    os_root = Path(root).expanduser()
    current_time = _as_utc(now)
    try:
        requested_limit = int(max_files)
    except (TypeError, ValueError) as exc:
        raise TypeError("max_files must be an integer") from exc
    file_limit = max(0, min(requested_limit, MAX_SCAN_FILES))
    diagnostics: dict[str, Any] = {
        "file_limit": file_limit,
        "limit_clamped": requested_limit != file_limit,
        "files_discovered": 0,
        "files_scanned": 0,
        "truncated": False,
        "configured_duplicates": 0,
        "malformed_records": 0,
        "ignored_records": 0,
        "malformed_files": [],
        "skipped_files": [],
        "notices": [],
    }
    if not os_root.is_dir():
        diagnostics["notices"].append({"path": ".", "reason": "OS root missing"})
        return {
            "schema_version": 1,
            "generated_at": _iso(current_time),
            "configured": [],
            "observed": [],
            "suggestions": [],
            "diagnostics": diagnostics,
        }

    configured, configured_keys = _configured_sources(os_root, diagnostics)
    candidates = _candidate_files(os_root)
    diagnostics["files_discovered"] = len(candidates)
    diagnostics["truncated"] = len(candidates) > file_limit
    selected = candidates[:file_limit]

    observations: dict[str, dict[str, Any]] = {}
    slack_names: dict[str, str] = {}

    def add_signal(
        source_key: str,
        source_type: str,
        external_ref: Mapping[str, Any],
        entity: str,
        signal: str,
        observed_at: datetime,
        evidence_ref: str,
        occurrences: int = 1,
    ) -> None:
        multiplier = _recency_multiplier(observed_at, current_time)
        contribution = SIGNAL_WEIGHTS[signal] * multiplier
        item = observations.setdefault(
            source_key,
            {
                "source_key": source_key,
                "source_type": source_type,
                "external_ref": dict(external_ref),
                "score": 0.0,
                "signal_count": 0,
                "last_observed_at": _iso(observed_at),
                "reasons": [],
                "evidence_refs": [],
            },
        )
        item["external_ref"].update({key: value for key, value in external_ref.items() if value})
        item["score"] += contribution
        item["signal_count"] += 1
        if _parse_time(item["last_observed_at"], observed_at) < observed_at:
            item["last_observed_at"] = _iso(observed_at)
        item["reasons"].append(
            {
                "signal": signal,
                "entity": entity,
                "weight": SIGNAL_WEIGHTS[signal],
                "recency_multiplier": multiplier,
                "contribution": round(contribution, 3),
                "occurrences": occurrences,
            }
        )
        if evidence_ref not in item["evidence_refs"]:
            item["evidence_refs"].append(evidence_ref)

    for _, category, path in selected:
        diagnostics["files_scanned"] += 1
        fallback_time = _file_time(path, current_time)
        if category == "work_item":
            try:
                if path.stat().st_size > MAX_FILE_BYTES:
                    diagnostics["skipped_files"].append({"path": _relative_ref(os_root, path), "reason": "file exceeds size limit"})
                    continue
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeError) as exc:
                diagnostics["skipped_files"].append({"path": _relative_ref(os_root, path), "reason": type(exc).__name__})
                continue
            for source_key, source_type, external_ref, entity in _text_signals(text, slack_names):
                add_signal(source_key, source_type, external_ref, entity, "work_item_reference", fallback_time, _relative_ref(os_root, path))
            continue

        rows = _read_json_lines(os_root, path, diagnostics)
        if category == "slack_ingest":
            grouped: dict[str, dict[str, Any]] = {}
            for line_number, row, _ in rows:
                channel_id = row.get("channel")
                channel_name = row.get("channel_name")
                if not isinstance(channel_id, str) or not channel_id:
                    diagnostics["ignored_records"] += 1
                    continue
                channel_id = channel_id.upper()
                external_ref: dict[str, Any] = {"channel_id": channel_id}
                if isinstance(channel_name, str) and channel_name:
                    normalized_name = channel_name.lower().lstrip("#")
                    external_ref["channel_name"] = normalized_name
                    slack_names[normalized_name] = channel_id
                key = f"slack:id:{channel_id}"
                item = grouped.setdefault(key, {"external_ref": external_ref, "time": fallback_time, "line": line_number, "count": 0})
                item["count"] += 1
                observed_at = _parse_time(row.get("ingest_at") or row.get("ts"), fallback_time)
                if observed_at > item["time"]:
                    item["time"] = observed_at
                    item["line"] = line_number
                item["external_ref"].update(external_ref)
            for source_key in sorted(grouped):
                item = grouped[source_key]
                add_signal(
                    source_key,
                    "slack_channel",
                    item["external_ref"],
                    "slack",
                    "slack_ingest_activity",
                    item["time"],
                    _relative_ref(os_root, path, item["line"]),
                    item["count"],
                )
            continue

        signal = "conversation_reference" if category == "conversation" else "report_reference"
        per_file: dict[str, tuple[str, dict[str, Any], str, int, datetime]] = {}
        for line_number, row, raw_line in rows:
            observed_at = _parse_time(
                row.get("timestamp") or row.get("observed_at") or row.get("created_at") or row.get("updated_at"),
                fallback_time,
            )
            for source_key, source_type, external_ref, entity in _text_signals(raw_line, slack_names):
                existing = per_file.get(source_key)
                if existing is None or observed_at > existing[4]:
                    per_file[source_key] = (source_type, external_ref, entity, line_number, observed_at)
        for source_key in sorted(per_file):
            source_type, external_ref, entity, line_number, observed_at = per_file[source_key]
            add_signal(source_key, source_type, external_ref, entity, signal, observed_at, _relative_ref(os_root, path, line_number))

    # Merge name-only Slack references into the corresponding observed channel
    # ID when Slack ingest supplied the mapping later in the bounded scan.
    for name, channel_id in sorted(slack_names.items()):
        name_key, id_key = f"slack:name:{name}", f"slack:id:{channel_id}"
        if name_key not in observations or name_key == id_key:
            continue
        source = observations.pop(name_key)
        target = observations.get(id_key)
        source["source_key"] = id_key
        source["external_ref"]["channel_id"] = channel_id
        if target is None:
            observations[id_key] = source
            continue
        target["score"] += source["score"]
        target["signal_count"] += source["signal_count"]
        target["reasons"].extend(source["reasons"])
        target["evidence_refs"] = sorted(set(target["evidence_refs"] + source["evidence_refs"]))
        if source["last_observed_at"] > target["last_observed_at"]:
            target["last_observed_at"] = source["last_observed_at"]

    observed = list(observations.values())
    for item in observed:
        item["score"] = round(float(item["score"]), 3)
        grouped_reasons: dict[tuple[str, str, float, float], dict[str, Any]] = {}
        for reason in item["reasons"]:
            key = (
                str(reason["signal"]),
                str(reason["entity"]),
                float(reason["weight"]),
                float(reason["recency_multiplier"]),
            )
            grouped = grouped_reasons.setdefault(
                key,
                {
                    "signal": reason["signal"],
                    "entity": reason["entity"],
                    "weight": reason["weight"],
                    "recency_multiplier": reason["recency_multiplier"],
                    "contribution": 0.0,
                    "occurrences": 0,
                },
            )
            grouped["contribution"] += float(reason["contribution"])
            grouped["occurrences"] += int(reason["occurrences"])
        reasons = list(grouped_reasons.values())
        for reason in reasons:
            reason["contribution"] = round(float(reason["contribution"]), 3)
        reasons.sort(key=lambda reason: (-reason["contribution"], reason["signal"], reason["entity"]))
        item["reason_group_count"] = len(reasons)
        item["reasons_truncated"] = len(reasons) > MAX_REASON_GROUPS
        item["reasons"] = reasons[:MAX_REASON_GROUPS]

        evidence_refs = sorted(set(item["evidence_refs"]))
        item["evidence_count"] = len(evidence_refs)
        item["evidence_truncated"] = len(evidence_refs) > MAX_EVIDENCE_REFS
        item["evidence_refs"] = evidence_refs[:MAX_EVIDENCE_REFS]
        item["configured"] = bool(_source_keys(item["source_type"], item["external_ref"]) & configured_keys)
    observed.sort(key=lambda item: (-item["score"], item["source_key"]))
    suggestion_candidates = [item for item in observed if not item["configured"]]
    suggestions = [_suggestion(item) for item in suggestion_candidates[:MAX_SUGGESTIONS]]

    diagnostics["skipped_files"] = sorted(
        diagnostics["skipped_files"], key=lambda item: (item["path"], item["reason"])
    )[:50]
    diagnostics["malformed_files"] = sorted(
        diagnostics["malformed_files"], key=lambda item: (item["path"], item["reason"])
    )[:50]
    diagnostics["signal_weights"] = dict(SIGNAL_WEIGHTS)
    diagnostics["recency_buckets_days"] = [
        {"maximum_days": maximum, "multiplier": multiplier} for maximum, multiplier in RECENCY_BUCKETS
    ]
    diagnostics["suggestion_threshold"] = "at least one normalized, non-configured signal"
    diagnostics["suggestion_candidates"] = len(suggestion_candidates)
    diagnostics["suggestion_limit"] = MAX_SUGGESTIONS
    diagnostics["suggestions_truncated"] = len(suggestion_candidates) > MAX_SUGGESTIONS

    return {
        "schema_version": 1,
        "generated_at": _iso(current_time),
        "configured": configured,
        "observed": observed,
        "suggestions": suggestions,
        "diagnostics": diagnostics,
    }
