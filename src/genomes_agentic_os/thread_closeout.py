"""Thread lifecycle finalization helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
from typing import Any

import yaml

from .lifecycle import (
    ACTIVE_WORK_ITEM_STATES,
    WorkItemRecord,
    lane_for_status,
    load_yaml_mapping,
    local_project_work_items,
    now_iso,
    select_project_work_item,
    today_iso,
)
from .scaffold import domain_path, expand_path, normalize_domain, validate_name


WORK_LEVELS = ("trivial", "contextual", "artifact", "implementation", "operational")
CLOSEOUT_MODES = ("noop", "status-only", "artifact-closeout", "implementation-closeout", "cleanup", "archive")
DEFAULT_STALE_DAYS = 3
NO_NEXT_ACTION_VALUES = {"", "none", "null", "n/a", "na", "no", "false"}


@dataclass(frozen=True)
class CloseoutTarget:
    kind: str
    root: Path
    artifact_root: Path
    source_of_truth: list[Path]
    project_root: Path | None = None
    work_item: WorkItemRecord | None = None


def format_thread_closeout_result(result: dict[str, Any]) -> str:
    return yaml.safe_dump(result, sort_keys=False).strip()


def safe_thread_id(value: str | None) -> str:
    if value:
        text = re.sub(r"[^a-zA-Z0-9_.-]+", "_", value).strip("._-")
        if text:
            return text
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{stamp}_thread_closeout"


def path_for_display(path: Path) -> str:
    try:
        return str(path.resolve())
    except OSError:
        return str(path)


def append_once(path: Path, content: str) -> bool:
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    if content in existing:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    separator = "" if not existing or existing.endswith("\n") else "\n"
    path.write_text(f"{existing}{separator}{content}", encoding="utf-8")
    return True


def write_yaml(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def append_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    with path.open("a", encoding="utf-8") as handle:
        if existing and not existing.endswith("\n"):
            handle.write("\n")
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")


def root_project_dirs(root: Path, *, domain: str | None = None, project: str | None = None) -> list[Path]:
    roots: list[Path] = []
    if domain:
        domain_root = domain_path(root, normalize_domain(domain))
        projects_root = domain_root / "02-projects"
        if project:
            candidate = projects_root / validate_name(project, "project")
            if candidate.is_dir():
                roots.append(candidate)
        elif projects_root.is_dir():
            roots.extend(path for path in sorted(projects_root.iterdir()) if path.is_dir())
        return roots

    seen: set[str] = set()
    projects_roots = list(root.glob("*/02-projects"))
    projects_roots.append(root / "harness" / "shared_factory" / "02-projects")
    for projects_root in sorted(projects_roots):
        if not projects_root.is_dir():
            continue
        for candidate in sorted(projects_root.iterdir()):
            if not candidate.is_dir():
                continue
            if project and candidate.name != project:
                continue
            key = path_for_display(candidate)
            if key not in seen:
                seen.add(key)
                roots.append(candidate)
    return roots


def project_root_from_cwd(root: Path, cwd: Path) -> Path | None:
    try:
        relative = cwd.resolve().relative_to(root.resolve())
    except ValueError:
        return None
    parts = relative.parts
    if len(parts) >= 3 and parts[1] == "02-projects":
        return root / parts[0] / "02-projects" / parts[2]
    if len(parts) >= 5 and parts[0] == "harness" and parts[1] == "shared_factory" and parts[2] == "02-projects":
        return root / "harness" / "shared_factory" / "02-projects" / parts[3]
    return None


def resolve_work_item(
    root: Path,
    *,
    domain: str | None = None,
    project: str | None = None,
    work_item: str | None = None,
    request: str | None = None,
    cwd: Path | None = None,
) -> tuple[Path | None, WorkItemRecord | None]:
    cwd = cwd.resolve() if cwd else None
    cwd_project = project_root_from_cwd(root, cwd) if cwd else None
    if cwd_project and (not project or cwd_project.name == project):
        record = select_project_work_item(cwd_project, request=request, cwd=cwd, work_item=work_item)
        if record:
            return cwd_project, record

    matches: list[tuple[Path, WorkItemRecord]] = []
    for project_root in root_project_dirs(root, domain=domain, project=project):
        try:
            record = select_project_work_item(project_root, request=request, cwd=cwd, work_item=work_item)
        except ValueError:
            if work_item:
                continue
            raise
        if record:
            matches.append((project_root, record))

    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        labels = ", ".join(f"{path.name}/{record.path.name}" for path, record in matches)
        raise ValueError(f"work item is ambiguous; specify --domain/--project/--work-item: {labels}")
    if work_item:
        raise ValueError(f"work item not found: {work_item}")
    return None, None


def make_run_target(root: Path, thread_id: str) -> CloseoutTarget:
    run_root = root / "harness" / "shared_factory" / "06-runs-and-logs" / "runs" / thread_id
    run_root.mkdir(parents=True, exist_ok=True)
    run_log = run_root / "run-log.md"
    if not run_log.exists():
        write_text(
            run_log,
            f"# Run Log: {thread_id}\n\n## Created\n\n- Created by thread closeout on {now_iso()}.\n",
        )
    return CloseoutTarget(
        kind="run",
        root=run_root,
        artifact_root=run_root,
        source_of_truth=[run_log],
    )


def make_work_item_target(project_root: Path, record: WorkItemRecord, thread_id: str) -> CloseoutTarget:
    if record.path.is_file():
        artifact_root = record.path.parent / f"{record.path.stem}.artifacts" / "thread-closeouts" / thread_id
    else:
        artifact_root = record.path / "artifacts" / "thread-closeouts" / thread_id
    return CloseoutTarget(
        kind="work_item",
        root=record.path,
        artifact_root=artifact_root,
        source_of_truth=[record.path],
        project_root=project_root,
        work_item=record,
    )


def resolve_target(
    root: Path,
    thread_id: str,
    *,
    domain: str | None = None,
    project: str | None = None,
    work_item: str | None = None,
    request: str | None = None,
    cwd: Path | None = None,
) -> CloseoutTarget:
    project_root, record = resolve_work_item(
        root,
        domain=domain,
        project=project,
        work_item=work_item,
        request=request,
        cwd=cwd,
    )
    if project_root and record and record.source == "project_work_item":
        return make_work_item_target(project_root, record, thread_id)
    return make_run_target(root, thread_id)


def next_action_is_clear(next_action: str | None) -> bool:
    if next_action is None:
        return True
    return next_action.strip().lower() in NO_NEXT_ACTION_VALUES


def mode_final_state(mode: str, next_action: str | None) -> str:
    if mode == "noop":
        return "noop"
    if mode == "archive":
        return "archived"
    if next_action and not next_action_is_clear(next_action):
        return "blocked"
    return "finalized"


def notion_receipt(
    *,
    work_level: str,
    local_source: Path,
    notion_url: str | None,
    notion_warning: str | None,
    verified_workspace: str | None,
    skip_notion: bool,
    timestamp: str,
) -> tuple[dict[str, Any], str]:
    if skip_notion or work_level == "trivial":
        status = "skipped"
        workspace = "not_applicable"
        target = "not_applicable"
        result = "Notion projection was skipped for this closeout."
        warning = "None"
        follow_up = "None"
    elif notion_url:
        if verified_workspace != "Genome's Notion":
            raise ValueError("Notion projection requires --verified-notion-workspace \"Genome's Notion\"")
        status = "verified"
        workspace = "Genome's Notion"
        target = notion_url
        result = "Projection receipt supplied for the verified Genome's Notion target."
        warning = "None"
        follow_up = "None"
    else:
        status = "warning"
        workspace = verified_workspace or "unverified"
        target = "not_applicable"
        warning = notion_warning or "Notion projection requires a verified Genome's Notion write path; local closeout continued."
        result = "Local filesystem closeout completed; Notion projection was not written by this CLI path."
        follow_up = "Run a verified Notion projection if this closeout needs external visibility."

    payload = {
        "status": status,
        "workspace": workspace,
        "target": target,
        "attempted_at": timestamp if status != "skipped" else "not_applicable",
        "local_source": path_for_display(local_source),
        "warning": None if warning == "None" else warning,
    }
    markdown = f"""# Notion Sync Receipt

