"""CLI for retention-based work-item archival."""

from __future__ import annotations

import argparse
import json

from ..work_item_archive import archive_retained_work_items
from ._shared import DEFAULT_ROOT


def handle(args: argparse.Namespace) -> int:
    result = archive_retained_work_items(args.root, apply=args.apply)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 1 if result.get("skipped") else 0


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "work-item-archive",
        help="Run Work Item Archive Health retention cleanup.",
    )
    parser.add_argument("--root", default=DEFAULT_ROOT)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    parser.set_defaults(handler=handle)
