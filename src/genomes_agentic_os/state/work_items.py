"""Canonical local work-item truth and compact active-context projections."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
from typing import Any, Mapping
from uuid import uuid4

import yaml

from .db import transaction, utc_now_iso

CANONICAL_STATES = (
    "captured",
    "triaged",
    "specified",
    "ready",
    "building",
    "validating",
    "blocked",
    "finished",
    "documented",
    "archived",
)
ATTENTION_STATES = ("active", "queued", "parked", "closed")
TERMINAL_STATES = {"finished", "documented", "archived"}
ACTIVE_NOW_RELATIVE = Path("harness/shared_factory/00-control-plane/active-now.json")
IDENTIFIER = re.compile(r"^[a-z0-9][a-z0-9_.:-]*$")
LEGACY_LANE_STATE = {
    "01-intake": ("captured", "queued"),
    "02-active": ("ready", "queued"),
    "03-complete": ("finished", "closed"),
}


class WorkItemError(ValueError):
    """Raised when canonical work-item state would become ambiguous."""


def _identifier(value: Any, label: str) -> str:
    normalized = str(value or "").strip().lower().replace(" ", "-")
    if not IDENTIFIER.fullmatch(normalized):
        raise WorkItemError(f"invalid {label}: {value!r}")
    return normalized


def _optional(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _json_mapping(value: Mapping[str, Any] | None) -> str:
    return json.dumps(dict(value or {}), sort_keys=True, separators=(",", ":"))


def _normalize(
    *,
    item_id: str,
    title: str,
    state: str,
    attention: str,
    domain: str | None,
    project: str | None,
    source_system: str | None,
    source_key: str | None,
    source_url: str | None,
    owner: str | None,
    priority: int,
    packet_path: str | None,
    worktree_path: str | None,
    branch: str | None,
    context_summary: str,
    blocked_reason: str | None,
    metadata: Mapping[str, Any] | None,
) -> dict[str, Any]:
    item_id = _identifier(item_id, "work-item id")
    state = _identifier(state, "work-item state")
    attention = _identifier(attention, "attention state")
    if state not in CANONICAL_STATES:
        raise WorkItemError(f"unsupported work-item state: {state}")
    if attention not in ATTENTION_STATES:
        raise WorkItemError(f"unsupported attention state: {attention}")
    title = str(title or "").strip()
    if not title:
        raise WorkItemError("work-item title is required")
    if state in TERMINAL_STATES:
        attention = "closed"
    if attention == "closed" and state not in TERMINAL_STATES:
        raise WorkItemError("closed attention requires finished, documented, or archived state")
    context_summary = str(context_summary or "").strip()
    if attention == "active" and not context_summary:
        raise WorkItemError("active work items require a context summary")
    blocked_reason = _optional(blocked_reason)
    if state == "blocked" and not blocked_reason:
        raise WorkItemError("blocked work items require a blocker receipt or reason")
    source_system = _optional(source_system)
    source_key = _optional(source_key)
    if bool(source_system) != bool(source_key):
        raise WorkItemError("source_system and source_key must be supplied together")
    return {
        "id": item_id,
        "title": title,
        "state": state,
        "attention": attention,
        "domain": _identifier(domain, "domain") if domain else None,
        "project": _identifier(project, "project") if project else None,
        "source_system": source_system,
        "source_key": source_key,
        "source_url": _optional(source_url),
        "owner": _optional(owner),
        "priority": int(priority),
        "packet_path": _optional(packet_path),
        "worktree_path": _optional(worktree_path),
        "branch": _optional(branch),
        "context_summary": context_summary,
        "blocked_reason": blocked_reason,
        "metadata_json": _json_mapping(metadata),
    }


def _row(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    result = dict(row)
    result["metadata"] = json.loads(result.pop("metadata_json") or "{}")
    return result


def get(conn: sqlite3.Connection, item_id: str) -> dict[str, Any] | None:
    return _row(conn.execute("SELECT * FROM work_items WHERE id = ?", (item_id,)).fetchone())


def upsert(
    conn: sqlite3.Connection,
    *,
    item_id: str,
    title: str,
    state: str = "captured",
    attention: str = "queued",
    domain: str | None = None,
    project: str | None = None,
    source_system: str | None = None,
    source_key: str | None = None,
    source_url: str | None = None,
    owner: str | None = None,
    priority: int = 0,
    packet_path: str | None = None,
    worktree_path: str | None = None,
    branch: str | None = None,
    context_summary: str = "",
    blocked_reason: str | None = None,
    metadata: Mapping[str, Any] | None = None,
    actor: str = "agentic-os",
    receipt_ref: str | None = None,
    verified: bool = False,
    now: str | None = None,
) -> dict[str, Any]:
    normalized = _normalize(
        item_id=item_id,
        title=title,
        state=state,
        attention=attention,
        domain=domain,
        project=project,
        source_system=source_system,
        source_key=source_key,
        source_url=source_url,
        owner=owner,
        priority=priority,
        packet_path=packet_path,
        worktree_path=worktree_path,
        branch=branch,
        context_summary=context_summary,
        blocked_reason=blocked_reason,
        metadata=metadata,
    )
    timestamp = now or utc_now_iso()
    existing = get(conn, normalized["id"])
    previous_state = existing["state"] if existing else None
    previous_attention = existing["attention"] if existing else None
    closed_at = timestamp if normalized["attention"] == "closed" else None
    last_verified = timestamp if verified else (existing or {}).get("last_verified_at")
    with transaction(conn):
        conn.execute(
            """
            INSERT INTO work_items (
                id, title, state, attention, domain, project, source_system,
                source_key, source_url, owner, priority, packet_path,
                worktree_path, branch, context_summary, blocked_reason,
                previous_state, metadata_json, created_at, updated_at,
                last_verified_at, closed_at
            ) VALUES (
                :id, :title, :state, :attention, :domain, :project,
                :source_system, :source_key, :source_url, :owner, :priority,
                :packet_path, :worktree_path, :branch, :context_summary,
                :blocked_reason, :previous_state, :metadata_json, :created_at,
                :updated_at, :last_verified_at, :closed_at
            )
            ON CONFLICT(id) DO UPDATE SET
                title = excluded.title,
                state = excluded.state,
                attention = excluded.attention,
                domain = excluded.domain,
                project = excluded.project,
                source_system = excluded.source_system,
                source_key = excluded.source_key,
                source_url = excluded.source_url,
                owner = excluded.owner,
                priority = excluded.priority,
                packet_path = excluded.packet_path,
                worktree_path = excluded.worktree_path,
                branch = excluded.branch,
                context_summary = excluded.context_summary,
                blocked_reason = excluded.blocked_reason,
                previous_state = excluded.previous_state,
                metadata_json = excluded.metadata_json,
                updated_at = excluded.updated_at,
                last_verified_at = excluded.last_verified_at,
                closed_at = excluded.closed_at
            """,
            {
                **normalized,
                "previous_state": previous_state,
                "created_at": (existing or {}).get("created_at") or timestamp,
                "updated_at": timestamp,
                "last_verified_at": last_verified,
                "closed_at": closed_at,
            },
        )
        changed = (
            existing is None
            or previous_state != normalized["state"]
            or previous_attention != normalized["attention"]
        )
        if changed:
            conn.execute(
                """
                INSERT INTO work_item_history (
                    work_item_id, changed_at, actor, from_state, to_state,
                    from_attention, to_attention, summary, receipt_ref,
                    metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    normalized["id"],
                    timestamp,
                    actor,
                    previous_state,
                    normalized["state"],
                    previous_attention,
                    normalized["attention"],
                    normalized["context_summary"],
                    _optional(receipt_ref),
                    normalized["metadata_json"],
                ),
            )
    return get(conn, normalized["id"]) or {}