| Field | Value |
| --- | --- |
| Workspace | `{workspace}` |
| Status | `{status}` |
| Attempted At | `{payload['attempted_at']}` |
| Target | `{target}` |
| Local Source | `{path_for_display(local_source)}` |

## Result

{result}

## Non-Blocking Warning

{warning}

## Follow-Up

{follow_up}
"""
    return payload, markdown


def evidence_rows(
    *,
    timestamp: str,
    validations: list[str],
    artifacts: list[str],
    receipts: list[str],
    stale_reason: str | None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for value in validations:
        rows.append(
            {
                "schema_version": 1,
                "recorded_at": timestamp,
                "kind": "test",
                "summary": value,
                "ref": value,
                "status": "pass",
            }
        )
    for value in artifacts:
        rows.append(
            {
                "schema_version": 1,
                "recorded_at": timestamp,
                "kind": "artifact",
                "summary": value,
                "ref": value,
                "status": "pass",
            }
        )
    for value in receipts:
        rows.append(
            {
                "schema_version": 1,
                "recorded_at": timestamp,
                "kind": "external_ref",
                "summary": value,
                "ref": value,
                "status": "pass",
            }
        )
    if stale_reason:
        rows.append(
            {
                "schema_version": 1,
                "recorded_at": timestamp,
                "kind": "external_ref",
                "summary": stale_reason,
                "ref": "stale-thread-finalizer",
                "status": "warning",
            }
        )
    if not rows:
        rows.append(
            {
                "schema_version": 1,
                "recorded_at": timestamp,
                "kind": "artifact",
                "summary": "Thread closeout artifacts written.",
                "ref": "closeout.md",
                "status": "pass",
            }
        )
    return rows


def memory_rows(timestamp: str, memory_receipts: list[str], work_level: str) -> list[dict[str, Any]]:
    if memory_receipts:
        rows = []
        for value in memory_receipts:
            action = "written"
            summary = value
            if value.lower().startswith("skipped:"):
                action = "skipped"
                summary = value.split(":", 1)[1].strip()
            memory_type = "project"
            prefix = summary.split(":", 1)[0].strip().lower()
            if prefix in {"user", "feedback", "project", "reference"}:
                memory_type = prefix
            rows.append(
                {
                    "schema_version": 1,
                    "recorded_at": timestamp,
                    "action": action,
                    "memory_type": memory_type,
                    "summary": summary,
                    "receipt": None,
                }
            )
        return rows
    return [
        {
            "schema_version": 1,
            "recorded_at": timestamp,
            "action": "skipped",
            "memory_type": "project",
            "summary": f"No durable memory write was provided for {work_level} closeout.",
            "receipt": None,
        }
    ]


def closeout_markdown(
    *,
    thread_id: str,
    mode: str,
    work_level: str,
    final_state: str,
    timestamp: str,
    summary: str,
    source_of_truth: list[Path],
    receipts: list[str],
    notion_status: str,
    next_action: str | None,
    stale_reason: str | None,
) -> str:
    receipt_lines = receipts or ["closeout.md"]
    source_lines = [path_for_display(path) for path in source_of_truth]
    next_text = next_action if next_action and not next_action_is_clear(next_action) else "None"
    risk = stale_reason or "None"
    return f"""# Thread Closeout

