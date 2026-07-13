"""CLI commands for connected systems and source watchers."""

from __future__ import annotations

import argparse

from ..source_watch import (
    create_watch_source,
    doctor_connected_system,
    doctor_watch_source,
    format_source_watch_result,
    list_connected_systems,
    list_watch_sources,
    parse_external_refs,
    poll_watch_source,
    run_due_watch_sources,
)

from ._shared import DEFAULT_ROOT


def handle_connected_system_list(args: argparse.Namespace) -> int:
    print(format_source_watch_result(list_connected_systems(args.root)))
    return 0


def handle_connected_system_doctor(args: argparse.Namespace) -> int:
    result = doctor_connected_system(args.root, args.system_id)
    print(format_source_watch_result(result))
    return 0 if result["ok"] else 1


def handle_watch_source_list(args: argparse.Namespace) -> int:
    print(format_source_watch_result(list_watch_sources(args.root)))
    return 0


def handle_watch_source_create(args: argparse.Namespace) -> int:
    result = create_watch_source(
        args.root,
        args.source_id,
        connected_system=args.connected_system,
        source_type=args.source_type,
        display_name=args.display_name,
        cadence=args.cadence,
        external_ref=parse_external_refs(args.external_ref),
        route_to=args.route_to,
        enabled=args.enabled,
    )
    print(format_source_watch_result(result))
    return 0


def handle_watch_source_doctor(args: argparse.Namespace) -> int:
    result = doctor_watch_source(args.root, args.source_id)
    print(format_source_watch_result(result))
    return 0 if result["ok"] else 1


def handle_watch_source_poll(args: argparse.Namespace) -> int:
    result = poll_watch_source(args.root, args.source_id, dry_run=args.dry_run)
    print(format_source_watch_result(result))
    return 0 if result["ok"] else 1


def handle_watch_source_run_due(args: argparse.Namespace) -> int:
    print(format_source_watch_result(run_due_watch_sources(args.root, dry_run=args.dry_run)))
    return 0


def register(subparsers) -> None:
    """Register the connected-system / watch-source command group."""
    connected_parser = subparsers.add_parser("connected-system", help="Manage connected source systems.")
    connected_subparsers = connected_parser.add_subparsers(dest="connected_system_command", required=True)
    connected_list = connected_subparsers.add_parser("list", help="List connected systems and selected providers.")
    connected_list.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    connected_list.set_defaults(handler=handle_connected_system_list)
    connected_doctor = connected_subparsers.add_parser("doctor", help="Check a connected system.")
    connected_doctor.add_argument("system_id")
    connected_doctor.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    connected_doctor.set_defaults(handler=handle_connected_system_doctor)

    watch_parser = subparsers.add_parser("watch-source", help="Manage connected source watchers.")
    watch_subparsers = watch_parser.add_subparsers(dest="watch_source_command", required=True)
    watch_list = watch_subparsers.add_parser("list", help="List watch sources.")
    watch_list.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    watch_list.set_defaults(handler=handle_watch_source_list)
    watch_create = watch_subparsers.add_parser("create", help="Create a file-backed watch source.")
    watch_create.add_argument("source_id")
    watch_create.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    watch_create.add_argument("--connected-system", default="notion_genome")
    watch_create.add_argument("--source-type", default="notion_database")
    watch_create.add_argument("--display-name")
    watch_create.add_argument("--cadence", default="manual")
    watch_create.add_argument("--external-ref", action="append", default=[])
    watch_create.add_argument("--route-to", default="shared_factory")
    watch_create.add_argument("--enabled", action="store_true")
    watch_create.set_defaults(handler=handle_watch_source_create)
    watch_doctor = watch_subparsers.add_parser("doctor", help="Check a watch source.")
    watch_doctor.add_argument("source_id")
    watch_doctor.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    watch_doctor.set_defaults(handler=handle_watch_source_doctor)
    watch_poll = watch_subparsers.add_parser("poll", help="Poll one watch source.")
    watch_poll.add_argument("source_id")
    watch_poll.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    watch_poll_mode = watch_poll.add_mutually_exclusive_group(required=True)
    watch_poll_mode.add_argument("--dry-run", action="store_true")
    watch_poll_mode.add_argument("--apply", action="store_true")
    watch_poll.set_defaults(handler=handle_watch_source_poll)
    watch_run_due = watch_subparsers.add_parser("run-due", help="Poll enabled watch sources.")
    watch_run_due.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    watch_run_due_mode = watch_run_due.add_mutually_exclusive_group(required=True)
    watch_run_due_mode.add_argument("--dry-run", action="store_true")
    watch_run_due_mode.add_argument("--apply", action="store_true")
    watch_run_due.set_defaults(handler=handle_watch_source_run_due)
