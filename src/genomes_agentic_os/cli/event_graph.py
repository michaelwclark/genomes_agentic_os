"""CLI commands for the event ledger and chain rules."""

from __future__ import annotations

import argparse

from ..event_graph import (
    append_event,
    chain_doctor,
    chain_list,
    format_event_graph_result,
    list_events,
    process_due,
    replay_event,
    summarize_events,
    test_chain_rule,
)

from ._shared import DEFAULT_ROOT


def handle_event_append(args: argparse.Namespace) -> int:
    print(
        format_event_graph_result(
            append_event(
                args.root,
                event_type=args.event_type,
                source_ref=args.source_ref,
                summary=args.summary,
                correlation_id=args.correlation_id,
            )
        )
    )
    return 0


def handle_event_list(args: argparse.Namespace) -> int:
    print(format_event_graph_result(list_events(args.root, limit=args.limit)))
    return 0


def handle_event_summary(args: argparse.Namespace) -> int:
    print(format_event_graph_result(summarize_events(args.root, limit=args.limit)))
    return 0


def handle_event_process_due(args: argparse.Namespace) -> int:
    print(format_event_graph_result(process_due(args.root, dry_run=args.dry_run)))
    return 0


def handle_event_replay(args: argparse.Namespace) -> int:
    print(format_event_graph_result(replay_event(args.root, args.event_id, dry_run=args.dry_run)))
    return 0


def handle_chain_list(args: argparse.Namespace) -> int:
    print(format_event_graph_result(chain_list(args.root)))
    return 0


def handle_chain_test(args: argparse.Namespace) -> int:
    print(format_event_graph_result(test_chain_rule(args.root, args.chain_rule_id, args.event)))
    return 0


def handle_chain_doctor(args: argparse.Namespace) -> int:
    result = chain_doctor(args.root)
    print(format_event_graph_result(result))
    return 0 if result["ok"] else 1


def register(subparsers) -> None:
    """Register the event / chain command group."""
    event_parser = subparsers.add_parser("event", help="Manage the file-backed event ledger.")
    event_subparsers = event_parser.add_subparsers(dest="event_command", required=True)
    event_append = event_subparsers.add_parser("append", help="Append a normalized event.")
    event_append.add_argument("--type", required=True, dest="event_type")
    event_append.add_argument("--source", required=True, dest="source_ref")
    event_append.add_argument("--summary", default="")
    event_append.add_argument("--correlation-id")
    event_append.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    event_append.set_defaults(handler=handle_event_append)
    event_list = event_subparsers.add_parser("list", help="List recent events.")
    event_list.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    event_list.add_argument("--limit", type=int, default=20)
    event_list.set_defaults(handler=handle_event_list)
    event_summary = event_subparsers.add_parser("summary", help="Summarize recent events and pending follow-up.")
    event_summary.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    event_summary.add_argument("--limit", type=int, default=20)
    event_summary.set_defaults(handler=handle_event_summary)
    event_process = event_subparsers.add_parser("process-due", help="Process matching chain rules.")
    event_process.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    event_process_mode = event_process.add_mutually_exclusive_group(required=True)
    event_process_mode.add_argument("--dry-run", action="store_true")
    event_process_mode.add_argument("--apply", action="store_true")
    event_process.set_defaults(handler=handle_event_process_due)
    event_replay = event_subparsers.add_parser("replay", help="Replay one event against chain rules.")
    event_replay.add_argument("event_id")
    event_replay.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    event_replay_mode = event_replay.add_mutually_exclusive_group(required=True)
    event_replay_mode.add_argument("--dry-run", action="store_true")
    event_replay_mode.add_argument("--apply", action="store_true")
    event_replay.set_defaults(handler=handle_event_replay)

    chain_parser = subparsers.add_parser("chain", help="Manage event chain rules.")
    chain_subparsers = chain_parser.add_subparsers(dest="chain_command", required=True)
    chain_list_parser = chain_subparsers.add_parser("list", help="List chain rules.")
    chain_list_parser.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    chain_list_parser.set_defaults(handler=handle_chain_list)
    chain_test = chain_subparsers.add_parser("test", help="Test a chain rule against an event file.")
    chain_test.add_argument("chain_rule_id")
    chain_test.add_argument("--event", required=True)
    chain_test.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    chain_test.set_defaults(handler=handle_chain_test)
    chain_doctor_parser = chain_subparsers.add_parser("doctor", help="Check chain rule safety.")
    chain_doctor_parser.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    chain_doctor_parser.set_defaults(handler=handle_chain_doctor)
