"""Project work-item lifecycle helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
import shlex
import shutil
import subprocess
from typing import Any, Mapping

import yaml
from jsonschema import Draft202012Validator

from .artifact_naming import dated_name, load_artifact_naming_policy
from .scaffold import (
    ScaffoldResult,
    append_control_signal,
    append_domain_memory,
    append_once,
    domain_path,
    ensure_spotlight_never_index,
    expand_path,
    normalize_domain,
    validate_name,
    write_file_once,
)


WORK_LIFECYCLE_STATES = (
    "captured",
    "triaged",
    "specified",
    "ready",
    "building",
    "validating",
    "finished",
    "documented",
    "blocked",
    "archived",
)

WORK_ITEM_LANES = ("01-intake", "02-active", "03-complete")
ARCHIVE_DIRECTORY = "99-archived"
TERMINAL_JIRA_STATUSES = {"qa_ready", "done", "ready_for_production", "wont_do", "won_t_do"}
TERMINAL_WORKTREE_STATUSES = TERMINAL_JIRA_STATUSES | {"merged", "closed", "archived", "inactive"}

WORK_ITEM_STATE_LANES: dict[str, str] = {
    "captured": "01-intake",
    "triaged": "01-intake",
    "specified": "02-active",
    "ready": "02-active",
    "building": "02-active",
    "validating": "02-active",
    "blocked": "02-active",
    "finished": "03-complete",
    "documented": "03-complete",
    "archived": "03-complete",
}

INTAKE_MARKDOWN_STATES = {"captured", "triaged"}

WORK_ITEM_METADATA_FILES = ("work.yml", "feature.yml", "work-item.md")

WORK_ITEM_FILES = (
    "SPEC.md",
    "PLAN.md",
    "INVESTIGATION.md",
    "JUDGMENT.md",
    "HOLDOUT_QA.md",
    "HOLDOUT_QA_RESULTS.md",
    "WORKLOG.md",
    "SUMMARY.md",
    "NEXT.md",
    "MEMORY.md",
)

WORK_ITEM_DIRECTORIES = (
    "artifacts",
    "logs",
    "logs/conversations",
)

STATE_REQUIRED_FILES: dict[str, tuple[str, ...]] = {
    "captured": ("SPEC.md", "WORKLOG.md", "NEXT.md"),
    "triaged": ("SPEC.md", "JUDGMENT.md", "WORKLOG.md", "NEXT.md"),
    "specified": ("SPEC.md", "JUDGMENT.md", "WORKLOG.md", "NEXT.md"),
    "ready": ("SPEC.md", "PLAN.md", "JUDGMENT.md", "WORKLOG.md", "NEXT.md"),
    "building": ("SPEC.md", "PLAN.md", "WORKLOG.md", "NEXT.md"),
    "validating": ("SPEC.md", "PLAN.md", "HOLDOUT_QA.md", "WORKLOG.md", "NEXT.md"),
    "finished": ("SUMMARY.md", "HOLDOUT_QA_RESULTS.md", "WORKLOG.md", "NEXT.md"),
    "documented": ("SUMMARY.md", "MEMORY.md", "WORKLOG.md", "NEXT.md"),
    "blocked": ("JUDGMENT.md", "WORKLOG.md", "NEXT.md"),
    "archived": ("SUMMARY.md", "WORKLOG.md"),
}

LEGACY_FILE_ALIASES: dict[str, tuple[str, ...]] = {
    "SPEC.md": ("IDEA.md",),
}

ACTIVE_WORK_ITEM_STATES = {
    "captured",
    "triaged",
    "specified",
    "ready",
    "building",
    "validating",
    "blocked",
}

ACTIVE_CONTAINER_WORK_ITEM_STATES = {"specified", "ready", "building", "validating", "blocked"}

TERMINAL_WORK_ITEM_STATES = {"finished", "documented", "archived"}
COMPLETION_INFERENCE_DECISIONS = ("finish-ready", "needs-thread-finalizer", "manual-review", "keep-active")

WORK_ITEM_INDEX_RE = re.compile(r"^(?:[A-Za-z0-9]{4,12}[-_])?(?P<index>\d{3})[_-](?P<slug>.+)$")

WORK_ITEM_MATCH_STOPWORDS = {
    "a",
    "an",
    "and",
    "for",
    "from",
    "in",
    "into",
    "item",
    "of",
    "on",
    "the",
    "to",
    "work",
}

TOKEN_SHAPED_VALUE_RE = re.compile(
    r"(?i)("
    r"sk-[a-z0-9_-]{20,}|"
    r"gh[pousr]_[a-z0-9_]{20,}|"
    r"xox[baprs]-[a-z0-9-]{20,}|"
    r"bearer\s+[a-z0-9._~+/=-]{20,}|"
    r"(api[_-]?key|token|secret)\s*[:=]\s*[a-z0-9._~+/=-]{16,}"
    r")"
)


@dataclass
class WorkItemRecord:
    path: Path
    metadata_path: Path
    status: str
    title: str
    slug: str
    source: str
    metadata: dict[str, Any]

    @property
    def required_files(self) -> list[Path]:
        return state_file_paths(self.path, self.status)

    @property
    def missing_required_files(self) -> list[Path]:
        return [path for path in self.required_files if not path.is_file()]

    @property
    def conversation_logs_path(self) -> Path:
        if self.path.is_file():
            return self.path.parent / f"{self.path.stem}.logs" / "conversations"
        return self.path / "logs" / "conversations"

    def as_lifecycle_dict(self) -> dict[str, Any]:
        return {
            "enabled": True,
            "state": self.status,
            "work_item": str(self.path),
            "metadata": str(self.metadata_path),
            "source": self.source,
            "lane": str(self.metadata.get("lane") or lane_for_status(self.status)),
            "format": "markdown" if self.path.is_file() else "folder",
            "required_files": [str(path) for path in self.required_files],
            "missing_required_files": [str(path) for path in self.missing_required_files],
            "conversation_logs": str(self.conversation_logs_path),
            "promotion_target": promotion_target_from_metadata(self.metadata),
        }


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def today_iso() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def slugify_work_id(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    return slug or "work-item"


def lane_for_status(status: str) -> str:
    return WORK_ITEM_STATE_LANES.get(status, "01-intake")


def work_items_root(project_root: Path) -> Path:
    return project_root / "work-items"


def work_lifecycle_settings(project_root: Path) -> dict[str, Any]:
    """Return the project lifecycle mapping from either supported config surface."""
    path = project_root / "config" / "work-lifecycle.yml"
    payload = load_yaml_mapping(path) if path.is_file() else load_yaml_mapping(project_root / "project.yml")
    nested = payload.get("work_lifecycle")
    return dict(nested) if isinstance(nested, dict) else dict(payload)


def lane_root(project_root: Path, status: str) -> Path:
    if str(work_lifecycle_settings(project_root).get("layout") or "single_canonical_root") == "single_canonical_root":
        return work_items_root(project_root)
    return work_items_root(project_root) / lane_for_status(status)


def root_project_dirs(root: Path, *, domain: str | None = None, project: str | None = None) -> list[Path]:
    roots: list[Path] = []
    if domain:
        domain_root = domain_path(root, normalize_domain(domain))
        projects_root = (
            domain_root / "projects"
            if (domain_root / "projects").is_dir()
            else domain_root / "02-projects"
        )
        if project:
            candidate = projects_root / validate_name(project, "project")
            if candidate.is_dir():
                roots.append(candidate)
        elif projects_root.is_dir():
            roots.extend(path for path in sorted(projects_root.iterdir()) if path.is_dir())
        return roots

    seen: set[str] = set()
    projects_roots = list(root.glob("*/02-projects"))
    projects_roots.extend(root.glob("domains/*/projects"))
    projects_roots.extend(root.glob("domains/*/02-projects"))
    projects_roots.append(root / "harness" / "shared_factory" / "02-projects")
    for projects_root in sorted(projects_roots):
        if not projects_root.is_dir():
            continue
        for candidate in sorted(projects_root.iterdir()):
            if not candidate.is_dir():
                continue
            if project and candidate.name != project:
                continue
            key = str(candidate.resolve())
            if key in seen:
                continue
            seen.add(key)
            roots.append(candidate)
    return roots


def work_item_index_from_name(name: str) -> int | None:
    match = WORK_ITEM_INDEX_RE.match(Path(name).stem)
    if not match:
        return None
    return int(match.group("index"))


def next_work_item_index(project_root: Path) -> int:
    indexes = []
    root = work_items_root(project_root)
    if not root.is_dir():
        return 1
    candidates = list(root.iterdir())
    for lane in WORK_ITEM_LANES:
        lane_path = root / lane
        if lane_path.is_dir():
            candidates.extend(lane_path.iterdir())
    archive_path = root / ARCHIVE_DIRECTORY
    if archive_path.is_dir():
        candidates.extend(archive_path.iterdir())
    for candidate in candidates:
        index = work_item_index_from_name(candidate.name)
        if index is not None:
            indexes.append(index)
    return max(indexes, default=0) + 1


def indexed_work_id(project_root: Path, value: str) -> str:
    slug = slugify_work_id(value)
    if WORK_ITEM_INDEX_RE.match(slug):
        return slug
    return f"{next_work_item_index(project_root):03d}_{slug}"


def work_item_path(project_root: Path, work_id: str, status: str, *, item_format: str | None = None) -> Path:
    if item_format not in {None, "markdown", "packet"}:
        raise ValueError(f"item_format must be markdown or packet: {item_format!r}")
    lane = lane_root(project_root, status)
    if lane == work_items_root(project_root):
        return lane / work_id
    if status in INTAKE_MARKDOWN_STATES and item_format != "packet":
        return lane / f"{work_id}.md"
    return lane / work_id


def metadata_path_for(work_item_root: Path) -> Path | None:
    if work_item_root.is_file() and work_item_root.suffix == ".md":
        return work_item_root
    for filename in WORK_ITEM_METADATA_FILES:
        candidate = work_item_root / filename
        if candidate.is_file():
            return candidate
    return None


def load_yaml_mapping(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    if path.suffix == ".md":
        text = path.read_text(encoding="utf-8", errors="replace")
        if text.startswith("---\n"):
            _, front_matter, _ = text.split("---", 2)
            data = yaml.safe_load(front_matter) or {}
            return data if isinstance(data, dict) else {}
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def lifecycle_status(metadata: dict[str, Any]) -> str:
    lifecycle = metadata.get("lifecycle") if isinstance(metadata.get("lifecycle"), dict) else {}
    status = str(lifecycle.get("state") or metadata.get("state") or metadata.get("status") or "captured")
    return status if status in WORK_LIFECYCLE_STATES else status


def promotion_target_from_metadata(metadata: dict[str, Any]) -> str:
    external_tracker = metadata.get("external_tracker") if isinstance(metadata.get("external_tracker"), dict) else {}
    tracker_type = str(external_tracker.get("type") or "")
    if tracker_type and tracker_type != "none":
        return tracker_type
    spec_destination = metadata.get("spec_destination") if isinstance(metadata.get("spec_destination"), dict) else {}
    return str(spec_destination.get("type") or "local")


def state_file_paths(work_item_root: Path, state: str) -> list[Path]:
    if work_item_root.is_file():
        return [work_item_root]
    names = STATE_REQUIRED_FILES.get(state, STATE_REQUIRED_FILES["captured"])
    paths = []
    for name in names:
        path = work_item_root / name
        if not path.is_file():
            for alias in LEGACY_FILE_ALIASES.get(name, ()):
                alias_path = work_item_root / alias
                if alias_path.is_file():
                    path = alias_path
                    break
        paths.append(path)
    return paths


def work_item_metadata(
    *,
    domain: str,
    project: str,
    work_id: str,
    title: str,
    status: str,
    summary: str,
    item_format: str | None = None,
) -> str:
    resolved_format = (
        "folder"
        if item_format == "packet"
        else item_format or ("markdown" if status in INTAKE_MARKDOWN_STATES else "folder")
    )
    payload = {
        "id": work_id,
        "title": title,
        "domain": domain,
        "project": project,
        "status": status,
        "lane": lane_for_status(status),
        "format": resolved_format,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "summary": summary,
        "lifecycle": {
            "state": status,
            "state_vocabulary": list(WORK_LIFECYCLE_STATES),
            "required_files": list(STATE_REQUIRED_FILES[status]),
            "conversation_logs": "logs/conversations",
        },
        "spec_destination": {
            "type": "local",
            "path": "work-items",
        },
        "external_tracker": {
            "type": "none",
        },
    }
    return yaml.safe_dump(payload, sort_keys=False)


def intake_spec_markdown(*, domain: str, project: str, work_id: str, title: str, status: str, summary: str) -> str:
    metadata = {
        "id": work_id,
        "title": title,
        "domain": domain,
        "project": project,
        "status": status,
        "lane": lane_for_status(status),
        "format": "markdown",
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "summary": summary,
        "lifecycle": {
            "state": status,
            "state_vocabulary": list(WORK_LIFECYCLE_STATES),
            "lane_vocabulary": list(WORK_ITEM_LANES),
            "required_files": ["this file"],
            "conversation_logs": f"{work_id}.logs/conversations",
        },
        "spec_destination": {"type": "local", "path": "work-items"},
        "external_tracker": {"type": "none"},
    }
    return f"""---
{yaml.safe_dump(metadata, sort_keys=False).strip()}
---

