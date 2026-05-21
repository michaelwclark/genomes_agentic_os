"""Room-first profile install helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .customer import render_agent_router
from .scaffold import create_domain_structure, ensure_dir, expand_path, install_docs, validate_name, write_file_once


def load_os_profile(path: str | Path) -> dict[str, Any]:
    profile_path = expand_path(path)
    if not profile_path.is_file():
        raise ValueError(f"profile file is missing: {profile_path}")
    data = yaml.safe_load(profile_path.read_text(encoding="utf-8")) or {}
    validate_os_profile(data)
    return data


def validate_os_profile(data: dict[str, Any]) -> None:
    if not isinstance(data, dict):
        raise ValueError("profile must be a YAML mapping")
    rooms = data.get("rooms")
    if not isinstance(rooms, list) or not rooms:
        raise ValueError("profile must include at least one room")
    seen = set()
    for room in rooms:
        if not isinstance(room, dict):
            raise ValueError("each room must be a mapping")
        slug = validate_name(str(room.get("slug") or ""), "room.slug")
        if slug in seen:
            raise ValueError(f"duplicate room slug: {slug}")
        seen.add(slug)
        if not room.get("purpose"):
            raise ValueError(f"room {slug!r} is missing purpose")
        if not room.get("done_means"):
            raise ValueError(f"room {slug!r} is missing done_means")
        approvals = room.get("approvals") or data.get("approval_policy")
        if not approvals:
            raise ValueError(f"room {slug!r} is missing approval defaults")


def room_slugs(profile: dict[str, Any]) -> list[str]:
    return [str(room["slug"]) for room in profile["rooms"]]


def profile_root_router(profile: dict[str, Any]) -> str:
    rows = "\n".join(f"| `{room['slug']}` | {room.get('purpose', '')} | `{room['slug']}/ROUTER.md` |" for room in profile["rooms"])
    return f"""# Agent Router

Read this map first, then load only the room router and context files needed for the request.

## Routing Table

| Room | Purpose | Router |
| --- | --- | --- |
{rows}

## Operating Rules

- Route to one room before loading room internals.
- Skip unrelated rooms by default.
- Stop at approval gates before external, production, destructive, billing, legal, secrets, or customer-visible actions.
"""


def room_context(room: dict[str, Any]) -> str:
    inputs = "\n".join(f"- {item}" for item in room.get("inputs", []) or ["TBD"])
    outputs = "\n".join(f"- `{name}` -> `{path}`" for name, path in (room.get("output_folders") or {}).items()) or "- TBD"
    tools = "\n".join(
        f"| {tool.get('name', '')} | {tool.get('trigger', '')} | {tool.get('notes', '')} |"
        for tool in room.get("tools", [])
    ) or "|  |  |  |"
    done = "\n".join(f"- {item}" for item in room.get("done_means", []))
    load_rows = []
    for route in room.get("routing", []):
        load_rows.append(
            f"| {route.get('task', '')} | {', '.join(route.get('read_first', []))} | "
            f"{', '.join(route.get('read_when_needed', []))} | {', '.join(route.get('skip_by_default', []))} | "
            f"{route.get('output_path', '')} |"
        )
    loads = "\n".join(load_rows) or "|  |  |  |  |  |"
    return f"""# Context: {room.get('display_name') or room['slug']}

<!-- room-profile-managed -->

## Purpose

{room.get('purpose', '')}

## Inputs

{inputs}

## Output Folders

{outputs}

## What To Load

| Task | Read First | Read When Needed | Skip By Default | Output Path |
| --- | --- | --- | --- | --- |
{loads}

## Tools And Skills

| Tool Or Skill | Trigger | Notes |
| --- | --- | --- |
{tools}

## Done Means

{done}
"""


def room_router(room: dict[str, Any]) -> str:
    rows = "\n".join(f"| {route.get('task', '')} | {route.get('output_path', '')} |" for route in room.get("routing", [])) or "|  |  |"
    return f"""# Agent Router: {room.get('display_name') or room['slug']}

<!-- room-profile-managed -->

## Where To Put Work

| Task | Output |
| --- | --- |
{rows}

## Approval Rules

External, production, destructive, billing, legal, secrets, and customer-visible actions require approval unless this room profile explicitly says otherwise.
"""


def install_profile_os(target: str | Path, profile_path: str | Path) -> dict[str, Any]:
    profile = load_os_profile(profile_path)
    root = expand_path(target)
    result = _Result()
    root.mkdir(parents=True, exist_ok=True)
    write_file_once(root / "README.md", f"# {profile.get('os', {}).get('display_name', 'Agentic OS')}\n", result)
    write_file_once(root / "ROUTER.md", profile_root_router(profile), result)
    for filename in ("AGENTS.md", "CLAUDE.md", "AGENT.md"):
        write_file_once(root / filename, render_agent_router(), result)
    write_file_once(root / "profile.yml", yaml.safe_dump(profile, sort_keys=False), result)
    install_docs(root)
    for room in profile["rooms"]:
        create_domain_structure(root, room["slug"], result)
        write_room_profile_file(root / room["slug"] / "CONTEXT.md", room_context(room), result)
        write_room_profile_file(root / room["slug"] / "ROUTER.md", room_router(room), result)
    return {"root": str(root), "rooms": room_slugs(profile)}


def write_room_profile_file(path: Path, content: str, result: Any) -> None:
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    if "<!-- room-profile-managed -->" in existing:
        result.skipped.append(path)
        return
    path.write_text(content, encoding="utf-8")
    result.updated.append(path)


def write_profile_template(target: str | Path) -> dict[str, Any]:
    path = expand_path(target)
    content = """os:
  display_name: Example Agentic OS
  owner: Operator
approval_policy:
  external_writes_require_approval: true
rooms:
  - slug: writing_room
    display_name: Writing Room
    purpose: Ideas become polished drafts.
    inputs:
      - rough ideas
    output_folders:
      drafts: drafts
    routing:
      - task: write blog post
        read_first:
          - docs/voice.md
        read_when_needed: []
        skip_by_default: []
        output_path: drafts/
    tools: []
    done_means:
      - output exists in the expected folder
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(content, encoding="utf-8")
    return {"profile": str(path)}


def format_profile_result(result: dict[str, Any]) -> str:
    return yaml.safe_dump(result, sort_keys=False).strip()


@dataclass
class _Result:
    created: list[Path] = field(default_factory=list)
    skipped: list[Path] = field(default_factory=list)
    updated: list[Path] = field(default_factory=list)