def update(
    conn: sqlite3.Connection,
    item_id: str,
    *,
    state: str | None = None,
    attention: str | None = None,
    context_summary: str | None = None,
    blocked_reason: str | None = None,
    worktree_path: str | None = None,
    branch: str | None = None,
    actor: str = "agentic-os",
    receipt_ref: str | None = None,
    verified: bool = False,
    now: str | None = None,
) -> dict[str, Any]:
    current = get(conn, _identifier(item_id, "work-item id"))
    if current is None:
        raise WorkItemError(f"work item not found: {item_id}")
    next_state = state or current["state"]
    next_attention = attention or current["attention"]
    if state and next_state not in TERMINAL_STATES and next_attention == "closed":
        next_attention = "parked"
    next_blocked_reason = (
        blocked_reason if blocked_reason is not None else current["blocked_reason"]
    )
    if state and next_state != "blocked" and blocked_reason is None:
        next_blocked_reason = None
    return upsert(
        conn,
        item_id=current["id"],
        title=current["title"],
        state=next_state,
        attention=next_attention,
        domain=current["domain"],
        project=current["project"],
        source_system=current["source_system"],
        source_key=current["source_key"],
        source_url=current["source_url"],
        owner=current["owner"],
        priority=current["priority"],
        packet_path=current["packet_path"],
        worktree_path=worktree_path if worktree_path is not None else current["worktree_path"],
        branch=branch if branch is not None else current["branch"],
        context_summary=(
            context_summary if context_summary is not None else current["context_summary"]
        ),
        blocked_reason=next_blocked_reason,
        metadata=current["metadata"],
        actor=actor,
        receipt_ref=receipt_ref,
        verified=verified,
        now=now,
    )


