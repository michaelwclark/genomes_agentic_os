#!/usr/bin/env python3
"""Create or update an Agentic OS initiative context pack.

The script intentionally writes small managed blocks into project indexes so it
can be rerun as an initiative changes without duplicating entries.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path
from typing import Iterable

try:
    import yaml  # type: ignore
except Exception:  # pragma: no cover - fallback for minimal Python envs
    yaml = None


REQUIRED_PACKET_FILES = [
    "CONTEXT.md",
    "SPEC.md",
    "PLAN.md",
    "DECISIONS.md",
    "NEXT.md",
    "WORKLOG.md",
]


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_key_value(raw: str) -> tuple[str, str]:
    if "=" not in raw:
        raise argparse.ArgumentTypeError(f"expected LABEL=VALUE, got {raw!r}")
    key, value = raw.split("=", 1)
    key = key.strip()
    value = value.strip()
    if not key or not value:
        raise argparse.ArgumentTypeError(f"expected non-empty LABEL=VALUE, got {raw!r}")
    return key, value


def derive_domain_project(project_path: Path) -> tuple[str, str]:
    parts = project_path.resolve().parts
    project = project_path.name
    if "02-projects" in parts:
        idx = parts.index("02-projects")
        if idx > 0:
            return parts[idx - 1], project
    return "unknown", project


def marker(identifier: str, body: str) -> str:
    return (
        f"<!-- initiative-context-resume:{identifier}:start -->\n"
        f"{body.rstrip()}\n"
        f"<!-- initiative-context-resume:{identifier}:end -->\n"
    )


def upsert_marker_block(path: Path, identifier: str, body: str) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = path.read_text() if path.exists() else ""
    block = marker(identifier, body)
    pattern = re.compile(
        rf"<!-- initiative-context-resume:{re.escape(identifier)}:start -->.*?"
        rf"<!-- initiative-context-resume:{re.escape(identifier)}:end -->\n?",
        re.DOTALL,
    )
    if pattern.search(existing):
        updated = pattern.sub(block, existing)
    else:
        sep = "\n" if existing and not existing.endswith("\n") else ""
        updated = f"{existing}{sep}\n{block}" if existing else block
    if updated != existing:
        path.write_text(updated)
        return True
    return False


def write_if_missing(path: Path, content: str) -> bool:
    if path.exists():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.rstrip() + "\n")
    return True


def write_text_if_changed(path: Path, content: str) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    normalized = content.rstrip() + "\n"
    existing = path.read_text() if path.exists() else None
    if existing == normalized:
        return False
    path.write_text(normalized)
    return True


def bullet_lines(items: Iterable[str]) -> str:
    values = [item.strip() for item in items if item.strip()]
    if not values:
        return "- None captured yet."
    return "\n".join(f"- {item}" for item in values)


def kv_lines(items: Iterable[tuple[str, str]]) -> str:
    values = [(k.strip(), v.strip()) for k, v in items if k.strip() and v.strip()]
    if not values:
        return "- None captured yet."
    return "\n".join(f"- {k}: {v}" for k, v in values)


def relative_to_project(path: Path, project_path: Path) -> str:
    try:
        return str(path.relative_to(project_path))
    except ValueError:
        return str(path)


def dump_work_yml(data: dict) -> str:
    if yaml is not None:
        return yaml.safe_dump(data, sort_keys=False, allow_unicode=False)
    return json.dumps(data, indent=2, sort_keys=False)


def load_work_yml(path: Path) -> dict:
    if not path.exists():
        return {}
    raw = path.read_text()
    if yaml is not None:
        loaded = yaml.safe_load(raw)
        return loaded if isinstance(loaded, dict) else {}
    try:
        loaded = json.loads(raw)
        return loaded if isinstance(loaded, dict) else {}
    except json.JSONDecodeError:
        return {}


def build_context(args: argparse.Namespace, domain: str, project: str, work_item_dir: Path) -> str:
    context_rel = relative_to_project(work_item_dir / "CONTEXT.md", args.project_path)
    return f"""# Context Pack: {args.title}

