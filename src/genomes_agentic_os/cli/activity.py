"""CLI for privacy-safe activity analytics ingestion."""

import yaml
from ..activity_ingestion import (
    collect_local_activity,
    health,
    ingest_fixture,
    list_sources,
    validate_sources,
)
from ._shared import DEFAULT_ROOT


def _print(value):
    print(yaml.safe_dump(value, sort_keys=False).strip())


def register(subparsers):
    parser = subparsers.add_parser(
        "activity", help="Ingest privacy-safe operator analytics events."
    )
    commands = parser.add_subparsers(dest="activity_command", required=True)
    for name, fn in (
        ("list", lambda root: {"activity_sources": list_sources(root)}),
        ("validate", validate_sources),
        ("health", health),
    ):
        command = commands.add_parser(name)
        command.add_argument("--root", default=DEFAULT_ROOT)
        command.set_defaults(handler=lambda args, op=fn: _print(op(args.root)) or 0)
    ingest = commands.add_parser(
        "ingest", help="Ingest a credential-free provider fixture."
    )
    ingest.add_argument("fixture")
    ingest.add_argument("--root", default=DEFAULT_ROOT)
    mode = ingest.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    ingest.set_defaults(
        handler=lambda args: (
            _print(ingest_fixture(args.root, args.fixture, apply=args.apply)) or 0
        )
    )
    collect = commands.add_parser(
        "collect-local", help="Collect canonical metadata-only local runtime evidence."
    )
    collect.add_argument("source_id")
    collect.add_argument("--root", default=DEFAULT_ROOT)
    collect.add_argument("--limit", type=int, default=100)
    collect_mode = collect.add_mutually_exclusive_group(required=True)
    collect_mode.add_argument("--dry-run", action="store_true")
    collect_mode.add_argument("--apply", action="store_true")
    collect.set_defaults(
        handler=lambda args: (
            _print(
                collect_local_activity(
                    args.root, args.source_id, limit=args.limit, apply=args.apply
                )
            )
            or 0
        )
    )
