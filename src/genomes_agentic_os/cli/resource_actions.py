"""CLI surface for governed Agentic OS resource creation and validation."""

from __future__ import annotations

import argparse
import json

from ..resource_actions import SUPPORTED_RESOURCE_KINDS, create_resource, validate_resource

from ._shared import DEFAULT_ROOT, yaml_dump


def _print(result: dict, *, json_output: bool) -> None:
    print(json.dumps(result, sort_keys=True) if json_output else yaml_dump(result))


def handle_resource_validate(args: argparse.Namespace) -> int:
    result = validate_resource(
        args.root,
        args.kind,
        args.name,
        domain=args.domain,
        lane=args.lane,
    )
    _print(result, json_output=args.json)
    return 0 if result["ok"] else 1


def handle_resource_create(args: argparse.Namespace) -> int:
    result = create_resource(
        args.root,
        args.kind,
        args.name,
        domain=args.domain,
        lane=args.lane,
        dry_run=not args.apply,
    )
    _print(result, json_output=args.json)
    return 0 if result.get("readback", {}).get("ok") else 1


def register(subparsers) -> None:
    parser = subparsers.add_parser(
        "resource",
        help="Plan, create, and validate governed Agentic OS resources.",
        description=(
            "Operate filesystem-backed automations, workflows, and programs without executing them. "
            "Creation is a dry-run unless --apply is passed."
        ),
    )
    commands = parser.add_subparsers(dest="resource_command", required=True)

    validate_parser = commands.add_parser("validate", help="Validate a resource contract without changing it.")
    validate_parser.add_argument("kind", choices=SUPPORTED_RESOURCE_KINDS)
    validate_parser.add_argument("name")
    validate_parser.add_argument("--domain")
    validate_parser.add_argument("--lane")
    validate_parser.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    validate_parser.add_argument("--json", action="store_true", help="Print deterministic JSON instead of YAML.")
    validate_parser.set_defaults(handler=handle_resource_validate)

    create_parser = commands.add_parser("create", help="Plan or create a resource scaffold; never run it.")
    create_parser.add_argument("kind", choices=SUPPORTED_RESOURCE_KINDS)
    create_parser.add_argument("name")
    create_parser.add_argument("--domain")
    create_parser.add_argument("--lane")
    create_parser.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    mode = create_parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", default=True)
    mode.add_argument("--apply", action="store_true")
    create_parser.add_argument("--json", action="store_true", help="Print deterministic JSON instead of YAML.")
    create_parser.set_defaults(handler=handle_resource_create)