| Field | Value |
| --- | --- |
| Domain | `{domain}` |
| Project | `{project}` |
| Work Item | `{args.work_item_id}` |
| Lane | `{args.lane}` |
| Status | `{args.status}` |
| Phase | `{args.phase}` |
| Updated | `{args.updated_at}` |

## Summary

{args.summary}

## Resume Load Order

1. Read project routing and status in `{args.project_path}`.
2. Read this context pack: `{context_rel}`.
3. Load the source-of-truth docs and artifacts listed below.
4. Load only the code anchors needed for the next action.
5. Check `NEXT.md` and `WORKLOG.md` before changing scope.

## Source Of Truth

{kv_lines(args.source)}

## Artifacts

{kv_lines(args.artifact)}

## Decisions

{bullet_lines(args.decision)}

## Code Anchors

{bullet_lines(args.code_anchor)}

## Open Questions

{bullet_lines(args.open_question)}

## Next Actions

{bullet_lines(args.next_action)}

## External Output Boundary

- Keep private Notion links, local filesystem paths, and OS-internal run artifacts out of Jira, GitHub, Slack, and work email unless the user explicitly approves sharing them.
- Use this local context pack to derive external-ready summaries when Jira or software SPEC work starts.

## Staleness Rule

- Refresh this context after major Notion/spec changes, Claude Design output, Jira conversion, codebase implementation, or any material phase change.
"""


def build_simple_doc(title: str, body: str) -> str:
    return f"# {title}\n\n{body.rstrip()}\n"


def update_work_yml(path: Path, args: argparse.Namespace, domain: str, project: str) -> bool:
    data = load_work_yml(path)
    created_at = data.get("created_at") or args.updated_at
    required_files = list(REQUIRED_PACKET_FILES)
    if args.open_question:
        required_files.append("QUESTIONS.md")
    data.update(
        {
            "id": args.work_item_id,
            "title": args.title,
            "domain": domain,
            "project": project,
            "status": args.status,
            "lane": args.lane,
            "format": "folder",
            "created_at": created_at,
            "updated_at": args.updated_at,
            "summary": args.summary,
            "lifecycle": {
                "state": args.status,
                "state_vocabulary": [
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
                ],
                "required_files": required_files,
                "conversation_logs": "logs/conversations",
            },
            "context": {
                "pack": "CONTEXT.md",
                "generated_by": "initiative-context-resume",
                "phase": args.phase,
            },
            "sources": {key: value for key, value in args.source},
            "artifacts": {key: value for key, value in args.artifact},
        }
    )
    return write_text_if_changed(path, dump_work_yml(data))


def update_project_indexes(args: argparse.Namespace, domain: str, project: str, work_item_dir: Path) -> list[str]:
    changed: list[str] = []
    work_rel = relative_to_project(work_item_dir, args.project_path)
    context_rel = relative_to_project(work_item_dir / "CONTEXT.md", args.project_path)
    status_body = f"""## Initiative: {args.title}

- Status: `{args.status}`
- Phase: `{args.phase}`
- Path: `{work_rel}`
- Context: `{context_rel}`
- Updated: `{args.updated_at}`
- Next: {args.next_action[0] if args.next_action else "Review context pack and confirm next action."}
"""
    source_body = f"""## Initiative Sources: {args.title}

- Context pack: `{context_rel}`
- Work item: `{work_rel}`

### Source Of Truth

{kv_lines(args.source)}

### Artifacts

{kv_lines(args.artifact)}

### Code Anchors

{bullet_lines(args.code_anchor)}
"""
    if upsert_marker_block(args.project_path / "status.md", f"status:{args.work_item_id}", status_body):
        changed.append(str(args.project_path / "status.md"))
    if upsert_marker_block(args.project_path / "source-map.md", f"source-map:{args.work_item_id}", source_body):
        changed.append(str(args.project_path / "source-map.md"))
    if args.active_work_file:
        active_path = args.active_work_file
        active_body = f"""## Initiative: {project}/{args.work_item_id}