# Spec: {title}

## Captured

| Field | Value |
| --- | --- |
| Date | {today_iso()} |
| Status | `{status}` |
| Work Item | `{work_id}` |
| Lane | `{lane_for_status(status)}` |

## Raw Capture

{summary}

## Initial Notes

-
"""


def work_item_file_content(filename: str, *, title: str, summary: str, status: str, work_id: str) -> str:
    if filename == "IDEA.md":
        return f"""# Idea: {title}

## Captured

| Field | Value |
| --- | --- |
| Date | {today_iso()} |
| Status | `{status}` |
| Work Item | `{work_id}` |

## Raw Idea

{summary}

## Initial Notes

-
"""
    if filename == "SPEC.md":
        return f"""# Spec: {title}

## Raw Capture

{summary}

## Problem

- TBD.

## Outcome

- TBD.

## Scope

- TBD.

## Acceptance Criteria

- TBD.
"""
    if filename == "PLAN.md":
        return f"""# Plan: {title}

## Architecture Prerequisite

- [ ] Before code or state changes, read the routed architecture guide and its canonical ports-and-adapters reference.
- [ ] Record the exact architecture sources read in a work-item receipt.

## Approach

- TBD.

## Implementation Steps

- [ ] Define the first build step.

## Validation

- [ ] Define validation evidence before marking the work finished.
"""
    if filename == "INVESTIGATION.md":
        return f"""# Investigation: {title}

## Findings

- TBD.

## Source Evidence

| Source | Finding | Link |
| --- | --- | --- |
"""
    if filename == "JUDGMENT.md":
        return f"""# Judgment: {title}

## Routing Decision

- Status: `{status}`
- Destination: local project work item

## Promotion Decision

- External tracker: none
- Rationale: TBD.
"""
    if filename == "HOLDOUT_QA.md":
        return f"""# Holdout QA: {title}

## Risk Areas

- TBD.

## Checks

- [ ] Run the project validation plan.
"""
    if filename == "HOLDOUT_QA_RESULTS.md":
        return f"""# Holdout QA Results: {title}

## Result

- Pending.

## Evidence

| Check | Result | Evidence |
| --- | --- | --- |
"""
    if filename == "WORKLOG.md":
        return f"""# Worklog: {title}

## {today_iso()}

- Created lifecycle work item `{work_id}` with status `{status}`.
"""
    if filename == "SUMMARY.md":
        return f"""# Summary: {title}

## Current Summary

- Pending implementation and validation.

## Final State

- Pending.
"""
    if filename == "NEXT.md":
        return f"""# Next: {title}

## Next Action

- Triage this work item and fill the next required lifecycle file.

## Blockers

- None recorded.
"""
    if filename == "MEMORY.md":
        return f"""# Memory: {title}

