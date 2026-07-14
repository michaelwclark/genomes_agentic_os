"""CLI parser and handlers for the local read-only resource graph.

Top-level registration is intentionally left to the integrating branch.
"""

from __future__ import annotations

import argparse
import json

from ..resource_graph import ResourceGraphError, ResourceGraphService
from ._shared import DEFAULT_ROOT


def handle_resource_graph_query(args: argparse.Namespace) -> int:
    try:
        variables = json.loads(args.variables) if args.variables else None
        if variables is not None and not isinstance(variables, dict):
            raise ValueError("variables must be a JSON object")
        payload = ResourceGraphService(args.root).execute(
            args.query,
            variables=variables,
            operation_name=args.operation_name,
        )
    except (ResourceGraphError, ValueError, json.JSONDecodeError) as error:
        payload = {
            "data": None,
            "errors": [{"message": str(error), "extensions": {"code": "INVALID_REQUEST"}}],
        }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 1 if payload.get("errors") else 0


def handle_resource_graph_schema(_args: argparse.Namespace) -> int:
    print(ResourceGraphService.schema_sdl())
    return 0


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "resource-graph",
        help="Query the bounded local Agentic OS resource graph.",
        description=(
            "Execute read-only GraphQL against the allowlisted installed OS root. "
            "Resolvers never fan out to live providers and the schema has no mutations."
        ),
    )
    commands = parser.add_subparsers(dest="resource_graph_command", required=True)

    query_parser = commands.add_parser("query", help="Execute one GraphQL query string.")
    query_parser.add_argument("--root", default=DEFAULT_ROOT, help="Allowlisted installed OS root.")
    query_parser.add_argument("--query", required=True, help="GraphQL query text; file paths are not accepted.")
    query_parser.add_argument("--variables", help="Optional JSON object of GraphQL variables.")
    query_parser.add_argument("--operation-name", help="Operation name for multi-operation documents.")
    query_parser.set_defaults(handler=handle_resource_graph_query)

    schema_parser = commands.add_parser("schema", help="Print the read-only GraphQL schema SDL.")
    schema_parser.set_defaults(handler=handle_resource_graph_schema)


__all__ = ["handle_resource_graph_query", "handle_resource_graph_schema", "register"]