def query(
    conn: sqlite3.Connection,
    *,
    attention: str | None = None,
    state: str | None = None,
    domain: str | None = None,
    project: str | None = None,
    limit: int = 300,
) -> list[dict[str, Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if attention:
        clauses.append("attention = ?")
        params.append(_identifier(attention, "attention state"))
    if state:
        clauses.append("state = ?")
        params.append(_identifier(state, "work-item state"))
    if domain:
        clauses.append("domain = ?")
        params.append(_identifier(domain, "domain"))
    if project:
        clauses.append("project = ?")
        params.append(_identifier(project, "project"))
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = conn.execute(
        f"""
        SELECT * FROM work_items{where}
        ORDER BY
            CASE attention WHEN 'active' THEN 0 WHEN 'queued' THEN 1
                WHEN 'parked' THEN 2 ELSE 3 END,
            priority DESC,
            updated_at DESC,
            id
        LIMIT ?
        """,
        (*params, max(1, int(limit))),
    ).fetchall()
    return [_row(row) or {} for row in rows]


def migrate_path_prefix(
    conn: sqlite3.Connection,
    *,
    from_prefix: str,
    to_prefix: str,
    domain: str | None = None,
    dry_run: bool = True,
    actor: str = "agentic-os",
    receipt_ref: str | None = None,
    now: str | None = None,
) -> dict[str, Any]:
    """Plan or atomically migrate canonical path-bearing work-item fields."""

    old_prefix = str(from_prefix or "").strip()
    new_prefix = str(to_prefix or "").strip()
    if not old_prefix or not new_prefix:
        raise WorkItemError("both path prefixes are required")
    if old_prefix == new_prefix:
        raise WorkItemError("path prefixes must differ")
    normalized_domain = _identifier(domain, "domain") if domain else None
    rows = query(conn, domain=normalized_domain, limit=1_000_000)
    changes: list[dict[str, Any]] = []
    path_fields = ("source_key", "packet_path", "worktree_path")
    for item in rows:
        field_changes: dict[str, dict[str, str]] = {}
        for field in path_fields:
            current = item.get(field)
            if not isinstance(current, str) or not current.startswith(old_prefix):
                continue
            field_changes[field] = {
                "from": current,
                "to": f"{new_prefix}{current[len(old_prefix):]}",
            }
        if field_changes:
            changes.append({"id": item["id"], "fields": field_changes})

    result = {
        "api_version": "agentic-os-work-path-migration/v1",
        "status": "planned" if dry_run else "migrated",
        "dry_run": dry_run,
        "from_prefix": old_prefix,
        "to_prefix": new_prefix,
        "domain": normalized_domain,
        "item_count": len(changes),
        "field_count": sum(len(change["fields"]) for change in changes),
        "changes": changes,
    }
    if dry_run or not changes:
        return result

    timestamp = now or utc_now_iso()
    with transaction(conn):
        for change in changes:
            assignments = ", ".join(
                f"{field} = ?" for field in change["fields"]
            )
            values = [details["to"] for details in change["fields"].values()]
            conn.execute(
                f"UPDATE work_items SET {assignments}, updated_at = ? WHERE id = ?",
                (*values, timestamp, change["id"]),
            )
            current = get(conn, change["id"]) or {}
            conn.execute(
                """
                INSERT INTO work_item_history (
                    work_item_id, changed_at, actor, from_state, to_state,
                    from_attention, to_attention, summary, receipt_ref,
                    metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    change["id"],
                    timestamp,
                    actor,
                    current.get("state"),
                    current.get("state"),
                    current.get("attention"),
                    current.get("attention"),
                    f"Migrated path prefix {old_prefix!r} to {new_prefix!r}.",
                    _optional(receipt_ref),
                    _json_mapping({"path_prefix_migration": change["fields"]}),
                ),
            )
    return result


def active_now(conn: sqlite3.Connection, *, stale_hours: int = 72) -> dict[str, Any]:
    rows = conn.execute(
        "SELECT * FROM active_now ORDER BY priority DESC, updated_at DESC, id"
    ).fetchall()
    threshold = datetime.now(timezone.utc) - timedelta(hours=max(1, stale_hours))
    items: list[dict[str, Any]] = []
    for row in rows:
        item = _row(row) or {}
        verified = item.get("last_verified_at")
        try:
            verified_at = datetime.fromisoformat(str(verified).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            verified_at = None
        item["verification_stale"] = verified_at is None or verified_at < threshold
        items.append(item)
    return {
        "api_version": "agentic-os-active-now/v1",
        "generated_at": utc_now_iso(),
        "source_of_truth": "harness/shared_factory/00-control-plane/state.db",
        "stale_after_hours": max(1, stale_hours),
        "active_count": len(items),
        "stale_count": sum(bool(item["verification_stale"]) for item in items),
        "items": items,
    }


def write_active_projection(
    conn: sqlite3.Connection,
    root: str | Path,
    *,
    stale_hours: int = 72,
) -> dict[str, Any]:
    os_root = Path(root).expanduser().resolve()
    path = os_root / ACTIVE_NOW_RELATIVE
    payload = active_now(conn, stale_hours=stale_hours)
    encoded = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{uuid4().hex}.tmp")
    try:
        with temporary.open("wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
    return {**payload, "projection": ACTIVE_NOW_RELATIVE.as_posix()}


def _legacy_summary(path: Path) -> str:
    for name in ("NEXT.md", "WORKLOG.md", "README.md", "SPEC.md", "PLAN.md"):
        candidate = path / name
        if not candidate.is_file() or candidate.stat().st_size > 1_000_000:
            continue
        try:
            body = candidate.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        paragraphs: list[str] = []
        for line in body.splitlines():
            text = line.strip().lstrip("#").strip()
            if not text or text in {"---", "..."} or text.startswith(("<!--", "|")):
                if paragraphs:
                    break
                continue
            paragraphs.append(text)
            if sum(len(item) for item in paragraphs) >= 500:
                break
        if paragraphs:
            return " ".join(paragraphs)[:600]
    return "Imported from the legacy filesystem; needs context verification."


def legacy_import_plan(root: str | Path) -> dict[str, Any]:
    os_root = Path(root).expanduser().resolve()
    candidates: list[dict[str, Any]] = []
    seen_paths: set[Path] = set()
    indexed_state: dict[Path, str] = {}
    active_index = os_root / "00-control-plane/active/index.yml"
    if active_index.is_file():
        try:
            index_payload = yaml.safe_load(active_index.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError):
            index_payload = {}
        for item in index_payload.get("work_items") or []:
            if not isinstance(item, Mapping) or not item.get("target"):
                continue
            status = str(item.get("status") or "").strip().lower()
            if status in CANONICAL_STATES:
                indexed_state[Path(str(item["target"])).expanduser().resolve()] = status
    project_roots = [
        *os_root.glob("*/02-projects/*"),
        *os_root.glob("domains/*/projects/*"),
    ]
    for project_root in sorted(set(project_roots)):
        work_root = project_root / "work-items"
        if not work_root.is_dir():
            continue
        try:
            relative_project = project_root.relative_to(os_root)
        except ValueError:
            continue
        parts = relative_project.parts
        if parts[0] == "domains":
            domain, project = parts[1], parts[3]
        else:
            domain, project = parts[0], parts[2]
        for lane, (state, attention) in LEGACY_LANE_STATE.items():
            lane_root = work_root / lane
            if not lane_root.is_dir():
                continue
            for packet in sorted(
                path
                for path in lane_root.iterdir()
                if path.is_dir()
                and not path.name.startswith(".")
                and not path.name.endswith(".artifacts")
            ):
                resolved = packet.resolve()
                if resolved in seen_paths:
                    continue
                seen_paths.add(resolved)
                slug = re.sub(r"[^a-z0-9_.-]+", "-", packet.name.lower()).strip("-.")
                digest = hashlib.sha256(str(packet.relative_to(os_root)).encode()).hexdigest()[:10]
                item_id = _identifier(f"{domain}:{project}:{slug or digest}", "work-item id")
                indexed = indexed_state.get(resolved)
                item_state = state
                item_attention = attention
                if indexed:
                    item_state = indexed
                    if item_state in TERMINAL_STATES:
                        item_attention = "closed"
                    elif item_state in {"building", "validating", "blocked"}:
                        item_attention = "parked"
                    else:
                        item_attention = "queued"
                candidates.append(
                    {
                        "id": item_id,
                        "title": packet.name.replace("_", " ").replace("-", " ").strip().title(),
                        "state": item_state,
                        "attention": item_attention,
                        "domain": domain,
                        "project": project,
                        "source_system": "legacy-filesystem",
                        "source_key": packet.relative_to(os_root).as_posix(),
                        "packet_path": packet.relative_to(os_root).as_posix(),
                        "context_summary": _legacy_summary(packet),
                        "blocked_reason": (
                            "Legacy active index recorded this item as blocked; "
                            "the blocker receipt requires verification."
                            if item_state == "blocked"
                            else None
                        ),
                        "metadata": {
                            "legacy_lane": lane,
                            "migration_digest": digest,
                            "active_index_observation": indexed,
                        },
                    }
                )
    return {
        "api_version": "agentic-os-work-import/v1",
        "status": "planned",
        "candidate_count": len(candidates),
        "attention_counts": {
            attention: sum(item["attention"] == attention for item in candidates)
            for attention in ATTENTION_STATES
        },
        "items": candidates,
    }


def import_legacy(
    conn: sqlite3.Connection,
    root: str | Path,
    *,
    dry_run: bool = True,
) -> dict[str, Any]:
    plan = legacy_import_plan(root)
    if dry_run:
        return plan
    imported = 0
    existing = 0
    for item in plan["items"]:
        if get(conn, item["id"]):
            existing += 1
            continue
        values = deepcopy(item)
        values["item_id"] = values.pop("id")
        upsert(conn, **values, actor="layout-v2-migration")
        imported += 1
    projection = write_active_projection(conn, root)
    return {
        **plan,
        "status": "imported",
        "dry_run": False,
        "imported": imported,
        "existing": existing,
        "projection": projection,
    }
