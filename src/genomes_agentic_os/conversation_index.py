"""Shared, local-only conversation indexing primitives for AgenticOSGui.

The provider adapters deliberately keep private harness state at the edge.  This
module owns normalization, OS project routing, compact reference extraction,
and relative-age labels used by both Claude and Codex projections.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import re
from typing import Any, Iterable
from urllib.parse import unquote, urlparse

import yaml


JIRA_RE = re.compile(r"\b([A-Z][A-Z0-9]{1,15}-\d+)\b")
JIRA_URL_RE = re.compile(
    r"https://[A-Za-z0-9.-]+\.atlassian\.net/browse/(?P<key>[A-Z][A-Z0-9]{1,15}-\d+)",
    re.IGNORECASE,
)
LINEAR_URL_RE = re.compile(
    r"https://linear\.app/[A-Za-z0-9_-]+/issue/(?P<key>[A-Z][A-Z0-9]{1,15}-\d+)(?:/[A-Za-z0-9_-]+)?",
    re.IGNORECASE,
)
PR_URL_RE = re.compile(
    r"https://github\.com/(?P<owner>[A-Za-z0-9_.-]+)/(?P<repo>[A-Za-z0-9_.-]+)/pull/(?P<number>\d+)",
    re.IGNORECASE,
)
SLACK_URL_RE = re.compile(
    r"https://(?P<workspace>[A-Za-z0-9-]+)\.slack\.com/archives/"
    r"(?P<channel>[A-Z0-9]+)/p(?P<timestamp>\d+)",
    re.IGNORECASE,
)
FILE_URL_RE = re.compile(r"file://(?P<path>/[^\s<>\]\[\)\(\"']+)")
ABSOLUTE_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9_.-])(?P<path>/(?:Users|Volumes|private|tmp)/[^\s<>\]\[\)\(\"']+)"
)
OPAQUE_TITLE_RE = re.compile(
    r"^(?:conversation|session|thread)\s+(?:[0-9a-f]{8,}|[0-9a-f-]{20,})$",
    re.IGNORECASE,
)


def utc_now(value: datetime | None = None) -> datetime:
    current = value or datetime.now(timezone.utc)
    return current if current.tzinfo else current.replace(tzinfo=timezone.utc)


def iso_from_timestamp(value: Any) -> str:
    """Normalize epoch seconds/milliseconds or ISO input to a UTC ISO string."""
    if value in (None, ""):
        return ""
    if isinstance(value, (int, float)):
        seconds = float(value)
        if seconds > 10_000_000_000:
            seconds /= 1000
        try:
            return datetime.fromtimestamp(seconds, tz=timezone.utc).isoformat().replace("+00:00", "Z")
        except (OverflowError, OSError, ValueError):
            return ""
    text = str(value).strip()
    if not text:
        return ""
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return text
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def age_label(updated_at: str, *, now: datetime | None = None) -> str:
    """Return the compact age used in conversation list rows (5m, 3h, 2d, 1w)."""
    if not updated_at:
        return ""
    try:
        parsed = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
    except ValueError:
        return ""
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    seconds = max(0, int((utc_now(now) - parsed.astimezone(timezone.utc)).total_seconds()))
    if seconds < 60:
        return "now"
    if seconds < 3_600:
        return f"{seconds // 60}m"
    if seconds < 86_400:
        return f"{seconds // 3_600}h"
    if seconds < 604_800:
        return f"{seconds // 86_400}d"
    return f"{seconds // 604_800}w"


def human_title(*candidates: Any, fallback: str = "Untitled conversation", limit: int = 100) -> str:
    """Choose a readable one-line title without ever exposing an opaque UUID label."""
    for candidate in candidates:
        if not isinstance(candidate, str):
            continue
        title = re.sub(r"\s+", " ", candidate).strip(" #\t\r\n-")
        if not title or OPAQUE_TITLE_RE.fullmatch(title):
            continue
        if len(title) > limit:
            title = title[: limit - 1].rstrip() + "…"
        return title
    return fallback


def normalize_effort(value: Any, model: str = "") -> str:
    text = str(value or "").lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "extra_high": "xhigh",
        "very_high": "xhigh",
        "minimal": "low",
    }
    text = aliases.get(text, text)
    if text in {"low", "medium", "high", "xhigh", "max", "ultra"}:
        return text
    return "unknown"


def infer_model_tier(model: Any) -> str:
    """Infer the presentation tier from a known model family, never effort."""
    name = str(model or "").lower()
    if not name or name == "unknown":
        return "unknown"
    if any(token in name for token in ("human-gate", "human_gate")):
        return "human_gate"
    if any(token in name for token in ("frontier-max", "frontier_max", "ultra", "-max")):
        return "frontier_max"
    if any(token in name for token in ("haiku", "mini", "spark", "luna")):
        return "economy"
    if any(token in name for token in ("fable", "sonnet", "terra", "balanced")):
        return "balanced"
    if any(token in name for token in ("opus", "sol", "frontier", "gpt-5.5", "gpt-5.6")):
        return "frontier"
    return "unknown"


def model_metadata(provider: str, model: Any, effort: Any) -> dict[str, str]:
    model_name = str(model or "unknown")
    normalized_effort = normalize_effort(effort, model_name)
    return {
        "provider": provider,
        "model": model_name,
        "reasoning_effort": normalized_effort,
        "model_tier": infer_model_tier(model_name),
    }


def _clean_asset_path(raw: str) -> str:
    value = raw.rstrip(".,;:!?`}")
    if value.startswith("file://"):
        value = unquote(urlparse(value).path)
    return value


def extract_references(texts: Iterable[str]) -> dict[str, list[dict[str, str]]]:
    """Extract local metadata links without making external calls."""
    text = "\n".join(value for value in texts if isinstance(value, str))
    linear: dict[str, dict[str, str]] = {}
    for match in LINEAR_URL_RE.finditer(text):
        key = match.group("key").upper()
        linear[key] = {"key": key, "url": match.group(0)}

    jira: dict[str, dict[str, str]] = {
        key: {"key": key}
        for key in sorted(set(JIRA_RE.findall(text)))
        if key not in linear
    }
    for match in JIRA_URL_RE.finditer(text):
        key = match.group("key").upper()
        jira[key] = {"key": key, "url": match.group(0)}

    prs: dict[str, dict[str, str]] = {}
    for match in PR_URL_RE.finditer(text):
        owner = match.group("owner")
        repo = match.group("repo")
        number = match.group("number")
        url = f"https://github.com/{owner}/{repo}/pull/{number}"
        prs[url.lower()] = {"owner": owner, "repo": repo, "number": number, "url": url}

    slack: dict[str, dict[str, str]] = {}
    for match in SLACK_URL_RE.finditer(text):
        url = match.group(0)
        slack[url.lower()] = {
            "workspace": match.group("workspace"),
            "channel_id": match.group("channel"),
            "message_ts": match.group("timestamp"),
            "url": url,
        }

    assets: dict[str, dict[str, str]] = {}
    for regex in (FILE_URL_RE, ABSOLUTE_PATH_RE):
        for match in regex.finditer(text):
            path = _clean_asset_path(match.group("path"))
            if not path or path == "/":
                continue
            suffix = Path(path).suffix.lower().lstrip(".")
            assets[path] = {"path": path, "kind": suffix or "path"}

    return {
        "jira": [jira[key] for key in sorted(jira)],
        "linear": [linear[key] for key in sorted(linear)],
        "pull_requests": [prs[key] for key in sorted(prs)],
        "slack": [slack[key] for key in sorted(slack)],
        "assets": [assets[key] for key in sorted(assets)],
    }


def visible_text(content: Any) -> str:
    """Extract visible text blocks while excluding tool/system payloads."""
    if isinstance(content, str):
        return content.strip()
    if not isinstance(content, list):
        return ""
    values: list[str] = []
    for block in content:
        if isinstance(block, str):
            values.append(block)
            continue
        if not isinstance(block, dict):
            continue
        if str(block.get("type") or "") not in {"text", "input_text", "output_text"}:
            continue
        value = block.get("text")
        if isinstance(value, str) and value.strip():
            values.append(value.strip())
    return "\n\n".join(values).strip()


def _read_yaml(path: Path) -> dict[str, Any]:
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return value if isinstance(value, dict) else {}
    except (OSError, UnicodeError, yaml.YAMLError):
        return {}


def build_project_routes(root: str | Path) -> list[dict[str, Any]]:
    """Build longest-path-first domain/project routes from installed project roots."""
    os_root = Path(root).expanduser().resolve(strict=False)
    routes: dict[str, dict[str, Any]] = {}
    project_roots = {
        *os_root.glob("*/02-projects/*"),
        *os_root.glob("domains/*/02-projects/*"),
        *os_root.glob("domains/*/projects/*"),
    }
    for project_root in sorted(project_roots):
        if not project_root.is_dir():
            continue
        relative_parts = project_root.relative_to(os_root).parts
        domain = relative_parts[1] if relative_parts[0] == "domains" else relative_parts[0]
        project = project_root.name
        metadata = _read_yaml(project_root / "project.yml")
        title = human_title(metadata.get("title"), metadata.get("name"), project.replace("_", " ").title())
        candidates = [project_root, project_root / "src"]
        worktrees = project_root / "worktrees"
        if worktrees.is_dir():
            try:
                candidates.extend(worktrees.iterdir())
            except OSError:
                pass
        sources = metadata.get("sources") if isinstance(metadata.get("sources"), dict) else {}
        repo = sources.get("repo") if isinstance(sources, dict) else None
        if isinstance(repo, str) and repo.startswith("/"):
            candidates.append(Path(repo))
        for candidate in candidates:
            try:
                if not candidate.exists() and not candidate.is_symlink():
                    continue
                resolved = candidate.resolve(strict=False)
            except OSError:
                continue
            routes[str(resolved)] = {
                "path": resolved,
                "domain": domain,
                "project": project,
                "project_title": title,
                "project_root": str(project_root.resolve(strict=False)),
            }
    return sorted(routes.values(), key=lambda item: len(item["path"].parts), reverse=True)


def route_cwd(cwd: str | Path, routes: list[dict[str, Any]]) -> dict[str, str]:
    if not str(cwd or "").strip():
        return {"domain": "", "project": "", "project_title": "", "project_root": ""}
    try:
        resolved = Path(cwd).expanduser().resolve(strict=False)
    except OSError:
        return {"domain": "", "project": "", "project_title": "", "project_root": ""}
    for route in routes:
        target = route["path"]
        if resolved == target or target in resolved.parents:
            return {key: str(route[key]) for key in ("domain", "project", "project_title", "project_root")}
    return {"domain": "", "project": "", "project_title": "", "project_root": ""}


def build_work_item_routes(root: str | Path) -> list[dict[str, Any]]:
    """Index Jira/PR evidence already captured in installed project work items."""
    os_root = Path(root).expanduser().resolve(strict=False)
    items: list[dict[str, Any]] = []
    work_items = {
        *os_root.glob("*/02-projects/*/work-items/*/*/work.yml"),
        *os_root.glob("domains/*/02-projects/*/work-items/*/*/work.yml"),
        *os_root.glob("domains/*/projects/*/work-items/*/*/work.yml"),
    }
    for work_yml in work_items:
        try:
            relative = work_yml.relative_to(os_root)
        except ValueError:
            continue
        parts = relative.parts
        if len(parts) < 7:
            continue
        if parts[0] == "domains":
            domain, project = parts[1], parts[3]
        else:
            domain, project = parts[0], parts[2]
        item_root = work_yml.parent
        text_parts: list[str] = []
        for path in (work_yml, item_root / "SPEC.md", item_root / "NEXT.md", item_root / "SUMMARY.md"):
            try:
                text_parts.append(path.read_text(encoding="utf-8")[:128_000])
            except (OSError, UnicodeError):
                continue
        references = extract_references(text_parts)
        items.append(
            {
                "domain": domain,
                "project": project,
                "work_item": item_root.name,
                "jira_keys": {item["key"] for item in references["jira"]},
                "pr_urls": {item["url"].lower() for item in references["pull_requests"]},
            }
        )
    return items


def route_conversation(
    *,
    cwd: str,
    routes: list[dict[str, Any]],
    work_items: list[dict[str, Any]],
    title: str,
    visible_texts: Iterable[str],
    references: dict[str, list[dict[str, str]]],
    native_hints: Iterable[str] = (),
) -> dict[str, Any]:
    """Route with explicit evidence, ending in a conservative unique alias match."""
    strong: list[tuple[str, dict[str, str], str]] = []
    direct = route_cwd(cwd, routes)
    if direct["project"]:
        strong.append(("cwd", direct, ""))

    for hint in native_hints:
        candidate = route_cwd(hint, routes)
        if candidate["project"]:
            strong.append(("native_workspace_hint", candidate, ""))

    for asset in references.get("assets", []):
        candidate = route_cwd(asset.get("path", ""), routes)
        if candidate["project"]:
            strong.append(("asset_path", candidate, ""))

    jira_keys = {item["key"] for item in references.get("jira", []) if item.get("key")}
    pr_urls = {item["url"].lower() for item in references.get("pull_requests", []) if item.get("url")}
    evidence_matches = [
        item
        for item in work_items
        if (jira_keys and jira_keys.intersection(item["jira_keys"]))
        or (pr_urls and pr_urls.intersection(item["pr_urls"]))
    ]
    evidence_projects = {(item["domain"], item["project"]) for item in evidence_matches}
    for domain, project in evidence_projects:
        route = next((item for item in routes if item["domain"] == domain and item["project"] == project), None)
        if not route:
            continue
        matched_items = sorted(
            {
                item["work_item"]
                for item in evidence_matches
                if item["domain"] == domain and item["project"] == project
            }
        )
        strong.append(
            (
                "work_item_reference",
                {key: str(route[key]) for key in ("domain", "project", "project_title", "project_root")},
                matched_items[0] if len(matched_items) == 1 else "",
            )
        )

    strong_projects = {(item[1]["domain"], item[1]["project"]) for item in strong}
    if len(strong_projects) > 1:
        return {
            "domain": "",
            "project": "",
            "project_title": "",
            "project_root": "",
            "work_item": "",
            "route_confidence": "none",
            "route_source": "conflicting_strong_evidence",
            "route_conflict": True,
        }
    if len(strong_projects) == 1:
        priorities = {"cwd": 0, "native_workspace_hint": 1, "work_item_reference": 2, "asset_path": 3}
        source, selected, work_item = sorted(strong, key=lambda item: priorities[item[0]])[0]
        evidence_item = next((item[2] for item in strong if item[2]), work_item)
        confidence = "medium" if all(item[0] == "asset_path" for item in strong) else "high"
        return {
            **selected,
            "work_item": evidence_item,
            "route_confidence": confidence,
            "route_source": source,
            "route_conflict": False,
        }

    searchable = " ".join([title, *visible_texts]).lower()
    alias_matches: dict[tuple[str, str], dict[str, Any]] = {}
    for route in routes:
        aliases = {
            str(route["project"]).lower().replace("_", " "),
            str(route["project_title"]).lower(),
        }
        broad_aliases = {"os", "app", "application", "agentic", "django", "project", "service"}
        if any(
            alias not in broad_aliases
            and len(alias) >= 4
            and re.search(rf"(?<!\w){re.escape(alias)}(?!\w)", searchable)
            for alias in aliases
        ):
            alias_matches[(str(route["domain"]), str(route["project"]))] = route
    if len(alias_matches) == 1:
        route = next(iter(alias_matches.values()))
        return {
            "domain": str(route["domain"]),
            "project": str(route["project"]),
            "project_title": str(route["project_title"]),
            "project_root": str(route["project_root"]),
            "work_item": "",
            "route_confidence": "low",
            "route_source": "unique_project_alias",
            "route_conflict": False,
        }
    return {
        "domain": "",
        "project": "",
        "project_title": "",
        "project_root": "",
        "work_item": "",
        "route_confidence": "none",
        "route_source": "unclassified",
        "route_conflict": False,
    }


def build_navigation(root: str | Path, conversations: list[dict[str, Any]]) -> dict[str, Any]:
    """Return the domain -> project tree as a first-class GUI navigation model."""
    os_root = Path(root).expanduser().resolve(strict=False)
    counts: dict[tuple[str, str], int] = {}
    for item in conversations:
        key = (str(item.get("domain") or ""), str(item.get("project") or ""))
        counts[key] = counts.get(key, 0) + 1

    domains: list[dict[str, Any]] = []
    for domain_root in sorted(os_root.glob("*")):
        projects_root = domain_root / "02-projects"
        if not domain_root.is_dir() or not projects_root.is_dir():
            continue
        domain_meta = _read_yaml(domain_root / "domain.yml")
        domain_id = domain_root.name
        projects: list[dict[str, Any]] = []
        for project_root in sorted(projects_root.iterdir()):
            if not project_root.is_dir():
                continue
            project_meta = _read_yaml(project_root / "project.yml")
            project_id = project_root.name
            projects.append(
                {
                    "id": project_id,
                    "name": human_title(
                        project_meta.get("title"),
                        project_meta.get("name"),
                        project_id.replace("_", " ").title(),
                    ),
                    "domain": domain_id,
                    "status": str(project_meta.get("status") or "active"),
                    "path": str(project_root.resolve(strict=False)),
                    "conversation_count": counts.get((domain_id, project_id), 0),
                }
            )
        domains.append(
            {
                "id": domain_id,
                "name": human_title(
                    domain_meta.get("title"),
                    domain_meta.get("name"),
                    domain_id.replace("_", " ").title(),
                ),
                "conversation_count": sum(project["conversation_count"] for project in projects),
                "projects": projects,
            }
        )
    return {"domains": domains}
