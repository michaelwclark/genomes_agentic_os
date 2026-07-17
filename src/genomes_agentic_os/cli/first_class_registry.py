"""CLI for the materialized first-class resource registry."""

from __future__ import annotations

import argparse
import json

from ..first_class_registry import (
    RESOURCE_KINDS,
    list_resource_tags,
    mutate_resource_tag,
    query_first_class_registry,
    refresh_first_class_registry,
)
from ._shared import DEFAULT_ROOT


def _print(value: dict) -> None:
    print(json.dumps(value, indent=2, sort_keys=True))


def handle_refresh(args: argparse.Namespace) -> int:
    _print(refresh_first_class_registry(args.root))
    return 0


def handle_query(args: argparse.Namespace) -> int:
    _print(
        query_first_class_registry(
            args.root,
            kind=args.kind,
            domain=args.domain,
            project=args.project,
            query=args.query,
            ensure=args.ensure,
        )
    )
    return 0


def handle_tag_list(args: argparse.Namespace) -> int:
    _print(list_resource_tags(args.root, args.resource_id))
    return 0


def handle_tag_mutation(args: argparse.Namespace) -> int:
    _print(
        mutate_resource_tag(
            args.root,
            operation=args.tag_operation,
            resource_id=args.resource_id,
            tag=args.tag,
        )
    )
    return 0


def register(subparsers) -> None:
    parser = subparsers.add_parser(
        "resource-registry",
        help="Read or refresh the canonical first-class resource snapshot.",
    )
    commands = parser.add_subparsers(dest="resource_registry_command", required=True)
    refresh = commands.add_parser(
        "refresh",
        help="Discover first-class resources and atomically refresh the top-level snapshot.",
    )
    refresh.add_argument("--root", default=DEFAULT_ROOT)
    refresh.set_defaults(handler=handle_refresh)
    query = commands.add_parser(
        "query", help="Read the materialized snapshot without scanning the OS tree."
    )
    query.add_argument("--kind", choices=RESOURCE_KINDS)
    query.add_argument("--domain")
    query.add_argument("--project")
    query.add_argument("--query")
    query.add_argument(
        "--ensure",
        action="store_true",
        help="Refresh only when the snapshot does not exist.",
    )
    query.add_argument("--root", default=DEFAULT_ROOT)
    query.set_defaults(handler=handle_query)
    tags = commands.add_parser(
        "tags", help="List or safely mutate durable operator-defined resource tags."
    )
    tag_commands = tags.add_subparsers(dest="tag_operation", required=True)
    list_tags = tag_commands.add_parser(
        "list", help="List derived and custom tags for one stable resource id."
    )
    list_tags.add_argument("--resource-id", required=True)
    list_tags.add_argument("--root", default=DEFAULT_ROOT)
    list_tags.set_defaults(handler=handle_tag_list)
    for operation in ("add", "remove"):
        mutation = tag_commands.add_parser(
            operation, help=f"{operation.title()} one normalized custom resource tag."
        )
        mutation.add_argument("--resource-id", required=True)
        mutation.add_argument("--tag", required=True)
        mutation.add_argument("--root", default=DEFAULT_ROOT)
        mutation.set_defaults(handler=handle_tag_mutation)
