"""Project work-item lifecycle helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import re
from typing import Any

import yaml

from .scaffold import (
    ScaffoldResult,
    append_control_signal,
    append_domain_memory,
    append_once,
    domain_path,
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
    "IDEA.md",
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
    "captured": ("IDEA.md", "WORKLOG.md", "NEXT.md"),
    "triaged": ("IDEA.md", "JUDGMENT.md", "WORKLOG.md", "NEXT.md"),
    "specified": ("IDEA.md", "SPEC.md", "JUDGMENT.md", "WORKLOG.md", "NEXT.md"),
    "ready": ("SPEC.md", "PLAN.md", "JUDGMENT.md", "WORKLOG.md", "NEXT.md"),
    "building": ("SPEC.md", "PLAN.md", "WORKLOG.md", "NEXT.md"),
    "validating": ("SPEC.md", "PLAN.md", "HOLDOUT_QA.md", "WORKLOG.md", "NEXT.md"),
    "finished": ("SUMMARY.md", "HOLDOUT_QA_RESULTS.md", "WORKLOG.md", "NEXT.md"),
    "documented": ("SUMMARY.md", "MEMORY.md", "WORKLOG.md", "NEXT.md"),
    "blocked": ("JUDGMENT.md", "WORKLOG.md", "NEXT.md"),
    "archived": ("SUMMARY.md", "WORKLOG.md"),
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

WORK_ITEM_INDEX_RE = re.compile(r"^(?P<index>\d{3})[_-](?P<slug>.+)$")

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


def lane_root(project_root: Path, status: str) -> Path:
    return work_items_root(project_root) / lane_for_status(status)


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
    return [work_item_root / name for name in names]


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
            "path": "work-items/02-active",
        },
        "external_tracker": {
            "type": "none",
        },
    }
    return yaml.safe_dump(payload, sort_keys=False)


def intake_idea_markdown(*, domain: str, project: str, work_id: str, title: str, status: str, summary: str) -> str:
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
        "spec_destination": {"type": "local", "path": "work-items/02-active"},
        "external_tracker": {"type": "none"},
    }
    return f"""---
{yaml.safe_dump(metadata, sort_keys=False).strip()}
---

# Idea: {title}

## Captured

| Field | Value |
| --- | --- |
| Date | {today_iso()} |
| Status | `{status}` |
| Work Item | `{work_id}` |
| Lane | `{lane_for_status(status)}` |

## Raw Idea

{summary}

## Notes

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

## Problem

{summary}

## Outcome

- TBD.

## Scope

- TBD.

## Acceptance Criteria

- TBD.
"""
    if filename == "PLAN.md":
        return f"""# Plan: {title}

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
    payload.setdefault("spec_destination", {"type": "local", "path": "work-items/02-active"})
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
    work_root = work_items_root(project_root)
    work_item_root = work_item_path(project_root, work_id, status, item_format=item_format)
    result = ScaffoldResult()
    for directory in (work_root, *(work_root / lane for lane in WORK_ITEM_LANES)):
        if directory.is_dir():
            result.skipped.append(directory)
        else:
            directory.mkdir(parents=True, exist_ok=True)
            result.created.append(directory)
    if status in INTAKE_MARKDOWN_STATES and item_format != "packet":
        write_file_once(
            work_item_root,
            intake_idea_markdown(
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
        if child.name in WORK_ITEM_LANES and child.is_dir():
            candidates.extend(sorted(item for item in child.iterdir() if item.is_dir() or item.suffix == ".md"))
        elif child.is_dir() and child.name not in {".logs", "logs"}:
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
        metadata = load_yaml_mapping(metadata_path)
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
