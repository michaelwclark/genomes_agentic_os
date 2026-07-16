"""CLI for the read-only Program and Automation operator projection."""

from __future__ import annotations

import argparse
import json

from ..operator_resources import get_operator_resource, query_operator_resources
from ._shared import DEFAULT_ROOT


def _print(result: dict) -> None:
    print(json.dumps(result, indent=2, sort_keys=True))


def handle_query(args: argparse.Namespace) -> int:
    _print(query_operator_resources(args.root, args.kind))
    return 0


def handle_get(args: argparse.Namespace) -> int:
    _print(get_operator_resource(args.root, args.kind, args.resource_id))
    return 0


def register(subparsers) -> None:
    parser = subparsers.add_parser(
        "operator-resource",
        help="Query the read-only Program and Automation operator projection.",
    )
    commands = parser.add_subparsers(dest="operator_resource_command", required=True)
    query = commands.add_parser(
        "query", help="List projected resources as versioned JSON."
    )
    query.add_argument("kind", choices=("program", "automation"))
    query.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    query.set_defaults(handler=handle_query)
    get = commands.add_parser(
        "get", help="Get one exact projected resource as versioned JSON."
    )
    get.add_argument("kind", choices=("program", "automation"))
    get.add_argument("resource_id", help="Exact resource id returned by query.")
    get.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    get.set_defaults(handler=handle_get)
