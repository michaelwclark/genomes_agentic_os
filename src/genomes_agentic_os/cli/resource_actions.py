"""CLI surface for governed Agentic OS resource creation and validation."""

from __future__ import annotations

import argparse
import json

from ..registry_resource_actions import (
    REGISTRY_RESOURCE_KINDS,
    REGISTRY_SCOPES,
    create_registry_resource,
    registry_resource_get,
    registry_resource_list,
    rollback_registry_resource,
    set_registry_resource_archive,
    update_registry_resource,
    validate_registry_resource,
)
from ..resource_actions import SUPPORTED_RESOURCE_KINDS, create_resource, validate_resource

from ._shared import DEFAULT_ROOT, yaml_dump


ALL_RESOURCE_KINDS = (*SUPPORTED_RESOURCE_KINDS, *REGISTRY_RESOURCE_KINDS)


def _print(result: dict, *, json_output: bool) -> None:
    print(json.dumps(result, sort_keys=True) if json_output else yaml_dump(result))


def handle_resource_validate(args: argparse.Namespace) -> int:
    if args.kind in REGISTRY_RESOURCE_KINDS:
        result = validate_registry_resource(
            args.root,
            args.kind,
            args.name,
            scope=args.scope,
            domain=args.domain,
            project=args.project,
        )
    else:
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
    if args.kind in REGISTRY_RESOURCE_KINDS:
        if not args.display_name or not args.description or not args.prompt:
            raise ValueError("--display-name, --description, and --prompt are required for registry resources")
        result = create_registry_resource(
            args.root,
            args.kind,
            args.name,
            name=args.display_name,
            description=args.description,
            prompt=args.prompt,
            scope=args.scope,
            domain=args.domain,
            project=args.project,
            dry_run=not args.apply,
        )
    else:
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


def handle_resource_list(args: argparse.Namespace) -> int:
    result = registry_resource_list(
        args.root,
        args.kind,
        scope=args.scope,
        domain=args.domain,
        project=args.project,
    )
    _print(result, json_output=args.json)
    return 0


def handle_resource_get(args: argparse.Namespace) -> int:
    result = registry_resource_get(
        args.root,
        args.kind,
        args.name,
        scope=args.scope,
        domain=args.domain,
        project=args.project,
    )
    _print(result, json_output=args.json)
    return 0


def handle_resource_update(args: argparse.Namespace) -> int:
    result = update_registry_resource(
        args.root,
        args.kind,
        args.name,
        name=args.display_name,
        description=args.description,
        prompt=args.prompt,
        scope=args.scope,
        domain=args.domain,
        project=args.project,
        dry_run=not args.apply,
    )
    _print(result, json_output=args.json)
    return 0 if result.get("readback", {}).get("ok") else 1


def handle_resource_archive(args: argparse.Namespace) -> int:
    result = set_registry_resource_archive(
        args.root,
        args.kind,
        args.name,
        archived=args.archive_value,
        scope=args.scope,
        domain=args.domain,
        project=args.project,
        dry_run=not args.apply,
    )
    _print(result, json_output=args.json)
    return 0 if result.get("readback", {}).get("ok") else 1


def handle_resource_rollback(args: argparse.Namespace) -> int:
    result = rollback_registry_resource(
        args.root,
        args.kind,
        args.name,
        backup_id=args.backup_id,
        scope=args.scope,
        domain=args.domain,
        project=args.project,
        dry_run=not args.apply,
    )
    _print(result, json_output=args.json)
    return 0 if result.get("readback", {}).get("ok") else 1


def _add_scope_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--scope", choices=REGISTRY_SCOPES, default="system")
    parser.add_argument("--domain")
    parser.add_argument("--project")


def _add_output_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--root", default=DEFAULT_ROOT, help="Installed OS root path.")
    parser.add_argument("--json", action="store_true", help="Print deterministic JSON instead of YAML.")


def _add_mutation_mode(parser: argparse.ArgumentParser) -> None:
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", default=True)
    mode.add_argument("--apply", action="store_true")


def register(subparsers) -> None:
    parser = subparsers.add_parser(
        "resource",
        help="Plan, create, and validate governed Agentic OS resources.",
        description=(
            "Operate filesystem-backed automations, workflows, and programs, plus registry-backed "
            "rules, reports, skills, and commands, without executing them. Mutations are dry-runs "
            "unless --apply is passed."
        ),
    )
    commands = parser.add_subparsers(dest="resource_command", required=True)

    validate_parser = commands.add_parser("validate", help="Validate a resource contract without changing it.")
    validate_parser.add_argument("kind", choices=ALL_RESOURCE_KINDS)
    validate_parser.add_argument("name")
    _add_scope_args(validate_parser)
    validate_parser.add_argument("--lane")
    _add_output_args(validate_parser)
    validate_parser.set_defaults(handler=handle_resource_validate)

    create_parser = commands.add_parser("create", help="Plan or create a resource scaffold; never run it.")
    create_parser.add_argument("kind", choices=ALL_RESOURCE_KINDS)
    create_parser.add_argument("name")
    _add_scope_args(create_parser)
    create_parser.add_argument("--lane")
    create_parser.add_argument("--display-name")
    create_parser.add_argument("--description")
    create_parser.add_argument("--prompt")
    _add_mutation_mode(create_parser)
    _add_output_args(create_parser)
    create_parser.set_defaults(handler=handle_resource_create)

    list_parser = commands.add_parser("list", help="List registry-backed resources from a canonical scope.")
    list_parser.add_argument("kind", choices=REGISTRY_RESOURCE_KINDS)
    _add_scope_args(list_parser)
    _add_output_args(list_parser)
    list_parser.set_defaults(handler=handle_resource_list)

    get_parser = commands.add_parser("get", help="Read one registry-backed resource and its prompt source.")
    get_parser.add_argument("kind", choices=REGISTRY_RESOURCE_KINDS)
    get_parser.add_argument("name")
    _add_scope_args(get_parser)
    _add_output_args(get_parser)
    get_parser.set_defaults(handler=handle_resource_get)

    update_parser = commands.add_parser("update", help="Update allowlisted registry metadata or prompt content.")
    update_parser.add_argument("kind", choices=REGISTRY_RESOURCE_KINDS)
    update_parser.add_argument("name")
    update_parser.add_argument("--display-name")
    update_parser.add_argument("--description")
    update_parser.add_argument("--prompt")
    _add_scope_args(update_parser)
    _add_mutation_mode(update_parser)
    _add_output_args(update_parser)
    update_parser.set_defaults(handler=handle_resource_update)

    for command_name, archive_value in (("archive", True), ("restore", False)):
        archive_parser = commands.add_parser(command_name, help=f"{command_name.title()} a managed registry resource.")
        archive_parser.add_argument("kind", choices=REGISTRY_RESOURCE_KINDS)
        archive_parser.add_argument("name")
        _add_scope_args(archive_parser)
        _add_mutation_mode(archive_parser)
        _add_output_args(archive_parser)
        archive_parser.set_defaults(handler=handle_resource_archive, archive_value=archive_value)

    rollback_parser = commands.add_parser("rollback", help="Restore a managed registry resource from a fixed backup ID.")
    rollback_parser.add_argument("kind", choices=REGISTRY_RESOURCE_KINDS)
    rollback_parser.add_argument("name")
    rollback_parser.add_argument("--backup-id", required=True)
    _add_scope_args(rollback_parser)
    _add_mutation_mode(rollback_parser)
    _add_output_args(rollback_parser)
    rollback_parser.set_defaults(handler=handle_resource_rollback)
