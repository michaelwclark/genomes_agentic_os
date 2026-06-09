"""Project work-item lifecycle helpers."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import re
from typing import Any

import yaml

from .scaffold import (
    ScaffoldResult,
    append_control_signal,
    append_once,
    domain_path,
    expand_path,
    template_source_dir,
    validate_name,
    write_file_once,
)


WORK_ITEM_STATES = (
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

TERMINAL_WORK_ITEM_STATES = {"documented", "archived"}

WORK_ITEM_LANES = ("01-intake", "02-active", "03-complete")

WORK_ITEM_STATE_LANES = {
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

WORK_ITEM_MARKDOWN_FILES = (
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

WORK_ITEM_REQUIRED_PATHS = (
    "work.yml",
    *WORK_ITEM_MARKDOWN_FILES,
    "artifacts",
    "logs",
    "logs/conversations",
)

STATE_CONTEXT_FILES = {
    "captured": ("IDEA.md", "work.yml"),
    "triaged": ("JUDGMENT.md", "work.yml"),
    "specified": ("SPEC.md", "JUDGMENT.md", "work.yml"),
    "ready": ("PLAN.md", "NEXT.md", "work.yml"),
    "building": ("WORKLOG.md", "INVESTIGATION.md", "NEXT.md", "work.yml"),
    "validating": ("HOLDOUT_QA.md", "HOLDOUT_QA_RESULTS.md", "WORKLOG.md", "work.yml"),
    "finished": ("SUMMARY.md", "WORKLOG.md", "HOLDOUT_QA_RESULTS.md", "work.yml"),
    "documented": ("MEMORY.md", "SUMMARY.md", "NEXT.md", "work.yml"),
    "blocked": ("NEXT.md", "JUDGMENT.md", "WORKLOG.md", "work.yml"),
    "archived": ("SUMMARY.md", "NEXT.md", "work.yml"),
}

SOURCE_FEATURE_CONTEXT_FILES = (
    "feature.yml",
    "SPEC.md",
    "PLAN.md",
    "WORKLOG.md",
    "NEXT.md",
    "INVESTIGATION.md",
    "JUDGMENT.md",
    "HOLDOUT_QA.md",
    "HOLDOUT_QA_RESULTS.md",
    "SUMMARY.md",
    "MEMORY.md",
)


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def slugify_work_id(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    if not slug:
        raise ValueError("work item id could not be derived from an empty title")
    return validate_name(slug, "work_item")


def project_root_for(root: str | Path, domain: str, project: str) -> Path:
    domain = validate_name(domain, "domain")
    project = validate_name(project, "project")
    project_root = domain_path(root, domain) / "02-projects" / project
    if not (project_root / "project.yml").is_file():
        raise ValueError(f"project not found: {domain}/{project}")
    return project_root


def load_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def work_lifecycle_config(project_root: Path) -> dict[str, Any]:
    config = load_yaml(project_root / "config" / "work-lifecycle.yml")
    if not config:
        config = load_yaml(project_root / "project.yml").get("work_lifecycle") or {}
    if not isinstance(config, dict):
        config = {}
    return {
        "enabled": config.get("enabled", True),
        "work_items_root": config.get("work_items_root") or "work-items",
        "default_state": config.get("default_state") or "captured",
        "transcript_logging": config.get("transcript_logging")
        or {
            "enabled": True,
            "include_raw_transcript": True,
            "include_tool_call_jsonl": True,
            "include_tool_call_markdown": True,
            "redaction_policy": "strict",
        },
        "spec_destination": config.get("spec_destination") or {"type": "local", "path": "work-items/02-active"},
        "external_tracker": config.get("external_tracker") or {"type": "none"},
    }


def project_work_items_root(project_root: Path) -> Path:
    configured = str(work_lifecycle_config(project_root).get("work_items_root") or "work-items")
    return project_root / configured


def lane_for_state(state: str) -> str:
    return WORK_ITEM_STATE_LANES.get(state, "01-intake")


def iter_work_item_roots(project_root: Path) -> list[Path]:
    root = project_work_items_root(project_root)
    if not root.is_dir():
        return []
    candidates: list[Path] = []
    for child in sorted(root.iterdir()):
        if child.name in WORK_ITEM_LANES and child.is_dir():
            candidates.extend(sorted(item for item in child.iterdir() if item.is_dir()))
        elif child.is_dir():
            candidates.append(child)
    return candidates


def find_work_item_root(project_root: Path, work_item: str) -> Path | None:
    slug = slugify_work_id(work_item)
    for candidate in iter_work_item_roots(project_root):
        metadata = load_work_item_metadata(candidate)
        identifiers = {candidate.name, str(metadata.get("id") or ""), str(metadata.get("slug") or "")}
        if slug in identifiers:
            return candidate
    return None


def work_item_root_for(project_root: Path, work_item: str, state: str | None = None) -> Path:
    found = find_work_item_root(project_root, work_item)
    if found:
        return found
    root = project_work_items_root(project_root)
    if state:
        return root / lane_for_state(state) / slugify_work_id(work_item)
    return root / slugify_work_id(work_item)


def metadata_path(work_item_root: Path) -> Path:
    work_yml = work_item_root / "work.yml"
    if work_yml.is_file():
        return work_yml
    return work_item_root / "feature.yml"


def load_work_item_metadata(work_item_root: Path) -> dict[str, Any]:
    return load_yaml(metadata_path(work_item_root))


def render_work_item_file(
    filename: str,
    *,
    domain: str,
    project: str,
    work_item: str,
    title: str,
    summary: str,
    state: str,
    timestamp: str,
) -> str:
    template = template_source_dir() / "work-item" / filename
    content = template.read_text(encoding="utf-8")
    replacements = {
        "<domain>": domain,
        "<project>": project,
        "<work_item>": work_item,
        "<title>": title,
        "<summary>": summary,
        "<state>": state,
        "<timestamp>": timestamp,
    }
    for key, value in replacements.items():
        content = content.replace(key, value)
    return content


def render_work_metadata(
    *,
    domain: str,
    project: str,
    work_item: str,
    title: str,
    summary: str,
    state: str,
    timestamp: str,
    config: dict[str, Any],
) -> str:
    payload = {
        "schema_version": 1,
        "id": work_item,
        "title": title,
        "summary": summary,
        "domain": domain,
        "project": project,
        "state": state,
        "lane": lane_for_state(state),
        "format": "folder",
        "created_at": timestamp,
        "updated_at": timestamp,
        "lifecycle": "project_work_item",
        "transcript_logging": config["transcript_logging"],
        "spec_destination": config["spec_destination"],
        "external_tracker": config["external_tracker"],
        "files": {
            "idea": "IDEA.md",
            "spec": "SPEC.md",
            "plan": "PLAN.md",
            "investigation": "INVESTIGATION.md",
            "judgment": "JUDGMENT.md",
            "holdout_qa": "HOLDOUT_QA.md",
            "holdout_qa_results": "HOLDOUT_QA_RESULTS.md",
            "worklog": "WORKLOG.md",
            "summary": "SUMMARY.md",
            "next": "NEXT.md",
            "memory": "MEMORY.md",
            "conversations": "logs/conversations",
        },
    }
    return yaml.safe_dump(payload, sort_keys=False)


def work_item_summary(work_item_root: Path) -> dict[str, Any]:
    metadata = load_work_item_metadata(work_item_root)
    return {
        "id": str(metadata.get("id") or work_item_root.name),
        "title": str(metadata.get("title") or work_item_root.name),
        "state": str(metadata.get("state") or metadata.get("status") or ""),
        "path": str(work_item_root),
        "updated_at": str(metadata.get("updated_at") or ""),
        "metadata_file": str(metadata_path(work_item_root)),
    }


def create_project_work_item(
    root: str | Path,
    domain: str,
    project: str,
    work_item: str | None = None,
    *,
    title: str,
    summary: str = "",
    state: str | None = None,
) -> dict[str, Any]:
    domain = validate_name(domain, "domain")
    project = validate_name(project, "project")
    project_root = project_root_for(root, domain, project)
    config = work_lifecycle_config(project_root)
    if not config.get("enabled", True):
        raise ValueError(f"work lifecycle is disabled for project: {domain}/{project}")
    state = state or str(config.get("default_state") or "captured")
    if state not in WORK_ITEM_STATES:
        raise ValueError(f"state must be one of {', '.join(WORK_ITEM_STATES)}: {state!r}")
    work_item = slugify_work_id(work_item or title)
    work_root = work_item_root_for(project_root, work_item, state)
    timestamp = utc_timestamp()
    result = ScaffoldResult()
    for lane in WORK_ITEM_LANES:
        lane_root = project_work_items_root(project_root) / lane
        if lane_root.is_dir():
            result.skipped.append(lane_root)
        else:
            lane_root.mkdir(parents=True, exist_ok=True)
            result.created.append(lane_root)
    for directory in (work_root, work_root / "artifacts", work_root / "logs", work_root / "logs" / "conversations"):
        if directory.is_dir():
            result.skipped.append(directory)
        else:
            directory.mkdir(parents=True, exist_ok=True)
            result.created.append(directory)
    write_file_once(
        work_root / "work.yml",
        render_work_metadata(
            domain=domain,
            project=project,
            work_item=work_item,
            title=title,
            summary=summary,
            state=state,
            timestamp=timestamp,
            config=config,
        ),
        result,
    )
    for filename in WORK_ITEM_MARKDOWN_FILES:
        write_file_once(
            work_root / filename,
            render_work_item_file(
                filename,
                domain=domain,
                project=project,
                work_item=work_item,
                title=title,
                summary=summary,
                state=state,
                timestamp=timestamp,
            ),
            result,
        )
    append_once(
        project_root / "status.md",
        f"\n## Work Item: {title}\n\n- ID: `{work_item}`\n- State: `{state}`\n- Summary: {summary}\n- Path: `{work_root.relative_to(project_root)}/`\n",
        result,
    )
    append_control_signal(
        domain_path(root, domain),
        "Project Activity",
        f"`{project}/{work_item}`",
        state,
        f"`02-projects/{project}/{work_root.relative_to(project_root)}/`",
        "Project work item created or repaired.",
        result,
    )
    return {
        "domain": domain,
        "project": project,
        "work_item": work_item,
        "state": state,
        "path": str(work_root),
        "created": [str(path) for path in result.created],
        "updated": [str(path) for path in result.updated],
        "skipped": [str(path) for path in result.skipped],
    }


def list_project_work_items(root: str | Path, domain: str, project: str) -> dict[str, Any]:
    project_root = project_root_for(root, validate_name(domain, "domain"), validate_name(project, "project"))
    work_items_root = project_work_items_root(project_root)
    items = []
    if work_items_root.is_dir():
        for child in iter_work_item_roots(project_root):
            if (child / "work.yml").is_file() or (child / "feature.yml").is_file():
                items.append(work_item_summary(child))
    return {"domain": domain, "project": project, "work_items_root": str(work_items_root), "items": items}


def show_project_work_item(root: str | Path, domain: str, project: str, work_item: str) -> dict[str, Any]:
    project_root = project_root_for(root, validate_name(domain, "domain"), validate_name(project, "project"))
    work_root = work_item_root_for(project_root, work_item)
    if not work_root.is_dir():
        raise ValueError(f"work item not found: {domain}/{project}/{work_item}")
    metadata = load_work_item_metadata(work_root)
    state = str(metadata.get("state") or metadata.get("status") or "")
    required_files = [str(work_root / name) for name in STATE_CONTEXT_FILES.get(state, ("work.yml",))]
    return {
        **work_item_summary(work_root),
        "domain": domain,
        "project": project,
        "metadata": metadata,
        "state_required_files": required_files,
        "missing_required_files": [path for path in required_files if not Path(path).is_file()],
    }


def promote_project_work_item(
    root: str | Path,
    domain: str,
    project: str,
    work_item: str,
    *,
    state: str,
    note: str = "",
) -> dict[str, Any]:
    if state not in WORK_ITEM_STATES:
        raise ValueError(f"state must be one of {', '.join(WORK_ITEM_STATES)}: {state!r}")
    project_root = project_root_for(root, validate_name(domain, "domain"), validate_name(project, "project"))
    work_root = work_item_root_for(project_root, work_item)
    if not work_root.is_dir():
        raise ValueError(f"work item not found: {domain}/{project}/{work_item}")
    path = metadata_path(work_root)
    if not path.is_file():
        raise ValueError(f"work item metadata is missing: {path}")
    metadata = load_yaml(path)
    old_state = str(metadata.get("state") or metadata.get("status") or "")
    timestamp = utc_timestamp()
    target_root = project_work_items_root(project_root) / lane_for_state(state) / work_root.name
    result = ScaffoldResult()
    if target_root != work_root:
        if target_root.exists():
            raise ValueError(f"target work item already exists: {target_root}")
        target_root.parent.mkdir(parents=True, exist_ok=True)
        work_root.rename(target_root)
        result.updated.append(target_root)
        work_root = target_root
    if "state" in metadata or path.name == "work.yml":
        metadata["state"] = state
    else:
        metadata["status"] = state
    metadata["lane"] = lane_for_state(state)
    metadata["format"] = "folder"
    metadata["updated_at"] = timestamp
    path = metadata_path(work_root)
    before = path.read_text(encoding="utf-8")
    after = yaml.safe_dump(metadata, sort_keys=False)
    if before != after:
        path.write_text(after, encoding="utf-8")
        result.updated.append(path)
    append_once(
        work_root / "WORKLOG.md",
        f"\n## {timestamp}\n\n- State: `{old_state}` -> `{state}`\n- Note: {note or 'No note provided.'}\n",
        result,
    )
    append_once(
        work_root / "NEXT.md",
        f"\n## {timestamp}\n\n- Current state: `{state}`\n- Next action: {note or 'Define the next action before handoff.'}\n",
        result,
    )
    append_once(
        project_root / "status.md",
        f"\n## Work Item State: {work_item}\n\n- State: `{old_state}` -> `{state}`\n- Note: {note or 'No note provided.'}\n- Updated: {timestamp}\n",
        result,
    )
    append_control_signal(
        domain_path(root, validate_name(domain, "domain")),
        "Project Activity",
        f"`{project}/{slugify_work_id(work_item)}`",
        state,
        f"`02-projects/{project}/{work_root.relative_to(project_root)}/`",
        note or "Project work item state changed.",
        result,
    )
    return {
        "domain": domain,
        "project": project,
        "work_item": slugify_work_id(work_item),
        "old_state": old_state,
        "state": state,
        "path": str(work_root),
        "updated": [str(item) for item in result.updated],
        "skipped": [str(item) for item in result.skipped],
    }


def project_work_item_records(root: str | Path) -> list[dict[str, Any]]:
    os_root = expand_path(root)
    records: list[dict[str, Any]] = []
    for project_yml in sorted(os_root.glob("*/02-projects/*/project.yml")):
        project_root = project_yml.parent
        project_data = load_yaml(project_yml)
        domain = str(project_data.get("domain") or project_yml.parents[2].name)
        project = str(project_data.get("id") or project_root.name)
        work_items_root = project_work_items_root(project_root)
        if not work_items_root.is_dir():
            continue
        for child in iter_work_item_roots(project_root):
            metadata = load_work_item_metadata(child)
            if not metadata:
                continue
            records.append(
                {
                    "domain": domain,
                    "project": project,
                    "work_item": str(metadata.get("id") or child.name),
                    "title": str(metadata.get("title") or child.name),
                    "state": str(metadata.get("state") or metadata.get("status") or ""),
                    "path": child,
                }
            )
    return records


def work_item_context_files(work_item_root: Path, state: str) -> list[Path]:
    files = STATE_CONTEXT_FILES.get(state) or ("work.yml",)
    paths = []
    for filename in files:
        path = work_item_root / filename
        if filename == "work.yml" and not path.is_file() and (work_item_root / "feature.yml").is_file():
            path = work_item_root / "feature.yml"
        paths.append(path)
    return paths


def find_source_feature(repo_root: str | Path, request: str) -> dict[str, Any] | None:
    source_root = expand_path(repo_root)
    features_root = source_root / "features"
    if not features_root.is_dir():
        return None
    text = request.lower()
    matches = []
    for feature_yml in sorted(features_root.glob("*/feature.yml")):
        folder = feature_yml.parent
        data = load_yaml(feature_yml)
        labels = {
            folder.name,
            str(data.get("slug") or ""),
            str(data.get("prefix") or ""),
            str(data.get("title") or "").lower(),
            folder.name.replace("-", " "),
        }
        labels = {label.lower() for label in labels if label}
        if any(label and label in text for label in labels):
            matches.append((folder, data))
    if len(matches) != 1:
        return None
    folder, data = matches[0]
    state = str(data.get("state") or data.get("status") or "")
    return {
        "domain": "shared_factory",
        "project": "genomes_agentic_os",
        "work_item": str(data.get("slug") or folder.name),
        "title": str(data.get("title") or folder.name),
        "state": state,
        "path": folder,
        "sources": [folder / filename for filename in SOURCE_FEATURE_CONTEXT_FILES],
    }
