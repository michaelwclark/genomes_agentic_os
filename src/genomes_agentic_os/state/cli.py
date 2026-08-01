"""Self-contained ``state`` command group for the state-plane package.

Deliberately does not import anything from ``cli.py`` / ``cli_help.py`` /
``pyproject.toml`` (those are owned by a concurrent CLI-split effort).
``register_state_cli`` is the single integration point: whoever wires this
in imports it and calls it once against their own top-level
``parser.add_subparsers(...)`` result — see the module docstring in
``state/__init__.py`` for the exact one-line contract.

``DEFAULT_ROOT`` duplicates the value used elsewhere in the CLI
(``"~/agentic_os"``) rather than importing it, for the same reason
``mcp_catalog.py`` duplicates ``ROOT_MARKER_FILENAME`` from ``scaffold.py``:
avoiding a dependency on a module under concurrent, unrelated change.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from typing import Any

import yaml

from . import cursors as cursors_module
from . import events as events_module
from . import queue as queue_module
from . import work_items as work_items_module
from .db import (
    StateDbError,
    backup_state_database,
    connect,
    connect_readonly,
    default_db_path,
    resolve_os_root,
    schema_version,
    table_counts,
)
from .importers import import_all, scan_all, verify_import

DEFAULT_ROOT = "~/agentic_os"


def _resolve_db_path(args: argparse.Namespace) -> str:
    explicit = getattr(args, "db", None)
    if explicit:
        return str(explicit)
    return str(default_db_path(args.root))


def _format_result(result: dict[str, Any], *, as_json: bool) -> str:
    if as_json:
        return json.dumps(result, indent=2, sort_keys=True, default=str)
    return yaml.safe_dump(result, sort_keys=False).strip()


def handle_state_init(args: argparse.Namespace) -> int:
    db_path = _resolve_db_path(args)
    conn = connect(db_path)
    try:
        result = {
            "ok": True,
            "db_path": db_path,
            "schema_version": schema_version(conn),
            "table_counts": table_counts(conn),
        }
    finally:
        conn.close()
    print(_format_result(result, as_json=args.json))
    return 0


def handle_state_status(args: argparse.Namespace) -> int:
    db_path = _resolve_db_path(args)
    conn = connect(db_path)
    try:
        result = {
            "db_path": db_path,
            "schema_version": schema_version(conn),
            "table_counts": table_counts(conn),
        }
    finally:
        conn.close()
    print(_format_result(result, as_json=args.json))
    return 0


def handle_state_backup(args: argparse.Namespace) -> int:
    result = backup_state_database(
        args.root,
        retention=args.retention,
        if_due_hours=args.if_due_hours,
        dry_run=not args.apply,
    )
    print(_format_result(result, as_json=args.json))
    return 0


def handle_state_import(args: argparse.Namespace) -> int:
    root = resolve_os_root(args.root)
    if args.dry_run:
        # Pure source scan: never connects to, creates, or touches any
        # database, regardless of what --db would otherwise resolve to.
        result: dict[str, Any] = {"dry_run": True, "root": str(root), **scan_all(root, source=args.source)}
        print(_format_result(result, as_json=args.json))
        return 0
    db_path = _resolve_db_path(args)
    conn = connect(db_path)
    try:
        result = {"dry_run": False, "db_path": db_path, "root": str(root), **import_all(conn, root, source=args.source)}
    finally:
        conn.close()
    print(_format_result(result, as_json=args.json))
    return 0


def handle_state_query(args: argparse.Namespace) -> int:
    db_path = _resolve_db_path(args)
    conn = connect(db_path)
    try:
        if args.table == "events":
            rows = events_module.query(
                conn,
                event_type=args.type,
                since=args.since,
                until=args.until,
                correlation_id=args.correlation_id,
                limit=args.limit,
            )
        elif args.table == "run_queue":
            rows = queue_module.query(conn, status=args.status, kind=args.kind, limit=args.limit)
        else:
            rows = cursors_module.list_cursors(conn, limit=args.limit)
    finally:
        conn.close()
    result = {"table": args.table, "count": len(rows), "rows": rows}
    print(_format_result(result, as_json=args.json))
    return 0


def handle_state_prune(args: argparse.Namespace) -> int:
    db_path = _resolve_db_path(args)
    dry_run = not args.apply
    conn = connect(db_path)
    try:
        if args.table == "events":
            result = events_module.prune_events(conn, older_than_days=args.older_than_days, dry_run=dry_run)
        else:
            statuses = tuple(args.status) if args.status else queue_module.TERMINAL_STATUSES
            result = queue_module.prune(conn, older_than_days=args.older_than_days, statuses=statuses, dry_run=dry_run)
    finally:
        conn.close()
    result = {"table": args.table, **result}
    print(_format_result(result, as_json=args.json))
    return 0


def handle_state_verify_import(args: argparse.Namespace) -> int:
    root = resolve_os_root(args.root)
    db_path = _resolve_db_path(args)
    conn = connect(db_path)
    try:
        result = {"db_path": db_path, "root": str(root), **verify_import(conn, root)}
    finally:
        conn.close()
    print(_format_result(result, as_json=args.json))
    return 0 if result["ok"] else 1


def handle_state_reconcile_traces(args: argparse.Namespace) -> int:
    """Report unsupported successful run/agent claims without mutating state."""
    db_path = _resolve_db_path(args)
    try:
        conn = connect_readonly(db_path)
    except StateDbError as exc:
        result = {
            "api_version": "agentic-os-trace-reconciliation/v1",
            "status": "unavailable",
            "reason": "state_database_missing" if "is missing:" in str(exc) else "state_database_unavailable",
            "db_path": db_path,
            "detail": str(exc),
            "claim_count": 0,
            "supported_count": 0,
            "phantom_count": 0,
            "claims": [],
        }
    else:
        try:
            result = work_items_module.reconcile_completion_claims(conn, limit=args.limit)
        except sqlite3.Error as exc:
            result = {
                "api_version": "agentic-os-trace-reconciliation/v1",
                "status": "unavailable",
                "reason": "state_database_unavailable",
                "db_path": db_path,
                "detail": str(exc),
                "claim_count": 0,
                "supported_count": 0,
                "phantom_count": 0,
                "claims": [],
            }
        finally:
            conn.close()
    print(_format_result(result, as_json=args.json))
    return 0 if result["status"] == "clean" else 1


def _add_common_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    parser.add_argument("--db", default=None, help="Override state.db path (default: derived from --root).")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON instead of YAML.")


def register_state_cli(subparsers: argparse._SubParsersAction) -> None:
    """Add the ``state`` command group to an existing top-level subparsers.

    Integration contract (for whoever wires this in):

        from genomes_agentic_os.state import register_state_cli
        register_state_cli(subparsers)

    where ``subparsers`` is the object returned by
    ``parser.add_subparsers(dest="command", required=True)``.
    """
    state_parser = subparsers.add_parser("state", help="SQLite state-plane operations (events, run_queue, cursors).")
    state_subparsers = state_parser.add_subparsers(dest="state_command", required=True)

    init_parser = state_subparsers.add_parser("init", help="Create the state.db and apply schema migrations.")
    _add_common_arguments(init_parser)
    init_parser.set_defaults(handler=handle_state_init)

    status_parser = state_subparsers.add_parser("status", help="Show db path, schema version, and per-table counts.")
    _add_common_arguments(status_parser)
    status_parser.set_defaults(handler=handle_state_status)

    backup_parser = state_subparsers.add_parser(
        "backup", help="Create a consistent, integrity-checked local state.db snapshot."
    )
    backup_parser.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    backup_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON instead of YAML.")
    backup_parser.add_argument("--retention", type=int, default=7, help="Number of valid snapshots to retain.")
    backup_parser.add_argument("--if-due-hours", type=int, default=None, help="Skip when a newer snapshot exists.")
    backup_parser.add_argument("--apply", action="store_true", help="Create the snapshot; default is a dry run.")
    backup_parser.set_defaults(handler=handle_state_backup)

    import_parser = state_subparsers.add_parser("import", help="Import run-queue/events/cursors YAML into state.db.")
    _add_common_arguments(import_parser)
    import_parser.add_argument(
        "--source", choices=("run-queue", "events", "cursors", "all"), default="all", help="Which source to import."
    )
    import_parser.add_argument(
        "--dry-run", action="store_true", help="Parse and count only; never opens or creates a database."
    )
    import_parser.set_defaults(handler=handle_state_import)

    query_parser = state_subparsers.add_parser("query", help="Query rows from one state table.")
    _add_common_arguments(query_parser)
    query_parser.add_argument("--table", choices=("events", "run_queue", "cursors"), required=True)
    query_parser.add_argument("--status", default=None, help="run_queue: filter by status.")
    query_parser.add_argument("--kind", default=None, help="run_queue: filter by kind.")
    query_parser.add_argument("--type", default=None, help="events: filter by event type.")
    query_parser.add_argument("--correlation-id", default=None, help="events: filter by correlation_id.")
    query_parser.add_argument("--since", default=None, help="events: occurred_at >= this ISO timestamp.")
    query_parser.add_argument("--until", default=None, help="events: occurred_at <= this ISO timestamp.")
    query_parser.add_argument("--limit", type=int, default=50)
    query_parser.set_defaults(handler=handle_state_query)

    prune_parser = state_subparsers.add_parser("prune", help="Delete old terminal run_queue items, or old events.")
    _add_common_arguments(prune_parser)
    prune_parser.add_argument("--table", choices=("run_queue", "events"), default="run_queue")
    prune_parser.add_argument("--older-than-days", type=int, required=True)
    prune_parser.add_argument(
        "--status", action="append", default=None, help="run_queue only; repeatable. Default: done/failed/skipped."
    )
    prune_parser.add_argument("--apply", action="store_true", help="Actually delete. Without this, prune is a dry run.")
    prune_parser.set_defaults(handler=handle_state_prune)

    verify_parser = state_subparsers.add_parser(
        "verify-import", help="Compare source file counts against table counts and report drift."
    )
    _add_common_arguments(verify_parser)
    verify_parser.set_defaults(handler=handle_state_verify_import)

    reconcile_traces_parser = state_subparsers.add_parser(
        "reconcile-traces",
        help="Read-only doctor: flag successful run/agent claims without exact completion evidence.",
    )
    _add_common_arguments(reconcile_traces_parser)
    reconcile_traces_parser.add_argument("--limit", type=int, default=100, help="Maximum completion claims to inspect.")
    reconcile_traces_parser.set_defaults(handler=handle_state_reconcile_traces)
