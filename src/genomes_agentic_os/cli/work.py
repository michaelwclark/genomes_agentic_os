"""CLI for canonical local work-item truth and active context."""

from __future__ import annotations

import argparse
import json

from ..state import work_items
from ..state.db import connect, default_db_path, resolve_os_root


def _print(value: object) -> None:
    print(json.dumps(value, indent=2, sort_keys=True, default=str))


def _paths(args: argparse.Namespace) -> tuple[object, str]:
    root = resolve_os_root(args.root)
    return root, str(args.db or default_db_path(root))


def handle_list(args: argparse.Namespace) -> int:
    root, db_path = _paths(args)
    conn = connect(db_path)
    try:
        items = work_items.query(
            conn,
            attention=args.attention,
            state=args.state,
            domain=args.domain,
            project=args.project,
            limit=args.limit,
        )
    finally:
        conn.close()
    _print({"root": str(root), "db_path": db_path, "count": len(items), "items": items})
    return 0


def handle_show(args: argparse.Namespace) -> int:
    _root, db_path = _paths(args)
    conn = connect(db_path)
    try:
        item = work_items.get(conn, args.item_id)
    finally:
        conn.close()
    if item is None:
        _print({"error": "not_found", "id": args.item_id})
        return 1
    _print(item)
    return 0


def handle_upsert(args: argparse.Namespace) -> int:
    root, db_path = _paths(args)
    conn = connect(db_path)
    try:
        item = work_items.upsert(
            conn,
            item_id=args.item_id,
            title=args.title,
            state=args.state,
            attention=args.attention,
            domain=args.domain,
            project=args.project,
            source_system=args.source_system,
            source_key=args.source_key,
            source_url=args.source_url,
            owner=args.owner,
            priority=args.priority,
            packet_path=args.packet_path,
            worktree_path=args.worktree_path,
            branch=args.branch,
            context_summary=args.summary,
            blocked_reason=args.blocked_reason,
            actor=args.actor,
            receipt_ref=args.receipt,
            verified=args.verified,
        )
        projection = work_items.write_active_projection(conn, root)
    finally:
        conn.close()
    _print({"item": item, "projection": projection})
    return 0


def handle_set(args: argparse.Namespace) -> int:
    root, db_path = _paths(args)
    conn = connect(db_path)
    try:
        item = work_items.update(
            conn,
            args.item_id,
            state=args.state,
            attention=args.attention,
            context_summary=args.summary,
            blocked_reason=args.blocked_reason,
            packet_path=args.packet_path,
            worktree_path=args.worktree_path,
            branch=args.branch,
            clear_worktree=args.clear_worktree,
            actor=args.actor,
            receipt_ref=args.receipt,
            verified=args.verified,
        )
        projection = work_items.write_active_projection(conn, root)
    finally:
        conn.close()
    _print({"item": item, "projection": projection})
    return 0


def handle_active_now(args: argparse.Namespace) -> int:
    root, db_path = _paths(args)
    conn = connect(db_path)
    try:
        payload = work_items.write_active_projection(
            conn,
            root,
            stale_hours=args.stale_hours,
        )
    finally:
        conn.close()
    _print(payload)
    return 0 if payload["stale_count"] == 0 else 2


def handle_import_legacy(args: argparse.Namespace) -> int:
    root, db_path = _paths(args)
    if not args.apply:
        _print(work_items.legacy_import_plan(root))
        return 0
    conn = connect(db_path)
    try:
        result = work_items.import_legacy(conn, root, dry_run=False)
    finally:
        conn.close()
    _print(result)
    return 0


def handle_migrate_path_prefix(args: argparse.Namespace) -> int:
    root, db_path = _paths(args)
    conn = connect(db_path)
    try:
        result = work_items.migrate_path_prefix(
            conn,
            from_prefix=args.from_prefix,
            to_prefix=args.to_prefix,
            domain=args.domain,
            dry_run=not args.apply,
            actor=args.actor,
            receipt_ref=args.receipt,
        )
        if args.apply:
            result["projection"] = work_items.write_active_projection(conn, root)
    finally:
        conn.close()
    _print(result)
    return 0


