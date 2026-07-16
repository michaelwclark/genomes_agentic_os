"""CLI for the materialized first-class resource registry."""

from __future__ import annotations

import argparse
import json

from ..first_class_registry import RESOURCE_KINDS, query_first_class_registry, refresh_first_class_registry
from ._shared import DEFAULT_ROOT


def _print(value: dict) -> None:
    print(json.dumps(value, indent=2, sort_keys=True))


def handle_refresh(args: argparse.Namespace) -> int:
    _print(refresh_first_class_registry(args.root))
    return 0


def handle_query(args: argparse.Namespace) -> int:
    _print(query_first_class_registry(args.root, kind=args.kind, domain=args.domain, project=args.project, query=args.query, ensure=args.ensure))
    return 0


def register(subparsers) -> None:
    parser = subparsers.add_parser("resource-registry", help="Read or refresh the canonical first-class resource snapshot.")
    commands = parser.add_subparsers(dest="resource_registry_command", required=True)
    refresh = commands.add_parser("refresh", help="Discover first-class resources and atomically refresh the top-level snapshot.")
    refresh.add_argument("--root", default=DEFAULT_ROOT)
    refresh.set_defaults(handler=handle_refresh)
    query = commands.add_parser("query", help="Read the materialized snapshot without scanning the OS tree.")
    query.add_argument("--kind", choices=RESOURCE_KINDS)
    query.add_argument("--domain")
    query.add_argument("--project")
    query.add_argument("--query")
    query.add_argument("--ensure", action="store_true", help="Refresh only when the snapshot does not exist.")
    query.add_argument("--root", default=DEFAULT_ROOT)
    query.set_defaults(handler=handle_query)
