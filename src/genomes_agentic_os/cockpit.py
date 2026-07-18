"""Local-first engineering cockpit snapshot aggregation.

The cockpit is a read-only projection.  Collectors intentionally avoid network
calls, subprocesses, linked source repositories, and mutation of the installed
OS.  Existing guarded CLI commands remain the action surface.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Iterable
import webbrowser

import yaml

from .report_registry import collect_reports
from .runtime_backend import queue_mode_status
from .source_observation import build_source_observation_snapshot


SCHEMA_VERSION = "agentic-os-cockpit/v1"
DEFAULT_OUTPUT = Path("harness/shared_factory/06-runs-and-logs/cockpit/latest")
MAX_TEXT_BYTES = 256_000
JIRA_RE = re.compile(r"\b([A-Z][A-Z0-9]{1,15}-\d+)\b")
PR_URL_RE = re.compile(r"https://github\.com/([^/\s]+)/([^/\s]+)/pull/(\d+)", re.IGNORECASE)
PR_SHORT_RE = re.compile(r"(?<![\w/])#(\d{2,7})\b")
TERMINAL_STATES = {"finished", "documented", "archived", "dropped", "done", "complete", "completed"}
ACTIVE_LANES = {"01-intake", "02-active"}
SKIP_PARTS = {".git", ".venv", "node_modules", "__pycache__", ".pytest_cache", "worktrees"}


def _now(value: datetime | None = None) -> datetime:
    current = value or datetime.now(timezone.utc)
    return current if current.tzinfo else current.replace(tzinfo=timezone.utc)


def _iso(value: datetime | None = None) -> str:
    return _now(value).astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _stable_id(*parts: object) -> str:
    raw = "\x1f".join(str(part) for part in parts)
    return hashlib.sha256(raw.encode("utf-8", errors="replace")).hexdigest()[:16]


def _relative(path: Path, root: Path) -> str:
    try:
        return str(path.resolve(strict=False).relative_to(root.resolve(strict=False)))
    except ValueError:
        return str(path)


def _safe_text(path: Path, *, limit: int = MAX_TEXT_BYTES) -> str:
    try:
        with path.open("rb") as handle:
            return handle.read(limit).decode("utf-8", errors="replace")
    except (OSError, ValueError):
        return ""


def _safe_yaml(path: Path) -> dict[str, Any]:
    try:
        value = yaml.safe_load(_safe_text(path)) or {}
        return value if isinstance(value, dict) else {}
    except yaml.YAMLError:
        return {}


def _mtime(path: Path) -> str:
    try:
        return _iso(datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc))
    except OSError:
        return ""


def _first_sentence(text: str, *, fallback: str, limit: int = 180) -> str:
    cleaned = re.sub(r"\s+", " ", text).strip(" -#\t\n")
    if not cleaned:
        return fallback
    match = re.search(r"(?<=[.!?])\s", cleaned)
    sentence = cleaned[: match.start() + 1] if match else cleaned
    return sentence if len(sentence) <= limit else sentence[: limit - 1].rstrip() + "…"


def _first_useful_line(text: str, *, fallback: str) -> str:
    for line in text.splitlines():
        value = line.strip()
        if value and not value.startswith(("#", "---", "```", "Status:", "Created:")):
            return _first_sentence(value, fallback=fallback)
    return fallback


def _extract_refs(text: str) -> tuple[list[str], list[dict[str, str]]]:
    jira = sorted(set(JIRA_RE.findall(text)))
    prs: dict[str, dict[str, str]] = {}
    for owner, repo, number in PR_URL_RE.findall(text):
        url = f"https://github.com/{owner}/{repo}/pull/{number}"
        prs[url.lower()] = {"owner": owner, "repo": repo, "number": number, "url": url}
    return jira, [prs[key] for key in sorted(prs)]


def _project_from_path(path: Path, root: Path) -> tuple[str, str, str]:
    try:
        parts = path.resolve(strict=False).relative_to(root.resolve(strict=False)).parts
    except ValueError:
        return "", "", ""
    domain = parts[0] if parts else ""
    project = ""
    work_item = ""
    if "02-projects" in parts:
        index = parts.index("02-projects")
        if len(parts) > index + 1:
            project = parts[index + 1]
    if "work-items" in parts:
        index = parts.index("work-items")
        if len(parts) > index + 2:
            work_item = parts[index + 2]
    return domain, project, work_item


def _project_route_index(root: Path) -> list[tuple[Path, str, str]]:
    """Map installed project/link targets back to their OS domain and project."""
    routes: dict[str, tuple[Path, str, str]] = {}
    for project_root in root.glob("*/02-projects/*"):
        if not project_root.is_dir():
            continue
        try:
            relative = project_root.relative_to(root)
        except ValueError:
            continue
        domain, project = relative.parts[0], project_root.name
        candidates = [project_root, project_root / "src"]
        worktrees = project_root / "worktrees"
        if worktrees.is_dir():
            candidates.extend(worktrees.iterdir())
        for candidate in candidates:
            try:
                if not candidate.exists() and not candidate.is_symlink():
                    continue
                target = candidate.resolve(strict=False)
            except OSError:
                continue
            routes[str(target)] = (target, domain, project)
    return sorted(routes.values(), key=lambda route: len(route[0].parts), reverse=True)


def _project_for_cwd(cwd: Path, root: Path, routes: list[tuple[Path, str, str]]) -> tuple[str, str]:
    domain, project, _ = _project_from_path(cwd, root)
    if project:
        return domain, project
    try:
        resolved = cwd.resolve(strict=False)
    except OSError:
        return "", ""
    for target, route_domain, route_project in routes:
        if resolved == target or target in resolved.parents:
            return route_domain, route_project
    return "", ""


def _bounded_recent(paths: Iterable[Path], limit: int) -> list[Path]:
    unique: dict[str, Path] = {}
    for path in paths:
        if any(part in SKIP_PARTS for part in path.parts):
            continue
        unique[str(path)] = path

    def key(path: Path) -> tuple[float, str]:
        try:
            return (path.stat().st_mtime, str(path))
        except OSError:
            return (0.0, str(path))

    return sorted(unique.values(), key=key, reverse=True)[: max(0, limit)]


def _work_item_paths(root: Path) -> list[Path]:
    return sorted(root.glob("*/02-projects/*/work-items/*/*/work.yml"))


def collect_work_items(root: str | Path, *, max_items: int = 1_000) -> list[dict[str, Any]]:
    os_root = Path(root).expanduser().resolve()
    items: list[dict[str, Any]] = []
    for metadata_path in _work_item_paths(os_root)[:max_items]:
        item_root = metadata_path.parent
        metadata = _safe_yaml(metadata_path)
        domain, project, work_item = _project_from_path(item_root, os_root)
        status = str(metadata.get("status") or metadata.get("state") or "unknown")
        title = str(metadata.get("title") or work_item.replace("_", " ").title())
        summary = str(metadata.get("summary") or "")
        next_text = _safe_text(item_root / "NEXT.md", limit=32_000)
        spec_text = _safe_text(item_root / "SPEC.md", limit=96_000)
        refs_text = "\n".join((summary, next_text, spec_text))
        jira, prs = _extract_refs(refs_text)
        lane = item_root.parent.name
        conversations = len(list((item_root / "logs" / "conversations").glob("*.jsonl")))
        closeout = any((item_root / name).exists() for name in ("HOLDOUT_QA_RESULTS.md", "SUMMARY.md"))
        items.append(
            {
                "id": str(metadata.get("id") or work_item),
                "title": title,
                "summary": _first_sentence(summary, fallback=f"{title} is {status}."),
                "detail": _first_useful_line(next_text, fallback="No next action recorded."),
                "status": status,
                "lane": lane,
                "domain": domain,
                "project": project,
                "work_item": work_item,
                "updated_at": str(metadata.get("updated_at") or _mtime(metadata_path)),
                "source": _relative(metadata_path, os_root),
                "tags": sorted({domain, project, lane, status} - {""}),
                "jira_keys": jira,
                "pull_requests": prs,
                "conversation_count": conversations,
                "closeout_evidence": closeout,
            }
        )
    lane_order = {"02-active": 0, "01-intake": 1, "03-complete": 2}
    return sorted(items, key=lambda item: (lane_order.get(item["lane"], 9), item["status"], item["id"]))


def _conversation_paths(root: Path, max_files: int, *, include_harness_sessions: bool = True) -> list[Path]:
    paths: list[Path] = []
    patterns = (
        "*/02-projects/*/logs/conversations/*.jsonl",
        "*/02-projects/*/work-items/*/*/logs/conversations/*.jsonl",
        "*/06-runs-and-logs/conversations/*.jsonl",
        "harness/logs/conversations/*.jsonl",
    )
    for pattern in patterns:
        paths.extend(root.glob(pattern))

    # Harness-owned local transcripts are metadata-only inputs.  They are
    # bounded aggressively because a long-lived host can have thousands.
    if include_harness_sessions:
        home = Path.home()
        for base in (home / ".codex" / "sessions", home / ".codex" / "archived_sessions", home / ".claude" / "projects"):
            if base.exists():
                try:
                    paths.extend(base.rglob("*.jsonl"))
                except OSError:
                    continue
    return _bounded_recent(paths, max_files)


def _jsonl_metadata(path: Path) -> tuple[dict[str, Any], str]:
    metadata: dict[str, Any] = {}
    searchable: list[str] = []
    for line in _safe_text(path).splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(row, dict):
            continue
        payload = row.get("payload") if isinstance(row.get("payload"), dict) else row
        row_type = str(row.get("type") or payload.get("type") or "")
        if row_type in {"session_meta", "custom-title", "summary"} or not metadata:
            for key in ("id", "session_id", "sessionId", "thread_id", "timestamp", "created_at", "cwd", "originator", "source", "title", "customTitle", "git"):
                value = payload.get(key)
                if value not in (None, "", [], {}):
                    metadata[key] = value
        # Text is used only for reference extraction and is never returned.
        encoded = json.dumps(row, ensure_ascii=False)
        searchable.append(encoded[:8_000])
        if sum(map(len, searchable)) >= 96_000:
            break
    return metadata, "\n".join(searchable)


def _harness_for(path: Path, metadata: dict[str, Any]) -> str:
    value = " ".join(str(metadata.get(key) or "") for key in ("originator", "source")).lower()
    if ".codex" in path.parts or "codex" in value:
        return "codex"
    if ".claude" in path.parts or "claude" in value:
        return "claude"
    return "unknown"


def collect_conversations(
    root: str | Path,
    *,
    max_files: int = 500,
    include_harness_sessions: bool = True,
) -> list[dict[str, Any]]:
    os_root = Path(root).expanduser().resolve()
    conversations: list[dict[str, Any]] = []
    route_index = _project_route_index(os_root)
    for path in _conversation_paths(os_root, max_files, include_harness_sessions=include_harness_sessions):
        metadata, searchable = _jsonl_metadata(path)
        session_id = str(metadata.get("id") or metadata.get("session_id") or metadata.get("sessionId") or path.stem)
        title = str(metadata.get("title") or metadata.get("customTitle") or f"Conversation {session_id[:10]}")
        cwd = Path(str(metadata.get("cwd") or "")).expanduser() if metadata.get("cwd") else path.parent
        domain, project, work_item = _project_from_path(path, os_root)
        if not project:
            cwd_domain, cwd_project = _project_for_cwd(cwd, os_root, route_index)
            domain, project = cwd_domain, cwd_project
        jira, prs = _extract_refs(searchable)
        archived = "archived_sessions" in path.parts
        source = _relative(path, os_root)
        launcher = ""
        if cwd and str(cwd):
            launcher = f"cd {json.dumps(str(cwd))} && agentic-os here context build --root {json.dumps(str(os_root))}"
        conversations.append(
            {
                "id": session_id,
                "title": title,
                "summary": f"{_harness_for(path, metadata).title()} conversation routed to {project or domain or 'unclassified OS work'}.",
                "detail": "Metadata-only inventory; open the canonical harness transcript for full context.",
                "status": "archived" if archived else "observed",
                "harness": _harness_for(path, metadata),
                "domain": domain,
                "project": project,
                "work_item": work_item,
                "updated_at": str(metadata.get("timestamp") or metadata.get("created_at") or _mtime(path)),
                "source": source,
                "tags": sorted({domain, project, work_item, _harness_for(path, metadata)} - {""}),
                "jira_keys": jira,
                "pull_requests": prs,
                "launcher_command": launcher,
            }
        )
    return sorted(conversations, key=lambda item: (item["updated_at"], item["id"]), reverse=True)


def collect_reviews(work_items: list[dict[str, Any]], conversations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    reviews: dict[str, dict[str, Any]] = {}
    for item in [*work_items, *conversations]:
        for pr in item.get("pull_requests", []):
            key = str(pr.get("url") or f"{pr.get('owner')}/{pr.get('repo')}#{pr.get('number')}").lower()
            review = reviews.setdefault(
                key,
                {
                    "id": _stable_id("github-pr", key),
                    "title": f"{pr.get('owner')}/{pr.get('repo')} PR #{pr.get('number')}",
                    "summary": "Pull request observed in Agentic OS activity.",
                    "detail": "Open the linked PR for live review state; this snapshot does not query GitHub.",
                    "status": "observed",
                    "domain": item.get("domain", ""),
                    "project": item.get("project", ""),
                    "work_item": item.get("work_item", ""),
                    "updated_at": item.get("updated_at", ""),
                    "source": pr.get("url", ""),
                    "url": pr.get("url", ""),
                    "tags": ["github", "pull-request"],
                    "evidence": [],
                },
            )
            evidence = str(item.get("source") or "")
            if evidence and evidence not in review["evidence"]:
                review["evidence"].append(evidence)
            if str(item.get("updated_at") or "") > str(review.get("updated_at") or ""):
                review["updated_at"] = item.get("updated_at", "")
    return sorted(reviews.values(), key=lambda item: (item["updated_at"], item["title"]), reverse=True)


def collect_automations(root: str | Path, *, max_items: int = 500) -> list[dict[str, Any]]:
    os_root = Path(root).expanduser().resolve()
    paths: list[tuple[str, Path]] = []
    for kind, patterns in {
        "workflow": ("*/03-workflows/*/*/workflow.md", "harness/shared_factory/03-workflows/*/*/workflow.md"),
        "automation": ("*/04-automations/*/*/automation.md", "harness/shared_factory/04-automations/*/*/automation.md"),
        "program": ("*/00-programs/*/program.md", "harness/shared_factory/00-programs/*/program.md"),
    }.items():
        for pattern in patterns:
            paths.extend((kind, path) for path in os_root.glob(pattern))
    items: list[dict[str, Any]] = []
    for kind, path in sorted(paths, key=lambda pair: str(pair[1]))[:max_items]:
        text = _safe_text(path, limit=64_000)
        domain, project, work_item = _project_from_path(path, os_root)
        title_match = re.search(r"^#\s+(.+)$", text, re.MULTILINE)
        title = title_match.group(1).strip() if title_match else path.parent.name.replace("_", " ").title()
        status_match = re.search(r"(?im)^status:\s*([^\n]+)", text)
        status = status_match.group(1).strip() if status_match else "declared"
        items.append(
            {
                "id": _stable_id(kind, _relative(path, os_root)),
                "title": title,
                "summary": _first_useful_line(text, fallback=f"Declared {kind}."),
                "detail": f"{kind.title()} definition and runbook metadata.",
                "status": status,
                "kind": kind,
                "domain": domain,
                "project": project,
                "work_item": work_item,
                "updated_at": _mtime(path),
                "source": _relative(path, os_root),
                "tags": sorted({domain, kind, status} - {""}),
            }
        )
    return items


def collect_hosts(root: str | Path) -> list[dict[str, Any]]:
    os_root = Path(root).expanduser().resolve()
    hosts: dict[str, dict[str, Any]] = {}
    for relative in ("config/hosts.yml", "harness/config/hosts.yml"):
        path = os_root / relative
        data = _safe_yaml(path)
        mapping = data.get("hosts") if isinstance(data.get("hosts"), dict) else {}
        for alias, value in mapping.items():
            entry = value if isinstance(value, dict) else {}
            roles = entry.get("roles") or entry.get("capabilities") or []
            if isinstance(roles, str):
                roles = [roles]
            hosts[str(alias)] = {
                "id": str(alias),
                "title": str(entry.get("label") or alias),
                "summary": f"Registered host {alias} ({entry.get('hostname') or entry.get('ssh_alias') or 'local route'}).",
                "detail": "Registry state only; run the guarded host/runtime doctors for live health.",
                "status": str(entry.get("status") or "registered"),
                "domain": "",
                "project": "",
                "work_item": "",
                "updated_at": _mtime(path),
                "source": relative,
                "tags": sorted({"host", *[str(role) for role in roles]}),
                "hostname": str(entry.get("hostname") or entry.get("ssh_alias") or alias),
                "os_root": str(entry.get("os_root") or entry.get("agentic_os_root") or ""),
                "roles": [str(role) for role in roles],
            }
    return [hosts[key] for key in sorted(hosts)]


def collect_runtime(root: str | Path) -> list[dict[str, Any]]:
    """Project backend-neutral queue and worker metrics without subprocesses."""
    backend = queue_mode_status(root)
    metrics = backend["metrics"]
    cards: list[dict[str, Any]] = []
    for queue in metrics.get("queues") or []:
        statuses = queue.get("statuses") or {}
        queued = int(statuses.get("queued", 0)) + int(statuses.get("approval-needed", 0))
        failed = int(statuses.get("failed", 0)) + int(statuses.get("dead-letter", 0))
        health = "critical" if statuses.get("dead-letter") else "degraded" if failed else "healthy"
        cards.append({
            "id": f"runtime-queue-{queue['queue_name']}",
            "title": f"Queue: {queue['queue_name']}",
            "summary": f"{queued} waiting, {int(statuses.get('running', 0))} running, {failed} failed/dead-letter.",
            "status": health,
            "kind": "execution_queue",
            "queue_mode": backend["queue_mode"],
            **queue,
            "tags": ["runtime", "queue", backend["queue_mode"]],
        })
    for pool in metrics.get("worker_pools") or []:
        cards.append({
            "id": f"runtime-pool-{pool['name']}",
            "title": f"Worker pool: {pool['name']}",
            "summary": f"{int(pool.get('live_workers') or 0)} live, {int(pool.get('active_tasks') or 0)} active of {int(pool.get('max_concurrency') or 0)} task slots.",
            "status": "degraded" if int(pool.get("unhealthy_workers") or 0) else "healthy",
            "kind": "worker_pool",
            **pool,
            "tags": ["runtime", "workers", str(pool.get("provider") or "local")],
        })
    return cards


def collect_hygiene(
    root: str | Path,
    work_items: list[dict[str, Any]],
    conversations: list[dict[str, Any]],
    *,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    os_root = Path(root).expanduser().resolve()
    findings: list[dict[str, Any]] = []
    current = _now(now)
    for item in work_items:
        if item.get("lane") in ACTIVE_LANES and str(item.get("status", "")).lower() in TERMINAL_STATES:
            findings.append(
                {
                    "id": _stable_id("terminal-active", item["id"]),
                    "title": f"Finalize lingering work item {item['id']}",
                    "summary": "A terminal-state work item remains in an active lifecycle lane.",
                    "detail": f"Current state {item['status']} is recorded in {item['lane']}.",
                    "status": "needs-review",
                    "severity": "warning",
                    "kind": "work-item-lifecycle",
                    "domain": item.get("domain", ""),
                    "project": item.get("project", ""),
                    "work_item": item.get("work_item", ""),
                    "updated_at": item.get("updated_at", ""),
                    "source": item.get("source", ""),
                    "tags": ["cleanup", "work-item"],
                    "suggested_command": f"agentic-os project work-item finalize-lingering {item.get('domain')} {item.get('project')} --root {os_root}",
                }
            )
    for link in os_root.glob("*/02-projects/*/worktrees/*"):
        if not link.is_symlink():
            continue
        try:
            target_exists = link.resolve(strict=False).exists()
        except OSError:
            target_exists = False
        if not target_exists:
            domain, project, _ = _project_from_path(link, os_root)
            findings.append(
                {
                    "id": _stable_id("broken-worktree", str(link)),
                    "title": f"Broken worktree registration {link.name}",
                    "summary": "A registered worktree link no longer resolves.",
                    "detail": "Review the project worktree registry before removing the stale link.",
                    "status": "needs-review",
                    "severity": "warning",
                    "kind": "worktree",
                    "domain": domain,
                    "project": project,
                    "work_item": "",
                    "updated_at": _mtime(link),
                    "source": _relative(link, os_root),
                    "tags": ["cleanup", "worktree"],
                    "suggested_command": f"agentic-os project worktree cleanup-closed {domain} {project} --root {os_root}",
                }
            )
    stale_count = 0
    for conversation in conversations:
        stamp = str(conversation.get("updated_at") or "").replace("Z", "+00:00")
        try:
            age_days = (current - datetime.fromisoformat(stamp)).days
        except ValueError:
            continue
        if conversation.get("status") != "archived" and age_days >= 7:
            stale_count += 1
    if stale_count:
        findings.append(
            {
                "id": _stable_id("stale-conversations", stale_count),
                "title": f"Review {stale_count} quiet conversations",
                "summary": "Unarchived conversations have been quiet for at least seven days.",
                "detail": "Run stale finalization to plan closeout; no thread is archived or deleted by this snapshot.",
                "status": "needs-review",
                "severity": "info",
                "kind": "conversation",
                "domain": "",
                "project": "",
                "work_item": "",
                "updated_at": _iso(current),
                "source": "harness conversation metadata",
                "tags": ["cleanup", "conversation"],
                "suggested_command": f"agentic-os thread stale-finalize --root {os_root}",
            }
        )
    severity_order = {"critical": 0, "error": 1, "warning": 2, "info": 3}
    return sorted(findings, key=lambda finding: (severity_order.get(finding["severity"], 9), finding["title"]))


def _source_label(value: Any) -> str:
    if isinstance(value, dict):
        for key in ("project_key", "repo", "channel_name", "channel_id", "jql", "path"):
            if value.get(key):
                return str(value[key])
        return ", ".join(f"{key}={item}" for key, item in sorted(value.items())[:3])
    return str(value or "")


def _decorate_sources(payload: dict[str, Any]) -> dict[str, Any]:
    decorated: dict[str, list[dict[str, Any]]] = {"configured": [], "observed": [], "suggestions": []}
    for group in decorated:
        rows = payload.get(group, []) if isinstance(payload.get(group), list) else []
        for raw in rows:
            if not isinstance(raw, dict):
                continue
            item = dict(raw)
            source_type = str(item.get("source_type") or "source")
            external_ref = _source_label(item.get("external_ref"))
            observation = item.get("observation") if isinstance(item.get("observation"), dict) else item
            signal_count = observation.get("signal_count") or len(observation.get("reasons") or [])
            score = observation.get("score")
            item.setdefault("id", str(item.get("source_key") or f"{group}:{source_type}:{external_ref}"))
            item.setdefault("title", str(item.get("display_name") or external_ref or item.get("id") or source_type))
            if group == "configured":
                item.setdefault("status", "enabled" if item.get("enabled") else "configured")
                item.setdefault("summary", f"Configured {source_type.replace('_', ' ')} watch.")
            elif group == "observed":
                score_text = f", score {score}" if score is not None else ""
                item.setdefault("status", "configured" if item.get("configured") else "observed")
                item.setdefault("summary", f"Observed {signal_count or 1} usage signals for {external_ref or source_type}{score_text}.")
            else:
                item.setdefault("status", "proposed")
                item.setdefault("summary", f"Proposed {source_type.replace('_', ' ')} coverage from {signal_count or 1} observed signals.")
            reasons = observation.get("reasons") if isinstance(observation, dict) else []
            if reasons:
                item.setdefault("detail", "; ".join(str(reason) for reason in reasons[:5]))
            item.setdefault("tags", sorted({group, source_type, item["status"]}))
            decorated[group].append(item)
    return decorated


def build_cockpit_snapshot(
    root: str | Path,
    *,
    now: datetime | None = None,
    max_files: int = 500,
    include_harness_sessions: bool = True,
) -> dict[str, Any]:
    os_root = Path(root).expanduser().resolve()
    if not os_root.exists():
        raise ValueError(f"Agentic OS root does not exist: {os_root}")
    diagnostics: list[dict[str, str]] = []

    def collect(name: str, function: Any, fallback: Any) -> Any:
        try:
            return function()
        except Exception as exc:  # one optional collector must not break the cockpit
            diagnostics.append({"collector": name, "severity": "warning", "message": f"{type(exc).__name__}: {exc}"})
            return fallback

    work_items = collect("work_items", lambda: collect_work_items(os_root), [])
    conversations = collect(
        "conversations",
        lambda: collect_conversations(
            os_root,
            max_files=max_files,
            include_harness_sessions=include_harness_sessions,
        ),
        [],
    )
    reviews = collect("reviews", lambda: collect_reviews(work_items, conversations), [])
    reports = collect("reports", lambda: collect_reports(os_root, now=now, max_files=max_files), [])
    automations = collect("automations", lambda: collect_automations(os_root), [])
    runtime = collect("runtime", lambda: collect_runtime(os_root), [])
    sources = collect(
        "sources",
        lambda: build_source_observation_snapshot(os_root, now=now, max_files=max_files),
        {"configured": [], "observed": [], "suggestions": [], "diagnostics": []},
    )
    hosts = collect("hosts", lambda: collect_hosts(os_root), [])
    hygiene = collect("hygiene", lambda: collect_hygiene(os_root, work_items, conversations, now=now), [])
    source_diagnostics = sources.pop("diagnostics", []) if isinstance(sources, dict) else []
    if isinstance(source_diagnostics, dict):
        diagnostics.extend(
            {
                "collector": "sources",
                "severity": "info",
                "message": f"{key}: {value}",
            }
            for key, value in sorted(source_diagnostics.items())
        )
    elif isinstance(source_diagnostics, list):
        diagnostics.extend(
            item if isinstance(item, dict) else {"collector": "sources", "severity": "info", "message": str(item)}
            for item in source_diagnostics
        )
    source_payload = _decorate_sources(sources) if isinstance(sources, dict) else {"configured": [], "observed": [], "suggestions": []}
    for key in ("configured", "observed", "suggestions"):
        source_payload.setdefault(key, [])

    active = sum(1 for item in work_items if item.get("lane") == "02-active")
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _iso(now),
        "root": str(os_root),
        "summary": {
            "active_work": active,
            "conversations": len(conversations),
            "reviews": len(reviews),
            "reports": len(reports),
            "automations": len(automations),
            "queue_depth": sum(
                int((item.get("statuses") or {}).get("queued", 0))
                + int((item.get("statuses") or {}).get("approval-needed", 0))
                for item in runtime
                if item.get("kind") == "execution_queue"
            ),
            "active_workers": sum(int(item.get("live_workers") or 0) for item in runtime if item.get("kind") == "worker_pool"),
            "runtime_health": "critical" if any(item.get("status") == "critical" for item in runtime) else "degraded" if any(item.get("status") == "degraded" for item in runtime) else "healthy",
            "source_suggestions": len(source_payload["suggestions"]),
            "hosts": len(hosts),
            "hygiene_findings": len(hygiene),
        },
        "work_items": work_items,
        "conversations": conversations,
        "reviews": reviews,
        "reports": reports,
        "automations": automations,
        "runtime": runtime,
        "sources": source_payload,
        "hosts": hosts,
        "hygiene": hygiene,
        "diagnostics": diagnostics,
    }


def write_cockpit_snapshot(snapshot: dict[str, Any], output_path: str | Path) -> Path:
    path = Path(output_path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(snapshot, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def build_cockpit_bundle(
    root: str | Path,
    *,
    output_dir: str | Path | None = None,
    now: datetime | None = None,
    max_files: int = 500,
    include_harness_sessions: bool = True,
) -> dict[str, Any]:
    from .cockpit_render import write_cockpit_html

    os_root = Path(root).expanduser().resolve()
    destination = Path(output_dir).expanduser() if output_dir else os_root / DEFAULT_OUTPUT
    destination.mkdir(parents=True, exist_ok=True)
    snapshot = build_cockpit_snapshot(
        os_root,
        now=now,
        max_files=max_files,
        include_harness_sessions=include_harness_sessions,
    )
    snapshot_path = write_cockpit_snapshot(snapshot, destination / "snapshot.json")
    html_path = write_cockpit_html(snapshot, destination / "index.html")
    return {"snapshot": snapshot, "snapshot_path": str(snapshot_path), "html_path": str(html_path)}


def open_cockpit(
    root: str | Path,
    *,
    output_dir: str | Path | None = None,
    max_files: int = 500,
    include_harness_sessions: bool = True,
) -> dict[str, Any]:
    result = build_cockpit_bundle(
        root,
        output_dir=output_dir,
        max_files=max_files,
        include_harness_sessions=include_harness_sessions,
    )
    result["opened"] = bool(webbrowser.open(Path(result["html_path"]).resolve().as_uri()))
    return result