def _common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--root", default="~/agentic_os")
    parser.add_argument("--db")


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "work",
        help="Read and update canonical local work state without tracker or code-path scans.",
    )
    commands = parser.add_subparsers(dest="work_command", required=True)

    list_parser = commands.add_parser("list", help="List canonical work items.")
    _common(list_parser)
    list_parser.add_argument("--attention", choices=work_items.ATTENTION_STATES)
    list_parser.add_argument("--state", choices=work_items.CANONICAL_STATES)
    list_parser.add_argument("--domain")
    list_parser.add_argument("--project")
    list_parser.add_argument("--limit", type=int, default=300)
    list_parser.set_defaults(handler=handle_list)

    show_parser = commands.add_parser("show", help="Show one canonical work item.")
    _common(show_parser)
    show_parser.add_argument("item_id")
    show_parser.set_defaults(handler=handle_show)

    upsert_parser = commands.add_parser("upsert", help="Create or fully reconcile one work item.")
    _common(upsert_parser)
    upsert_parser.add_argument("item_id")
    upsert_parser.add_argument("--title", required=True)
    upsert_parser.add_argument("--state", choices=work_items.CANONICAL_STATES, default="captured")
    upsert_parser.add_argument("--attention", choices=work_items.ATTENTION_STATES, default="queued")
    upsert_parser.add_argument("--domain")
    upsert_parser.add_argument("--project")
    upsert_parser.add_argument("--source-system")
    upsert_parser.add_argument("--source-key")
    upsert_parser.add_argument("--source-url")
    upsert_parser.add_argument("--owner")
    upsert_parser.add_argument("--priority", type=int, default=0)
    upsert_parser.add_argument("--packet-path")
    upsert_parser.add_argument("--worktree-path")
    upsert_parser.add_argument("--branch")
    upsert_parser.add_argument("--summary", default="")
    upsert_parser.add_argument("--blocked-reason")
    upsert_parser.add_argument("--actor", default="agentic-os")
    upsert_parser.add_argument("--receipt")
    upsert_parser.add_argument("--verified", action="store_true")
    upsert_parser.set_defaults(handler=handle_upsert)

    set_parser = commands.add_parser("set", help="Change state, attention, or resume context.")
    _common(set_parser)
    set_parser.add_argument("item_id")
    set_parser.add_argument("--state", choices=work_items.CANONICAL_STATES)
    set_parser.add_argument("--attention", choices=work_items.ATTENTION_STATES)
    set_parser.add_argument("--summary")
    set_parser.add_argument("--blocked-reason")
    set_parser.add_argument("--packet-path", help="Reconcile the packet path after a governed lane move.")
    worktree_group = set_parser.add_mutually_exclusive_group()
    worktree_group.add_argument("--worktree-path")
    worktree_group.add_argument(
        "--clear-worktree",
        action="store_true",
        help="Clear the reconstructable worktree and branch pointers after verified cleanup.",
    )
    set_parser.add_argument("--branch")
    set_parser.add_argument("--actor", default="agentic-os")
    set_parser.add_argument("--receipt")
    set_parser.add_argument("--verified", action="store_true")
    set_parser.set_defaults(handler=handle_set)

    active_parser = commands.add_parser(
        "active-now",
        help="Refresh and print the compact active-context projection.",
    )
    _common(active_parser)
    active_parser.add_argument("--stale-hours", type=int, default=72)
    active_parser.set_defaults(handler=handle_active_now)

    import_parser = commands.add_parser(
        "import-legacy",
        help="Plan or import legacy lane folders without marking them active.",
    )
    _common(import_parser)
    import_parser.add_argument("--apply", action="store_true")
    import_parser.set_defaults(handler=handle_import_legacy)

    migrate_parser = commands.add_parser(
        "migrate-path-prefix",
        help="Plan or atomically migrate path prefixes in canonical work state.",
    )
    _common(migrate_parser)
    migrate_parser.add_argument("--from-prefix", required=True)
    migrate_parser.add_argument("--to-prefix", required=True)
    migrate_parser.add_argument("--domain")
    migrate_parser.add_argument("--actor", default="agentic-os")
    migrate_parser.add_argument("--receipt")
    migrate_parser.add_argument("--apply", action="store_true")
    migrate_parser.set_defaults(handler=handle_migrate_path_prefix)
