"""Future idea and plan capture helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
import re
from typing import Any

import yaml

from .scaffold import expand_path, normalize_domain, validate_name, write_file_once


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
        plans_root = os_root / "shared_factory" / "05-knowledge" / "plans"
        target = plans_root / "future-ideas" / f"{slugify_title(title)}.md"
        write_file_once(target, render_future_idea(title, summary, "shared_factory plans"), _Result())
        append_once(plans_root / "README.md", f"| `{target.relative_to(plans_root)}` | captured | {title} |\n")
        return {"target": str(target), "kind": kind, "status": "captured"}

    if not domain:
        raise ValueError("domain is required for domain or customer plan capture")
    domain = normalize_domain(domain)
    if project:
        project = validate_name(project, "project")
        target = os_root / domain / "02-projects" / project / "status.md"
        if not target.is_file():
            raise ValueError(f"project status file is missing: {target}")
        append_once(
            target,
            f"\n## Future Idea: {title}\n\n- Kind: `{kind}`\n- Summary: {summary}\n- Status: captured\n",
        )
        return {"target": str(target), "kind": kind, "status": "captured"}

    target = os_root / domain / "01-inbox" / "raw-ideas.md"
    if not target.is_file():
        raise ValueError(f"domain inbox file is missing: {target}")
    append_once(target, f"\n## {title}\n\n- Kind: `{kind}`\n- Summary: {summary}\n- Status: captured\n")
    return {"target": str(target), "kind": kind, "status": "captured"}


def format_plan_result(result: dict[str, Any]) -> str:
    return yaml.safe_dump(result, sort_keys=False).strip()


@dataclass
class _Result:
    created: list[Path] = field(default_factory=list)
    skipped: list[Path] = field(default_factory=list)
    updated: list[Path] = field(default_factory=list)
