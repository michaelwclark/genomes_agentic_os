"""Future idea and plan capture helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
import re
from typing import Any

import yaml

from .lifecycle import create_project_work_item, slugify_work_id
from .scaffold import (
    append_control_signal,
    append_domain_memory,
    domain_path,
    expand_path,
    normalize_domain,
    shared_factory_path,
    validate_name,
    write_file_once,
)


def slugify_title(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return slug or "future-idea"


def render_future_idea(title: str, summary: str, target: str) -> str:
    return f"""# Future Idea: {title}

## Captured

| Field | Value |
| --- | --- |
| Date | {datetime.now(timezone.utc).date().isoformat()} |
| Target | {target} |
| Status | captured |

## Problem

{summary}

## Outcome

TBD.

## Scope

- TBD.

## Acceptance Criteria

- TBD.

## Validation

- TBD.
"""


def append_once(path: Path, content: str) -> None:
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    if content in existing:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    separator = "" if not existing or existing.endswith("\n") else "\n"
    path.write_text(f"{existing}{separator}{content}", encoding="utf-8")


def classify_control_signal(title: str, summary: str, *, project: bool = False) -> tuple[str, str, str]:
    text = f"{title} {summary}".lower()
    if any(keyword in text for keyword in ("research", "investigate", "discovery", "analysis", "spike")):
        return ("Research", "research", "Research captured for control-plane visibility.")
    if project:
        if any(keyword in text for keyword in ("bug", "fix", "defect", "regression")):
            return ("Project Activity", "bugfix", "Project bugfix captured for control-plane visibility.")
        if any(keyword in text for keyword in ("feature", "build", "implement", "ship")):
            return ("Project Activity", "feature", "Project feature work captured for control-plane visibility.")
        return ("Project Activity", "captured", "Project-scoped idea captured.")
    if any(keyword in text for keyword in ("workflow", "runbook", "process")):
        return ("Workflow Opportunities", "candidate", "Workflow opportunity captured before promotion.")
    if any(keyword in text for keyword in ("automation", "heartbeat", "scheduled", "disabled", "enable")):
        return ("Automation Status", "candidate", "Automation opportunity captured before promotion.")
    return ("Ideas", "captured", "Domain idea captured before promotion.")


def capture_plan(
    root: str | Path,
    *,
    title: str,
    summary: str,
    kind: str = "os",
    domain: str | None = None,
    project: str | None = None,
) -> dict[str, Any]:
    os_root = expand_path(root)
    if kind not in {"os", "domain", "customer"}:
        raise ValueError(f"kind must be one of os, domain, customer: {kind!r}")
    if kind == "os":
        plans_root = shared_factory_path(os_root, "05-knowledge", "plans")
        target = plans_root / "future-ideas" / f"{slugify_title(title)}.md"
        write_file_once(target, render_future_idea(title, summary, "shared_factory plans"), _Result())
        append_once(plans_root / "README.md", f"| `{target.relative_to(plans_root)}` | captured | {title} |\n")
        return {"target": str(target), "kind": kind, "status": "captured"}

    if not domain:
        raise ValueError("domain is required for domain or customer plan capture")
    domain = normalize_domain(domain)
    domain_root = domain_path(os_root, domain)
    if project:
        project = validate_name(project, "project")
        signal_section, signal_status, signal_notes = classify_control_signal(title, summary, project=True)
        work_id = slugify_work_id(title)
        work_item_root = domain_root / "02-projects" / project / "work-items" / work_id
        create_project_work_item(
            os_root,
            domain,
            project,
            title=title,
            summary=summary,
            status="captured",
            work_id=work_id,
        )
        target = work_item_root / "IDEA.md"
        append_once(
            domain_root / "02-projects" / project / "status.md",
            f"\n## Future Idea: {title}\n\n- Kind: `{kind}`\n- Summary: {summary}\n- Status: {signal_status}\n",
        )
        append_once(
            domain_root / "00-control-plane" / "active-work.md",
            f"| `{project}/{work_id}` | `{signal_status}` | OS Owner | Triage project signal `{title}`. | `02-projects/{project}/work-items/{work_id}/` |\n",
        )
        append_control_signal(
            domain_root,
            signal_section,
            f"`{project}` {signal_status}: {title}",
            signal_status,
            f"`02-projects/{project}/work-items/{work_id}/`",
            signal_notes,
            _Result(),
        )
        append_domain_memory(domain_root, f"Captured project signal `{title}` for `{project}` with status `{signal_status}`; lifecycle work item is in `02-projects/{project}/work-items/{work_id}/`.", _Result())
        return {
            "target": str(target),
            "work_item": str(work_item_root),
            "kind": kind,
            "status": signal_status,
        }

    target = domain_root / "01-inbox" / "raw-ideas.md"
    if not target.is_file():
        raise ValueError(f"domain inbox file is missing: {target}")
    signal_section, signal_status, signal_notes = classify_control_signal(title, summary, project=False)
    append_once(target, f"\n## {title}\n\n- Kind: `{kind}`\n- Summary: {summary}\n- Status: {signal_status}\n")
    append_once(
        domain_root / "01-inbox" / "triage.md",
        (
            f"| {datetime.now(timezone.utc).date().isoformat()} | {title} | `{domain}` |  | idea_capture | low | "
            f"{signal_status} | `01-inbox/raw-ideas.md` |\n"
        ),
    )
    append_once(
        domain_root / "00-control-plane" / "active-work.md",
        f"| `{title}` | `{signal_status}` | OS Owner | Triage domain signal. | `01-inbox/raw-ideas.md` |\n",
    )
    append_control_signal(
        domain_root,
        signal_section,
        title,
        signal_status,
        "`01-inbox/raw-ideas.md`",
        signal_notes,
        _Result(),
    )
    append_domain_memory(domain_root, f"Captured domain signal `{title}` with status `{signal_status}`; first record is in `01-inbox/raw-ideas.md`.", _Result())
    return {"target": str(target), "kind": kind, "status": signal_status}


def format_plan_result(result: dict[str, Any]) -> str:
    return yaml.safe_dump(result, sort_keys=False).strip()


@dataclass
class _Result:
    created: list[Path] = field(default_factory=list)
    skipped: list[Path] = field(default_factory=list)
    updated: list[Path] = field(default_factory=list)