| Field | Value |
| --- | --- |
| Thread | `{thread_id}` |
| Mode | `{mode}` |
| Work Level | `{work_level}` |
| Final State | `{final_state}` |
| Finished At | `{timestamp}` |

## Result

{summary}

## Source Of Truth

{chr(10).join(f"- {value}" for value in source_lines)}

## Receipts

{chr(10).join(f"- {value}" for value in receipt_lines)}

## Notion Projection

- Status: `{notion_status}`
- Receipt: `notion-sync.md`

## Next Action

{next_text}

## Dirty State

- Unrelated: left alone
- Generated: closeout artifacts are in the Agentic OS wrapper path
- Intentional: none recorded

## Risks

- {risk}
"""


def thread_state_payload(
    *,
    thread_id: str,
    timestamp: str,
    work_level: str,
    routed_layer: Path,
    active_work_item: Path | None,
    final_state: str,
    receipts: list[str],
    artifacts: list[str],
    validations: list[str],
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "thread": {
            "id": thread_id,
            "started_at": timestamp,
            "finished_at": timestamp,
            "work_level": work_level,
            "routed_layer": path_for_display(routed_layer),
            "active_work_item": path_for_display(active_work_item) if active_work_item else None,
            "source_repo_context": None,
            "external_refs": {
                "prs": [],
                "jira": [],
                "notion": [],
            },
            "memory": {
                "reads": [],
                "writes": [],
            },
            "evidence": {
                "commands": receipts,
                "artifacts": artifacts,
                "tests": validations,
            },
            "final_state": final_state,
            "dirty_state": {
                "unrelated": [],
                "generated": [],
                "intentional": [],
            },
        },
    }


def closeout_payload(
    *,
    thread_id: str,
    work_level: str,
    mode: str,
    routed_layer: Path,
    active_work_item: Path | None,
    timestamp: str,
    final_state: str,
    summary: str,
    source_of_truth: list[Path],
    receipts: list[str],
    next_action: str | None,
    stale_reason: str | None,
    notion_status: str,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "thread": {
            "id": thread_id,
            "work_level": work_level,
            "closeout_mode": mode,
            "routed_layer": path_for_display(routed_layer),
            "active_work_item": path_for_display(active_work_item) if active_work_item else None,
            "started_at": timestamp,
            "finished_at": timestamp,
        },
        "closeout": {
            "final_state": final_state,
            "summary": summary,
            "source_of_truth": [path_for_display(path) for path in source_of_truth],
            "receipts": receipts,
            "next_action": next_action if next_action and not next_action_is_clear(next_action) else None,
            "blockers": [next_action] if final_state == "blocked" and next_action else [],
            "stale_reason": stale_reason,
        },
        "notion_sync": {
            "status": notion_status,
            "receipt": "notion-sync.md",
        },
        "dirty_state": {
            "unrelated": [],
            "generated": ["closeout artifacts under Agentic OS wrapper"],
            "intentional": [],
        },
    }


def update_work_item_files(target: CloseoutTarget, *, timestamp: str, mode: str, summary: str, next_action: str | None) -> list[Path]:
    updated: list[Path] = []
    if not target.work_item:
        run_log = target.source_of_truth[0]
        section = f"\n## {timestamp} Thread Closeout\n\n- Mode: `{mode}`\n- Summary: {summary}\n- Next action: {next_action or 'None'}\n"
        if append_once(run_log, section):
            updated.append(run_log)
        return updated

    work_root = target.work_item.path
    if work_root.is_file():
        next_text = next_action if next_action and not next_action_is_clear(next_action) else "None"
        section = f"\n## {today_iso()} Thread Closeout\n\n- Finished at: `{timestamp}`\n- Mode: `{mode}`\n- Summary: {summary}\n- Next action: {next_text}\n- Receipt: `{target.artifact_root.relative_to(work_root.parent) / 'closeout.md'}`\n"
        if append_once(work_root, section):
            updated.append(work_root)
        return updated

    worklog = work_root / "WORKLOG.md"
    next_file = work_root / "NEXT.md"
    section = f"\n## {today_iso()} Thread Closeout\n\n- Finished at: `{timestamp}`\n- Mode: `{mode}`\n- Summary: {summary}\n- Receipt: `artifacts/thread-closeouts/{target.artifact_root.name}/closeout.md`\n"
    if append_once(worklog, section):
        updated.append(worklog)
    next_text = next_action if next_action and not next_action_is_clear(next_action) else "None"
    next_section = f"\n## {today_iso()} Thread Closeout\n\n- Current closeout mode: `{mode}`\n- Next action: {next_text}\n"
    if append_once(next_file, next_section):
        updated.append(next_file)

    metadata_path = target.work_item.metadata_path
    metadata = load_yaml_mapping(metadata_path)
    if metadata:
        metadata["updated_at"] = timestamp
        if mode == "archive":
            metadata["status"] = "archived"
            metadata["lane"] = lane_for_status("archived")
            lifecycle = metadata.get("lifecycle") if isinstance(metadata.get("lifecycle"), dict) else {}
            lifecycle["state"] = "archived"
            metadata["lifecycle"] = lifecycle
        before = metadata_path.read_text(encoding="utf-8")
        after = yaml.safe_dump(metadata, sort_keys=False)
        if before != after:
            metadata_path.write_text(after, encoding="utf-8")
            updated.append(metadata_path)
    return updated


def write_archive_manifest(target: CloseoutTarget, *, thread_id: str, timestamp: str, allow_blocked_archive: bool) -> Path:
    path = target.artifact_root / "archive-manifest.yml"
    payload = {
        "schema_version": 1,
        "archive": {
            "archived_at": timestamp,
            "archived_by": "agentic-os",
            "finalizer_mode": "archive",
            "source_thread": thread_id,
            "source_of_truth": [path_for_display(path) for path in target.source_of_truth],
            "closeout_receipt": "closeout.md",
            "unresolved_next_action": allow_blocked_archive,
            "explicit_blocked_archive_accepted": allow_blocked_archive,
            "retained_artifacts": [
                "thread-closeout.yml",
                "closeout.md",
                "evidence.jsonl",
                "memory-write-receipts.jsonl",
                "notion-sync.md",
            ],
        },
    }
    write_yaml(path, payload)
    return path


def close_thread(
    root: str | Path,
    *,
    mode: str = "artifact-closeout",
    thread_id: str | None = None,
    domain: str | None = None,
    project: str | None = None,
    work_item: str | None = None,
    work_level: str | None = None,
    summary: str | None = None,
    next_action: str | None = None,
    validations: list[str] | None = None,
    artifacts: list[str] | None = None,
    receipts: list[str] | None = None,
    memory_receipts: list[str] | None = None,
    notion_url: str | None = None,
    notion_warning: str | None = None,
    verified_notion_workspace: str | None = None,
    skip_notion: bool = False,
    allow_blocked_archive: bool = False,
    request: str | None = None,
    cwd: str | Path | None = None,
    stale_reason: str | None = None,
) -> dict[str, Any]:
    if mode not in CLOSEOUT_MODES:
        raise ValueError(f"mode must be one of {', '.join(CLOSEOUT_MODES)}: {mode!r}")
    resolved_work_level = work_level or ("contextual" if mode == "status-only" else "artifact")
    if resolved_work_level not in WORK_LEVELS:
        raise ValueError(f"work level must be one of {', '.join(WORK_LEVELS)}: {resolved_work_level!r}")
    if mode == "archive" and not allow_blocked_archive and not next_action_is_clear(next_action):
        raise ValueError("archive refused: unresolved --next-action requires --allow-blocked-archive")

    os_root = expand_path(root)
    resolved_thread_id = safe_thread_id(thread_id)
    timestamp = now_iso()
    target = resolve_target(
        os_root,
        resolved_thread_id,
        domain=domain,
        project=project,
        work_item=work_item,
        request=request,
        cwd=Path(cwd).expanduser() if cwd else Path.cwd(),
    )

    final_state = mode_final_state(mode, next_action)
    closeout_summary = summary or f"Thread finalized in {mode} mode."
    validations = list(validations or [])
    artifacts = list(artifacts or [])
    receipts = list(receipts or [])
    memory_receipts = list(memory_receipts or [])

    notion_payload, notion_markdown = notion_receipt(
        work_level=resolved_work_level,
        local_source=target.source_of_truth[0],
        notion_url=notion_url,
        notion_warning=notion_warning,
        verified_workspace=verified_notion_workspace,
        skip_notion=skip_notion,
        timestamp=timestamp,
    )

    target.artifact_root.mkdir(parents=True, exist_ok=True)
    updated_paths = update_work_item_files(
        target,
        timestamp=timestamp,
        mode=mode,
        summary=closeout_summary,
        next_action=next_action,
    )

    evidence = evidence_rows(
        timestamp=timestamp,
        validations=validations,
        artifacts=artifacts,
        receipts=receipts,
        stale_reason=stale_reason,
    )
    memory = memory_rows(timestamp, memory_receipts, resolved_work_level)
    receipt_paths = [
        "thread.yml",
        "thread-closeout.yml",
        "closeout.md",
        "evidence.jsonl",
        "memory-write-receipts.jsonl",
        "notion-sync.md",
    ]
    write_yaml(
        target.artifact_root / "thread.yml",
        thread_state_payload(
            thread_id=resolved_thread_id,
            timestamp=timestamp,
            work_level=resolved_work_level,
            routed_layer=target.root,
            active_work_item=target.work_item.path if target.work_item else None,
            final_state=final_state,
            receipts=receipts,
            artifacts=artifacts,
            validations=validations,
        ),
    )
    write_yaml(
        target.artifact_root / "thread-closeout.yml",
        closeout_payload(
            thread_id=resolved_thread_id,
            work_level=resolved_work_level,
            mode=mode,
            routed_layer=target.root,
            active_work_item=target.work_item.path if target.work_item else None,
            timestamp=timestamp,
            final_state=final_state,
            summary=closeout_summary,
            source_of_truth=target.source_of_truth,
            receipts=receipt_paths,
            next_action=next_action,
            stale_reason=stale_reason,
            notion_status=str(notion_payload["status"]),
        ),
    )
    write_text(
        target.artifact_root / "closeout.md",
        closeout_markdown(
            thread_id=resolved_thread_id,
            mode=mode,
            work_level=resolved_work_level,
            final_state=final_state,
            timestamp=timestamp,
            summary=closeout_summary,
            source_of_truth=target.source_of_truth,
            receipts=receipt_paths,
            notion_status=str(notion_payload["status"]),
            next_action=next_action,
            stale_reason=stale_reason,
        ),
    )
    append_jsonl(target.artifact_root / "evidence.jsonl", evidence)
    append_jsonl(target.artifact_root / "memory-write-receipts.jsonl", memory)
    write_text(target.artifact_root / "notion-sync.md", notion_markdown)
    if mode == "archive":
        archive_path = write_archive_manifest(
            target,
            thread_id=resolved_thread_id,
            timestamp=timestamp,
            allow_blocked_archive=allow_blocked_archive,
        )
        receipt_paths.append(archive_path.name)

    return {
        "ok": True,
        "thread_id": resolved_thread_id,
        "mode": mode,
        "work_level": resolved_work_level,
        "final_state": final_state,
        "target": {
            "kind": target.kind,
            "root": path_for_display(target.root),
            "artifact_root": path_for_display(target.artifact_root),
            "source_of_truth": [path_for_display(path) for path in target.source_of_truth],
        },
        "files": {
            "thread": path_for_display(target.artifact_root / "thread.yml"),
            "closeout": path_for_display(target.artifact_root / "closeout.md"),
            "thread_closeout": path_for_display(target.artifact_root / "thread-closeout.yml"),
            "evidence": path_for_display(target.artifact_root / "evidence.jsonl"),
            "memory_receipts": path_for_display(target.artifact_root / "memory-write-receipts.jsonl"),
            "notion_sync": path_for_display(target.artifact_root / "notion-sync.md"),
        },
        "updated": [path_for_display(path) for path in updated_paths],
        "notion_sync": notion_payload,
        "warnings": [] if notion_payload["status"] != "warning" else [str(notion_payload["warning"])],
    }


def latest_mtime(path: Path) -> datetime | None:
    latest: float | None = None
    if path.is_file():
        try:
            latest = path.stat().st_mtime
        except OSError:
            return None
    else:
        try:
            for child in path.rglob("*"):
                if not child.is_file():
                    continue
                try:
                    mtime = child.stat().st_mtime
                except OSError:
                    continue
                if latest is None or mtime > latest:
                    latest = mtime
        except OSError:
            return None
    if latest is None:
        return None
    return datetime.fromtimestamp(latest, tz=timezone.utc)


def stale_candidates(
    root: Path,
    *,
    older_than_days: int = DEFAULT_STALE_DAYS,
    domain: str | None = None,
    project: str | None = None,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    if older_than_days < 1:
        raise ValueError("older-than-days must be at least 1")
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=older_than_days)
    candidates: list[dict[str, Any]] = []
    for project_root in root_project_dirs(root, domain=domain, project=project):
        for record in local_project_work_items(project_root):
            if record.status not in ACTIVE_WORK_ITEM_STATES:
                continue
            mtime = latest_mtime(record.path)
            if mtime and mtime > cutoff:
                continue
            age_days = (now - mtime).days if mtime else None
            candidates.append(
                {
                    "project": project_root.name,
                    "project_root": path_for_display(project_root),
                    "work_item": record.slug,
                    "title": record.title,
                    "status": record.status,
                    "path": path_for_display(record.path),
                    "last_activity": mtime.isoformat().replace("+00:00", "Z") if mtime else None,
                    "age_days": age_days,
                    "reason": f"untouched for more than {older_than_days} days",
                }
            )
    return candidates


def stale_finalize_threads(
    root: str | Path,
    *,
    older_than_days: int = DEFAULT_STALE_DAYS,
    domain: str | None = None,
    project: str | None = None,
    apply: bool = False,
) -> dict[str, Any]:
    os_root = expand_path(root)
    candidates = stale_candidates(os_root, older_than_days=older_than_days, domain=domain, project=project)
    result: dict[str, Any] = {
        "ok": True,
        "mode": "apply" if apply else "dry-run",
        "older_than_days": older_than_days,
        "candidate_count": len(candidates),
        "candidates": candidates,
        "applied": [],
    }
    if not apply:
        return result
    for candidate in candidates:
        closeout = close_thread(
            os_root,
            mode="status-only",
            thread_id=f"stale_{candidate['work_item']}_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}",
            work_item=str(candidate["work_item"]),
            work_level="contextual",
            summary=f"Stale thread auto-finalization: {candidate['title']}.",
            next_action="Review stale work item if work remains.",
            skip_notion=True,
            stale_reason=str(candidate["reason"]),
            cwd=candidate["path"],
        )
        result["applied"].append(closeout)
    return result