- Status: `{args.status}`
- Phase: `{args.phase}`
- Project: `{args.project_path}`
- Work item: `{work_item_dir}`
- Context: `{work_item_dir / "CONTEXT.md"}`
- Next: {args.next_action[0] if args.next_action else "Review context pack and confirm next action."}
"""
        if upsert_marker_block(active_path, f"active-work:{project}:{args.work_item_id}", active_body):
            changed.append(str(active_path))
    return changed


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-path", type=Path, required=True)
    parser.add_argument("--work-item-id", required=True)
    parser.add_argument("--lane", default="01-intake")
    parser.add_argument("--title", required=True)
    parser.add_argument("--summary", required=True)
    parser.add_argument("--status", default="captured")
    parser.add_argument("--phase", default="planning")
    parser.add_argument("--source", action="append", type=parse_key_value, default=[])
    parser.add_argument("--artifact", action="append", type=parse_key_value, default=[])
    parser.add_argument("--code-anchor", action="append", default=[])
    parser.add_argument("--decision", action="append", default=[])
    parser.add_argument("--open-question", action="append", default=[])
    parser.add_argument("--next-action", action="append", default=[])
    parser.add_argument("--active-work-file", type=Path)
    parser.add_argument("--updated-at", help="Override the generated UTC timestamp for reproducible validation.")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    args.project_path = args.project_path.resolve()
    if args.active_work_file:
        args.active_work_file = args.active_work_file.resolve()
    args.updated_at = args.updated_at or utc_now()

    domain, project = derive_domain_project(args.project_path)
    work_item_dir = args.project_path / "work-items" / args.lane / args.work_item_id
    context = build_context(args, domain, project, work_item_dir)

    planned_paths = [
        work_item_dir / "CONTEXT.md",
        work_item_dir / "work.yml",
        work_item_dir / "SPEC.md",
        work_item_dir / "PLAN.md",
        work_item_dir / "DECISIONS.md",
        work_item_dir / "NEXT.md",
        work_item_dir / "WORKLOG.md",
        args.project_path / "status.md",
        args.project_path / "source-map.md",
    ]
    if args.open_question:
        planned_paths.append(work_item_dir / "QUESTIONS.md")
    if args.active_work_file:
        planned_paths.append(args.active_work_file)

    if args.dry_run:
        print(json.dumps({"would_update": [str(path) for path in planned_paths]}, indent=2))
        return 0

    changed: list[str] = []
    if write_text_if_changed(work_item_dir / "CONTEXT.md", context):
        changed.append(str(work_item_dir / "CONTEXT.md"))
    if update_work_yml(work_item_dir / "work.yml", args, domain, project):
        changed.append(str(work_item_dir / "work.yml"))

    initial_docs = {
        "SPEC.md": build_simple_doc(
            f"Spec Notes: {args.title}",
            "Canonical design/spec content is still being developed. Use CONTEXT.md as the resume map and source-of-truth index until this file is expanded.",
        ),
        "PLAN.md": build_simple_doc(
            f"Plan: {args.title}",
            "Use the source-of-truth docs and artifacts in CONTEXT.md. Do not convert to Jira until the design/spec is validated.",
        ),
        "DECISIONS.md": build_simple_doc(f"Decisions: {args.title}", bullet_lines(args.decision)),
        "NEXT.md": build_simple_doc(f"Next: {args.title}", bullet_lines(args.next_action)),
    }
    if args.open_question:
        initial_docs["QUESTIONS.md"] = build_simple_doc(f"Questions: {args.title}", bullet_lines(args.open_question))
    for filename, content in initial_docs.items():
        if write_if_missing(work_item_dir / filename, content):
            changed.append(str(work_item_dir / filename))

    worklog_body = f"""## Context Pack Update

- Updated: `{args.updated_at}`
- Skill: `initiative-context-resume`
- Context: `CONTEXT.md`
- Status: `{args.status}`
- Phase: `{args.phase}`
"""
    if upsert_marker_block(work_item_dir / "WORKLOG.md", f"worklog:{args.work_item_id}", worklog_body):
        changed.append(str(work_item_dir / "WORKLOG.md"))

    changed.extend(update_project_indexes(args, domain, project, work_item_dir))
    result = {
        "domain": domain,
        "project": project,
        "work_item": str(work_item_dir),
        "context_pack": str(work_item_dir / "CONTEXT.md"),
        "changed": changed,
    }
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