Record durable, non-secret project learnings promoted from this work item.
"""
    raise ValueError(f"unknown work item file: {filename}")


def repaired_work_item_metadata(record: WorkItemRecord, *, status: str, summary: str) -> str:
    payload = dict(record.metadata)
    payload.setdefault("id", record.slug or record.path.name)
    payload.setdefault("title", record.title)
    payload.setdefault("summary", summary)
    payload.setdefault("created_at", payload.get("created") or now_iso())
    payload["updated_at"] = now_iso()
    payload["status"] = status
    payload["state"] = status
    payload["lane"] = lane_for_status(status)
    payload["format"] = "folder"
    lifecycle = payload.get("lifecycle") if isinstance(payload.get("lifecycle"), dict) else {}
    lifecycle.update(
        {
            "state": status,
            "state_vocabulary": list(WORK_LIFECYCLE_STATES),
            "required_files": list(STATE_REQUIRED_FILES.get(status, STATE_REQUIRED_FILES["captured"])),
            "conversation_logs": "logs/conversations",
        }
    )
    payload["lifecycle"] = lifecycle
    payload.setdefault("spec_destination", {"type": "local", "path": "work-items"})
    payload.setdefault("external_tracker", {"type": "none"})
    return yaml.safe_dump(payload, sort_keys=False)


def ensure_work_item_dirs(work_item_root: Path, result: ScaffoldResult) -> None:
    for directory in WORK_ITEM_DIRECTORIES:
        path = work_item_root / directory
        if path.is_dir():
            result.skipped.append(path)
            continue
        path.mkdir(parents=True, exist_ok=True)
        result.created.append(path)


def create_project_work_item(
    root: str | Path,
    domain: str,
    project: str,
    *,
    title: str,
    summary: str,
    status: str = "captured",
    work_id: str | None = None,
    item_format: str | None = None,
    naming_time: datetime | date | str | None = None,
) -> ScaffoldResult:
    if status not in WORK_LIFECYCLE_STATES:
        raise ValueError(f"status must be one of {', '.join(WORK_LIFECYCLE_STATES)}: {status!r}")
    if item_format not in {None, "markdown", "packet"}:
        raise ValueError(f"format must be one of markdown, packet: {item_format!r}")
    os_root = expand_path(root)
    domain = normalize_domain(domain)
    project = validate_name(project, "project")
    domain_root = domain_path(os_root, domain)
    project_root = domain_root / "02-projects" / project
    if not project_root.is_dir():
        raise ValueError(f"project not found: {domain}/{project}")

    work_id = indexed_work_id(project_root, work_id or title)
    work_id = dated_name(
        work_id,
        when=naming_time or datetime.now(timezone.utc),
        policy=load_artifact_naming_policy(os_root),
        scope="work_items",
    )
    work_root = work_items_root(project_root)
    work_item_root = work_item_path(project_root, work_id, status, item_format=item_format)
    result = ScaffoldResult()
    canonical = lane_root(project_root, status) == work_root
    directories = (
        (work_root, work_root / ARCHIVE_DIRECTORY)
        if canonical
        else (work_root, *(work_root / lane for lane in WORK_ITEM_LANES))
    )
    for directory in directories:
        if directory.is_dir():
            result.skipped.append(directory)
        else:
            directory.mkdir(parents=True, exist_ok=True)
            result.created.append(directory)
    if not canonical and status in INTAKE_MARKDOWN_STATES and item_format != "packet":
        write_file_once(
            work_item_root,
            intake_spec_markdown(
                domain=domain,
                project=project,
                work_id=work_id,
                title=title,
                status=status,
                summary=summary,
            ),
            result,
        )
    else:
        if work_item_root.is_dir():
            result.skipped.append(work_item_root)
        else:
            work_item_root.mkdir(parents=True, exist_ok=True)
            result.created.append(work_item_root)
        ensure_work_item_dirs(work_item_root, result)
        write_file_once(
            work_item_root / "work.yml",
            work_item_metadata(
                domain=domain,
                project=project,
                work_id=work_id,
                title=title,
                status=status,
                summary=summary,
                item_format="packet",
            ),
            result,
        )
        for filename in WORK_ITEM_FILES:
            write_file_once(
                work_item_root / filename,
                work_item_file_content(filename, title=title, summary=summary, status=status, work_id=work_id),
                result,
            )

    relative_work_item = work_item_root.relative_to(project_root)
    append_once(
        project_root / "ideas" / "raw-ideas.md",
        f"| {today_iso()} | plan capture | {title} | `{relative_work_item}` |\n",
        result,
    )
    append_once(
        project_root / "status.md",
        f"\n## Work Item: {title}\n\n- Status: `{status}`\n- Path: `{relative_work_item}`\n- Next: `{relative_work_item}`\n",
        result,
    )
    append_once(
        domain_root / "00-control-plane" / "active-work.md",
        f"| `{project}/{work_id}` | `{status}` | OS Owner | Review work item. | `02-projects/{project}/{relative_work_item}` |\n",
        result,
    )
    append_control_signal(
        domain_root,
        "Project Activity",
        f"`{project}` {status}: {title}",
        status,
        f"`02-projects/{project}/{relative_work_item}`",
        "Lifecycle work item created or repaired.",
        result,
    )
    append_domain_memory(
        domain_root,
        f"Created lifecycle work item `{project}/{work_id}` with status `{status}`; local evidence is in `02-projects/{project}/{relative_work_item}`.",
        result,
    )
    return result


def local_work_item_candidates(work_items_root: Path) -> list[Path]:
    if not work_items_root.is_dir():
        return []
    candidates: list[Path] = []
    for child in sorted(work_items_root.iterdir()):
        if child.name == ARCHIVE_DIRECTORY and child.is_dir():
            candidates.extend(
                sorted(
                    item
                    for item in child.iterdir()
                    if (item.is_dir() or item.suffix == ".md")
                    and not item.name.endswith(".artifacts")
                )
            )
        elif child.name in WORK_ITEM_LANES and child.is_dir():
            candidates.extend(
                sorted(
                    item
                    for item in child.iterdir()
                    if (item.is_dir() or item.suffix == ".md")
                    and not item.name.endswith(".artifacts")
                )
            )
        elif child.is_dir() and child.name not in {".logs", "logs"}:
            if child.name.endswith(".artifacts"):
                continue
            candidates.append(child)
        elif child.suffix == ".md":
            candidates.append(child)
    return candidates


def local_project_work_items(project_root: Path) -> list[WorkItemRecord]:
    records: list[WorkItemRecord] = []
    work_items_root = project_root / "work-items"
    if not work_items_root.is_dir():
        return records
    for candidate in local_work_item_candidates(work_items_root):
        metadata_path = metadata_path_for(candidate)
        if not metadata_path:
            continue
        try:
            metadata = load_yaml_mapping(metadata_path)
        except yaml.YAMLError as exc:
            # Agent-authored metadata can be malformed; validation must report
            # the broken work item, not crash every caller that walks the tree.
            metadata = {"metadata_error": f"invalid yaml: {exc}"[:300]}
        status = lifecycle_status(metadata)
        records.append(
            WorkItemRecord(
                path=candidate,
                metadata_path=metadata_path,
                status=status,
                title=str(metadata.get("title") or candidate.name),
                slug=str(metadata.get("slug") or metadata.get("id") or candidate.stem),
                source="project_work_item",
                metadata=metadata,
            )
        )
    return records


def project_source_roots(project_root: Path) -> list[Path]:
    roots: list[Path] = []
    src = project_root / "src"
    if src.exists():
        try:
            roots.append(src.resolve())
        except OSError:
            pass
    project_config = load_yaml_mapping(project_root / "project.yml")
    sources = project_config.get("sources") if isinstance(project_config.get("sources"), dict) else {}
    repo = str(sources.get("repo") or "")
    if repo and "://" not in repo and not repo.startswith("git@"):
        repo_path = Path(repo).expanduser()
        if repo_path.exists():
            roots.append(repo_path.resolve())
    worktree_index = load_yaml_mapping(project_root / "worktrees" / "index.yml")
    for entry in worktree_index.get("worktrees") or []:
        if not isinstance(entry, dict):
            continue
        path_value = str(entry.get("path") or "")
        if not path_value:
            continue
        path = Path(path_value).expanduser()
        if path.exists():
            roots.append(path.resolve())
    unique: list[Path] = []
    seen: set[str] = set()
    for path in roots:
        key = str(path)
        if key not in seen:
            seen.add(key)
            unique.append(path)
    return unique


def source_feature_work_items(project_root: Path) -> list[WorkItemRecord]:
    records: list[WorkItemRecord] = []
    for source_root in project_source_roots(project_root):
        for metadata_path in sorted((source_root / "features").glob("*/feature.yml")):
            work_item_root = metadata_path.parent
            metadata = load_yaml_mapping(metadata_path)
            status = lifecycle_status(metadata)
            records.append(
                WorkItemRecord(
                    path=work_item_root,
                    metadata_path=metadata_path,
                    status=status,
                    title=str(metadata.get("title") or work_item_root.name),
                    slug=str(metadata.get("slug") or metadata.get("id") or work_item_root.name),
                    source="source_feature",
                    metadata=metadata,
                )
            )
    return records


def project_work_item_records(project_root: Path) -> list[WorkItemRecord]:
    return local_project_work_items(project_root) + source_feature_work_items(project_root)


def normalized_labels(record: WorkItemRecord) -> set[str]:
    index_match = WORK_ITEM_INDEX_RE.match(record.path.stem)
    index = index_match.group("index") if index_match else ""
    labels = {
        record.path.name,
        record.path.stem,
        record.slug,
        record.title,
        str(record.metadata.get("id") or ""),
        str(record.metadata.get("prefix") or ""),
        str(record.metadata.get("ticket") or ""),
        index,
        f"idea {index}" if index else "",
        f"idea {int(index)}" if index else "",
    }
    normalized: set[str] = set()
    for label in labels:
        label = label.strip().lower()
        if not label:
            continue
        normalized.add(label)
        normalized.add(label.replace("_", "-"))
        normalized.add(label.replace("-", " "))
    return normalized


def record_matches_request(record: WorkItemRecord, request: str) -> bool:
    text = request.lower()
    for label in normalized_labels(record):
        if len(label) < 2:
            continue
        if label in text:
            return True
        label_tokens = {
            token
            for token in re.findall(r"[a-z0-9]+", label)
            if token not in WORK_ITEM_MATCH_STOPWORDS and (len(token) >= 3 or token.isdigit())
        }
        request_tokens = {
            token
            for token in re.findall(r"[a-z0-9]+", text)
            if token not in WORK_ITEM_MATCH_STOPWORDS and (len(token) >= 3 or token.isdigit())
        }
        overlap = label_tokens & request_tokens
        if len(overlap) >= 3 or (len(label_tokens) <= 3 and len(overlap) >= 2):
            return True
    return False


def record_from_cwd(project_root: Path, cwd: Path) -> WorkItemRecord | None:
    try:
        relative = cwd.resolve().relative_to(project_root.resolve())
    except ValueError:
        relative = None
    if relative and len(relative.parts) >= 2 and relative.parts[0] == "work-items":
        local_records = local_project_work_items(project_root)
        match = next(
            (
                record
                for record in local_records
                if record.path.is_dir()
                and (
                    record.path.name in relative.parts
                    or record.path.stem in relative.parts
                )
            ),
            None,
        )
        if match:
            return match

    for record in source_feature_work_items(project_root):
        try:
            cwd.resolve().relative_to(record.path.resolve())
        except ValueError:
            continue
        return record
    return None


def select_project_work_item(
    project_root: Path,
    *,
    request: str | None = None,
    cwd: Path | None = None,
    work_item: str | None = None,
) -> WorkItemRecord | None:
    if cwd:
        from_cwd = record_from_cwd(project_root, cwd)
        if from_cwd:
            return from_cwd

    records = project_work_item_records(project_root)
    if work_item:
        requested_label = work_item.strip().lower()
        for record in records:
            if requested_label in normalized_labels(record):
                return record
        raise ValueError(f"work item not found: {work_item}")

    if request:
        matches = [record for record in records if record_matches_request(record, request)]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            exact = [record for record in matches if record.path.name.lower() in request.lower()]
            if len(exact) == 1:
                return exact[0]
            raise ValueError("routing confidence is low: request matches multiple work items")

    active = [record for record in records if record.status in ACTIVE_WORK_ITEM_STATES]
    if len(active) == 1:
        return active[0]
    if not active and len(records) == 1:
        return records[0]
    return None


def repair_project_work_item(
    root: str | Path,
    domain: str,
    project: str,
    *,
    work_item: str | None = None,
    all_items: bool = False,
) -> ScaffoldResult:
    if bool(work_item) == bool(all_items):
        raise ValueError("provide exactly one of work_item or all_items=True")
    os_root = expand_path(root)
    domain = normalize_domain(domain)
    project = validate_name(project, "project")
    project_root = domain_path(os_root, domain) / "02-projects" / project
    if not project_root.is_dir():
        raise ValueError(f"project not found: {domain}/{project}")

    records = local_project_work_items(project_root)
    if work_item:
        target = select_project_work_item(project_root, work_item=work_item)
        if target is None or target.source != "project_work_item":
            raise ValueError(f"project work item not found: {work_item}")
        records = [target]
    else:
        records = [record for record in records if record.source == "project_work_item"]

    result = ScaffoldResult()
    for record in records:
        if record.path.is_file():
            result.skipped.append(record.path)
            continue
        status = record.status if record.status in WORK_LIFECYCLE_STATES else "captured"
        work_id = str(record.metadata.get("id") or record.slug or record.path.name)
        title = record.title
        summary = str(
            record.metadata.get("summary")
            or record.metadata.get("description")
            or f"Recovered lifecycle scaffold for {title}."
        )
        ensure_work_item_dirs(record.path, result)
        write_file_once(
            record.path / "work.yml",
            repaired_work_item_metadata(record, status=status, summary=summary),
            result,
        )
        for filename in WORK_ITEM_FILES:
            write_file_once(
                record.path / filename,
                work_item_file_content(filename, title=title, summary=summary, status=status, work_id=work_id),
                result,
            )
        append_once(
            record.path / "WORKLOG.md",
            f"\n## {today_iso()}\n\n- Repaired lifecycle packet scaffold for status `{status}` without overwriting existing artifacts.\n",
            result,
        )
    return result


def parse_timestamp(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value)
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def is_stale_building(record: WorkItemRecord, *, now: datetime | None = None, stale_days: int = 7) -> bool:
    if record.status != "building":
        return False
    now = now or datetime.now(timezone.utc)
    timestamp = parse_timestamp(record.metadata.get("updated_at") or record.metadata.get("created_at"))
    if timestamp is None:
        return True
    return (now - timestamp).days >= stale_days


def has_documentation_evidence(record: WorkItemRecord) -> bool:
    if record.path.is_file():
        return False
    memory = record.path / "MEMORY.md"
    summary = record.path / "SUMMARY.md"
    return memory.is_file() and summary.is_file() and "Pending." not in summary.read_text(encoding="utf-8")


def contains_token_shaped_value(text: str) -> bool:
    return bool(TOKEN_SHAPED_VALUE_RE.search(text))


def redact_text(text: str) -> str:
    return TOKEN_SHAPED_VALUE_RE.sub("[REDACTED]", text)


def conversation_log_files(work_item_root: Path) -> list[Path]:
    if work_item_root.is_file():
        logs_root = work_item_root.parent / f"{work_item_root.stem}.logs" / "conversations"
    else:
        logs_root = work_item_root / "logs" / "conversations"
    if not logs_root.is_dir():
        return []
    return [path for path in sorted(logs_root.rglob("*")) if path.is_file()]


def project_domain(project_root: Path) -> str:
    if (
        project_root.parent.name == "02-projects"
        and project_root.parent.parent.name == "shared_factory"
        and project_root.parent.parent.parent.name == "harness"
    ):
        return "shared_factory"
    if project_root.parent.name == "02-projects":
        return project_root.parent.parent.name
    if project_root.parent.name == "projects" and project_root.parent.parent.parent.name == "domains":
        return project_root.parent.parent.name
    metadata = load_yaml_mapping(project_root / "project.yml")
    return str(metadata.get("domain") or project_root.parent.parent.name)


def current_lane(record: WorkItemRecord) -> str | None:
    try:
        parts = record.path.relative_to(record.path.parents[2]).parts
    except ValueError:
        return None
    if len(parts) >= 2 and parts[0] == "work-items" and parts[1] in WORK_ITEM_LANES:
        return parts[1]
    path_parts = record.path.parts
    for index, part in enumerate(path_parts):
        if part == "work-items" and index + 1 < len(path_parts) and path_parts[index + 1] in WORK_ITEM_LANES:
            return path_parts[index + 1]
        if part == "work-items" and index + 1 < len(path_parts) and path_parts[index + 1] == ARCHIVE_DIRECTORY:
            return ARCHIVE_DIRECTORY
        if part == "work-items" and index + 1 < len(path_parts):
            return "work-items"
    return None


def is_lingering_terminal_record(record: WorkItemRecord) -> bool:
    lane = current_lane(record)
    return (
        record.source == "project_work_item"
        and record.status in TERMINAL_WORK_ITEM_STATES
        and lane not in {"work-items", ARCHIVE_DIRECTORY, lane_for_status(record.status)}
    )


def file_has_substantive_content(path: Path, *, empty_markers: tuple[str, ...] = ("pending", "tbd")) -> bool:
    if not path.is_file():
        return False
    text = path.read_text(encoding="utf-8", errors="ignore").strip()
    if not text:
        return False
    body_lines = [
        line.strip().lower().strip("-* ")
        for line in text.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    body = "\n".join(body_lines).strip()
    if not body:
        return False
    return not any(marker in body for marker in empty_markers)


def closeout_artifact_paths(work_item_root: Path) -> list[Path]:
    if work_item_root.is_file():
        artifact_root = work_item_root.parent / f"{work_item_root.stem}.artifacts" / "thread-closeouts"
    else:
        artifact_root = work_item_root / "artifacts" / "thread-closeouts"
    if not artifact_root.is_dir():
        return []
    return [path for path in sorted(artifact_root.rglob("*")) if path.is_file() and path.name in {"closeout.md", "thread-closeout.yml", "thread.yml"}]


def latest_file_mtime(paths: list[Path]) -> datetime | None:
    latest: float | None = None
    for path in paths:
        try:
            mtime = path.stat().st_mtime
        except OSError:
            continue
        if latest is None or mtime > latest:
            latest = mtime
    if latest is None:
        return None
    return datetime.fromtimestamp(latest, tz=timezone.utc)


def conversation_activity_files_for_inference(work_item_root: Path) -> list[Path]:
    if work_item_root.is_file():
        roots = [work_item_root.parent / f"{work_item_root.stem}.logs" / "conversations"]
    else:
        roots = [work_item_root / "logs" / "conversations"]
    files: list[Path] = []
    for root in roots:
        if root.is_file():
            files.append(root)
        elif root.is_dir():
            files.extend(path for path in root.rglob("*") if path.is_file())
    return files


def next_action_clear(work_item_root: Path) -> bool:
    path = work_item_root if work_item_root.is_file() else work_item_root / "NEXT.md"
    if not path.is_file():
        return False
    text = path.read_text(encoding="utf-8", errors="ignore").lower()
    clear_markers = (
        "next action: none",
        "next action\n\nnone",
        "- next action: none",
        "- none",
        "none recorded",
        "no next action",
    )
    if any(marker in text for marker in clear_markers):
        return True
    unresolved_markers = ("implement ", "continue ", "review ", "fix ", "blocked", "pending", "tbd")
    return not any(marker in text for marker in unresolved_markers)


def work_item_pr_watch_terminal(work_item_root: Path) -> tuple[bool, list[str]]:
    artifacts_root = work_item_root.parent / f"{work_item_root.stem}.artifacts" if work_item_root.is_file() else work_item_root / "artifacts"
    evidence: list[str] = []
    if not artifacts_root.is_dir():
        return False, evidence
    for path in sorted(artifacts_root.rglob("pr-*-watch-state.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        text = yaml.safe_dump(payload, sort_keys=True).lower()
        if "merged" in text or "success" in text or "passed" in text:
            evidence.append(str(path))
    return bool(evidence), evidence


def worktree_entries_for_project(project_root: Path) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for path in (project_root / "config" / "worktrees.yml", project_root / "worktrees" / "index.yml"):
        payload = load_yaml_mapping(path)
        raw = payload.get("worktrees")
        if isinstance(raw, dict):
            candidate = raw.get("registered") or raw.get("worktrees") or []
        else:
            candidate = raw or payload.get("registered") or []
        if not isinstance(candidate, list):
            continue
        for entry in candidate:
            if isinstance(entry, dict):
                with_source = dict(entry)
                with_source.setdefault("_source", str(path))
                entries.append(with_source)
    return entries


def worktree_entries_for_record(project_root: Path, record: WorkItemRecord) -> list[dict[str, Any]]:
    labels = {label for label in normalized_labels(record) if label and len(label) >= 3}
    matches: list[dict[str, Any]] = []
    for entry in worktree_entries_for_project(project_root):
        fields = [
            entry.get("id"),
            entry.get("name"),
            entry.get("work_item"),
            entry.get("work_item_id"),
            entry.get("feature"),
            entry.get("ticket"),
            entry.get("branch"),
            entry.get("path"),
            entry.get("link"),
        ]
        field_text = " ".join(str(value or "").lower().replace("-", "_") for value in fields)
        if any(label.replace("-", "_").replace(" ", "_") in field_text for label in labels):
            matches.append(entry)
    return matches


def infer_completion_decision(
    project_root: Path,
    record: WorkItemRecord,
    *,
    older_than_days: int,
    include_blocked: bool = False,
    now: datetime | None = None,
) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=older_than_days)
    record_domain = str(record.metadata.get("domain") or project_domain(project_root))
    record_project = str(record.metadata.get("project") or project_root.name)
    evidence_paths: list[str] = []
    reasons: list[str] = []
    missing: list[str] = []

    terminal_reason = worktree_cleanup_reason(record.metadata)
    terminal_sources: list[str] = []
    if terminal_reason:
        terminal_sources.append(f"work_item:{terminal_reason}")
    local_terminal = record.status in TERMINAL_WORK_ITEM_STATES
    if local_terminal:
        terminal_sources.append(f"work_item_status:{record.status}")
    for entry in worktree_entries_for_record(project_root, record):
        reason = worktree_cleanup_reason(entry)
        if reason:
            terminal_sources.append(f"worktree:{reason}")
            evidence_paths.append(str(entry.get("_source") or "worktree registry"))
    pr_watch_terminal, pr_watch_paths = work_item_pr_watch_terminal(record.path)
    if pr_watch_terminal:
        terminal_sources.append("pr_watch:terminal")
        evidence_paths.extend(pr_watch_paths)

    closeout_paths = closeout_artifact_paths(record.path)
    evidence_paths.extend(str(path) for path in closeout_paths)
    has_summary = file_has_substantive_content(record.path / "SUMMARY.md") if record.path.is_dir() else False
    has_holdout = file_has_substantive_content(record.path / "HOLDOUT_QA_RESULTS.md") if record.path.is_dir() else False
    has_completion_artifact = bool(closeout_paths) or has_summary or has_holdout
    has_closeout = bool(closeout_paths)
    clear_next = next_action_clear(record.path)
    latest_activity = latest_file_mtime(conversation_activity_files_for_inference(record.path))
    recent_activity = bool(latest_activity and latest_activity > cutoff)
    recent_activity_blocks = recent_activity and not local_terminal
    blocked_status = record.status == "blocked"

    if terminal_sources:
        reasons.extend(terminal_sources)
    else:
        missing.append("terminal evidence")
    if has_summary:
        reasons.append("summary present")
        evidence_paths.append(str(record.path / "SUMMARY.md"))
    if has_holdout:
        reasons.append("holdout QA results present")
        evidence_paths.append(str(record.path / "HOLDOUT_QA_RESULTS.md"))
    if has_closeout:
        reasons.append("thread closeout present")
    if not has_completion_artifact:
        missing.append("completion artifact")
    if not clear_next:
        missing.append("clear next action")
    if recent_activity_blocks:
        missing.append("quiet window")
    if blocked_status and not include_blocked:
        missing.append("blocked status requires --include-blocked")

    if not terminal_sources:
        decision = "keep-active"
        confidence = "low"
        next_action = "Keep active until terminal PR/Jira/worktree evidence exists."
    elif recent_activity_blocks:
        decision = "keep-active"
        confidence = "medium"
        next_action = "Keep active until the quiet window passes."
    elif blocked_status and not include_blocked:
        decision = "manual-review"
        confidence = "medium"
        next_action = "Review blocked item before automatic completion."
    elif not has_completion_artifact:
        decision = "manual-review"
        confidence = "medium"
        next_action = "Add completion artifact or run thread-finalizer after review."
    elif not clear_next:
        decision = "manual-review"
        confidence = "medium"
        next_action = "Resolve NEXT.md before automatic completion."
    elif local_terminal:
        decision = "finish-ready"
        confidence = "high"
        next_action = "Move terminal local status to 03-complete."
    elif has_closeout:
        decision = "finish-ready"
        confidence = "high"
        next_action = "Mark finished and move to 03-complete."
    else:
        decision = "needs-thread-finalizer"
        confidence = "high"
        next_action = "Run thread-finalizer, then mark finished."

    return {
        "domain": record_domain,
        "project": record_project,
        "work_item": record.slug or record.path.name,
        "title": record.title,
        "current_status": record.status,
        "path": str(record.path),
        "decision": decision,
        "confidence": confidence,
        "evidence": {
            "terminal_sources": terminal_sources,
            "completion_artifacts": {
                "thread_closeout": has_closeout,
                "summary": has_summary,
                "holdout_qa_results": has_holdout,
            },
            "clear_next_action": clear_next,
            "last_activity": latest_activity.isoformat().replace("+00:00", "Z") if latest_activity else None,
            "recent_activity": recent_activity,
            "blocked_status": blocked_status,
        },
        "evidence_paths": sorted(set(evidence_paths)),
        "reasons": reasons,
        "missing": missing,
        "next_action": next_action,
    }


def infer_complete_work_items(
    root: str | Path,
    *,
    domain: str | None = None,
    project: str | None = None,
    older_than_days: int = 3,
    min_confidence: str = "high",
    include_blocked: bool = False,
    apply: bool = False,
) -> dict[str, Any]:
    if older_than_days < 1:
        raise ValueError("older-than-days must be at least 1")
    if min_confidence not in {"high", "medium", "low"}:
        raise ValueError("min-confidence must be high, medium, or low")
    os_root = expand_path(root)
    decisions: list[dict[str, Any]] = []
    applied: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for project_root in root_project_dirs(os_root, domain=domain, project=project):
        for record in local_project_work_items(project_root):
            if record.source != "project_work_item" or current_lane(record) not in {"work-items", "02-active"}:
                continue
            decision = infer_completion_decision(
                project_root,
                record,
                older_than_days=older_than_days,
                include_blocked=include_blocked,
            )
            decisions.append(decision)
            if not apply:
                continue
            if decision["decision"] not in {"finish-ready", "needs-thread-finalizer"}:
                skipped.append({"work_item": decision["work_item"], "reason": decision["decision"]})
                continue
            if decision["confidence"] != "high" and min_confidence == "high":
                skipped.append({"work_item": decision["work_item"], "reason": f"confidence:{decision['confidence']}"})
                continue
            closeout_artifact: str | None = None
            if decision["decision"] == "needs-thread-finalizer":
                from .thread_closeout import close_thread

                closeout = close_thread(
                    os_root,
                    mode="artifact-closeout",
                    thread_id=f"infer_complete_{record.slug or record.path.name}",
                    domain=decision["domain"],
                    project=decision["project"],
                    work_item=str(decision["work_item"]),
                    work_level="artifact",
                    summary=f"Completion inference finalized {record.title}.",
                    next_action="None",
                    skip_notion=True,
                    cwd=record.path,
                )
                closeout_artifact = str((Path(closeout["artifact_root"]) / "closeout.md")) if closeout.get("artifact_root") else None
            update_work_item_metadata(
                record,
                status="finished",
                lane=lane_for_status("finished"),
                metadata_path=record.metadata_path,
            )
            applied.append(
                {
                    "domain": decision["domain"],
                    "project": decision["project"],
                    "work_item": decision["work_item"],
                    "decision": decision["decision"],
                    "closeout_artifact": closeout_artifact,
                    "marked_status": "finished",
                }
            )
    finalize_result = finalize_lingering_work_items(os_root, domain=domain, project=project, apply=True) if apply else None
    return {
        "mode": "apply" if apply else "dry-run",
        "older_than_days": older_than_days,
        "min_confidence": min_confidence,
        "include_blocked": include_blocked,
        "decision_counts": {decision: sum(1 for row in decisions if row["decision"] == decision) for decision in COMPLETION_INFERENCE_DECISIONS},
        "decisions": decisions,
        "candidate_count": sum(1 for row in decisions if row["decision"] in {"finish-ready", "needs-thread-finalizer"}),
        "applied": applied,
        "skipped": skipped,
        "finalize_lingering": finalize_result,
        "active_container": finalize_result.get("active_container") if isinstance(finalize_result, dict) else None,
    }


def update_work_item_metadata(record: WorkItemRecord, *, status: str, lane: str, metadata_path: Path) -> None:
    payload = dict(record.metadata)
    payload["status"] = status
    payload["state"] = status
    payload["lane"] = lane
    payload["updated_at"] = now_iso()
    lifecycle = payload.get("lifecycle") if isinstance(payload.get("lifecycle"), dict) else {}
    lifecycle["state"] = status
    lifecycle["required_files"] = list(STATE_REQUIRED_FILES.get(status, STATE_REQUIRED_FILES["captured"]))
    payload["lifecycle"] = lifecycle
    metadata_path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def replace_markdown_table_row(
    path: Path,
    *,
    identifier: str,
    status: str,
    link: str,
    next_action: str,
) -> bool:
    if not path.is_file():
        return False
    lines = path.read_text(encoding="utf-8").splitlines()
    changed = False
    for index, line in enumerate(lines):
        if not line.startswith("|") or identifier not in line:
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) < 5 or cells[0] == "---":
            continue
        cells[1] = f"`{status}`"
        cells[3] = next_action
        cells[4] = f"`{link}`"
        lines[index] = "| " + " | ".join(cells) + " |"
        changed = True
    if changed:
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return changed


def finalize_lingering_work_items(
    root: str | Path,
    *,
    domain: str | None = None,
    project: str | None = None,
    apply: bool = False,
) -> dict[str, Any]:
    os_root = expand_path(root)
    candidates: list[dict[str, Any]] = []
    updated: list[str] = []
    skipped: list[dict[str, str]] = []
    for project_root in root_project_dirs(os_root, domain=domain, project=project):
        for record in local_project_work_items(project_root):
            if not is_lingering_terminal_record(record):
                continue
            target_lane = lane_for_status(record.status)
            target = work_items_root(project_root) / target_lane / record.path.name
            record_domain = str(record.metadata.get("domain") or project_domain(project_root))
            record_project = str(record.metadata.get("project") or project_root.name)
            relative_target = target.relative_to(project_root)
            entry = {
                "domain": record_domain,
                "project": record_project,
                "work_item": record.slug or record.path.name,
                "status": record.status,
                "from": str(record.path),
                "to": str(target),
            }
            candidates.append(entry)
            if not apply:
                continue
            if target.exists() and target.resolve() != record.path.resolve():
                skipped.append({"path": str(record.path), "reason": f"target exists: {target}"})
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            record.path.rename(target)
            metadata_path = target / record.metadata_path.name if record.metadata_path.parent == record.path else target / "work.yml"
            update_work_item_metadata(record, status=record.status, lane=target_lane, metadata_path=metadata_path)
            worklog = target / "WORKLOG.md"
            if worklog.is_file():
                append_once(
                    worklog,
                    f"\n## {today_iso()}\n\n- Finalized lingering active-lane packet: moved from `{record.path.relative_to(project_root)}` to `{relative_target}` because status is `{record.status}`.\n",
                    ScaffoldResult(),
                )
            active_work = project_root.parent.parent / "00-control-plane" / "active-work.md"
            identifier = f"{record_project}/{record.slug or record.path.name}"
            replace_markdown_table_row(
                active_work,
                identifier=identifier,
                status=record.status,
                link=f"02-projects/{record_project}/{relative_target}",
                next_action="Review completion receipts.",
            )
            status_file = project_root / "status.md"
            if status_file.is_file():
                text = status_file.read_text(encoding="utf-8")
                new_text = text.replace(str(record.path.relative_to(project_root)), str(relative_target))
                if new_text != text:
                    status_file.write_text(new_text, encoding="utf-8")
            updated.append(str(target))
    sync_result = sync_active_container(os_root, domain=domain, project=project) if apply else None
    return {
        "mode": "apply" if apply else "dry-run",
        "candidate_count": len(candidates),
        "candidates": candidates,
        "updated": updated,
        "skipped": skipped,
        "active_container": sync_result,
    }


def active_container_root(root: Path) -> Path:
    return root / "00-control-plane" / "active"


def reset_managed_category(category_root: Path) -> None:
    category_root.mkdir(parents=True, exist_ok=True)
    for child in category_root.iterdir():
        if child.is_symlink() or child.is_file():
            child.unlink()


def safe_link_name(*parts: str) -> str:
    text = "__".join(part for part in parts if part)
    return re.sub(r"[^a-zA-Z0-9_.-]+", "_", text).strip("._-") or "item"


def create_link(link: Path, target: Path) -> None:
    if link.exists() or link.is_symlink():
        link.unlink()
    link.symlink_to(target.resolve(), target_is_directory=target.is_dir())


def timestamp_from_epoch(value: float) -> str:
    return datetime.fromtimestamp(value, timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def filesystem_created_at(path: Path) -> str:
    stat = path.stat()
    birth_time = getattr(stat, "st_birthtime", None)
    return timestamp_from_epoch(birth_time if birth_time is not None else stat.st_ctime)


def filesystem_modified_at(path: Path, *, recursive: bool = False) -> str:
    modified_at = path.stat().st_mtime
    if recursive and path.is_dir():
        for child in path.rglob("*"):
            try:
                modified_at = max(modified_at, child.stat().st_mtime)
            except FileNotFoundError:
                continue
    return timestamp_from_epoch(modified_at)


def record_created_at(record: WorkItemRecord) -> str:
    return str(record.metadata.get("created_at") or record.metadata.get("created") or filesystem_created_at(record.path))


def record_modified_at(record: WorkItemRecord) -> str:
    return filesystem_modified_at(record.path, recursive=True)


def active_index_timestamps(path: Path, *, recursive: bool = False) -> dict[str, str]:
    return {
        "created_at": filesystem_created_at(path),
        "last_modified_at": filesystem_modified_at(path, recursive=recursive),
    }


def normalized_status(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").lower()).strip("_")


def nested_value(data: dict[str, Any], path: tuple[str, ...]) -> Any:
    current: Any = data
    for part in path:
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def first_entry_value(entry: dict[str, Any], paths: tuple[tuple[str, ...], ...]) -> Any:
    for path in paths:
        value = nested_value(entry, path)
        if value not in (None, ""):
            return value
    return None


def worktree_jira_status(entry: dict[str, Any]) -> str:
    value = first_entry_value(
        entry,
        (
            ("jira_status",),
            ("ticket_status",),
            ("issue_status",),
            ("jira", "status"),
            ("jira", "state"),
            ("jira", "fields", "status", "name"),
        ),
    )
    return normalized_status(value)


def worktree_pr_state(entry: dict[str, Any]) -> str:
    value = first_entry_value(
        entry,
        (
            ("pr_status",),
            ("pull_request_status",),
            ("pr_state",),
            ("pull_request_state",),
            ("pr", "status"),
            ("pr", "state"),
            ("pull_request", "status"),
            ("pull_request", "state"),
            ("github", "pr", "status"),
            ("github", "pr", "state"),
        ),
    )
    return normalized_status(value)


def worktree_merge_verified(entry: dict[str, Any]) -> bool:
    """Return true only for explicit pull-request merge evidence."""
    if truthy_entry_value(
        entry,
        (
            ("pr_merged",),
            ("pull_request_merged",),
            ("merged",),
            ("pr", "merged"),
            ("pull_request", "merged"),
            ("github", "pr", "merged"),
        ),
    ):
        return True
    return worktree_pr_state(entry) == "merged"


def truthy_entry_value(entry: dict[str, Any], paths: tuple[tuple[str, ...], ...]) -> bool:
    value = first_entry_value(entry, paths)
    if isinstance(value, bool):
        return value
    return normalized_status(value) in {"true", "yes", "y", "1", "merged", "done"}


def worktree_cleanup_reason(entry: dict[str, Any]) -> str | None:
    jira_status = worktree_jira_status(entry)
    if jira_status in TERMINAL_JIRA_STATUSES:
        return f"jira_status:{jira_status}"
    if worktree_merge_verified(entry):
        return "pr:merged"
    pr_state = worktree_pr_state(entry)
    if pr_state == "merged":
        return "pr_state:merged"
    status = normalized_status(entry.get("status"))
    if status in TERMINAL_WORKTREE_STATUSES:
        return f"status:{status}"
    return None


def worktree_registry_payload(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]], str | None]:
    payload = load_yaml_mapping(path)
    raw = payload.get("worktrees")
    if isinstance(raw, dict):
        for key in ("registered", "worktrees"):
            if isinstance(raw.get(key), list):
                return payload, raw[key], key
        raw["registered"] = []
        return payload, raw["registered"], "registered"
    if isinstance(raw, list):
        return payload, raw, None
    if isinstance(payload, list):
        return {"worktrees": payload}, payload, None
    payload["worktrees"] = []
    return payload, payload["worktrees"], None


def write_worktree_registry(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def archive_worktree_entry(
    project_root: Path,
    entry: dict[str, Any],
    *,
    reason: str,
    source: Path,
    health_gate: Mapping[str, Any] | None = None,
    health_preflight_ref: str | None = None,
) -> dict[str, Any]:
    closed_path = project_root / "worktrees" / "closed.yml"
    payload = load_yaml_mapping(closed_path)
    payload.setdefault("project", project_root.name)
    closed = payload.setdefault("worktrees", [])
    if not isinstance(closed, list):
        closed = []
        payload["worktrees"] = closed
    archived = dict(entry)
    archived["status"] = "closed"
    archived["closed_at"] = now_iso()
    archived["cleanup_reason"] = reason
    archived["cleanup_source"] = str(source)
    if health_gate is not None:
        archived["terminal_revision"] = str(health_gate.get("terminal_revision") or "")
        archived["reviewed_revision"] = str(health_gate.get("subject_revision") or "")
        archived["health_preflight_ref"] = str(health_preflight_ref or "")
        archived["runtime_cleanup_verified"] = True
    key = (str(archived.get("id") or archived.get("name") or ""), str(archived.get("path") or ""))
    replaced = False
    for index, existing in enumerate(closed):
        if not isinstance(existing, dict):
            continue
        existing_key = (str(existing.get("id") or existing.get("name") or ""), str(existing.get("path") or ""))
        if existing_key == key:
            closed[index] = archived
            replaced = True
            break
    if not replaced:
        closed.append(archived)
    closed_path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return {"path": str(closed_path), "entry": archived}


def _read_json_object(path: Path, label: str) -> dict[str, Any]:
    if not path.is_file():
        raise ValueError(f"{label} not found: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{label} must be valid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object: {path}")
    return value


def _verified_packet_hash(packet: Path, descriptor: Mapping[str, Any], label: str) -> Path:
    raw = str(descriptor.get("ref") or "").strip()
    expected = str(descriptor.get("sha256") or "").strip().lower()
    relative = Path(raw)
    if not raw or relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"health preflight {label} must be packet-relative")
    path = (packet / relative).resolve()
    if packet.resolve() not in path.parents or not path.is_file():
        raise ValueError(f"health preflight {label} is missing: {raw}")
    if (
        len(expected) != 64
        or any(character not in "0123456789abcdef" for character in expected)
        or hashlib.sha256(path.read_bytes()).hexdigest() != expected
    ):
        raise ValueError(f"health preflight {label} hash does not match")
    return path


def _same_json_object(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    return json.dumps(left, sort_keys=True, separators=(",", ":")) == json.dumps(
        right, sort_keys=True, separators=(",", ":")
    )


def _task_receipt_payload(
    task: Mapping[str, Any],
    target_state: str,
    *,
    task_path: Path,
    packet: Path,
) -> dict[str, Any]:
    """Read the canonical task receipt, including a moved-packet fallback."""

    for row in reversed(task.get("receipts") or []):
        if not isinstance(row, Mapping) or row.get("state") != target_state:
            continue
        raw = str(row.get("ref") or "").strip()
        if not raw:
            continue
        candidate = Path(raw).expanduser()
        candidates = [candidate] if candidate.is_absolute() else [task_path.parent / candidate, packet / candidate]
        if candidate.is_absolute() and packet.name in candidate.parts:
            offset = candidate.parts.index(packet.name)
            candidates.append(packet.joinpath(*candidate.parts[offset + 1 :]))
        for receipt_path in candidates:
            try:
                resolved = receipt_path.resolve()
            except OSError:
                continue
            if not resolved.is_file():
                continue
            expected_hash = str(row.get("sha256") or "").strip().lower()
            if (
                len(expected_hash) != 64
                or hashlib.sha256(resolved.read_bytes()).hexdigest() != expected_hash
            ):
                raise ValueError(
                    f"typed {target_state} task receipt lacks its immutable sha256 binding"
                )
            payload = _read_json_object(resolved, f"typed {target_state} task receipt")
            if (
                payload.get("schema") == "development-stage-evidence/v1"
                and payload.get("state") == target_state
            ):
                return payload
    raise ValueError(f"delivery task lacks a readable typed {target_state} receipt")


def _validate_auto_dev_health_document(
    document: Mapping[str, Any],
    *,
    schema_name: str,
    context_path: Path,
    label: str,
    trusted_root: Path,
) -> None:
    """Validate a destructive Health input against installed or packaged schema."""

    candidates = (
        trusted_root / "harness" / "schemas" / schema_name,
        trusted_root / "schemas" / schema_name,
        Path(__file__).resolve().parent / "_resources" / "schemas" / schema_name,
        Path(__file__).resolve().parents[2] / "schemas" / schema_name,
    )
    schema_path = next((path for path in candidates if path.is_file()), None)
    if schema_path is None:
        raise ValueError(f"{label} strict schema is unavailable")
    schema = _read_json_object(schema_path, f"{label} strict schema")
    findings = sorted(
        Draft202012Validator(schema).iter_errors(dict(document)),
        key=lambda item: list(item.absolute_path),
    )
    if findings:
        first = findings[0]
        location = ".".join(str(part) for part in first.absolute_path) or "root"
        raise ValueError(
            f"{label} violates its strict schema at {location}: {first.message}"
        )


def _health_cleanup_gate(
    preflight_file: str | Path,
    runtime_receipt_file: str | Path,
    *,
    domain: str,
    project: str,
    entry: Mapping[str, Any],
    os_root: Path,
) -> tuple[dict[str, Any], dict[str, Any], Path]:
    preflight_path = Path(preflight_file).expanduser().resolve()
    preflight = _read_json_object(preflight_path, "Auto-Dev Health preflight")
    _validate_auto_dev_health_document(
        preflight,
        schema_name="auto-dev-health-preflight.schema.json",
        context_path=preflight_path,
        label="Auto-Dev Health preflight",
        trusted_root=os_root,
    )
    packet = Path(str(preflight.get("packet_path") or "")).expanduser().resolve()
    worktree = preflight.get("worktree") if isinstance(preflight.get("worktree"), Mapping) else {}
    runtime = preflight.get("runtime") if isinstance(preflight.get("runtime"), Mapping) else {}
    entry_path = Path(str(entry.get("path") or "")).expanduser().resolve()
    gate_path = Path(str(worktree.get("path") or "")).expanduser().resolve()
    if not (
        preflight.get("schema") == "auto-dev-health-preflight/v1"
        and preflight.get("mode") == "apply"
        and preflight.get("safe_to_cleanup") is True
        and preflight.get("residual_holds") == []
        and preflight.get("domain") == domain
        and preflight.get("project") == project
        and str(preflight.get("work_item_id") or "").strip()
        and str(preflight.get("canonical_work_id") or "").strip()
        and str(preflight.get("subject_revision") or "").strip()
        and preflight.get("source_head_sha") == preflight.get("subject_revision")
        and str(preflight.get("terminal_revision") or "").strip()
        and preflight.get("merge_sha") == preflight.get("terminal_revision")
        and gate_path == entry_path
        and str(worktree.get("identity") or "")
        in {
            str(entry.get("id") or ""),
            str(entry.get("name") or ""),
            str(entry.get("path") or ""),
            entry_path.name,
        }
    ):
        raise ValueError("Health preflight does not match the exact worktree cleanup target")
    if not packet.is_dir() or packet not in preflight_path.parents:
        raise ValueError("Health preflight must live inside its durable work-item packet")
    if (packet / "REOPEN.md").exists():
        raise ValueError("Health cleanup is blocked by the packet root REOPEN.md hold")
    task_state = Path(str(preflight.get("task_state_ref") or "")).expanduser().resolve()
    task_hash = str(preflight.get("task_state_sha256") or "").lower()
    if not task_state.is_file() or hashlib.sha256(task_state.read_bytes()).hexdigest() != task_hash:
        raise ValueError("Health preflight task-state hash no longer matches")
    task = _read_json_object(task_state, "Development Delivery task state")
    task_snapshot_descriptor = preflight.get("task_snapshot")
    if not isinstance(task_snapshot_descriptor, Mapping):
        raise ValueError("Health preflight lacks its immutable task snapshot")
    task_snapshot_path = _verified_packet_hash(
        packet, task_snapshot_descriptor, "task snapshot"
    )
    task_snapshot = _read_json_object(task_snapshot_path, "Health task snapshot")
    if not _same_json_object(task_snapshot, task):
        raise ValueError("Health task snapshot no longer matches the live delivery task")
    task_worktree = task.get("worktree") if isinstance(task.get("worktree"), Mapping) else {}
    task_runtime = task.get("runtime") if isinstance(task.get("runtime"), Mapping) else {}
    task_work_item = Path(str(task.get("work_item") or "")).expanduser().resolve()
    if not (
        task.get("state") == "delivery_complete"
        and task.get("domain") == domain
        and task.get("project") == project
        and task.get("canonical_work_id") == preflight.get("canonical_work_id")
        and task_work_item == packet
        and task.get("subject_revision") == preflight.get("subject_revision")
        and task.get("terminal_revision") == preflight.get("terminal_revision")
        and not task.get("failure")
        and str(task_worktree.get("name") or "") == str(worktree.get("identity") or "")
        and Path(str(task_worktree.get("path") or "")).expanduser().resolve() == gate_path
        and str(task_worktree.get("branch") or "") == str(worktree.get("branch") or "")
        and dict(task_runtime) == dict(runtime)
        and preflight.get("repository")
        == {
            "id": (
                task.get("repository", {}).get("id")
                if isinstance(task.get("repository"), Mapping)
                else None
            ),
            "base_branch": (
                str(task.get("repository", {}).get("base_branch") or "").strip()
                if isinstance(task.get("repository"), Mapping)
                else ""
            ),
        }
    ):
        raise ValueError("Health preflight does not match the canonical delivered task state")
    merge_descriptor = {
        "ref": preflight.get("merge_receipt_ref"),
        "sha256": preflight.get("merge_receipt_sha256"),
    }
    closeout_descriptor = {
        "ref": preflight.get("closeout_receipt_ref"),
        "sha256": preflight.get("closeout_receipt_sha256"),
    }
    merge_path = _verified_packet_hash(packet, merge_descriptor, "merge receipt")
    closeout_path = _verified_packet_hash(packet, closeout_descriptor, "Closeout receipt")
    merge_receipt = _read_json_object(merge_path, "Health merge receipt snapshot")
    closeout_receipt = _read_json_object(closeout_path, "Health Closeout receipt snapshot")
    canonical_merge = _task_receipt_payload(
        task, "merged", task_path=task_state, packet=packet
    )
    canonical_pr_open = _task_receipt_payload(
        task, "pr_open", task_path=task_state, packet=packet
    )
    canonical_ready = _task_receipt_payload(
        task, "ready_for_merge", task_path=task_state, packet=packet
    )
    canonical_closeout = _task_receipt_payload(
        task, "delivery_complete", task_path=task_state, packet=packet
    )
    merge_evidence = (
        merge_receipt.get("evidence")
        if isinstance(merge_receipt.get("evidence"), Mapping)
        else {}
    )
    closeout_evidence = (
        closeout_receipt.get("evidence")
        if isinstance(closeout_receipt.get("evidence"), Mapping)
        else {}
    )
    pr_open_evidence = (
        canonical_pr_open.get("evidence")
        if isinstance(canonical_pr_open.get("evidence"), Mapping)
        else {}
    )
    ready_evidence = (
        canonical_ready.get("evidence")
        if isinstance(canonical_ready.get("evidence"), Mapping)
        else {}
    )

    from .auto_dev_orchestration import (
        same_pull_request_authority,
        validate_pull_request_authority,
    )

    try:
        open_authority = validate_pull_request_authority(
            task, pr_open_evidence, "Health pr_open receipt"
        )
        ready_authority = validate_pull_request_authority(
            task, ready_evidence, "Health ready_for_merge receipt"
        )
        merge_authority = validate_pull_request_authority(
            task, merge_evidence, "Health merged receipt"
        )
    except ValueError as exc:
        raise ValueError(str(exc)) from exc
    if not (
        canonical_pr_open.get("status") in {"verified", "passed", "completed"}
        and pr_open_evidence.get("readback_verified") is True
        and canonical_ready.get("status") in {"verified", "passed", "completed"}
        and ready_evidence.get("checks_verified") is True
        and ready_evidence.get("reviews_verified") is True
        and ready_evidence.get("readback_verified") is True
        and ready_evidence.get("subject_revision") == preflight.get("subject_revision")
        and same_pull_request_authority(open_authority, ready_authority)
        and same_pull_request_authority(ready_authority, merge_authority)
    ):
        raise ValueError(
            "Health cleanup authority is not bound to one reviewed provider pull request"
        )
    if not (
        _same_json_object(merge_receipt, canonical_merge)
        and merge_receipt.get("schema") == "development-stage-evidence/v1"
        and merge_receipt.get("state") == "merged"
        and merge_receipt.get("status") == "completed"
        and merge_evidence.get("merge_sha") == preflight.get("terminal_revision")
        and merge_evidence.get("source_head_sha") == preflight.get("subject_revision")
        and str(merge_evidence.get("provider") or "").strip()
        and str(merge_evidence.get("pull_request") or "").strip()
        and merge_evidence.get("readback_verified") is True
    ):
        raise ValueError("Health merge snapshot is not the canonical typed merge authority")
    if not (
        _same_json_object(closeout_receipt, canonical_closeout)
        and closeout_receipt.get("schema") == "development-stage-evidence/v1"
        and closeout_receipt.get("state") == "delivery_complete"
        and closeout_receipt.get("status") in {"verified", "passed", "completed"}
        and closeout_evidence.get("closeout_verified") is True
    ):
        raise ValueError("Health Closeout snapshot is not the canonical typed Closeout receipt")

    resume_descriptor = preflight.get("resume_manifest")
    audit_descriptor = preflight.get("receipt_audit")
    if not isinstance(resume_descriptor, Mapping) or not isinstance(audit_descriptor, Mapping):
        raise ValueError("Health preflight lacks its resume manifest or receipt audit")
    _verified_packet_hash(packet, resume_descriptor, "resume_manifest")
    audit_path = _verified_packet_hash(packet, audit_descriptor, "receipt_audit")
    audit = _read_json_object(audit_path, "Health pre-cleanup receipt audit")
    audit_stages = audit.get("stages") if isinstance(audit.get("stages"), list) else []
    from .auto_dev_orchestration import (
        configured_auto_dev_workflow_stages,
        read_auto_dev_state,
        _validate_health_stage_source,
        validate_auto_dev_packet_manifest,
    )

    projected = read_auto_dev_state(packet / "autodev.json")
    expected_stages = configured_auto_dev_workflow_stages(
        projected, include_health=False
    )
    if not (
        audit.get("schema") == "auto-dev-health-receipt-audit/v1"
        and audit.get("work_item_id") == preflight.get("work_item_id")
        and audit.get("canonical_work_id") == preflight.get("canonical_work_id")
        and audit.get("missing") == []
        and audit.get("resume_ready") is True
        and audit.get("terminal_authority") == merge_descriptor
        and audit.get("closeout") == closeout_descriptor
        and [row.get("stage") for row in audit_stages if isinstance(row, Mapping)]
        == expected_stages
        and len(audit_stages) == len(expected_stages)
    ):
        raise ValueError("Health pre-cleanup audit is incomplete or belongs to another item")
    for row in audit_stages:
        if not isinstance(row, Mapping) or row.get("status") not in {"completed", "not_required"}:
            raise ValueError("Health pre-cleanup audit contains a non-terminal stage")
        stage_path = _verified_packet_hash(packet, row, f"{row.get('stage')} stage receipt")
        try:
            _validate_health_stage_source(
                packet,
                str(row.get("stage") or ""),
                str(row.get("status") or ""),
                stage_path,
            )
        except ValueError as exc:
            raise ValueError(str(exc)) from exc
    try:
        validate_auto_dev_packet_manifest(
            preflight,
            packet,
            verify_live_files=True,
        )
    except ValueError as exc:
        raise ValueError(str(exc)) from exc

    runtime_path = Path(runtime_receipt_file).expanduser().resolve()
    runtime_receipt = _read_json_object(runtime_path, "Auto-Dev runtime cleanup receipt")
    _validate_auto_dev_health_document(
        runtime_receipt,
        schema_name="auto-dev-runtime-cleanup.schema.json",
        context_path=runtime_path,
        label="Auto-Dev runtime cleanup receipt",
        trusted_root=os_root,
    )
    preflight_hash = hashlib.sha256(preflight_path.read_bytes()).hexdigest()
    try:
        runtime_path.relative_to(packet)
    except ValueError as exc:
        raise ValueError("runtime cleanup receipt must live inside the durable packet") from exc
    teardown_operation = runtime_receipt.get("teardown")
    readback_operation = runtime_receipt.get("readback")
    if not isinstance(teardown_operation, Mapping) or not isinstance(readback_operation, Mapping):
        raise ValueError("runtime cleanup receipt lacks typed teardown/readback operations")
    _verified_packet_hash(packet, teardown_operation, "runtime teardown operation")
    _verified_packet_hash(packet, readback_operation, "runtime readback operation")
    expected_teardown = (
        str(runtime.get("teardown_command") or "")
        if runtime.get("ownership") == "managed"
        else "not_managed"
    )
    expected_readback = (
        str(runtime.get("readback_command") or "")
        if runtime.get("ownership") == "managed"
        else "not_managed"
    )
    if not (
        runtime_receipt.get("schema") == "auto-dev-runtime-cleanup/v1"
        and runtime_receipt.get("work_item_id") == preflight.get("work_item_id")
        and runtime_receipt.get("canonical_work_id") == preflight.get("canonical_work_id")
        and runtime_receipt.get("runtime_identity") == runtime.get("identity")
        and runtime_receipt.get("ownership") == runtime.get("ownership")
        and runtime_receipt.get("provider") == runtime.get("provider")
        and runtime_receipt.get("result") in {"removed", "absent", "not_managed"}
        and runtime_receipt.get("readback_verified") is True
        and runtime_receipt.get("preflight_sha256") == preflight_hash
        and teardown_operation.get("command") == expected_teardown
        and readback_operation.get("command") == expected_readback
        and str(runtime_receipt.get("verified_at") or "").strip()
    ):
        raise ValueError("runtime cleanup receipt does not match the Health preflight")
    if runtime.get("ownership") == "managed" and runtime_receipt.get("result") not in {
        "removed",
        "absent",
    }:
        raise ValueError("managed runtime cleanup must prove removed or absent")
    if (
        runtime.get("ownership") == "not_managed"
        and runtime_receipt.get("result") != "not_managed"
    ):
        raise ValueError("not-managed runtime cleanup must use not_managed")

    def parsed_time(value: Any, label: str) -> datetime:
        raw = str(value or "").strip()
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"{label} must be an ISO-8601 timestamp") from exc
        if parsed.tzinfo is None:
            raise ValueError(f"{label} must include a timezone")
        return parsed.astimezone(timezone.utc)

    prepared_at = parsed_time(preflight.get("prepared_at"), "Health preflight prepared_at")
    runtime_verified_at = parsed_time(
        runtime_receipt.get("verified_at"), "runtime cleanup verified_at"
    )
    current_time = datetime.now(timezone.utc)
    if runtime_verified_at < prepared_at:
        raise ValueError("runtime cleanup receipt predates the Health preflight")
    if runtime_verified_at > current_time + timedelta(minutes=2):
        raise ValueError("runtime cleanup receipt timestamp is in the future")
    if current_time - runtime_verified_at > timedelta(minutes=15):
        raise ValueError(
            "runtime cleanup readback is stale; recreate it immediately before cleanup"
        )
    if runtime.get("ownership") == "managed":
        command = str(runtime.get("readback_command") or "").strip()
        try:
            argv = shlex.split(command)
        except ValueError as exc:
            raise ValueError("registered runtime readback command is malformed") from exc
        if not argv:
            raise ValueError("registered runtime readback command is empty")
        repository = task.get("repository") if isinstance(task.get("repository"), Mapping) else {}
        working_directory = Path(str(repository.get("root") or "")).expanduser()
        if not working_directory.is_dir():
            raise ValueError(
                "canonical repository root is unavailable for exact runtime readback"
            )
        try:
            immediate = subprocess.run(
                argv,
                cwd=str(working_directory),
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ValueError("exact runtime readback could not be executed") from exc
        if immediate.returncode != 0:
            raise ValueError(
                "exact runtime readback did not prove the registered target absent"
            )

    if preflight.get("dirty_disposition") != "clean_only":
        raise ValueError("unsupported Health dirty_disposition")
    return preflight, runtime_receipt, preflight_path


def _protected_worktree_branch(branch: str, base_branch: str | None) -> bool:
    normalized = branch.strip().lower()
    protected = {"main", "master", "develop"}
    if base_branch:
        protected.add(base_branch.strip().lower())
    return normalized in protected or normalized.startswith(("release/", "hotfix/"))


def removable_git_checkout(path: Path) -> tuple[bool, str]:
    if not path.exists():
        return True, "missing"
    probe = subprocess.run(["git", "-C", str(path), "rev-parse", "--is-inside-work-tree"], capture_output=True, text=True, check=False)
    if probe.returncode != 0:
        return False, "not a git checkout"
    status = subprocess.run(
        ["git", "-C", str(path), "status", "--porcelain", "--untracked-files=all"],
        capture_output=True,
        text=True,
        check=False,
    )
    if status.returncode != 0:
        return False, (status.stderr or status.stdout or "git status failed").strip()
    if status.stdout.strip():
        return False, "git checkout has uncommitted changes"
    return True, "clean"


def remove_worktree_files(
    project_root: Path,
    entry: dict[str, Any],
    *,
    health_gate: Mapping[str, Any] | None = None,
) -> tuple[bool, str]:
    target = Path(str(entry.get("path") or "")).expanduser()
    if not target.exists():
        return True, "missing"
    try:
        target_resolved = target.resolve()
        managed_root = (project_root / "worktrees").resolve()
    except OSError as exc:
        return False, str(exc)
    if not target_resolved.is_relative_to(managed_root):
        return False, "target is outside project worktrees/"
    if (target_resolved / "REOPEN.md").exists():
        return False, "REOPEN.md present; ask before cleanup"
    if health_gate is None:
        return False, "physical removal requires a typed Auto-Dev Health preflight"
    gate_worktree = (
        health_gate.get("worktree")
        if isinstance(health_gate.get("worktree"), Mapping)
        else {}
    )
    expected_branch = str(gate_worktree.get("branch") or "").strip()
    branch_probe = subprocess.run(
        ["git", "-C", str(target_resolved), "branch", "--show-current"],
        capture_output=True,
        text=True,
        check=False,
    )
    actual_branch = branch_probe.stdout.strip() if branch_probe.returncode == 0 else ""
    gate_repository = (
        health_gate.get("repository")
        if isinstance(health_gate.get("repository"), Mapping)
        else {}
    )
    canonical_base = str(gate_repository.get("base_branch") or "").strip()
    entry_base = str(entry.get("base_branch") or "").strip()
    if not canonical_base:
        return False, "Health preflight lacks the canonical repository base branch"
    if entry_base and entry_base != canonical_base:
        return False, "registry base branch disagrees with the Health preflight"
    base_branch = canonical_base
    if not expected_branch or actual_branch != expected_branch:
        return False, "worktree branch does not match the Health preflight"
    expected_revision = str(health_gate.get("subject_revision") or "").strip()
    head_probe = subprocess.run(
        ["git", "-C", str(target_resolved), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    actual_revision = head_probe.stdout.strip() if head_probe.returncode == 0 else ""
    if not expected_revision or actual_revision != expected_revision:
        return False, "worktree HEAD does not match the reviewed Health subject_revision"
    if _protected_worktree_branch(actual_branch, base_branch):
        return False, "refusing to remove a default or protected branch"
    removable, reason = removable_git_checkout(target_resolved)
    if not removable:
        return False, reason
    listing = subprocess.run(
        ["git", "-C", str(target_resolved), "worktree", "list", "--porcelain"],
        capture_output=True,
        text=True,
        check=False,
    )
    if listing.returncode != 0:
        return False, (listing.stderr or listing.stdout or "git worktree list failed").strip()
    registered = [
        Path(line.removeprefix("worktree ")).expanduser().resolve()
        for line in listing.stdout.splitlines()
        if line.startswith("worktree ")
    ]
    if target_resolved not in registered:
        return False, "checkout is not registered in git worktree metadata"
    if not registered or registered[0] == target_resolved:
        return False, "refusing to remove the primary git worktree"
    primary = registered[0]
    removal = subprocess.run(
        ["git", "-C", str(primary), "worktree", "remove", str(target_resolved)],
        capture_output=True,
        text=True,
        check=False,
    )
    if removal.returncode != 0:
        return False, (removal.stderr or removal.stdout or "git worktree remove failed").strip()
    return True, "removed exact typed merged git worktree"


def _validated_worktree_link(project_root: Path, entry: Mapping[str, Any]) -> Path | None:
    """Return one exact project-owned link or fail before any registry mutation."""

    link_value = str(entry.get("link") or "").strip()
    if not link_value:
        return None
    relative = Path(link_value).expanduser()
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("selected worktree link must be a project-relative worktrees path")
    link_path = (project_root / relative).absolute()
    managed_links = (project_root / "worktrees").absolute()
    if not link_path.is_relative_to(managed_links):
        raise ValueError("selected worktree link is outside the project worktrees directory")
    path_value = str(entry.get("path") or "").strip()
    if not path_value:
        raise ValueError("selected worktree registry entry with a link has no target path")
    if link_path.exists() or link_path.is_symlink():
        if link_path.resolve() != Path(path_value).expanduser().resolve():
            raise ValueError("selected worktree link does not point to the exact cleanup target")
    return link_path


def cleanup_terminal_worktrees(
    root: str | Path,
    *,
    domain: str | None = None,
    project: str | None = None,
    worktree: str | None = None,
    health_preflight: str | Path | None = None,
    runtime_receipt: str | Path | None = None,
    apply: bool = False,
    remove_files: bool = False,
) -> dict[str, Any]:
    os_root = expand_path(root)
    if apply and remove_files and not all(
        (domain, project, worktree, health_preflight, runtime_receipt)
    ):
        raise ValueError(
            "physical worktree removal requires --domain, --project, --worktree, "
            "--health-preflight, and --runtime-receipt"
        )
    candidates: list[dict[str, Any]] = []
    closed: list[dict[str, Any]] = []
    removed: list[dict[str, str]] = []
    skipped: list[dict[str, str]] = []
    registry_paths = ("config/worktrees.yml", "worktrees/index.yml")
    project_roots = list(root_project_dirs(os_root, domain=domain, project=project))
    physical_target_paths: set[Path] = set()
    physically_handled_paths: set[Path] = set()
    archived_by_path: dict[Path, dict[str, Any]] = {}
    if apply and remove_files:
        selector = str(worktree or "").strip()
        matched: list[tuple[Path, dict[str, Any]]] = []
        for selected_project in project_roots:
            for relative_registry in registry_paths:
                registry_path = selected_project / relative_registry
                if not registry_path.is_file():
                    continue
                _, entries, _ = worktree_registry_payload(registry_path)
                for entry in entries:
                    if not isinstance(entry, dict):
                        continue
                    path_value = str(entry.get("path") or "")
                    link_value = str(entry.get("link") or "")
                    values = {
                        str(entry.get("id") or ""),
                        str(entry.get("name") or ""),
                        path_value,
                        link_value,
                        Path(path_value).name if path_value else "",
                        Path(link_value).name if link_value else "",
                    }
                    selector_path_match = False
                    if Path(selector).expanduser().is_absolute() and path_value:
                        try:
                            selector_path_match = (
                                Path(selector).expanduser().resolve()
                                == Path(path_value).expanduser().resolve()
                            )
                        except OSError:
                            selector_path_match = False
                    if selector not in values and not selector_path_match:
                        continue
                    if not path_value:
                        raise ValueError("selected worktree registry entry has no path")
                    _validated_worktree_link(selected_project, entry)
                    matched.append((selected_project, entry))
                    physical_target_paths.add(Path(path_value).expanduser().resolve())
        if matched and len(physical_target_paths) != 1:
            raise ValueError(
                "worktree selector is ambiguous across active registries; refusing physical cleanup"
            )
        for selected_project, entry in matched:
            _health_cleanup_gate(
                health_preflight,
                runtime_receipt,
                domain=str(domain),
                project=str(project),
                entry=entry,
                os_root=os_root,
            )
    for project_root in project_roots:
        record_domain = project_domain(project_root)
        for relative_registry in registry_paths:
            registry_path = project_root / relative_registry
            if not registry_path.is_file():
                continue
            payload, entries, _ = worktree_registry_payload(registry_path)
            kept_entries: list[dict[str, Any]] = []
            changed = False
            for entry in entries:
                if not isinstance(entry, dict):
                    kept_entries.append(entry)
                    continue
                if worktree:
                    selector = str(worktree).strip()
                    path_value = str(entry.get("path") or "")
                    link_value = str(entry.get("link") or "")
                    entry_values = {
                        str(entry.get("id") or ""),
                        str(entry.get("name") or ""),
                        path_value,
                        link_value,
                        Path(path_value).name if path_value else "",
                        Path(link_value).name if link_value else "",
                    }
                    path_match = False
                    selector_path = Path(selector).expanduser()
                    if selector_path.is_absolute() and path_value:
                        try:
                            path_match = selector_path.resolve() == Path(path_value).expanduser().resolve()
                        except OSError:
                            path_match = False
                    if selector not in entry_values and not path_match:
                        kept_entries.append(entry)
                        continue
                gate: dict[str, Any] | None = None
                gate_path: Path | None = None
                if health_preflight or runtime_receipt:
                    if not health_preflight or not runtime_receipt or not domain or not project:
                        message = "Health cleanup gate requires domain, project, preflight, and runtime receipt"
                        if apply and remove_files:
                            raise ValueError(message)
                        skipped.append({"path": str(entry.get("path") or ""), "reason": message})
                        kept_entries.append(entry)
                        continue
                    try:
                        gate, _, gate_path = _health_cleanup_gate(
                            health_preflight,
                            runtime_receipt,
                            domain=domain,
                            project=project,
                            entry=entry,
                            os_root=os_root,
                        )
                    except ValueError as exc:
                        if apply and remove_files:
                            raise
                        skipped.append(
                            {"path": str(entry.get("path") or ""), "reason": str(exc)}
                        )
                        kept_entries.append(entry)
                        continue
                reason = worktree_cleanup_reason(entry)
                if gate is not None:
                    reason = "pr:typed_merge"
                if not reason:
                    kept_entries.append(entry)
                    continue
                path_value = str(entry.get("path") or "")
                candidate = {
                    "domain": record_domain,
                    "project": project_root.name,
                    "id": str(entry.get("id") or entry.get("name") or Path(path_value).name),
                    "path": path_value,
                    "source": str(registry_path),
                    "reason": reason,
                    "jira_status": worktree_jira_status(entry),
                    "pr_state": worktree_pr_state(entry),
                }
                candidates.append(candidate)
                if not apply:
                    kept_entries.append(entry)
                    continue
                validated_link = _validated_worktree_link(project_root, entry)
                if remove_files:
                    resolved_path = Path(path_value).expanduser().resolve()
                    if resolved_path in physically_handled_paths:
                        ok, removal_reason = True, "removed exact typed merged git worktree"
                    else:
                        ok, removal_reason = remove_worktree_files(
                            project_root, entry, health_gate=gate
                        )
                    if ok:
                        physically_handled_paths.add(resolved_path)
                        removed.append({"path": path_value, "reason": removal_reason})
                    else:
                        skipped.append({"path": path_value, "reason": removal_reason})
                        kept_entries.append(entry)
                        continue
                resolved_path = Path(path_value).expanduser().resolve()
                archived = archived_by_path.get(resolved_path)
                if archived is None:
                    archived = archive_worktree_entry(
                        project_root,
                        entry,
                        reason=reason,
                        source=registry_path,
                        health_gate=gate,
                        health_preflight_ref=(
                            gate_path.relative_to(
                                Path(str(gate.get("packet_path"))).expanduser().resolve()
                            ).as_posix()
                            if gate_path and gate
                            else None
                        ),
                    )
                    archived_by_path[resolved_path] = archived
                closed.append({"id": candidate["id"], "closed_registry": archived["path"], "reason": reason})
                if validated_link is not None and validated_link.is_symlink():
                    validated_link.unlink()
                    removed.append(
                        {
                            "path": str(validated_link),
                            "reason": "removed exact project-owned worktree symlink",
                        }
                    )
                changed = True
            if apply and changed:
                if isinstance(payload.get("worktrees"), dict):
                    raw = payload["worktrees"]
                    key = "registered" if "registered" in raw else "worktrees"
                    raw[key] = kept_entries
                else:
                    payload["worktrees"] = kept_entries
                write_worktree_registry(registry_path, payload)
    sync_result = sync_active_container(os_root, domain=domain, project=project) if apply else None
    return {
        "mode": "apply" if apply else "dry-run",
        "remove_files": remove_files,
        "worktree_selector": worktree,
        "health_preflight": str(health_preflight) if health_preflight else None,
        "runtime_receipt": str(runtime_receipt) if runtime_receipt else None,
        "candidate_count": len(candidates),
        "candidates": candidates,
        "closed": closed,
        "removed": removed,
        "skipped": skipped,
        "active_container": sync_result,
    }


def active_worktree_entries(project_root: Path) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    for path in (project_root / "config" / "worktrees.yml", project_root / "worktrees" / "index.yml"):
        data = load_yaml_mapping(path)
        worktrees = data.get("worktrees") if isinstance(data.get("worktrees"), dict) else data
        raw_entries = []
        if isinstance(worktrees, dict):
            raw_entries = worktrees.get("registered") or worktrees.get("worktrees") or []
        elif isinstance(worktrees, list):
            raw_entries = worktrees
        for entry in raw_entries:
            if not isinstance(entry, dict) or str(entry.get("status") or "active") != "active":
                continue
            target = Path(str(entry.get("path") or "")).expanduser()
            if not target.exists() and entry.get("link"):
                target = project_root / str(entry["link"])
            if not target.exists():
                continue
            entries.append(
                {
                    "id": str(entry.get("id") or entry.get("name") or target.name),
                    "path": str(target),
                    "source": str(path),
                    **active_index_timestamps(target),
                }
            )
    unique: dict[str, dict[str, str]] = {}
    for entry in entries:
        unique[f"{entry['id']}:{entry['path']}"] = entry
    return list(unique.values())


def active_automation_entries(root: Path) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    inactive = {"done", "finished", "documented", "archived", "inactive"}
    active_work_paths = list(root.glob("*/00-control-plane/active-work.md"))
    active_work_paths.extend(root.glob("domains/*/00-control-plane/active-work.md"))
    shared_factory_active_work = root / "harness" / "shared_factory" / "00-control-plane" / "active-work.md"
    if shared_factory_active_work.is_file():
        active_work_paths.append(shared_factory_active_work)
    for active_work in sorted(set(active_work_paths)):
        domain_root = active_work.parent.parent
        for line in active_work.read_text(encoding="utf-8").splitlines():
            if "04-automations/" not in line or not line.startswith("|"):
                continue
            cells = [cell.strip().strip("`") for cell in line.strip().strip("|").split("|")]
            if len(cells) < 5 or cells[0] == "---":
                continue
            status = cells[1].strip("`").lower()
            if status in inactive:
                continue
            link = cells[4].strip("`")
            target = domain_root / link
            if target.is_dir():
                entries.append(
                    {
                        "id": cells[0].replace("`", ""),
                        "status": status,
                        "path": str(target),
                        **active_index_timestamps(target, recursive=True),
                    }
                )
    return entries


def sync_active_container(root: str | Path, *, domain: str | None = None, project: str | None = None) -> dict[str, Any]:
    os_root = expand_path(root)
    container = active_container_root(os_root)
    work_item_links = container / "work-items"
    worktree_links = container / "worktrees"
    automation_links = container / "automations"
    for category in (work_item_links, worktree_links, automation_links):
        reset_managed_category(category)
    ensure_spotlight_never_index(worktree_links, ScaffoldResult())

    state_projection = (
        os_root / "harness" / "shared_factory" / "00-control-plane" / "active-now.json"
    )
    state_backed = state_projection.is_file()
    index: dict[str, Any] = {
        "generated_at": now_iso(),
        "source_of_truth": (
            "state.db active work_items and their verified worktree references"
            if state_backed
            else "filesystem work-items and project worktree registries"
        ),
        "work_items": [],
        "worktrees": [],
        "automations": [],
    }
    state_items_by_project: dict[tuple[str, str], list[dict[str, Any]]] = {}
    active_state_items: list[dict[str, Any]] = []
    if state_backed:
        from .state import work_items as work_items_state
        from .state.db import connect as connect_state
        from .state.db import default_db_path

        connection = connect_state(default_db_path(os_root))
        try:
            for item in work_items_state.query(connection, attention="active", limit=10000):
                key = (str(item.get("domain") or ""), str(item.get("project") or ""))
                state_items_by_project.setdefault(key, []).append(item)
                active_state_items.append(item)
        finally:
            connection.close()
        linked_worktree_paths: set[Path] = set()
        for item in active_state_items:
            worktree_value = str(item.get("worktree_path") or "").strip()
            if not worktree_value:
                continue
            worktree = Path(worktree_value).expanduser()
            if not worktree.is_absolute():
                worktree = os_root / worktree
            worktree = worktree.resolve()
            if not worktree.is_dir() or worktree in linked_worktree_paths:
                continue
            linked_worktree_paths.add(worktree)
            item_domain = str(item.get("domain") or "root")
            item_project = str(item.get("project") or "root")
            link = worktree_links / safe_link_name(
                item_domain,
                item_project,
                str(item["id"]),
            )
            create_link(link, worktree)
            index["worktrees"].append(
                {
                    "domain": item_domain,
                    "project": item_project,
                    "id": item["id"],
                    **active_index_timestamps(worktree, recursive=False),
                    "link": str(link),
                    "target": str(worktree),
                    "source_work_item": item["id"],
                }
            )
    for project_root in root_project_dirs(os_root, domain=domain, project=project):
        record_domain = project_domain(project_root)
        if state_backed:
            for item in state_items_by_project.get((record_domain, project_root.name), []):
                packet_value = str(item.get("packet_path") or "")
                packet = (os_root / packet_value).resolve() if packet_value else None
                link = None
                if packet and packet.exists():
                    link = work_item_links / safe_link_name(
                        record_domain,
                        project_root.name,
                        str(item["id"]),
                    )
                    create_link(link, packet)
                index["work_items"].append(
                    {
                        "domain": record_domain,
                        "project": project_root.name,
                        "id": item["id"],
                        "status": item["state"],
                        "attention": item["attention"],
                        "context_summary": item["context_summary"],
                        "last_verified_at": item.get("last_verified_at"),
                        "link": str(link) if link else None,
                        "target": str(packet) if packet else None,
                    }
                )
        else:
            linked_work_item_paths: set[Path] = set()
            for record in local_project_work_items(project_root):
                if record.status not in ACTIVE_CONTAINER_WORK_ITEM_STATES or current_lane(record) not in {"work-items", "02-active"}:
                    continue
                link = work_item_links / safe_link_name(
                    record_domain,
                    project_root.name,
                    record.path.name,
                )
                create_link(link, record.path)
                linked_work_item_paths.add(record.path.resolve())
                index["work_items"].append(
                    {
                        "domain": record_domain,
                        "project": project_root.name,
                        "id": record.slug,
                        "status": record.status,
                        "created_at": record_created_at(record),
                        "last_modified_at": record_modified_at(record),
                        "link": str(link),
                        "target": str(record.path),
                    }
                )
            active_lane = work_items_root(project_root) / "02-active"
            if active_lane.is_dir():
                for legacy in sorted(
                    item for item in active_lane.iterdir() if item.is_dir() or item.suffix == ".md"
                ):
                    if legacy.resolve() in linked_work_item_paths:
                        continue
                    link = work_item_links / safe_link_name(
                        record_domain,
                        project_root.name,
                        legacy.name,
                    )
                    create_link(link, legacy)
                    index["work_items"].append(
                        {
                            "domain": record_domain,
                            "project": project_root.name,
                            "id": legacy.stem,
                            "status": "legacy-active",
                            **active_index_timestamps(legacy, recursive=True),
                            "link": str(link),
                            "target": str(legacy),
                        }
                    )
        if not state_backed:
            for entry in active_worktree_entries(project_root):
                link = worktree_links / safe_link_name(
                    record_domain, project_root.name, entry["id"]
                )
                create_link(link, Path(entry["path"]))
                index["worktrees"].append(
                    {
                        "domain": record_domain,
                        "project": project_root.name,
                        "id": entry["id"],
                        "created_at": entry["created_at"],
                        "last_modified_at": entry["last_modified_at"],
                        "link": str(link),
                        "target": entry["path"],
                    }
                )
    if domain is None and project is None:
        for entry in active_automation_entries(os_root):
            target = Path(entry["path"])
            link = automation_links / safe_link_name(entry["id"])
            create_link(link, target)
            index["automations"].append({**entry, "link": str(link)})

    readme = container / "README.md"
    readme.write_text(
        "# Global Active Work\n\n"
        "This folder is generated by `agentic-os project work-item sync-active`.\n"
        + (
            "Work-item truth comes from state.db attention=active; symlinks are disposable projections.\n"
            if state_backed
            else "Work-item truth is still using the legacy filesystem compatibility scan.\n"
        )
        + "Do not edit generated links by hand; update canonical state or the owning registry, then resync.\n",
        encoding="utf-8",
    )
    index_path = container / "index.yml"
    index_path.write_text(yaml.safe_dump(index, sort_keys=False), encoding="utf-8")
    return {
        "container": str(container),
        "index": str(index_path),
        "work_items": len(index["work_items"]),
        "worktrees": len(index["worktrees"]),
        "automations": len(index["automations"]),
    }
